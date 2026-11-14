# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Pipeline 147 planning, phase execution, and immutable manual-attempt aggregation."""

import argparse
from concurrent.futures import as_completed, ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import subprocess
import sys
from threading import Event
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
RETRY = runpy.run_path(str(ROOT / "azext_iot/tests/_ado_retry.py"))
HANDOFF = runpy.run_path(str(ROOT / "azext_iot/tests/_cleanup_handoff.py"))
TARGET = runpy.run_path(str(ROOT / "azext_iot/tests/_integration_target.py"))
FOCUSED = runpy.run_path(str(ROOT / "azext_iot/tests/_focused_live.py"))
BUDGETS = json.loads((ROOT / "azext_iot/tests/ci_budgets.json").read_text(encoding="utf-8"))
GENERIC_PHASE_OVERRIDES = (
    "azext_iot_testhub", "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_adr_update_instance_id",
    "azext_iot_adr_update_instance_disposable", "azext_iot_teststorageaccount", "azext_iot_teststoragecontainer",
    "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
)
OWNERSHIP_MANIFEST = "AZEXT_IOT_RESOURCE_MANIFEST"


def ownership_identity(ctx, native_attempt):
    return {
        "product": "azure-iot", "cloud": TARGET["cloud"](ctx["endpoint"])["name"],
        "endpoint": ctx["endpoint"], "subscription": ctx["subscription"], "resourceGroup": ctx["resource_group"],
        "identity": ctx, "attempt": native_attempt,
    }


def prepare_ownership(ctx, output, native_attempt):
    from azext_iot.tests import _owned_resources as owned

    return owned.create_context(output, **ownership_identity(ctx, native_attempt))


def plan(services, versions, regions, endpoint, diagnostic=False, release_build_id="0"):
    if not services or len(set(services)) != len(services) or not set(services) <= set(RETRY["SERVICES"]):
        raise ValueError("Select distinct supported services.")
    if not versions or len(set(versions)) != len(versions) or not set(versions) <= {"3.10", "3.11", "3.12", "3.13"}:
        raise ValueError("Select distinct supported Python versions.")
    if not regions or len(set(regions)) != len(regions):
        raise ValueError("Select distinct regions.")
    sovereign = TARGET["cloud"](endpoint)["name"] != "AzureCloud"
    if sovereign and not set(services) <= {"DPS", "HubControl", "HubData"}:
        raise ValueError("Sovereign integration cohorts support DPS, HubControl and HubData only.")
    if sovereign and str(release_build_id) != "0":
        raise ValueError("Sovereign cohorts are standalone validation, not public release qualification.")
    jobs = []
    for service in (["RetrySelfTest"] if diagnostic else services):
        if not diagnostic and not (ROOT / BUDGETS[service]["test_dir"]).is_dir():
            raise ValueError(f"{service} is unavailable on this branch.")
        for version in versions:
            for region in regions:
                target = TARGET["target"](region, endpoint)
                jobs.append({"service": service, "python": version, **target,
                             **(TARGET["scope"](endpoint) if sovereign else {}),
                             "minutes": 10 if diagnostic else BUDGETS[service]["job_timeout_minutes"]})
    if len(jobs) > 40:
        raise ValueError("Select at most 40 combinations per run.")
    return jobs


def run_title(jobs, kind, mode, build_id, parent="0"):
    if (kind not in {"health", "integration"} or mode not in {"Dry run", "Integration tests"}
            or not re.fullmatch(r"[1-9][0-9]*", build_id) or not re.fullmatch(r"0|[1-9][0-9]*", parent)
            or kind == "health" and (mode != "Integration tests" or parent != "0")):
        raise ValueError("Invalid run title identity or mode.")
    services = {job["service"] for job in jobs}
    if not services or not services <= set(RETRY["SERVICES"]):
        raise ValueError("Run titles require a supported, nonempty service plan.")
    regions = sorted({TARGET["target"](job["region"], job["endpoint"])["region"] for job in jobs})
    for count in range(len(regions), 0, -1):
        region_label = ",".join(regions[:count]) + (f" +{len(regions) - count}" if count < len(regions) else "")
        if len(region_label) <= 80:
            break
    if services == {"ADU"}:
        region_label = "hub " + region_label
    if {"HubControl", "HubData"} <= services:
        services = services - {"HubControl", "HubData"} | {"Hub"}
    scope = ",".join(service for service in ("DPS", "Hub", "HubControl", "HubData", "ADU", "ADR")
                     if service in services)
    modes = []
    if mode == "Dry run":
        modes.append("dry-run")
    if any(job["endpoint"] == TARGET["CANARY_ARM"] for job in jobs):
        modes.append("canary")
    title = f"iot-{kind}-{build_id} ({region_label}) ({scope})"
    if modes:
        title += f" ({','.join(modes)})"
    if len(title) > 255 or not re.fullmatch(r"[A-Za-z0-9 (),+-]+", title):
        raise ValueError("Run title exceeds Azure Pipelines length or character limits.")
    return title


def results_title(service, python, region, wheel, attempt):
    """Name a published test run by what separates failures in dashboard trend legends."""
    wheels = list(Path(wheel).rglob("*.whl")) if Path(wheel).is_dir() else []
    version = wheels[0].name.split("-")[1] if len(wheels) == 1 else "unknown"
    # Publishing must not depend on naming, so normalize instead of rejecting unexpected values.
    return re.sub(r"[^A-Za-z0-9._+/#-]", "-", f"{service}/{version}/{region}/py{python}/#{attempt}")[:255]


def context(service, python, region, endpoint, wheel, diagnostic):
    wheels = list(Path(wheel).rglob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Exactly one candidate wheel is required.")
    interpreters = [sys.executable]
    if service == "DPS":
        interpreters.append(str(ROOT / ".tox/DPS-int/bin/python"))
    dependencies = [
        sorted(subprocess.run([python, "-m", "pip", "freeze"], check=True, capture_output=True, text=True).stdout.splitlines())
        for python in interpreters
    ]
    extensions = []
    if not diagnostic:
        extensions.append(Path(os.environ["AZURE_EXTENSION_DIR"]) / "azure-iot")
        if service == "DPS":
            purelib = subprocess.run(
                [interpreters[-1], "-c", 'import sysconfig; print(sysconfig.get_path("purelib"))'],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            extensions.append(Path(purelib) / "azure-cli-extensions/azure-iot")
        for extension in extensions:
            if not extension.is_dir():
                raise ValueError("Installed candidate dependencies are missing.")
            dependencies.append(sorted(
                (path.parent.name, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in extension.glob("*.dist-info/METADATA")
            ))
    result = {
        "build": os.environ["BUILD_BUILDID"], "definition": os.environ["SYSTEM_DEFINITIONID"],
        "commit": os.environ["BUILD_SOURCEVERSION"],
        "wheel": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
        "dependencies": RETRY["digest"](dependencies),
        "service": service, "python": python, "region": region, "endpoint": endpoint,
        **TARGET["scope"](endpoint),
        "diagnostic": str(diagnostic).lower(),
    }
    if os.environ.get("AZEXT_IOT_MONITOR_MANIFEST"):
        result["monitor"] = RETRY["digest"](RETRY["read"](os.environ["AZEXT_IOT_MONITOR_MANIFEST"]))
    return result


def candidate(directory, output):
    artifacts = sorted(Path(directory).glob("integration-wheel-*"),
                       key=lambda path: int(path.name.rsplit("-", 1)[1]))
    if not artifacts:
        raise ValueError("Original candidate wheel is unavailable.")
    wheels = list(artifacts[0].glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Original candidate is ambiguous.")
    target = Path(output)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(wheels[0], target / wheels[0].name)


def gate(directory):
    rejections = [RETRY["read"](path) for path in Path(directory).rglob("rejection.json")]
    if any(not value.get("recoverable") for value in rejections):
        raise ValueError("An immutable identity/artifact check failed; start a new run.")
    plans = sorted(Path(directory).glob("integration-plan-*/plan.json"))
    if not plans or any(RETRY["read"](path) != RETRY["read"](plans[0]) for path in plans):
        raise ValueError("Missing or changed execution plan.")
    expected = RETRY["read"](plans[0])
    paths = list(Path(directory).rglob("attempt.json"))
    records = [RETRY["read"](path) for path in paths]
    keys = {(value["service"], value["python"], value["region"]) for value in expected}
    if any(tuple(value.get("identity", {}).get(key) for key in ("service", "python", "region")) not in keys
           or type(value["identity"].get("nativeAttempt")) is not int for value in rejections):
        raise ValueError("Incomplete-job identity is missing or outside the execution plan.")
    if {(value["context"]["service"], value["context"]["python"], value["context"]["region"])
            for value in records} != keys:
        raise ValueError("Missing or unexpected service combinations.")
    wheels = sorted(Path(directory).glob("integration-wheel-*"), key=lambda path: int(path.name.rsplit("-", 1)[1]))
    candidates = list(wheels[0].glob("*.whl")) if wheels else []
    if len(candidates) != 1:
        raise ValueError("Original candidate wheel is missing or ambiguous.")
    wheel = hashlib.sha256(candidates[0].read_bytes()).hexdigest()
    for path, record in zip(paths, records):
        RETRY["verify_artifacts"](path, record)
    for config in expected:
        history = [value for value in records if all(value["context"][key] == config[key]
                                                     for key in ("service", "python", "region"))]
        history.sort(key=lambda value: value["sequence"])
        ctx = history[0]["context"]
        scope = TARGET["scope"](config["endpoint"])
        monitor = (RETRY["digest"](RETRY["read"](os.environ["AZEXT_IOT_MONITOR_MANIFEST"]))
                   if os.environ.get("AZEXT_IOT_MONITOR_MANIFEST") else None)
        if (ctx["build"] != os.environ["BUILD_BUILDID"] or ctx["commit"] != os.environ["BUILD_SOURCEVERSION"]
                or ctx["definition"] != os.environ.get("SYSTEM_DEFINITIONID", "147")
                or ctx["endpoint"] != config["endpoint"] or ctx["wheel"] != wheel or ctx.get("monitor") != monitor
                or any(ctx[key] != value for key, value in scope.items())
                or TARGET["cloud"](config["endpoint"])["name"] != "AzureCloud"
                and any(config.get(key) != value for key, value in scope.items())):
            raise ValueError("Evidence belongs to a different run/commit/target.")
        original, _, _ = RETRY["evaluate"](history, ctx)
        owned = owned_nodes(config["service"], config["endpoint"])
        if owned and {phase: list(nodes) for phase, nodes in original.items()} != owned:
            raise ValueError("Original phase selection does not cover the authoritative service manifest.")
        if config["service"] == "DPS":
            for attempt in history:
                for phase_name, value in attempt["phases"].items():
                    exclusions = phase_exclusions("DPS", config["endpoint"], phase_name)
                    if (value.get("excluded", []) != list(exclusions)
                            or value.get("exclusionReasons", {}) != exclusions):
                        raise ValueError("DPS cloud-specific skip evidence does not match the committed policy.")
        if RETRY["pending"](history, ctx):
            raise ValueError("Unresolved failures remain.")
        for rejected in rejections:
            identity = rejected.get("identity", {})
            if all(identity.get(key) == config[key] for key in ("service", "python", "region")) and not any(
                    attempt["mode"] == "full" and attempt["nativeAttempt"] > identity["nativeAttempt"]
                    for attempt in history):
                raise ValueError("An incomplete job still needs a full-service recovery.")
    diagnostic = any(value["context"]["diagnostic"] == "true" for value in records)
    if diagnostic:
        print("Diagnostic retry proof passed; NOT release qualification.")
    elif any(TARGET["cloud"](job["endpoint"])["name"] != "AzureCloud" for job in expected):
        print("Every selected sovereign cohort passed; this is NOT full public-cloud suite qualification.")
    else:
        print("Every expected service combination passed; manual retry history is retained.")


def coverage(directory):
    files = list(Path(directory).rglob(".coverage"))
    if not files:
        raise ValueError("No coverage artifacts were produced.")
    subprocess.run([sys.executable, "-m", "coverage", "combine", "--keep", *map(str, files)], check=True)
    subprocess.run([sys.executable, "-m", "coverage", "xml"], check=True)
    subprocess.run([sys.executable, "-m", "coverage", "html"], check=True)


def phase_exclusions(service, endpoint, phase_name):
    if service == "DPS" and endpoint == TARGET["CHINA_ARM"] and phase_name == "local-auth-toggle":
        return {FOCUSED["DPS_MOONCAKE_TLS_NODE"]: FOCUSED["DPS_MOONCAKE_TLS_REASON"]}
    return {}


def owned_nodes(service, endpoint=TARGET["PUBLIC_ARM"]):
    sovereign = TARGET["cloud"](endpoint)["name"] != "AzureCloud"
    if service == "DPS":
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/dps/_phase_manifest.py"))
        result = {}
        for phase in manifest["PHASE_NAMES"]:
            nodes = manifest["expected_nodeids"](phase)
            if sovereign:
                # Legacy registration cases embed .net hosts; CSR cases require public-only ADR APIs.
                nodes = {
                    node for node in nodes if node.startswith((
                        "enrollment/", "enrollment_group/",
                        "device_registration/test_iot_device_registration_fresh_keys_int.py::",
                        "core/test_dps_command_happy_paths_int.py::",
                        "core/test_dps_disable_local_auth_int.py::",
                    ))
                }
                if endpoint == TARGET["CHINA_ARM"]:
                    # Linked-Hub fixtures and management happy paths require unsupported DPS identity.
                    nodes = {
                        node for node in nodes
                        if node.startswith("core/test_dps_disable_local_auth_int.py::")
                    }
            nodes = {node for node in nodes
                     if FOCUSED["DPS_PREFIX"] + node not in phase_exclusions(service, endpoint, phase)}
            if nodes:
                result[phase] = sorted("azext_iot/tests/dps/" + node for node in nodes)
        return result
    if service.startswith("Hub"):
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_suite_manifest.py"))
        selected = None
        if sovereign:
            modules = (
                "core/test_iothub_certificate_int.py::",
                "core/test_iothub_command_happy_paths_int.py::",
                "devices/test_iothub_devices_int.py::",
                "devices/test_iothub_device_twin_int.py::",
                "modules/test_iothub_modules_int.py::",
                "modules/test_iothub_module_twin_int.py::",
                "messaging/test_iothub_c2d_messages_int.py::",
            )
            selected = {
                case.node for case in manifest["CASES"]
                if case.capability == "base" and set(case.dependencies) <= {"hub", "local-certificates"}
                and case.node.startswith(tuple("azext_iot/tests/iothub/" + module for module in modules))
            }
        return {
            phase: nodes for phase in manifest["phases"](service)
            if (nodes := [node for node in manifest["nodes"](service, phase) if selected is None or node in selected])
        }
    return {}


def dps_evidence(folder, selection, ctx):
    dps = runpy.run_path(str(ROOT / "azext_iot/tests/_dps_phase_runner.py"))
    hub = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_phase_runner.py"))
    summary = RETRY["read"](folder / "dps-phases.json")
    phase = selection["phase"]
    result, = summary["phases"]
    if summary.get("error") or result.get("status") == "blocked":
        raise ValueError("DPS phase controller failed; inspect dps-phases.json for error and ARM request diagnostics.")
    directory = folder / "dps-phases" / phase
    receipt = RETRY["read"](directory / "receipts/pytest.json")
    provenance = dps["FOCUSED"]["provenance"](selection)
    if (summary.get("cancelled") is not False or summary.get("status") not in ("attempt-passed", "attempt-failed")
            or any(summary.get(key) != value for key, value in provenance.items())
            or result != RETRY["read"](directory / "result.json")
            or result["name"] != phase or result.get("timed_out") is not False or result.get("interrupted") is not False
            or result["exit_code"] != receipt["exitstatus"] or summary.get("error") or result.get("execution_error")
            or summary["subscription"] != ctx["subscription"] or summary["resource_group"] != ctx["resource_group"]
            or any(summary.get(key) != ctx[key] for key in ("region", "endpoint"))):
        raise ValueError("Incomplete DPS attempt.")
    errors = hub["phase_errors"](receipt, selection["requestedNodes"], "DPS", phase, result["run_uid"],
                                 debug=selection, allow_failures=True)
    if errors:
        raise ValueError("DPS execution/teardown is unproven: " + "; ".join(errors))
    selected = dps["selection_count"](directory / "receipts", phase, debug=selection)
    cases = list(ET.parse(directory / "junit.xml").getroot().iter("testcase"))
    outcomes = RETRY["outcomes"](receipt, allow_fixture_failures=True)
    actual = {}
    for case in cases:
        node = "azext_iot/tests/dps/" + dps["MANIFEST"]["junit_nodeid"](case)
        actual.setdefault(node, []).append([child.tag for child in case])
    if selected != len(outcomes) or set(actual) != set(outcomes):
        raise ValueError("DPS collection/JUnit disagrees with phase evidence.")
    for node, stages in receipt["reports"].items():
        expected_tags = ["failure" if stage == "call" else "error"
                         for stage, status in stages.items() if status == ["failed"]]
        entries = actual[node]
        if (sorted(tag for entry in entries for tag in entry) != sorted(expected_tags)
                or not expected_tags and len(entries) != 1
                or expected_tags and any(not entry for entry in entries)):
            raise ValueError("DPS JUnit contains duplicate, skipped or inconsistent test stages.")
    baseline = {resource["id"].casefold() for resource in summary["baseline"]["resources"]}
    records = dps["ownership"](directory / "receipts", phase, result["run_uid"], ctx["subscription"],
                               ctx["resource_group"], baseline, region=ctx["region"], endpoint=ctx["endpoint"])
    ids = [record["id"] for record in records]
    cleanup = result["cleanup"]
    if (cleanup.get("mode") == "handoff" or cleanup.get("complete") is not True or cleanup.get("remaining") != []
            or set(cleanup["owned_ids"]) != set(ids) or set(cleanup["absent_ids"]) != set(ids)
            or any(not record["creation_resolved"] for record in records)
            or {value.casefold() for value in ids}.intersection(cleanup["inventory_ids"])):
        raise ValueError("DPS ownership/resource absence is unproven.")
    return receipt


def phase(selection_file, output):
    name = "azext_iot_cleanup_handoff"
    previous = os.environ.get(name)
    service = RETRY["read"](selection_file)["context"]["service"]
    if service in ("DPS", "HubControl", "HubData"):
        os.environ.pop(name, None)
    else:
        os.environ[name] = str(Path(output).resolve() / "cleanup-receipts")
    try:
        return _phase(selection_file, output)
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _phase(selection_file, output):
    """Each controller needs its own main thread, signal handlers and resource cohort."""
    from azext_iot.tests import _focused_live as focused
    from azext_iot.tests import _dps_phase_runner as dps
    from azext_iot.tests import _hub_phase_runner as hub
    value = RETRY["read"](selection_file)
    ctx, name, nodes = value["context"], value["phase"], value["nodes"]
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    service = ctx["service"]
    target = {"region": ctx["region"], "endpoint": ctx["endpoint"]}
    if service in ("DPS", "HubControl", "HubData"):
        chosen = focused.attempt(service, name, nodes, RETRY["digest"](value))
        if service == "DPS":
            with dps.bounded_read():
                reader = dps.ArmReader(ctx["subscription"], **target)
            dps.run(ctx["subscription"], ctx["resource_group"], folder / "dps-phases", reader,
                    attempt_selection=chosen, **target)
            receipt = dps_evidence(folder, chosen, ctx)
        else:
            hub.run(service, ctx["subscription"], ctx["resource_group"], ctx["region"], folder / "hub-phases",
                    endpoint=ctx["endpoint"], attempt_selection=chosen)
            check = hub.evaluate_hub_phases(folder / "hub-phases", attempt=True, allow_failures=True, **target)
            if not check["passed"]:
                raise ValueError("Hub ownership/execution evidence is invalid: " + "; ".join(check["errors"]))
            receipt = RETRY["read"](folder / "hub-phases" / name / "pytest.json")
        expected = value["expected"]
    else:
        diagnostic = service == "RetrySelfTest"
        if any(os.getenv(key) for key in GENERIC_PHASE_OVERRIDES):
            raise ValueError("Fresh service attempts reject external fixtures and pytest selection overrides.")
        env = dict(os.environ, azext_iot_ado_receipt=str(folder / "pytest.json"),
                   azext_iot_ado_expected=json.dumps(value["expected"]),
                   azext_iot_ado_selected=json.dumps(nodes),
                   azext_iot_ado_diagnostic_attempt=str(value["sequence"]),
                   COVERAGE_FILE=str(folder / ".coverage"))
        directory = ("azext_iot/tests/ado_diagnostic.py" if diagnostic else BUDGETS[service]["test_dir"])
        command = [sys.executable, "-m", "pytest", directory, "-vv", "-c", str(ROOT / "setup.cfg"),
                   "-o", "addopts=", "-o", "env=", "-p", "azext_iot.tests._ado_retry_plugin",
                   "-p", "no:rerunfailures", "--integration-progress-interval=60",
                   "-o", "faulthandler_timeout=300", "--cov=azext_iot", "--cov-config=.coveragerc",
                   "--cov-report=", "--capture=fd", "-n", "0" if diagnostic else ("4" if service == "ADR" else "7")]
        if service != "ADU":
            command.append("--timeout=900")
        if not diagnostic:
            command += ["-k", "_int.py", "--dist=loadgroup" if service == "ADR" else "--dist=loadfile"]
            from azext_iot.tests import _owned_resources as owned
            manifest = owned.Journal(os.environ[OWNERSHIP_MANIFEST])
            expected_owner = ownership_identity(ctx, int(os.environ["SYSTEM_JOBATTEMPT"]))
            if any(manifest.context.get(key) != expected_value for key, expected_value in expected_owner.items()):
                raise ValueError("Resource ownership manifest belongs to another job attempt.")
            ownership = folder / "ownership.json"
            owned.write_new(ownership, manifest.context)
            env[owned.ENV] = str(ownership)
            command += ["-p", "azext_iot.tests._ado_ownership_plugin"]
        try:
            execution = dps.child(command, env, folder / "output.log",
                                  (10 if diagnostic else BUDGETS[service]["job_timeout_minutes"] - 20) * 60, 600)
        finally:
            if not diagnostic:
                owned.cleanup(ownership, timeout=600)
        if execution["timed_out"] or execution["interrupted"]:
            raise ValueError("Timed out/interrupted execution cannot qualify.")
        receipt = RETRY["read"](folder / "pytest.json")
        if execution["exit_code"] != receipt["exitstatus"]:
            raise ValueError("Execution status disagrees with test evidence.")
        expected = receipt["expected"]
    RETRY["outcomes"](receipt, allow_fixture_failures=True)
    exclusions = phase_exclusions(service, ctx["endpoint"], name)
    exclusion_reasons = {**receipt.get("exclusionReasons", {}), **exclusions}
    phase_result = {
        "expected": expected, "receipt": receipt, "safe": True,
        "excluded": receipt.get("excluded", []) + list(exclusions),
        "cleanupMode": "handoff" if service == "RetrySelfTest" else "verified",
    }
    if exclusion_reasons:
        phase_result["exclusionReasons"] = exclusion_reasons
    RETRY["write"](folder / "phase.json", phase_result)


def run(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        return run_attempt(args, output)
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        reject(output, detail, recoverable=not isinstance(error, RETRY["IntegrityError"]),
               service=args.service, python=args.python, region=args.region)
        raise


def reject(output, reason, *, recoverable=False, service=None, python=None, region=None, publish_summary=True):
    """Publish an explicit orchestration error, never successful test coverage."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    RETRY["write"](output / "rejection.json", {
        "reason": reason, "qualifies": False, "recoverable": recoverable,
        "identity": {
            "service": service or os.getenv("SERVICE"), "python": python or os.getenv("TEST_PYTHON"),
            "region": region or os.getenv("TEST_REGION"), "nativeAttempt": int(os.getenv("SYSTEM_JOBATTEMPT", "1")),
        },
    })
    suite = ET.Element("testsuite", name="Attempt rejected", tests="1", failures="0", errors="1")
    case = ET.SubElement(suite, "testcase", classname="pipeline", name="Attempt execution evidence")
    ET.SubElement(case, "error", message=reason)
    ET.ElementTree(suite).write(output / "final.xml", encoding="utf-8", xml_declaration=True)
    action = ("Manually rerun the affected service with fresh fixtures." if recoverable
              else "Start a new run after correcting the immutable identity/artifact problem.")
    try:
        cleanup = cleanup_report(output)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        cleanup = f"\nCleanup reporting also failed ({type(error).__name__}); resource absence is unproven.\n"
        print(f"##vso[task.logissue type=error]{cleanup.strip()}")
    (output / "summary.md").write_text(
        f"## Attempt rejected\n\n{reason}\n\nNo successful recovery was recorded. "
        f"See the original attempt artifacts and task logs. {action}\n" + cleanup,
        encoding="utf-8",
    )
    if publish_summary:
        print(f"##vso[task.uploadsummary]{output / 'summary.md'}")


def cleanup_report(output):
    path = output / "cleanup-status.json"
    if path.exists():
        cleanup = RETRY["read"](path)
    else:
        cleanup = HANDOFF["summary"](output)
        merged = {item["resource"].casefold(): item for item in cleanup}
        for manifest in sorted(output.rglob("ownership.json")):
            for record in ownership_cleanup(manifest):
                merged[record["resource"].casefold()] = record
        cleanup = [merged[key] for key in sorted(merged)]
        if cleanup:
            RETRY["write"](path, cleanup)
    if not cleanup:
        return ""
    text = "\nCleanup is reported separately. Accepted deletion is not proof of resource absence.\n"
    for status in ("accepted", "deleting", "absent", "pending", "failed"):
        text += f"- Cleanup {status}: {sum(item['status'] == status for item in cleanup)}\n"
    return text + ("\nExact IDs and submission failures are in `cleanup-status.json`; "
                   "pending leftovers need operational cleanup.\n")


def ownership_cleanup(path):
    """Render producer-specific absence evidence without granting cleanup or qualification."""
    data = RETRY["read"](path)
    if data.get("schema") == 1:
        owned = runpy.run_path(str(ROOT / "azext_iot/tests/_owned_resources.py"))
        return [
            {"resource": record["id"], "status": record.get("cleanup", "pending"),
             "owner": record["owner"], "timeNs": record["timeNs"]}
            for record in owned["Journal"](path).records().values()
        ]
    if data.get("schemaVersion") == 1 and isinstance(data.get("resources"), dict) and data.get("runId"):
        owner = data["runId"]
        ids = set(data["resources"])
        receipt_path = path.with_name("cleanup.json")
        receipt = RETRY["read"](receipt_path) if receipt_path.exists() else {}
        if receipt and receipt.get("runId") != owner:
            raise ValueError("Hub cleanup report belongs to another run.")
        if "ownedIds" in receipt and set(receipt["ownedIds"]) != ids:
            raise ValueError("Hub cleanup report has different owned resources.")
        absent = set(receipt.get("absentIds", []))
        children = set(receipt.get("descendantIds", []))
        if any(not any(child.startswith(root + "/") for root in ids) for child in children):
            raise ValueError("Hub cleanup report has a descendant outside its owned resources.")
        if not absent <= ids or not set(receipt.get("absentDescendantIds", [])) <= children:
            raise ValueError("Hub cleanup report has unrecognized absence evidence.")
        ids |= children
        absent |= set(receipt.get("absentDescendantIds", []))
    elif data.get("phase") == "local-auth" and data.get("runUid") and isinstance(data.get("ids"), dict):
        owner = data["runUid"]
        if set(data["ids"]) != {"hub", "storage", "container", "role"}:
            raise ValueError("SAS cleanup report has an incomplete resource manifest.")
        absent_keys = set(data.get("absent", []))
        if not absent_keys <= set(data["ids"]):
            raise ValueError("SAS cleanup report has unrecognized absence evidence.")
        ids = set(data["ids"].values())
        absent = {data["ids"][key] for key in absent_keys}
    else:
        raise ValueError("Unrecognized cleanup ownership receipt schema.")
    if any(not isinstance(resource, str) or not resource.lower().startswith("/subscriptions/") for resource in ids):
        raise ValueError("Cleanup report has an invalid resource ID.")
    return [
        {"resource": resource, "status": "absent" if resource in absent else "pending", "owner": owner}
        for resource in sorted(ids)
    ]


def run_attempt(args, output):
    from azext_iot.tests import _dps_phase_runner as dps
    ctx = context(args.service, args.python, args.region, args.endpoint, args.wheel, args.diagnostic)
    if os.environ.get("AZEXT_IOT_MONITOR_MANIFEST"):
        manifest = RETRY["read"](os.environ["AZEXT_IOT_MONITOR_MANIFEST"])
        if "testCompatibility" in manifest:
            RETRY["write"](output / "test-compatibility.json", manifest["testCompatibility"])
    history = RETRY["load_history"](args.history, ctx)
    native_attempt = int(os.environ["SYSTEM_JOBATTEMPT"])
    last_native = history[-1]["nativeAttempt"] if history else 0
    if native_attempt <= last_native:
        raise RETRY["IntegrityError"]("Native job attempt is not newer than the immutable history.")
    missing = list(range(last_native + 1, native_attempt))
    prior_expected, _, _ = RETRY["evaluate"](history, ctx)
    plan = RETRY["recovery_plan"](history, ctx)
    rejections = [RETRY["read"](path) for path in Path(args.history).rglob("rejection.json")]
    if missing or any(
            all(value.get("identity", {}).get(key) == ctx[key] for key in ("service", "python", "region"))
            and value["identity"]["nativeAttempt"] >= last_native for value in rejections):
        plan["mode"] = "full"
    remaining = ((owned_nodes(args.service, args.endpoint) or {"tests": []})
                 if plan["mode"] == "full" else plan["phases"])
    record = {
        "schema": 3, "context": ctx, "sequence": len(history) + 1, "nativeAttempt": native_attempt,
        "mode": plan["mode"], "missingAttempts": missing,
        "parent": RETRY["digest"](history[-1]) if history else None,
        "executionErrors": ["Execution did not complete."], "phases": {},
    }
    if plan["mode"] == "reuse":
        record.update(executionErrors=[])
        RETRY["write"](output / "reuse.json", {"parent": record["parent"], "nativeAttempt": native_attempt})
        record["evidence"] = RETRY["evidence"](output)
        RETRY["write"](output / "attempt.json", record)
        history.append(record)
        RETRY["junit"](history, ctx, output / "final.xml")
        print("Already passed; retaining original evidence without executing tests.")
        return 0
    if history:
        print(f"Manual recovery mode: {plan['mode']}; selection (cases per phase): "
              + json.dumps({name: len(nodes) for name, nodes in remaining.items()}), flush=True)
    os.environ["azext_iot_candidate_wheel"] = str(next(Path(args.wheel).rglob("*.whl")).resolve())
    cancel = Event()
    previous = {sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    auth = None
    try:
        if not args.diagnostic:
            command = [sys.executable, str(ROOT / "azext_iot/tests/_refresh_ci_auth.py")]
            subprocess.run(command, check=True, timeout=180)
            ready = output / "auth.ready"
            auth = subprocess.Popen(command + ["--loop", "--ready-file", str(ready)])  # pylint: disable=consider-using-with
            deadline = time.monotonic() + 30
            while not ready.is_file() or not ready.stat().st_size:
                if auth.poll() is not None or time.monotonic() >= deadline or cancel.is_set():
                    raise ValueError("Credential refresher did not become ready.")
                time.sleep(0.05)

        def execute(item):
            name, nodes = item
            selection = output / f"{name}.json"
            expected = list(prior_expected.get(name, owned_nodes(args.service, args.endpoint).get(name, [])))
            RETRY["write"](selection, {"context": ctx, "phase": name, "nodes": nodes, "expected": expected,
                                       "sequence": record["sequence"], "parent": record["parent"]})
            minutes = 10 if args.diagnostic else BUDGETS[args.service]["job_timeout_minutes"]
            result = dps.child(
                [sys.executable, str(Path(__file__)), "phase", "--selection", str(selection),
                 "--output", str(output / name)],
                dict(os.environ, SERVICE=ctx["service"], TEST_PYTHON=ctx["python"], TEST_REGION=ctx["region"]),
                output / f"{name}.log", minutes * 60, 120 if args.diagnostic else 660,
                lambda: cancel.is_set() or auth is not None and auth.poll() is not None,
            )
            if result["exit_code"] or result["timed_out"] or result["interrupted"]:
                rejection = output / name / "rejection.json"
                if rejection.is_file():
                    raise ValueError(RETRY["read"](rejection)["reason"])
                raise ValueError("Execution/cleanup evidence incomplete. See redacted phase logs.")
            return name, RETRY["read"](output / name / "phase.json")

        errors = []
        with ThreadPoolExecutor(max_workers=len(remaining)) as pool:
            futures = {pool.submit(execute, item): item[0] for item in remaining.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    _, value = future.result()
                    record["phases"][name] = value
                except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
                    detail = str(error) if isinstance(error, ValueError) else type(error).__name__
                    errors.append(f"{name}: {detail}")
        record["phases"] = {name: record["phases"][name] for name in remaining if name in record["phases"]}
        if errors:
            record["executionErrors"] = sorted(errors)
            raise ValueError("; ".join(sorted(errors)))
        if auth is not None:
            if auth.poll() is not None:
                raise ValueError("Credential refresher stopped unexpectedly.")
            auth.terminate()
            if auth.wait(timeout=180):
                raise ValueError("Credential refresh failed.")
            auth = None
        if cancel.is_set():
            raise ValueError("Attempt was cancelled; full-service recovery is required.")
        record["executionErrors"] = []
    finally:
        execution_failed = sys.exc_info()[0] is not None
        try:
            if auth is not None:
                if auth.poll() is None:
                    auth.terminate()
                auth.wait(timeout=180)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            reporting_error = None
            try:
                cleanup_report(output)
            except (ValueError, RuntimeError, OSError, KeyError) as error:
                reporting_error = error
                record["executionErrors"].append(f"Cleanup reporting failed ({type(error).__name__}).")
            RETRY["write"](output / "execution.json", {
                "mode": record["mode"], "nativeAttempt": native_attempt, "executionErrors": record["executionErrors"],
            })
            record["evidence"] = RETRY["evidence"](output)
            RETRY["write"](output / "attempt.json", record)
            if reporting_error is not None and not execution_failed:
                raise ValueError("Cleanup reporting failed; resource absence is unproven.") from reporting_error
    history.append(record)
    failures = RETRY["junit"](history, ctx, output / "final.xml")
    _, effective, recovered = RETRY["evaluate"](history, ctx)
    summary = (f"## {args.service}: {'Failed' if failures else 'Passed'}\n\n"
               f"{sum(map(len, effective.values()))} required cases; {failures} unresolved; "
               f"{len(recovered)} passed on manual retry. Mode: {plan['mode']}. Diagnostic: {ctx['diagnostic']}.\n")
    summary += cleanup_report(output)
    for value in record["phases"].values():
        for node, reason in value.get("exclusionReasons", {}).items():
            summary += f"\nSkipped `{node}`: {reason}\n"
    (output / "summary.md").write_text(summary, encoding="utf-8")
    print(f"##vso[task.uploadsummary]{output / 'summary.md'}")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    planner = commands.add_parser("plan")
    planner.add_argument("--services", nargs="+", required=True)
    planner.add_argument("--versions", nargs="+", required=True)
    planner.add_argument("--regions", nargs="+", required=True)
    planner.add_argument("--endpoint", required=True)
    planner.add_argument("--diagnostic", action="store_true")
    planner.add_argument("--release-build-id", default="0")
    namer = commands.add_parser("title")
    namer.add_argument("--plan", type=Path, required=True)
    namer.add_argument("--kind", choices=["health", "integration"], required=True)
    namer.add_argument("--mode", choices=["Dry run", "Integration tests"], required=True)
    namer.add_argument("--release-build-id", default="0")
    labeler = commands.add_parser("results-title")
    for name in ("service", "python", "region", "wheel"):
        labeler.add_argument("--" + name, required=True)
    runner = commands.add_parser("run")
    for name in ("service", "python", "region", "endpoint", "wheel", "history", "output"):
        runner.add_argument("--" + name, required=True)
    runner.add_argument("--diagnostic", action="store_true")
    owner = commands.add_parser("ownership")
    for name in ("service", "python", "region", "endpoint", "wheel", "output"):
        owner.add_argument("--" + name, required=True)
    phase_parser = commands.add_parser("phase")
    phase_parser.add_argument("--selection", required=True)
    phase_parser.add_argument("--output", required=True)
    rejection = commands.add_parser("report-incomplete")
    rejection.add_argument("--output", required=True)
    for name in ("gate", "coverage", "candidate"):
        subparser = commands.add_parser(name)
        subparser.add_argument("--history", required=True)
        if name == "candidate":
            subparser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "ownership":
        if args.service not in ("ADU", "ADR"):
            raise ValueError("Generic ownership is restricted to ADU and ADR.")
        ctx = context(args.service, args.python, args.region, args.endpoint, args.wheel, False)
        prepare_ownership(ctx, args.output, int(os.environ["SYSTEM_JOBATTEMPT"]))
        return 0
    if args.command == "title":
        jobs = json.loads(args.plan.read_text(encoding="utf-8"))
        title = run_title(jobs, args.kind, args.mode, os.environ["BUILD_BUILDID"], args.release_build_id)
        print(f"##vso[build.updatebuildnumber]{title}", flush=True)
        if any(job["service"] == "ADU" for job in jobs):
            print("Device Update uses title regions for dependency Hubs only; account locations are fixture-defined.")
        return 0
    if args.command == "results-title":
        title = results_title(args.service, args.python, args.region, args.wheel, os.environ["SYSTEM_JOBATTEMPT"])
        print(f"##vso[task.setvariable variable=testRunTitle]{title}", flush=True)
        return 0
    if args.command == "report-incomplete":
        output = Path(args.output)
        incomplete = not (output / "final.xml").is_file()
        if incomplete:
            reject(args.output, "No terminal report was produced; installation, login or execution did not complete.",
                   recoverable=True)
        # Test percentages describe execution; final.xml and the ledger still enforce qualification.
        if (output / "rejection.json").is_file():
            RETRY["execution_junit"](output, output / "published.xml")
        else:
            RETRY["published_junit"](output / "final.xml", output / "published.xml")
        return int(incomplete)
    if args.command == "plan":
        print(json.dumps(plan(args.services, args.versions, args.regions, args.endpoint, args.diagnostic,
                              args.release_build_id), indent=2))
        return 0
    if args.command == "phase":
        try:
            phase(args.selection, args.output)
        except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as error:
            detail = str(error) if isinstance(error, ValueError) else type(error).__name__
            reject(args.output, detail, recoverable=True, publish_summary=False)
            raise
        return 0
    if args.command in ("gate", "coverage", "candidate"):
        if args.command == "candidate":
            candidate(args.history, args.output)
        else:
            {"gate": gate, "coverage": coverage}[args.command](args.history)
        return 0
    return run(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, subprocess.SubprocessError) as exc:
        # Azure and HTTP failures may contain credentials; keep diagnostics in the redacted child logs.
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print("Pipeline execution rejected: " + detail, file=sys.stderr)
        raise SystemExit(1) from None
