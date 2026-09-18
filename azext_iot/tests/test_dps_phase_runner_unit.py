# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline runner tests: fake ARM inventories/fixtures and harmless local child processes."""

from contextlib import nullcontext
import ast
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
import responses

ROOT = Path(__file__).resolve().parents[2]
RUNNER = runpy.run_path(str(ROOT / "azext_iot/tests/_dps_phase_runner.py"))
RUN = RUNNER["run"]
GATE = runpy.run_path(str(ROOT / "azext_iot/tests/_evaluate_test_results.py"))["evaluate_dps_phases"]
SUB = "11111111-2222-3333-4444-555555555555"
GROUP = "isolated-tests"
PREFIX = f"/subscriptions/{SUB}/resourceGroups/{GROUP}/providers/Microsoft.Devices/"


class Reader:
    def __init__(self, count=3):
        self.resources = [{"id": PREFIX + f"provisioningServices/baseline-{i}", "tags": {}} for i in range(count)]
        self.gets = []
        self.inventories = 0

    def inventory(self):
        self.inventories += 1
        return list(self.resources)

    def get(self, record):
        self.gets.append(record["id"])
        return None


def _json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _execution(command, env, log, _runtime, cleanup, _cancelled):
    assert command[1:] == ["-m", "tox", "r", "-e", "DPS-int", "--skip-pkg-install"]
    phase = env["azext_iot_dps_test_phase"]
    assert env["azext_iot_dps_workers"] == ("0" if phase == "local-auth-toggle" else "7")
    uid = env["azext_iot_dps_run_uid"]
    nodeids = sorted(RUNNER["MANIFEST"]["expected_nodeids"](phase))
    count = len(nodeids)
    directory = Path(env["azext_iot_dps_phase_receipts"])
    metadata = {"phase": phase, "run_uid": uid, "subscription": SUB}
    _json(directory / "started.json", dict(metadata, started=True))
    _json(directory / "selection-gw0.json", {"selected": count, "nodeids": nodeids})
    for kind in RUNNER["MANIFEST"]["resource_kinds"](phase):
        name = f"owned-{uid[:8]}-{kind}"
        resource_id = PREFIX.partition("/providers/")[0] + "/providers/" + RUNNER["MANIFEST"]["resource_type"](kind) + "/" + name
        _json(directory / f"owned-{kind}.json", dict(
            metadata, kind=kind, name=name, resource_group=GROUP, id=resource_id, create_attempted=True,
            tags={"intTest": "true", "runUid": uid if phase == "regular" else uid + "-" + phase, "kind": kind},
        ))
        _json(directory / f"created-{kind}.json", {"id": resource_id, "create_completed": True})
    suite = ET.Element("testsuite")
    for nodeid in nodeids:
        module, name = nodeid.split("::")
        case = ET.SubElement(suite, "testcase", name=name, classname="azext_iot.tests.dps." + module[:-3].replace("/", "."))
        ET.SubElement(case, "system-out").text = "UNSAFE_CAPTURED_CREDENTIAL"
    ET.ElementTree(suite).write(env["azext_iot_dps_junit"])
    log.write_text("Sanitized phase output\n", encoding="utf-8")
    return {"exit_code": 0, "timed_out": False, "interrupted": False,
            "cleanup_deadline": time.monotonic() + cleanup}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in (
        "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub", "azext_iot_dps_test_phase", "azext_iot_dps_run_uid",
        "azext_iot_dps_phase_receipts", "azext_iot_dps_junit", "azext_iot_dps_interrupt_timeout",
        "azext_iot_dps_workers",
    ):
        monkeypatch.delenv(name, raising=False)


def test_serial_success_preserves_real_baseline_and_distinct_sanitized_artifacts(tmp_path):
    reader = Reader()
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=_execution) == 0
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    assert summary["baseline"]["capacity"]["count"] == 3  # Neither hardcoded eight nor assumed empty.
    assert reader.inventories == 6  # Baseline, each cleanup, and both pre-phase gates.
    assert len(reader.gets) == 23  # Eight regular IDs and three SAS IDs, each rechecked, then one toggle DPS.
    assert summary["baseline"]["capacity"]["required"] == 4
    assert [phase["gate"]["capacity"]["required"] for phase in summary["phases"][1:]] == [2, 1]
    assert all(phase["cleanup"]["capacity"]["required"] == 4 for phase in summary["phases"])
    assert not GATE(tmp_path)
    for phase in RUNNER["MANIFEST"]["PHASE_NAMES"]:
        folder = tmp_path / "dps-phases" / phase
        assert (folder / "output.log").is_file()
        assert "UNSAFE_CAPTURED_CREDENTIAL" not in (folder / "junit.xml").read_text()
    with pytest.raises(FileExistsError):
        RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=_execution)


@pytest.mark.parametrize("defect", ["cleanup", "reappeared", "unrelated-capacity"])
def test_toggle_waits_for_immediately_previous_sas_cleanup_and_uses_one_slot(tmp_path, defect):
    reader = Reader()

    def execute(*args):
        result = _execution(*args)
        env = args[1]
        if env["azext_iot_dps_test_phase"] == "service-sas":
            directory = Path(env["azext_iot_dps_phase_receipts"])
            if defect == "cleanup":
                (directory / "created-h.json").unlink()
            elif defect == "reappeared":
                previous = reader.get
                reads = []

                def get(record):
                    reads.append(record)
                    previous(record)
                    return {"id": record["id"], "state": "Deleting"} if len(reads) > 3 else None
                reader.get = get
            else:
                reader.resources = Reader(9).resources
        return result

    status = RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute)
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    toggle = summary["phases"][2]
    if defect == "unrelated-capacity":
        assert status == 0 and not GATE(tmp_path)
        assert toggle["gate"]["capacity"]["required"] == 1
        assert toggle["gate"]["capacity"]["count"] == 9
    else:
        assert status == 1 and GATE(tmp_path)
        assert toggle["status"] == "blocked"


@pytest.mark.parametrize("defect", ["missing", "skip", "failed", "ownership", "gate"])
def test_final_gate_requires_complete_toggle_evidence(tmp_path, defect):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    summary_path = tmp_path / "dps-phases.json"
    summary = json.loads(summary_path.read_text())
    toggle = summary["phases"][2]
    folder = tmp_path / "dps-phases/local-auth-toggle"
    if defect == "missing":
        summary["phases"].pop()
    elif defect == "ownership":
        (folder / "receipts/owned-dla.json").unlink()
    elif defect == "skip":
        tree = ET.parse(folder / "junit.xml")
        ET.SubElement(next(tree.getroot().iter("testcase")), "skipped")
        tree.write(folder / "junit.xml")
    elif defect == "failed":
        toggle["exit_code"] = 1
    else:
        toggle["gate"]["capacity"]["ready"] = False
    _json(summary_path, summary)
    _json(folder / "result.json", toggle)
    assert GATE(tmp_path)


@pytest.mark.parametrize("defect", [
    "exit", "timeout", "interrupt", "missing-junit", "missing-selection", "missing-ownership",
    "uncertain-create", "capacity", "baseline-overlap", "reappeared", "five-regular", "regular-skips", "wrong-identity",
])
def test_failed_first_cannot_be_masked_by_successful_second(tmp_path, defect):
    reader = Reader()
    if defect == "reappeared":
        original_get = reader.get

        def get(record):
            original_get(record)
            regular_resources = len(RUNNER["MANIFEST"]["resource_kinds"]("regular"))
            return {"id": record["id"], "state": "Deleting"} if len(reader.gets) > regular_resources else None
        reader.get = get

    def execute(*args):
        result = _execution(*args)
        environment = args[1]
        if environment["azext_iot_dps_test_phase"] == "regular":
            directory = Path(environment["azext_iot_dps_phase_receipts"])
            if defect == "exit":
                result["exit_code"] = 1
            elif defect in ("timeout", "interrupt"):
                result["timed_out" if defect == "timeout" else "interrupted"] = True
            elif defect == "missing-junit":
                Path(environment["azext_iot_dps_junit"]).unlink()
            elif defect == "missing-selection":
                (directory / "selection-gw0.json").unlink()
            elif defect == "missing-ownership":
                for path in directory.glob("owned-*.json"):
                    path.unlink()
            elif defect == "uncertain-create":
                (directory / "created-h.json").unlink()
            elif defect == "capacity":
                reader.resources.extend(Reader(6).resources)
                # Fresh, distinct unrelated resources, not duplicate/partial inventory.
                for index, resource in enumerate(reader.resources):
                    resource["id"] = PREFIX + f"provisioningServices/unrelated-{index}"
            elif defect == "baseline-overlap":
                record = json.loads((directory / "owned-h.json").read_text())
                record.update(name="baseline-0", id=reader.resources[0]["id"])
                _json(directory / "owned-h.json", record)
            elif defect in ("five-regular", "regular-skips", "wrong-identity"):
                raw = Path(environment["azext_iot_dps_junit"])
                tree = ET.parse(raw)
                cases = list(tree.getroot())
                if defect == "five-regular":
                    for case in cases[5:]:
                        tree.getroot().remove(case)
                    selected = json.loads((directory / "selection-gw0.json").read_text())
                    selected.update(selected=5, nodeids=selected["nodeids"][:5])
                    _json(directory / "selection-gw0.json", selected)
                elif defect == "regular-skips":
                    for case in cases[1:]:
                        ET.SubElement(case, "skipped")
                else:
                    cases[0].set("name", "test_unknown")
                tree.write(raw)
        return result

    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute) == 1
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    assert GATE(tmp_path)
    phases = summary["phases"]
    if defect in ("exit", "timeout", "interrupt", "missing-junit", "missing-selection",
                  "five-regular", "regular-skips", "wrong-identity"):
        assert [phase["status"] for phase in phases] == ["failed", "passed", "passed"]
    else:
        assert phases[1]["status"] == "blocked"
        if defect == "reappeared":
            assert len(phases[1]["gate"]["remaining"]) == len(RUNNER["MANIFEST"]["resource_kinds"]("regular"))


@pytest.mark.parametrize("nodeid", sorted(RUNNER["MANIFEST"]["CSR_NODEIDS"]))
@pytest.mark.parametrize("defect", ["missing", "skipped"])
def test_final_gate_requires_each_csr_variant(tmp_path, nodeid, defect):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    path = tmp_path / "dps-phases/regular/junit.xml"
    tree = ET.parse(path)
    case = next(case for case in tree.getroot() if RUNNER["MANIFEST"]["junit_nodeid"](case) == nodeid)
    if defect == "missing":
        tree.getroot().remove(case)
    else:
        ET.SubElement(case, "skipped")
    tree.write(path)
    assert GATE(tmp_path)


@pytest.mark.parametrize("kind", RUNNER["MANIFEST"]["CSR_RESOURCE_KINDS"])
def test_csr_passes_cannot_mask_missing_dedicated_resource_evidence(tmp_path, kind):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    folder = tmp_path / "dps-phases/regular"
    receipt = folder / "receipts" / f"owned-{kind}.json"
    resource_id = json.loads(receipt.read_text())["id"]
    receipt.unlink()
    summary_path = tmp_path / "dps-phases.json"
    summary = json.loads(summary_path.read_text())
    phase = summary["phases"][0]
    for key in ("owned_ids", "absent_ids"):
        phase["cleanup"][key].remove(resource_id)
    _json(summary_path, summary)
    _json(folder / "result.json", phase)
    assert GATE(tmp_path)


@pytest.mark.parametrize("pin", [
    "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub", "azext_iot_dps_test_phase", "azext_iot_dps_run_uid",
    "azext_iot_dps_workers",
])
def test_incompatible_pins_fail_before_inventory_or_execution(tmp_path, monkeypatch, mocker, pin):
    monkeypatch.setenv(pin, "supplied-do-not-clear")
    reader = Reader()
    execute = mocker.Mock()
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute) == 1
    assert not reader.inventories
    execute.assert_not_called()
    assert os.environ[pin] == "supplied-do-not-clear"


def test_insufficient_initial_capacity_blocks_both_phases(tmp_path, mocker):
    execute = mocker.Mock()
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(9), execute=execute) == 1
    execute.assert_not_called()


@pytest.mark.parametrize("count,limit,ready", [
    (7, 10, False), (7, 100, True), (96, 100, True), (97, 100, False), (99, 100, False), (100, 100, False),
])
def test_explicit_subscription_limit_preserves_four_slot_full_admission(tmp_path, mocker, count, limit, ready):
    execute = mocker.Mock(side_effect=_execution)
    reader = Reader(count)
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute, capacity_limit=limit) == (0 if ready else 1)
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    assert summary["baseline"]["capacity"]["limit"] == limit
    assert summary["baseline"]["capacity"]["required"] == 4
    assert summary["baseline"]["capacity"]["ready"] is ready
    if not ready:
        execute.assert_not_called()
        return
    assert "operator-confirmed" in summary["baseline"]["capacity"]["limit_source"]
    assert [phase["gate"]["capacity"]["required"] for phase in summary["phases"][1:]] == [2, 1]
    assert all(phase["gate"]["capacity"]["limit"] == limit for phase in summary["phases"][1:])
    assert all(phase["cleanup"]["capacity"]["limit"] == limit for phase in summary["phases"])
    assert all(phase["cleanup"]["capacity"]["required"] == 4 for phase in summary["phases"])
    assert not GATE(tmp_path, expected_capacity_limit=limit)
    assert GATE(tmp_path)  # Receipt-supplied 100 does not authorize the independent default-ten gate.


@pytest.mark.parametrize("phase,count,ready", [
    ("regular", 98, True), ("regular", 99, False), ("service-sas", 99, True), ("service-sas", 100, False),
])
def test_override_fresh_gates_recheck_inventory_under_same_limit(tmp_path, phase, count, ready):
    reader = Reader(7)

    def execute(*args):
        result = _execution(*args)
        if args[1]["azext_iot_dps_test_phase"] == phase:
            reader.resources = Reader(count).resources
        return result

    status = RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute, capacity_limit=100)
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    next_phase = summary["phases"][1 if phase == "regular" else 2]
    assert next_phase["gate"]["capacity"]["limit"] == 100
    assert next_phase["gate"]["capacity"]["ready"] is ready
    assert status == (0 if ready else 1)
    assert bool(GATE(tmp_path, expected_capacity_limit=100)) is not ready


@pytest.mark.parametrize("invalid", [
    None, True, False, 0, -1, 10.0, "", "0", "-1", "010", "1.0", "1e2", " 100", "100 ",
    "NaN", "\uff11\uff10\uff10", "True", [], {}, b"100",
])
def test_invalid_capacity_limit_fails_before_artifacts_inventory_or_execution(tmp_path, mocker, invalid):
    reader, execute = mocker.Mock(), mocker.Mock()
    with pytest.raises(ValueError, match="capacity limit"):
        RUN(SUB, GROUP, tmp_path / "must-not-exist", reader, execute=execute, capacity_limit=invalid)
    with pytest.raises(ValueError, match="capacity limit"):
        RUNNER["capacity"]([], limit=invalid)
    with pytest.raises(ValueError, match="capacity limit"):
        RUNNER["verify_cleanup"](reader, [], "uid", 0, limit=invalid)
    with pytest.raises(ValueError, match="capacity limit"):
        GATE(tmp_path, expected_capacity_limit=invalid)
    reader.inventory.assert_not_called()
    reader.get.assert_not_called()
    execute.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_ambient_limit_cannot_override_explicit_run_default(tmp_path, mocker, monkeypatch):
    monkeypatch.setenv("DPS_CAPACITY_LIMIT", "100")
    execute = mocker.Mock()
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(7), execute=execute) == 1
    execute.assert_not_called()
    assert json.loads((tmp_path / "dps-phases.json").read_text())["baseline"]["capacity"]["limit"] == 10


@pytest.mark.parametrize("value", [None, "100", "1", "0", "-1", "10.0", "", "True"])
def test_runner_cli_limit_is_validated_before_authentication(mocker, value):
    arguments = ["runner", "--subscription", SUB, "--resource-group", GROUP]
    if value is not None:
        arguments += ["--dps-capacity-limit", value]
    reader, execute = mocker.Mock(), mocker.Mock(return_value=0)
    mocker.patch.object(sys, "argv", arguments)
    platform_check = mocker.Mock()
    mocker.patch.dict(RUNNER["main"].__globals__, ArmReader=reader, run=execute,
                      bounded_read=nullcontext, require_linux=platform_check)
    if value in (None, "100", "1"):
        assert RUNNER["main"]() == 0
        platform_check.assert_called_once_with()
        assert execute.call_args.kwargs["capacity_limit"] == (10 if value is None else int(value))
    else:
        with pytest.raises(SystemExit) as error:
            RUNNER["main"]()
        assert error.value.code == 2
        platform_check.assert_not_called()
        reader.assert_not_called()
        execute.assert_not_called()


@pytest.mark.parametrize("section", ["baseline", "regular-cleanup", "sas-gate", "sas-cleanup", "toggle-gate", "toggle-cleanup"])
@pytest.mark.parametrize("untrusted", [10, 101, "100", 100.0, True, None])
def test_independent_expected_limit_rejects_tampering_in_every_capacity_receipt(tmp_path, section, untrusted):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(7), execute=_execution, capacity_limit=100) == 0
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    if section == "baseline":
        summary["baseline"]["capacity"]["limit"] = untrusted
    else:
        name, field = section.split("-")
        phase = summary["phases"][{"regular": 0, "sas": 1, "toggle": 2}[name]]
        phase[field]["capacity"]["limit"] = untrusted
        _json(tmp_path / "dps-phases" / phase["name"] / "result.json", phase)
    _json(tmp_path / "dps-phases.json", summary)
    assert GATE(tmp_path, expected_capacity_limit=100)


@pytest.mark.parametrize("expected", [None, "100", "10", "101", "0", "", "100.0"])
def test_independent_evaluator_cli_binds_trusted_expected_limit(tmp_path, expected):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(7), execute=_execution, capacity_limit=100) == 0
    for field, value in (("service", "DPS"), ("python", "3.13"), ("region", "centraluseuap"),
                         ("status", "success"), ("failures", "")):
        (tmp_path / f"{field}.txt").write_text(value, encoding="utf-8")
    command = [sys.executable, "-I", "-S", str(ROOT / "azext_iot/tests/_evaluate_test_results.py"),
               "--results-dir", str(tmp_path)]
    if expected is not None:
        command += ["--expected-dps-capacity-limit", expected]
    result = subprocess.run(
        command, cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False,
        env=dict(os.environ, INTEGRATION_MATRIX=json.dumps([{
            "service": "DPS", "python": "3.13", "region": "centraluseuap",
        }]), SETUP_RESULT="success", UNIT_TEST_RESULT="success", INTEGRATION_RESULT="success",
            GATE_JOB_RESULT="success", GITHUB_STEP_SUMMARY=str(tmp_path / "gate-summary")),
    )
    assert result.returncode == (0 if expected == "100" else 2 if expected in ("0", "", "100.0") else 1)


@pytest.mark.parametrize("state", ["Deleting", "Succeeded"])
def test_cleanup_observes_without_deleting_or_retrying_mutations(state):
    reader = Reader()
    resource = {"id": PREFIX + "provisioningServices/owned", "state": state}
    reader.get = lambda _: resource
    result = RUNNER["verify_cleanup"](reader, [{"id": resource["id"]}], "uid", 0, clock=lambda: 0)
    assert not result["complete"]
    assert result["remaining"] == [resource]


def test_unrecorded_owned_resource_blocks_phase_gate():
    reader = Reader()
    reader.resources[0]["tags"] = {"runUid": "uid"}
    result = RUNNER["verify_cleanup"](reader, [{"id": "other"}], "uid", 0, clock=lambda: 0)
    assert not result["complete"]
    assert result["remaining"] == [reader.resources[0]]


def test_listed_owned_resource_cannot_be_declared_absent_from_get_alone():
    reader = Reader(1)
    result = RUNNER["verify_cleanup"](
        reader, [{"id": reader.resources[0]["id"], "creation_resolved": True}], "uid", 0, clock=lambda: 0,
    )
    assert not result["complete"]
    assert result["remaining"] == reader.resources


@pytest.mark.parametrize("exception", [OSError("incomplete inventory"), RuntimeError("fake credential body")])
def test_read_failure_blocks_without_publishing_raw_exception_body(tmp_path, exception):
    reader = Reader()
    reader.inventory = lambda: (_ for _ in ()).throw(exception)
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=_execution) == 1
    text = (tmp_path / "dps-phases.json").read_text()
    assert str(exception) not in text
    assert json.loads(text)["status"] == "failed"


def test_exhausted_read_budget_never_starts_network_work(mocker):
    timer = mocker.Mock()
    mocker.patch.dict(RUNNER["require_linux"].__globals__, signal=timer)
    with pytest.raises(RUNNER["PhaseError"], match="budget"):
        with RUNNER["bounded_read"](time.monotonic() - 1):
            pytest.fail("No operation may start outside its deadline")
    assert not timer.mock_calls


@pytest.mark.parametrize("deadline", [0, -1])
def test_exhausted_callable_read_never_starts_authentication(mocker, deadline):
    operation = mocker.Mock()
    mocker.patch.dict(RUNNER["require_linux"].__globals__, sys=SimpleNamespace(platform="linux"))
    with pytest.raises(RUNNER["PhaseError"], match="budget"):
        RUNNER["bounded_read_call"](operation, deadline)
    operation.assert_not_called()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_unsupported_entry_rejects_before_credentials_artifacts_or_execution(tmp_path, mocker, capsys, platform):
    reader = mocker.Mock()
    execute = mocker.Mock()
    output = tmp_path / "must-not-exist"
    mocker.patch.object(sys, "argv", [
        "_dps_phase_runner.py", "--subscription", SUB, "--resource-group", GROUP, "--output", str(output),
    ])
    mocker.patch.dict(RUNNER["main"].__globals__, sys=SimpleNamespace(platform=platform), ArmReader=reader, run=execute)
    assert RUNNER["main"]() == 1
    assert "requires Linux" in capsys.readouterr().out
    reader.assert_not_called()
    execute.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_unsupported_child_rejects_before_files_processes_or_signals(tmp_path, mocker, platform):
    processes = mocker.Mock()
    timer = mocker.Mock()
    mocker.patch.dict(
        RUNNER["child"].__globals__, sys=SimpleNamespace(platform=platform), subprocess=processes, signal=timer,
    )
    with pytest.raises(RUNNER["PhaseError"], match="requires Linux"):
        RUNNER["child"](["not-executed"], {}, tmp_path / "log", 1, 1)
    assert not processes.mock_calls and not timer.mock_calls
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_unsupported_read_rejects_before_timer_or_network_work(mocker, platform):
    timer = mocker.Mock()
    mocker.patch.dict(RUNNER["require_linux"].__globals__, sys=SimpleNamespace(platform=platform), signal=timer)
    with pytest.raises(RUNNER["PhaseError"], match="requires Linux"):
        with RUNNER["bounded_read"]():
            pytest.fail("Unsupported platform must not start credential or ARM work")
    assert not timer.mock_calls


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("deadline,seconds", [(None, 60), (107, 7), (200, 60)])
def test_linux_read_timer_is_bounded_and_restored_on_all_exit_paths(mocker, fails, deadline, seconds):
    previous = object()
    timer = SimpleNamespace(
        SIGALRM="alarm", ITIMER_REAL="real",
        signal=mocker.Mock(return_value=previous), setitimer=mocker.Mock(),
        getitimer=mocker.Mock(return_value=(0, 0)),
    )
    mocker.patch.dict(
        RUNNER["require_linux"].__globals__, sys=SimpleNamespace(platform="linux"), signal=timer,
        time=SimpleNamespace(monotonic=lambda: 100),
    )
    with pytest.raises(ValueError) if fails else nullcontext():
        with RUNNER["bounded_read"](deadline):
            if fails:
                raise ValueError("synthetic body failure")
    assert timer.setitimer.call_args_list == [mocker.call("real", seconds), mocker.call("real", 0)]
    assert timer.signal.call_count == 2
    assert timer.signal.call_args == mocker.call("alarm", previous)
    with pytest.raises(RUNNER["PhaseError"], match="exceeded"):
        timer.signal.call_args_list[0].args[1](None, None)


@pytest.mark.parametrize("member", ["SIGALRM", "ITIMER_REAL", "setitimer", "getitimer"])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_read_capability_rejects_before_timer_or_network_work(mocker, member, missing):
    timer = SimpleNamespace(SIGALRM=14, ITIMER_REAL=0, setitimer=mocker.Mock(),
                            getitimer=mocker.Mock(), signal=mocker.Mock())
    if missing:
        delattr(timer, member)
    else:
        setattr(timer, member, None)
    mocker.patch.dict(RUNNER["require_linux"].__globals__, sys=SimpleNamespace(platform="linux"), signal=timer)
    with pytest.raises(RUNNER["PhaseError"], match="POSIX interval timers"):
        with RUNNER["bounded_read"]():
            pytest.fail("Missing capabilities must not start credential or ARM work")
    timer.signal.assert_not_called()
    if member != "setitimer":
        timer.setitimer.assert_not_called()


@pytest.mark.skipif(sys.platform != "linux", reason="Real DPS interval timers are Linux-only.")
def test_linux_read_uses_real_interval_timer_and_restores_handler():
    timer = RUNNER["signal"]
    alarm = getattr(timer, "SIGALRM")
    real = getattr(timer, "ITIMER_REAL")
    previous = timer.getsignal(alarm)
    with pytest.raises(RUNNER["PhaseError"], match="exceeded"):
        with RUNNER["bounded_read"](time.monotonic() + .05):
            time.sleep(1)
    assert timer.getsignal(alarm) == previous
    assert getattr(timer, "getitimer")(real) == (0, 0)


@pytest.mark.parametrize("remaining,elapsed,expected", [(10, 3, 7), (0.00001, 0.001, 0.000001)])
def test_nested_read_restores_absolute_outer_timer_even_when_nearly_expired(mocker, remaining, elapsed, expected):
    clock = [100.0]
    previous = mocker.Mock()
    timer = SimpleNamespace(SIGALRM=14, ITIMER_REAL=0, signal=mocker.Mock(return_value=previous),
                            getitimer=lambda _: (remaining, 0), setitimer=mocker.Mock())
    mocker.patch.dict(RUNNER["require_linux"].__globals__, signal=timer, sys=SimpleNamespace(platform="linux"),
                      time=SimpleNamespace(monotonic=lambda: clock[0]))
    with RUNNER["bounded_read"]():
        assert timer.setitimer.call_args.args[1] == pytest.approx(remaining)
        clock[0] += elapsed
    assert timer.setitimer.call_args.args == pytest.approx((0, expected, 0))
    assert timer.signal.call_args == mocker.call(14, previous)


@pytest.mark.parametrize("outer_first", [False, True])
def test_nested_timer_dispatch_preserves_outer_exception_meaning(mocker, outer_first):
    clock = [100.0]
    outer = mocker.Mock(side_effect=ValueError("outer item timeout"))
    timer = SimpleNamespace(SIGALRM=14, ITIMER_REAL=0, signal=mocker.Mock(return_value=outer),
                            getitimer=lambda _: (0.01 if outer_first else 10, 0), setitimer=mocker.Mock())
    mocker.patch.dict(RUNNER["require_linux"].__globals__, signal=timer, sys=SimpleNamespace(platform="linux"),
                      time=SimpleNamespace(monotonic=lambda: clock[0]))
    with pytest.raises(ValueError if outer_first else RUNNER["PhaseError"],
                       match="outer item timeout" if outer_first else "exceeded"):
        with RUNNER["bounded_read"](101):
            handler = timer.signal.call_args.args[1]
            clock[0] += 0.02 if outer_first else 1
            handler(14, None)
    assert outer.call_count == int(outer_first)
    if not outer_first:
        assert timer.setitimer.call_args.args == (0, 9, 0)


@pytest.mark.skipif(sys.platform != "linux", reason="Real nested POSIX interval timer regression is Linux-only.")
@pytest.mark.parametrize("callable_read", [False, True])
def test_real_active_item_timer_fires_inside_bounded_read_without_being_extended(callable_read):
    timer = RUNNER["signal"]
    alarm, real = getattr(timer, "SIGALRM"), getattr(timer, "ITIMER_REAL")
    set_timer, get_timer = getattr(timer, "setitimer"), getattr(timer, "getitimer")
    previous = timer.getsignal(alarm)
    old_remaining, old_interval = get_timer(real)
    started = time.monotonic()

    def outer_timeout(_signum, _frame):
        raise ValueError("outer item deadline")

    try:
        timer.signal(alarm, outer_timeout)
        set_timer(real, .02)
        with pytest.raises(ValueError, match="outer item deadline"):
            if callable_read:
                RUNNER["bounded_read_call"](lambda _checkpoint: time.sleep(1), time.monotonic() + 5)
            else:
                with RUNNER["bounded_read"](time.monotonic() + 5):
                    time.sleep(1)
        assert time.monotonic() - started < .8
        assert timer.getsignal(alarm) is outer_timeout
        assert get_timer(real) == (0, 0)
    finally:
        set_timer(real, 0)
        timer.signal(alarm, previous)
        if old_remaining:
            set_timer(real, max(.000001, old_remaining - (time.monotonic() - started)), old_interval)


@pytest.mark.parametrize("member", ["getpgid", "killpg", "SIGUSR1", "SIGKILL"])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_child_capability_rejects_before_files_or_processes(tmp_path, mocker, member, missing):
    processes = mocker.Mock()
    operating_system = SimpleNamespace(getpgid=mocker.Mock(), killpg=mocker.Mock(), kill=mocker.Mock())
    signals = SimpleNamespace(SIGUSR1=10, SIGKILL=9)
    owner = operating_system if member in ("getpgid", "killpg") else signals
    if missing:
        delattr(owner, member)
    else:
        setattr(owner, member, None)
    mocker.patch.dict(
        RUNNER["child"].__globals__, sys=SimpleNamespace(platform="linux"),
        os=operating_system, signal=signals, subprocess=processes,
    )
    with pytest.raises(RUNNER["PhaseError"], match="POSIX process groups and signals"):
        RUNNER["child"](["not-executed"], {}, tmp_path / "log", 1, 1)
    assert not processes.mock_calls
    operating_system.kill.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("foreign_worker", [False, True])
def test_child_capabilities_keep_worker_ownership_and_absolute_cleanup_bound(tmp_path, mocker, foreign_worker):
    _json(tmp_path / "worker-1.json", {"pid": 123, "ready": True})
    process = mocker.Mock(pid=42, returncode=-9)
    process.poll.return_value = None
    processes = SimpleNamespace(Popen=mocker.Mock(return_value=process), PIPE=-1, STDOUT=-2)
    operating_system = SimpleNamespace(
        chmod=mocker.Mock(), fsync=mocker.Mock(), getpgid=mocker.Mock(return_value=43 if foreign_worker else 42),
        killpg=mocker.Mock(), kill=mocker.Mock(),
    )
    mocker.patch.dict(
        RUNNER["child"].__globals__, sys=SimpleNamespace(platform="linux"), os=operating_system,
        signal=SimpleNamespace(SIGUSR1=10, SIGKILL=9, SIGTERM=15), subprocess=processes,
        time=SimpleNamespace(monotonic=mocker.Mock(side_effect=[100, 101, 111, 112]), sleep=mocker.Mock()),
        select=SimpleNamespace(select=mocker.Mock(return_value=([], [], []))), READ_SECONDS=0,
    )
    with pytest.raises(RUNNER["PhaseError"], match="process group") if foreign_worker else nullcontext():
        result = RUNNER["child"](
            ["not-executed"], {"azext_iot_dps_phase_receipts": str(tmp_path)}, tmp_path / "log", .5, 10,
        )
        assert result["timed_out"] and result["interrupted"]
        assert result["cleanup_deadline"] == 110.5  # No new budget when interruption/cleanup is observed.
    operating_system.getpgid.assert_called_once_with(123)
    assert operating_system.kill.call_args_list == ([] if foreign_worker else [mocker.call(123, 10)])
    assert operating_system.killpg.call_args_list == [mocker.call(42, 15), mocker.call(42, 9)]
    assert processes.Popen.call_args.kwargs["start_new_session"] is True
    process.wait.assert_called_once_with(timeout=5)
    process.stdout.close.assert_called_once_with()


def test_windows_missing_posix_members_are_not_accessed_directly():
    tree = ast.parse(Path(RUNNER["__file__"]).read_text(encoding="utf-8"))
    missing = {"signal": {"SIGALRM", "ITIMER_REAL", "setitimer", "getitimer", "SIGUSR1", "SIGKILL"},
               "os": {"getpgid", "killpg"}}
    assert not [
        (node.value.id, node.attr, node.lineno) for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        and node.attr in missing.get(node.value.id, set())
    ]


@pytest.mark.parametrize("defect", [
    "summary", "junit", "log", "phase-result", "exit", "cleanup", "ownership", "gate", "skip", "count",
])
def test_final_gate_independently_rejects_missing_or_false_green_evidence(tmp_path, defect):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    summary_path = tmp_path / "dps-phases.json"
    summary = json.loads(summary_path.read_text())
    sas = summary["phases"][1]
    folder = tmp_path / "dps-phases/service-sas"
    if defect in ("summary", "junit", "log", "phase-result"):
        {"summary": summary_path, "junit": folder / "junit.xml", "log": folder / "output.log",
         "phase-result": folder / "result.json"}[defect].unlink()
    elif defect == "ownership":
        (folder / "receipts/owned-h.json").unlink()
    else:
        if defect == "exit":
            sas["exit_code"] = 1
        elif defect == "cleanup":
            sas["cleanup"]["complete"] = False
        elif defect == "gate":
            sas["gate"]["capacity"]["ready"] = False
        elif defect == "skip":
            tree = ET.parse(folder / "junit.xml")
            ET.SubElement(next(tree.getroot().iter("testcase")), "skipped")
            tree.write(folder / "junit.xml")
        elif defect == "count":
            sas["results"]["selected"] = 28
        _json(summary_path, summary)
        _json(folder / "result.json", sas)
    assert GATE(tmp_path)


@pytest.mark.parametrize("defect", ["five", "skips", "identity"])
def test_final_gate_rejects_self_consistent_but_incomplete_regular_evidence(tmp_path, defect):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    regular = summary["phases"][0]
    folder = tmp_path / "dps-phases/regular"
    tree = ET.parse(folder / "junit.xml")
    cases = list(tree.getroot())
    if defect == "five":
        for case in cases[5:]:
            tree.getroot().remove(case)
        regular["results"].update(tests=5, selected=5, passed=5, nodeids=regular["results"]["nodeids"][:5])
        _json(folder / "receipts/selection-gw0.json", {"selected": 5, "nodeids": regular["results"]["nodeids"]})
    elif defect == "skips":
        for case in cases[1:]:
            ET.SubElement(case, "skipped")
        regular["results"].update(passed=1, skipped=len(cases) - 1)
    else:
        cases[0].set("name", cases[1].get("name"))
    tree.write(folder / "junit.xml")
    _json(folder / "result.json", regular)
    _json(tmp_path / "dps-phases.json", summary)
    assert GATE(tmp_path)


@pytest.mark.parametrize("text", [
    "SharedAccessKey=secret-value;", "SharedAccessSignature sr=host&sig=secret-value",
    "{'primaryKey': 'secret-value'}", '{"secondaryKey": "secret-value"}',
    "--login 'HostName=host;SharedAccessKey=secret-value'", "--key secret-value",
    "{'access_token': 'secret-value'}", "Authorization: 'Bearer secret-value'",
])
def test_stream_redaction_handles_cli_json_dictionary_and_token_forms(text):
    assert "secret-value" not in RUNNER["Redactor"]().line(text)


def test_private_key_and_bare_service_keys_are_redacted():
    redactor = RUNNER["Redactor"]()
    for line in ("-----BEGIN PRIVATE KEY-----", "short-fragment", "-----END PRIVATE KEY-----", "A" * 43 + "="):
        assert line not in redactor.line(line)
    assert redactor.line("test_progress") == "test_progress"


@pytest.mark.skipif(sys.platform != "linux", reason="Real DPS child pipe polling/process-group cleanup is Linux-only.")
def test_child_stream_reassembles_chunks_before_redacting_and_omits_oversized_lines(tmp_path, capsys):
    script = (
        "import os,time; os.write(1,b'primary'); time.sleep(.01); "
        "os.write(1,b'Key: secret-value\\n'); print('x'*70000)"
    )
    result = RUNNER["child"]([sys.executable, "-c", script], dict(os.environ), tmp_path / "log", 10, 61)
    text = (tmp_path / "log").read_text()
    assert "secret-value" not in text + capsys.readouterr().out
    assert "oversized output line omitted" in text
    assert result["exit_code"] == 0 and not result["timed_out"]


@pytest.mark.parametrize("cooperative", [False, True])
@pytest.mark.skipif(sys.platform != "linux", reason="Real DPS process-group signaling/cleanup is Linux-only.")
def test_child_runtime_timeout_allows_cleanup_but_never_turns_green(tmp_path, mocker, cooperative):
    mocker.patch.dict(RUNNER["child"].__globals__, READ_SECONDS=0.1)
    handler = "lambda *_: (print('cleanup finished', flush=True), sys.exit(0))" if cooperative else "signal.SIG_IGN"
    script = f"import signal,time,sys; signal.signal(signal.SIGINT, {handler}); time.sleep(20)"
    started = time.monotonic()
    result = RUNNER["child"]([sys.executable, "-c", script], dict(os.environ), tmp_path / "log", .3, .6)
    assert time.monotonic() - started < 3
    assert result["timed_out"] and result["interrupted"]
    if cooperative:
        assert result["exit_code"] == 0
        assert "cleanup finished" in (tmp_path / "log").read_text()


@pytest.mark.parametrize("method,url", [
    ("DELETE", RUNNER["ARM"] + PREFIX + "provisioningServices/test"),
    ("GET", "https://management.azure.com" + PREFIX + "provisioningServices/test"),
    ("GET", RUNNER["ARM"] + "/subscriptions/other/providers/Microsoft.Devices/provisioningServices"),
    ("POST", RUNNER["ARM"] + f"/subscriptions/{SUB}/providers/Microsoft.Devices/register"),
])
def test_reader_transport_refuses_mutations_wrong_subscription_and_non_canary(mocker, method, url):
    from azure.core.pipeline.transport import HttpRequest
    send = mocker.patch("azure.core.pipeline.transport.RequestsTransport.send")
    reader = RUNNER["ArmReader"](SUB)
    with pytest.raises(RUNNER["PhaseError"], match="boundary"):
        reader.dps._client._pipeline._transport.send(HttpRequest(method, url))  # pylint: disable=protected-access
    send.assert_not_called()


def test_reader_uses_explicit_subscription_audience_and_branch_api(mocker):
    token = mocker.patch("azure.cli.core._profile.Profile.get_raw_token",
                         return_value=(("Bearer", "fake-unit-token", {"expires_on": 9999999999}), SUB, "tenant"))
    reader = RUNNER["ArmReader"](SUB)
    reader.dps._config.credential.get_token("ignored")  # pylint: disable=protected-access
    token.assert_called_once_with(subscription=SUB, resource="https://management.azure.com/")
    assert reader.dps._config.api_version == "2026-06-01-preview"  # pylint: disable=protected-access
    assert reader.hub._config.api_version == "2026-10-01-preview"  # pylint: disable=protected-access
    assert reader.adr._config.api_version == "2026-11-02-preview"  # pylint: disable=protected-access


@responses.activate
@pytest.mark.parametrize("kind", ["csrdps", "csrhub", "csrns"])
def test_reader_verifies_each_csr_resource_with_its_own_rp(mocker, kind):
    mocker.patch("azure.cli.core._profile.Profile.get_raw_token",
                 return_value=(("Bearer", "fake-unit-token", {"expires_on": 9999999999}), SUB, "tenant"))
    resource_id = PREFIX.partition("/providers/")[0] + "/providers/" + RUNNER["MANIFEST"]["resource_type"](kind) + "/owned"
    responses.add(responses.GET, RUNNER["ARM"] + resource_id, status=404)
    reader = RUNNER["ArmReader"](SUB)
    assert reader.get({"kind": kind, "name": "owned", "resource_group": GROUP}) is None
    assert len(responses.calls) == 1


def test_regular_admission_accounts_for_dedicated_csr_dps():
    assert RUNNER["capacity"](Reader(6).resources)["ready"]
    assert not RUNNER["capacity"](Reader(7).resources)["ready"]
    assert RUNNER["capacity"](Reader().resources)["required"] == 4


@pytest.mark.parametrize("defect", ["baseline-required", "baseline-limit", "baseline-count", "cleanup-required", "cleanup-limit"])
def test_full_qualification_cannot_accept_reduced_or_overridden_capacity_metadata(tmp_path, defect):
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", Reader(), execute=_execution) == 0
    summary_path = tmp_path / "dps-phases.json"
    summary = json.loads(summary_path.read_text())
    section, field = defect.split("-")
    capacity = summary["baseline"]["capacity"] if section == "baseline" else summary["phases"][0]["cleanup"]["capacity"]
    capacity[field] = {"required": 1, "limit": 11, "count": 1}[field]
    _json(summary_path, summary)
    if section == "cleanup":
        _json(tmp_path / "dps-phases/regular/result.json", summary["phases"][0])
    assert GATE(tmp_path)


@responses.activate
@pytest.mark.parametrize("body", [{}, None, {"value": None}, {"value": []}])
def test_inventory_wire_contract_does_not_confuse_missing_results_with_empty_inventory(mocker, body):
    # Test the real SDK/HTTP parsing on every OS, independently of Linux's alarm.
    mocker.patch.dict(RUNNER["ArmReader"].inventory.__globals__, bounded_read=nullcontext)
    mocker.patch("azure.cli.core._profile.Profile.get_raw_token",
                 return_value=(("Bearer", "fake-unit-token", {"expires_on": 9999999999}), SUB, "tenant"))
    url = RUNNER["ARM"] + f"/subscriptions/{SUB}/providers/Microsoft.Devices/provisioningServices"
    responses.add(responses.GET, url, body=json.dumps(body), content_type="application/json")
    reader = RUNNER["ArmReader"](SUB)
    if body == {"value": []}:
        assert reader.inventory() == []
    else:
        with pytest.raises(RUNNER["PhaseError"], match="Incomplete"):
            reader.inventory()
    assert len(responses.calls) == 1
    assert reader.reads[0]["api_version"] == "2026-06-01-preview"


@responses.activate
def test_inventory_pagination_failure_is_not_partial_capacity_or_retried(mocker):
    mocker.patch.dict(RUNNER["ArmReader"].inventory.__globals__, bounded_read=nullcontext)
    mocker.patch("azure.cli.core._profile.Profile.get_raw_token",
                 return_value=(("Bearer", "fake-unit-token", {"expires_on": 9999999999}), SUB, "tenant"))
    url = RUNNER["ARM"] + f"/subscriptions/{SUB}/providers/Microsoft.Devices/provisioningServices"
    next_page = url + "?api-version=2026-06-01-preview&page=2"
    responses.add(responses.GET, url, json={"value": Reader(1).resources, "nextLink": next_page})
    responses.add(responses.GET, url, status=500, json={"error": {"code": "UnitFailure"}})
    reader = RUNNER["ArmReader"](SUB)
    with pytest.raises(Exception):
        reader.inventory()
    assert len(responses.calls) == 2
    assert [read["status"] for read in reader.reads] == [200, 500]
