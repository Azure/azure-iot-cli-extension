# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Pipeline 147 planning, phase execution, and immutable manual-attempt aggregation."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
from threading import Event
import time

ROOT = Path(__file__).resolve().parents[2]
RETRY = runpy.run_path(str(ROOT / "azext_iot/tests/_ado_retry.py"))
TARGET = runpy.run_path(str(ROOT / "azext_iot/tests/_integration_target.py"))
BUDGETS = json.loads((ROOT / "azext_iot/tests/ci_budgets.json").read_text(encoding="utf-8"))


def plan(services, versions, regions, endpoint, diagnostic=False):
    if not services or len(set(services)) != len(services) or not set(services) <= set(RETRY["SERVICES"]):
        raise ValueError("Select distinct supported services.")
    if not versions or len(set(versions)) != len(versions) or not set(versions) <= {"3.10", "3.11", "3.12", "3.13"}:
        raise ValueError("Select distinct supported Python versions.")
    if not regions or len(set(regions)) != len(regions):
        raise ValueError("Select distinct regions.")
    jobs = []
    for service in (["RetrySelfTest"] if diagnostic else services):
        if not diagnostic and not (ROOT / BUDGETS[service]["test_dir"]).is_dir():
            raise ValueError(f"{service} is unavailable on this branch.")
        for version in versions:
            for region in regions:
                target = TARGET["target"](region, endpoint)
                jobs.append({"service": service, "python": version, **target,
                             "minutes": 10 if diagnostic else BUDGETS[service]["job_timeout_minutes"]})
    if len(jobs) > 40:
        raise ValueError("Select at most 40 combinations per run.")
    return jobs


def admission():
    import requests
    with requests.get(
        "https://api.github.com/repos/Azure/azure-iot-cli-extension/actions/workflows/int_test.yml/runs",
        params={"status": "in_progress", "per_page": 1}, timeout=(10, 30), allow_redirects=False,
    ) as response:
        if response.status_code != 200:
            raise RuntimeError("GitHub live-run admission could not be checked.")
        if response.json()["total_count"]:
            raise ValueError("A GitHub integration run is active.")


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
    return {
        "build": os.environ["BUILD_BUILDID"], "definition": os.environ["SYSTEM_DEFINITIONID"],
        "commit": os.environ["BUILD_SOURCEVERSION"],
        "wheel": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
        "dependencies": RETRY["digest"](dependencies),
        "service": service, "python": python, "region": region, "endpoint": endpoint,
        "subscription": TARGET["SUBSCRIPTION"], "resource_group": TARGET["RESOURCE_GROUP"],
        "diagnostic": str(diagnostic).lower(),
    }


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
    plans = sorted(Path(directory).glob("integration-plan-*/plan.json"))
    if not plans or any(RETRY["read"](path) != RETRY["read"](plans[0]) for path in plans):
        raise ValueError("Missing or changed execution plan.")
    expected = RETRY["read"](plans[0])
    paths = list(Path(directory).rglob("attempt.json"))
    records = [RETRY["read"](path) for path in paths]
    keys = {(value["service"], value["python"], value["region"]) for value in expected}
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
        if (ctx["build"] != os.environ["BUILD_BUILDID"] or ctx["commit"] != os.environ["BUILD_SOURCEVERSION"]
                or ctx["endpoint"] != config["endpoint"] or ctx["wheel"] != wheel
                or ctx["subscription"] != TARGET["SUBSCRIPTION"] or ctx["resource_group"] != TARGET["RESOURCE_GROUP"]):
            raise ValueError("Evidence belongs to a different run/commit/target.")
        original, _, _ = RETRY["evaluate"](history, ctx)
        owned = owned_nodes(config["service"])
        if owned and {phase: list(nodes) for phase, nodes in original.items()} != owned:
            raise ValueError("Original phase selection does not cover the authoritative service manifest.")
        if RETRY["pending"](history, ctx):
            raise ValueError("Unresolved failures remain.")
    diagnostic = any(value["context"]["diagnostic"] == "true" for value in records)
    print("Diagnostic retry proof passed; NOT release qualification." if diagnostic
          else "Every expected service combination passed; manual retry history is retained.")


def coverage(directory):
    files = list(Path(directory).rglob(".coverage"))
    if not files:
        raise ValueError("No coverage artifacts were produced.")
    subprocess.run([sys.executable, "-m", "coverage", "combine", "--keep", *map(str, files)], check=True)
    subprocess.run([sys.executable, "-m", "coverage", "xml"], check=True)
    subprocess.run([sys.executable, "-m", "coverage", "html"], check=True)


def owned_nodes(service):
    if service == "DPS":
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/dps/_phase_manifest.py"))
        return {phase: sorted("azext_iot/tests/dps/" + node for node in manifest["expected_nodeids"](phase))
                for phase in manifest["PHASE_NAMES"]}
    if service.startswith("Hub"):
        manifest = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_suite_manifest.py"))
        return {phase: list(manifest["nodes"](service, phase)) for phase in manifest["phases"](service)}
    return {}


def dps_evidence(folder, selection, ctx):
    dps = runpy.run_path(str(ROOT / "azext_iot/tests/_dps_phase_runner.py"))
    hub = runpy.run_path(str(ROOT / "azext_iot/tests/_hub_phase_runner.py"))
    summary = RETRY["read"](folder / "dps-phases.json")
    phase = selection["phase"]
    result, = summary["phases"]
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
    import xml.etree.ElementTree as ET
    cases = list(ET.parse(directory / "junit.xml").getroot().iter("testcase"))
    outcomes = RETRY["outcomes"](receipt)
    actual = {}
    for case in cases:
        node = "azext_iot/tests/dps/" + dps["MANIFEST"]["junit_nodeid"](case)
        if node in actual or [child.tag for child in case] not in ([], ["failure"]):
            raise ValueError("DPS JUnit contains duplicate, skipped or unsafe cases.")
        actual[node] = "failed" if list(case) else "passed"
    if selected != len(outcomes) or actual != outcomes:
        raise ValueError("DPS collection/JUnit disagrees with phase evidence.")
    baseline = {resource["id"].casefold() for resource in summary["baseline"]["resources"]}
    records = dps["ownership"](directory / "receipts", phase, result["run_uid"], ctx["subscription"],
                               ctx["resource_group"], baseline, region=ctx["region"], endpoint=ctx["endpoint"])
    ids = [record["id"] for record in records]
    cleanup = result["cleanup"]
    if (cleanup.get("complete") is not True or cleanup.get("remaining") != []
            or set(cleanup["owned_ids"]) != set(ids) or set(cleanup["absent_ids"]) != set(ids)
            or any(not record["creation_resolved"] for record in records)
            or {value.casefold() for value in ids}.intersection(cleanup["inventory_ids"])):
        raise ValueError("DPS ownership/resource absence is unproven.")
    return receipt


def phase(selection_file, output):
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
        env = dict(os.environ, azext_iot_ado_receipt=str(folder / "pytest.json"),
                   azext_iot_ado_expected=json.dumps(value["expected"]),
                   azext_iot_ado_selected=json.dumps(nodes),
                   azext_iot_ado_diagnostic_attempt=str(value["sequence"]),
                   COVERAGE_FILE=str(folder / ".coverage"))
        directory = ("azext_iot/tests/ado_diagnostic.py" if diagnostic else BUDGETS[service]["test_dir"])
        command = [sys.executable, "-m", "pytest", directory, "-vv", "-c", str(ROOT / "setup.cfg"),
                   "-o", "addopts=", "-o", "env=", "-p", "azext_iot.tests._ado_retry_plugin",
                   "-p", "no:rerunfailures", "--timeout=900", "--integration-progress-interval=60",
                   "-o", "faulthandler_timeout=300", "--cov=azext_iot", "--cov-config=.coveragerc",
                   "--cov-report=", "--capture=fd", "-n", "0" if diagnostic else ("4" if service == "ADR" else "7")]
        if not diagnostic:
            command += ["-k", "_int.py", "--dist=loadgroup" if service == "ADR" else "--dist=loadfile"]
        execution = dps.child(command, env, folder / "output.log",
                              (10 if diagnostic else BUDGETS[service]["job_timeout_minutes"] - 20) * 60, 600)
        if execution["timed_out"] or execution["interrupted"]:
            raise ValueError("Timed out/interrupted execution cannot qualify.")
        receipt = RETRY["read"](folder / "pytest.json")
        if execution["exit_code"] != receipt["exitstatus"]:
            raise ValueError("Execution status disagrees with test evidence.")
        expected = receipt["expected"]
    RETRY["outcomes"](receipt)
    RETRY["write"](folder / "phase.json", {
        "expected": expected, "receipt": receipt, "safe": True, "excluded": receipt.get("excluded", []),
    })


def run(args):
    from azext_iot.tests import _dps_phase_runner as dps
    ctx = context(args.service, args.python, args.region, args.endpoint, args.wheel, args.diagnostic)
    history = RETRY["load_history"](args.history, ctx)
    native_attempt = int(os.environ["SYSTEM_JOBATTEMPT"])
    if native_attempt != len(history) + 1:
        raise ValueError("An intervening native job attempt is missing; start a new full run.")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    prior_expected, _, _ = RETRY["evaluate"](history, ctx)
    remaining = RETRY["pending"](history, ctx) if history else owned_nodes(args.service) or {"tests": []}
    record = {
        "schema": 1, "context": ctx, "sequence": len(history) + 1, "nativeAttempt": native_attempt,
        "parent": RETRY["digest"](history[-1]) if history else None, "healthy": False, "phases": {},
    }
    if history and not remaining:
        record.update(healthy=True, reused=True)
        RETRY["write"](output / "reuse.json", {"parent": record["parent"], "nativeAttempt": native_attempt})
        record["evidence"] = RETRY["evidence"](output)
        RETRY["write"](output / "attempt.json", record)
        history.append(record)
        RETRY["junit"](history, ctx, output / "final.xml")
        print("Already passed; retaining original evidence without executing tests.")
        return 0
    if not args.diagnostic:
        admission()
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
            expected = list(prior_expected.get(name, owned_nodes(args.service).get(name, [])))
            RETRY["write"](selection, {"context": ctx, "phase": name, "nodes": nodes, "expected": expected,
                                       "sequence": record["sequence"], "parent": record["parent"]})
            minutes = 10 if args.diagnostic else BUDGETS[args.service]["job_timeout_minutes"]
            result = dps.child(
                [sys.executable, str(Path(__file__)), "phase", "--selection", str(selection),
                 "--output", str(output / name)], dict(os.environ), output / f"{name}.log", minutes * 60, 120,
                lambda: cancel.is_set() or auth is not None and auth.poll() is not None,
            )
            if result["exit_code"] or result["timed_out"] or result["interrupted"]:
                raise ValueError(f"{name}: execution/cleanup evidence incomplete. See redacted attempt logs.")
            return name, RETRY["read"](output / name / "phase.json")

        with ThreadPoolExecutor(max_workers=len(remaining)) as pool:
            for name, value in pool.map(execute, remaining.items()):
                record["phases"][name] = value
        if auth is not None:
            if auth.poll() is not None:
                raise ValueError("Credential refresher stopped unexpectedly.")
            auth.terminate()
            if auth.wait(timeout=180):
                raise ValueError("Credential refresh failed.")
            auth = None
        record["healthy"] = not cancel.is_set()
    finally:
        try:
            if auth is not None:
                if auth.poll() is None:
                    auth.terminate()
                auth.wait(timeout=180)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            record["evidence"] = RETRY["evidence"](output)
            RETRY["write"](output / "attempt.json", record)
    history.append(record)
    failures = RETRY["junit"](history, ctx, output / "final.xml")
    _, effective, recovered = RETRY["evaluate"](history, ctx)
    summary = (f"## {args.service}: {'Failed' if failures else 'Passed'}\n\n"
               f"{sum(map(len, effective.values()))} required cases; {failures} unresolved; "
               f"{len(recovered)} passed on manual retry. Diagnostic: {ctx['diagnostic']}.\n")
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
    runner = commands.add_parser("run")
    for name in ("service", "python", "region", "endpoint", "wheel", "history", "output"):
        runner.add_argument("--" + name, required=True)
    runner.add_argument("--diagnostic", action="store_true")
    phase_parser = commands.add_parser("phase")
    phase_parser.add_argument("--selection", required=True)
    phase_parser.add_argument("--output", required=True)
    for name in ("gate", "coverage", "candidate"):
        subparser = commands.add_parser(name)
        subparser.add_argument("--history", required=True)
        if name == "candidate":
            subparser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        print(json.dumps(plan(args.services, args.versions, args.regions, args.endpoint, args.diagnostic), indent=2))
        return 0
    if args.command == "phase":
        phase(args.selection, args.output)
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
