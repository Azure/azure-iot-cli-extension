# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Serial Hub controller. Gate from stdlib-only checkout via runpy.run_path(__file__).

HubControl: 155m execution + 15m cleanup + 5m admission = 175m controller.
HubData: 210m Entra + 100m SAS + 15m cleanup EACH + 5m admission = 345m controller.
Use 190m/360m jobs respectively, leaving another 15m for external setup.
Cleanup is a shared child-unwind/parent-verification budget, never an extra grace.
"""

import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import threading
import time
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
BUDGETS = {"HubControl": (("regular", 155 * 60),), "HubData": (("entra", 210 * 60), ("sas", 100 * 60))}
CLEANUP = 15 * 60
RESERVE = 5 * 60
HUB_LIMIT = 50  # Conservative documented subscription limit; includes every foreign Hub.
# Module-scoped fixtures coexist across state functions, including two migration
# destinations and a separate only-Hubs fixture. Reserve conservatively; the
# observer also rechecks all-subscription Hub capacity at each actual Hub create.
SLOTS = {"regular": 8, "entra": 4, "sas": 1}
FOCUSED = runpy.run_path(str(ROOT / "azext_iot/tests/_focused_live.py"))


def selection():
    return runpy.run_path(str(ROOT / "azext_iot/tests/_hub_suite_manifest.py"))


def helper():
    return runpy.run_path(str(ROOT / "azext_iot/tests/_hub_ownership.py"))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def phase_errors(receipt, expected, suite, phase, run_id, *, debug=None):
    errors = []
    if (receipt.get("schemaVersion") != 1 or receipt.get("suite") != suite or receipt.get("phase") != phase
            or receipt.get("runId") != run_id or receipt.get("finished") is not True
            or receipt.get("exitstatus") != 0 or receipt.get("errors")
            or receipt.get("expected") != expected or receipt.get("collected") != expected
            or len(set(expected)) != len(expected) or not FOCUSED["matches"](receipt, debug)):
        errors.append("phase identity, completion or exact collection failed")
    reports = receipt.get("reports", {})
    if set(reports) != set(expected) or any(
        reports.get(node) != {stage: ["passed"] for stage in ("setup", "call", "teardown")} for node in expected
    ):
        errors.append("every required node must pass once including setup/teardown; skips forbidden")
    return errors


def write_junit(receipt, expected, path):
    """Publish only manifest identities and outcomes, never captured output or tracebacks."""
    suite = ET.Element("testsuite", name="hub-" + receipt["phase"], tests=str(len(expected)))
    if receipt.get("mode") == "debug":
        suite.set("mode", "debug")
    failures = 0
    for node in expected:
        module, _, name = node.rpartition("::")
        case = ET.SubElement(suite, "testcase", classname=module, name=name, time="0")
        reports = receipt.get("reports", {}).get(node, {})
        if reports != {stage: ["passed"] for stage in ("setup", "call", "teardown")}:
            failures += 1
            ET.SubElement(case, "error", message="Required case did not pass all stages; see redacted phase evidence.")
    suite.set("errors", str(failures))
    suite.set("failures", "0")
    suite.set("skipped", "0")
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
    os.chmod(path, 0o600)


def sas_errors(data, expected, *, debug=None):
    """Validate existing SAS evidence without changing its membership/receipt format."""
    owned = helper()
    errors = []
    ids = data.get("ids", {})
    uid = data.get("runUid", "")
    if (data.get("phase") != "local-auth" or not data.get("runUid")
            or set(ids) != {"hub", "storage", "container", "role"}
            or not all(owned["scope_id"](value) for value in ids.values())
            or len(set(value.casefold() for value in ids.values())) != 4
            or sorted(data.get("passed", [])) != sorted(expected)
            or sorted(data.get("absent", [])) != sorted(ids)
            or data.get("cleanupFailures") != {} or not FOCUSED["matches"](data, debug)):
        errors.append("invalid SAS ownership, passes or cleanup")
    if ids:
        prefix = f"/subscriptions/{owned['SUBSCRIPTION']}/resourceGroups/{owned['GROUP']}/providers/"
        hub = prefix + "Microsoft.Devices/IotHubs/test-hubsas-" + uid
        storage = prefix + "Microsoft.Storage/storageAccounts/hubsas" + uid[:18]
        if (ids.get("hub") != hub or ids.get("storage") != storage
                or ids.get("container") != storage + "/blobServices/default/containers/devices"
                or not ids.get("role", "").startswith(hub + "/providers/Microsoft.Authorization/roleAssignments/")):
            errors.append("SAS IDs do not match the owned run")
        consumers = {(hub + "/eventHubEndpoints/events/ConsumerGroups/" + name).casefold()
                     for name in ("test1", "test2", "test3", "test4")}
        if set(data.get("consumerGroupIds", [])) != consumers:
            errors.append("SAS consumer group manifest mismatch")
    mutations, statuses = data.get("mutations", []), data.get("statuses", {})
    if len(set(mutations)) != len(mutations) or set(statuses) != set(mutations):
        errors.append("missing/duplicate/uncertain SAS mutation status")
    required = {"PUT " + value.casefold() for value in ids.values()}
    allowed = {value.casefold() for value in ids.values()} | set(data.get("consumerGroupIds", []))
    if any(m.split(" ", 1)[0] not in ("PUT", "PATCH", "DELETE")
           or m.split(" ", 1)[-1] not in allowed for m in mutations):
        errors.append("SAS mutation outside exact owned manifest")
    if not required.issubset(mutations) or any(
        not isinstance(status, int) or not 200 <= status < 300 for status in statuses.values()
    ):
        errors.append("SAS creation/mutation not confirmed")
    return errors


def evaluate_hub_phases(result_dir, *, debug=False):
    """Pure JSON gate, no pytest/Azure imports. Return {passed: bool, errors: list}.

    Load with runpy.run_path(path) to bypass Azure-dependent package __init__ files.
    The checkout's manifest, NOT artifact-supplied node counts, is authoritative.
    """
    errors = []
    try:
        output = Path(result_dir)
        summary = read_json(output / "hub-phases.json")
        suite = summary["suite"]
        requested = summary.get("debug", {})
        request = FOCUSED["select"](suite, requested.get("phase"), requested.get("requestedNodes")) if debug else {}
        if debug and (not isinstance(request, dict) or request != requested):
            raise ValueError("Invalid debug provenance")
        names = (request["phase"],) if request else selection()["phases"](suite)
        results = summary["phases"]
        owned = helper()
        if (summary.get("schemaVersion") != 1
                or (summary.get("subscription"), summary.get("resourceGroup"), summary.get("region"),
                    summary.get("endpoint")) != (owned["SUBSCRIPTION"], owned["GROUP"], owned["REGION"], owned["ARM"])
                or summary.get("status") != ("debug-passed" if debug else "passed")
                or not FOCUSED["matches"](summary, request) or summary.get("cancelled") is not False
                or summary.get("finished") is not True or [p["name"] for p in results] != list(names)):
            errors.append("incomplete, cancelled, duplicate or missing phase execution")
        if len({p["runId"] for p in results}) != len(results) or any(not p["runId"] for p in results):
            errors.append("missing/duplicate phase run identity")
        known_ids = set()
        for result in results:
            name, run_id = result["name"], result["runId"]
            if name not in names:
                errors.append("unexpected phase")
                continue
            expected = request["requestedNodes"] if request else list(selection()["nodes"](suite, name))
            errors.extend(phase_errors(read_json(output / name / "pytest.json"), expected, suite, name, run_id,
                                       debug=request))
            junit = ET.parse(output / name / "junit.xml").getroot()
            cases = list(junit.iter("testcase"))
            if ([case.get("classname", "") + "::" + case.get("name", "") for case in cases] != expected
                    or any(list(case) for case in cases) or junit.get("mode", "full") != ("debug" if debug else "full")):
                errors.append("missing or unsuccessful sanitized JUnit coverage")
            if (result.get("status") != "passed" or result.get("exit_code") != 0
                    or result.get("timed_out") is not False or result.get("interrupted") is not False
                    or not FOCUSED["matches"](result, request)):
                errors.append("phase execution failed")
            cleanup = read_json(output / name / "cleanup.json")
            evidence = read_json(output / name / "ownership.json")
            if name == "sas":
                errors.extend(sas_errors(evidence, expected, debug=request))
                ids = sorted(value.casefold() for value in evidence["ids"].values())
                if result.get("sasRunUid") != evidence.get("runUid"):
                    errors.append("SAS receipt identity mismatch")
            else:
                errors.extend(helper()["ownership_errors"](evidence, run_id, name))
                ids = sorted(evidence["resources"])
                children = sorted(helper()["descendants"](evidence))
                if (cleanup.get("descendantIds") != children or cleanup.get("absentDescendantIds") != children):
                    errors.append("owned descendant resource absence not proven")
            if (cleanup.get("runId") != run_id or cleanup.get("complete") is not True
                    or cleanup.get("ownedIds") != ids or cleanup.get("absentIds") != ids
                    or cleanup.get("errors") != []):
                errors.append("owned resource absence not proven")
            if known_ids.intersection(ids):
                errors.append("authentication phases reused resources")
            known_ids.update(ids)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError):
        errors.append("missing or malformed Hub phase evidence")
    return {"passed": not errors, "errors": errors}


def environment(base, suite, phase, folder, run_id, subscription, group, *, debug=None):
    forbidden = {
        "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTEST_XDIST_AUTO_NUM_WORKERS", "PYTEST_CURRENT_TEST",
        "AZURE_IOT_AUTH_TYPE", "AZURE_IOT_CONNECTION_STRING", "AZURE_DEFAULTS_GROUP", "AZURE_DEFAULTS_LOCATION",
        "azext_iot_testhub", "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_ep_rg",
        "azext_iot_teststorageaccount", "azext_iot_teststoragecontainer",
        FOCUSED["ENV"], FOCUSED["DPS_ARGS_ENV"],
    }
    for key, value in base.items():
        managed = key.startswith(("AZEXT_IOT_HUB_", "azext_iot_hubsas_", "azext_iot_dps_", "AZURE_IOT_"))
        if value and (key in forbidden or managed or key == "azext_iot_hub_auth_phase"):
            raise ValueError("Ambient resource/auth/selection override rejected: " + key)
    for key, expected in (("azext_iot_testrg", group), ("azext_iot_testhub_location", "centraluseuap")):
        if base.get(key) and base[key] != expected:
            raise ValueError("Conflicting ambient resource scope: " + key)
    result = dict(
        base, AZURE_TEST_RUN_LIVE="True", AZURE_IOT_AUTH_TYPE="login",
        azext_iot_testrg=group, azext_iot_testhub_location="centraluseuap",
        AZEXT_IOT_HUB_SUITE=suite, AZEXT_IOT_HUB_PHASE=phase, AZEXT_IOT_HUB_RUN_ID=run_id,
        AZEXT_IOT_HUB_RECEIPT=str(folder / "pytest.json"),
        AZEXT_IOT_HUB_OWNERSHIP=str(folder / "ownership.json"),
        azext_iot_hub_auth_phase="local-auth" if phase == "sas" else "regular",
        azext_iot_hubsas_subscription=subscription, azext_iot_hubsas_receipt=str(folder / "ownership.json"),
    )
    result["AZURE_DEFAULTS_IOTHUB-DATA-AUTH-TYPE"] = "login"
    if debug:
        result[FOCUSED["ENV"]] = json.dumps(debug)
        # Debug evidence is fresh and phase-local, never appended to a checkout's
        # possibly incompatible (statement/branch) or concurrently written database.
        result["COVERAGE_FILE"] = str((folder / ".coverage").resolve())
    return result


def command(suite, phase, *, debug=None, folder=None):
    return [
        sys.executable, "-m", "pytest", "-c", str(ROOT / "setup.cfg"),
        "--rootdir", str(ROOT), "--confcutdir", str(ROOT), "-p", "azext_iot.tests._hub_suite_plugin",
        "-p", "no:rerunfailures", "-n", "0", "--timeout=900", "--integration-progress-interval=60",
        # Debug keeps real deadlines/tracebacks, but opts out of periodic stack dumps.
        "-o", "faulthandler_timeout=0" if debug else "faulthandler_timeout=300",
        "-o", "addopts=", "-o", "env=", "-o", "log_cli=false",
        "--cov=azext_iot", "--cov-append", "--cov-config", str(ROOT / ".coveragerc"),
        f"--cov-report=xml:{(folder / 'coverage.xml').resolve()}" if debug and folder else "--cov-report=",
        "--capture=fd", "-vv", *(debug["requestedNodes"] if debug else selection()["nodes"](suite, phase)),
    ]


def cleanup_regular(arm, evidence, run_id, phase, deadline, path):
    owned = helper()
    arm.deadline = deadline
    # Only structurally valid receipts may authorize even reconciliation reads.
    errors = owned["ownership_errors"](evidence, run_id, phase)
    if errors and set(errors) <= {"unresolved mutation; no replay permitted", "unreconciled asynchronous acceptance"}:
        owned["reconcile"](arm, evidence, deadline, lambda: owned["write"](path, evidence))
        errors = owned["ownership_errors"](evidence, run_id, phase)
    ids = sorted(evidence.get("resources", {}))
    result = {"runId": run_id, "ownedIds": ids, "absentIds": [], "errors": errors, "complete": False,
              "descendantIds": [], "absentDescendantIds": []}
    # Never replay a possibly accepted mutation, even when the latest GET is 404.
    if errors:
        return result
    arm.deadline = deadline
    for resource_id in ids:
        record = evidence["resources"][resource_id]
        api = record["apiVersion"]
        status, resource = arm.request("GET", resource_id, api)
        if status != 404 and (
            resource.get("id", "").casefold() != resource_id
            or resource.get("tags", {}).get(owned["OWNER_TAG"]) != run_id
        ):
            result["errors"].append("Cleanup target ownership changed; no delete permitted")
            continue
        deleted = any(m["method"] == "DELETE" and m["id"] == resource_id for m in record["mutations"])
        if status != 404 and not deleted:
            # Persist intent BEFORE sending; a crash/timeout never permits a second DELETE.
            record["mutations"].append({"method": "DELETE", "id": resource_id, "apiVersion": api, "status": None})
            record["uncertain"] = True
            owned["write"](path, evidence)
            status, _ = arm.request("DELETE", resource_id, api)
            record["mutations"][-1]["status"] = status
            record["uncertain"] = status == 202 or status not in (200, 204, 404)
            owned["write"](path, evidence)
            if status not in (200, 202, 204, 404):
                result["errors"].append("Cleanup delete failed; no replay permitted")
                continue
        while time.monotonic() < deadline:
            status, _ = arm.request("GET", resource_id, api)
            if status == 404:
                owned["observe_get"](evidence, resource_id, status, None)
                owned["write"](path, evidence)
                result["absentIds"].append(resource_id)
                break
            time.sleep(min(5, max(0, deadline - time.monotonic())))
    children = owned["descendants"](evidence)
    result["descendantIds"] = sorted(children)
    for resource_id in sorted(children):
        status, _ = arm.request("GET", resource_id, children[resource_id])
        if status == 404:
            result["absentDescendantIds"].append(resource_id)
    result["complete"] = (not result["errors"] and result["absentIds"] == ids
                          and result["absentDescendantIds"] == result["descendantIds"])
    return result


def run(suite, subscription, group, region, output, arm=None, execute=None, base=None, *,
        debug_phase=None, debug_nodes=None):
    debug = FOCUSED["select"](suite, debug_phase, debug_nodes)
    sys.path.insert(0, str(ROOT))
    from azext_iot.tests._dps_phase_runner import child, require_linux, write_json
    require_linux()
    owned = helper()
    if (subscription, group, region) != (owned["SUBSCRIPTION"], owned["GROUP"], owned["REGION"]):
        raise ValueError("Controller is restricted to the authorized canary scope")
    output = Path(output).resolve()
    base = dict(os.environ if base is None else base)
    budgets = tuple(value for value in BUDGETS[suite] if not debug or value[0] == debug["phase"])
    environment(base, suite, budgets[0][0], output, "preflight", subscription, group, debug=debug)
    output.mkdir(parents=True, exist_ok=False)
    cancel = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: cancel.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    summary = {
        "schemaVersion": 1, "suite": suite, "status": "failed", "cancelled": False, "finished": False,
        "subscription": subscription, "resourceGroup": group, "region": region, "endpoint": owned["ARM"],
        "runnerSeconds": sum(runtime + CLEANUP for _, runtime in budgets) + RESERVE,
        "phases": [{"name": name, "status": "blocked", "runId": uuid4().hex,
                    **FOCUSED["provenance"](debug)} for name, _ in budgets],
        **FOCUSED["provenance"](debug),
    }
    summary_path = output / "hub-phases.json"
    write_json(summary_path, summary)
    deadline = time.monotonic() + summary["runnerSeconds"]
    try:
        arm = arm or owned["Arm"]()
        for result, (phase, runtime) in zip(summary["phases"], budgets):
            if cancel.is_set():
                break
            arm.deadline = min(deadline, time.monotonic() + RESERVE)
            inventory = arm.inventory()  # All subscription Hubs, never DPS inventory.
            result["capacity"] = {"ids": inventory, "prospective": SLOTS[phase], "limit": HUB_LIMIT}
            if len(inventory) + SLOTS[phase] > HUB_LIMIT:
                break
            if time.monotonic() + runtime + CLEANUP > deadline:
                break
            folder = output / phase
            folder.mkdir()
            env = environment(base, suite, phase, folder, result["runId"], subscription, group, debug=debug)
            result.update(status="running", runtimeSeconds=runtime, cleanupSeconds=CLEANUP)
            write_json(summary_path, summary)
            # pytest node args are repository-relative; retain every inherited dependency path.
            cwd = Path.cwd()
            try:
                os.chdir(ROOT)
                execution = (execute or child)(command(suite, phase, debug=debug, folder=folder), env, folder / "output.log",
                                               runtime, CLEANUP, cancel.is_set)
            finally:
                os.chdir(cwd)
            result.update({k: v for k, v in execution.items() if k != "cleanup_deadline"})
            cleanup = {"runId": result["runId"], "complete": False, "errors": ["missing ownership evidence"]}
            try:
                evidence = read_json(folder / "ownership.json")
                if phase == "sas":
                    result["sasRunUid"] = evidence["runUid"]
                    errors = sas_errors(evidence, debug["requestedNodes"] if debug else
                                        list(selection()["nodes"](suite, phase)), debug=debug)
                    ids = sorted(value.casefold() for value in evidence["ids"].values())
                    cleanup = {"runId": result["runId"], "complete": not errors, "errors": errors,
                               "ownedIds": ids, "absentIds": ids if not errors else []}
                else:
                    cleanup = cleanup_regular(arm, evidence, result["runId"], phase,
                                              min(deadline, execution["cleanup_deadline"]), folder / "ownership.json")
                    write_json(folder / "ownership.json", evidence)
                receipt = read_json(folder / "pytest.json")
                expected = debug["requestedNodes"] if debug else list(selection()["nodes"](suite, phase))
                write_junit(receipt, expected, folder / "junit.xml")
                receipt_errors = phase_errors(receipt, expected, suite, phase, result["runId"], debug=debug)
                result["receiptErrors"] = receipt_errors
                result["status"] = "passed" if (
                    not receipt_errors and cleanup["complete"] and execution["exit_code"] == 0
                    and not execution["timed_out"] and not execution["interrupted"] and not cancel.is_set()
                ) else "failed"
            except Exception as error:  # Never serialize credential-bearing exception messages.
                result["status"] = "failed"
                result["errorType"] = type(error).__name__
            write_json(folder / "cleanup.json", cleanup)
            write_json(summary_path, summary)
            if not cleanup["complete"] or execution["interrupted"] or execution["timed_out"]:
                break
        summary["status"] = "passed" if all(p["status"] == "passed" for p in summary["phases"]) else "failed"
    except Exception as error:
        summary["errorType"] = type(error).__name__
    finally:
        if debug:
            summary["status"] = "debug-passed" if summary["status"] == "passed" else "debug-failed"
        summary["cancelled"] = cancel.is_set()
        summary["finished"] = True
        write_json(summary_path, summary)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0 if evaluate_hub_phases(output, debug=bool(debug))["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(BUDGETS), required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", default="test-result/hub-phases")
    FOCUSED["add_arguments"](parser)
    args = parser.parse_args()
    try:
        return run(args.suite, args.subscription, args.resource_group, args.region, args.output,
                   debug_phase=args.debug_phase, debug_nodes=args.debug_node)
    except ValueError as error:
        print("Hub controller rejected launch: " + str(error), flush=True)
        return 1
    except Exception as error:
        print("Hub controller rejected launch: " + type(error).__name__, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
