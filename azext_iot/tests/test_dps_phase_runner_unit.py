# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline runner tests: fake ARM inventories/fixtures and harmless local child processes."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import runpy
import sys
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
import responses

ROOT = Path(__file__).resolve().parents[2]
RUNNER = runpy.run_path(str(ROOT / "scripts/run_dps_phases.py"))
RUN = RUNNER["run"]
GATE = runpy.run_path(str(ROOT / "scripts/evaluate_test_results.py"))["evaluate_dps_phases"]
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
    uid = env["azext_iot_dps_run_uid"]
    nodeids = sorted(RUNNER["MANIFEST"]["expected_nodeids"](phase))
    count = len(nodeids)
    directory = Path(env["azext_iot_dps_phase_receipts"])
    metadata = {"phase": phase, "run_uid": uid, "subscription": SUB}
    _json(directory / "started.json", dict(metadata, started=True))
    _json(directory / "selection-gw0.json", {"selected": count, "nodeids": nodeids})
    for kind in ("h", "nh", "hub"):
        name = f"owned-{uid[:8]}-{kind}"
        resource_type = "IotHubs" if kind == "hub" else "provisioningServices"
        resource_id = PREFIX + resource_type + "/" + name
        _json(directory / f"owned-{kind}.json", dict(
            metadata, kind=kind, name=name, resource_group=GROUP, id=resource_id, create_attempted=True,
            tags={"intTest": "true", "runUid": uid if phase == "regular" else uid + "-service-sas", "kind": kind},
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
    ):
        monkeypatch.delenv(name, raising=False)


def test_serial_success_preserves_real_baseline_and_distinct_sanitized_artifacts(tmp_path):
    reader = Reader()
    assert RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=_execution) == 0
    summary = json.loads((tmp_path / "dps-phases.json").read_text())
    assert summary["baseline"]["capacity"]["count"] == 3  # Neither hardcoded eight nor assumed empty.
    assert reader.inventories == 4  # Baseline, cleanup, fresh pre-SAS, final cleanup.
    assert len(reader.gets) == 9  # Exact regular IDs are checked again immediately before phase two.
    assert not GATE(tmp_path)
    for phase in ("regular", "service-sas"):
        folder = tmp_path / "dps-phases" / phase
        assert (folder / "output.log").is_file()
        assert "UNSAFE_CAPTURED_CREDENTIAL" not in (folder / "junit.xml").read_text()
    with pytest.raises(FileExistsError):
        RUN(SUB, GROUP, tmp_path / "dps-phases", reader, execute=_execution)


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
            return {"id": record["id"], "state": "Deleting"} if len(reader.gets) > 3 else None
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
        assert [phase["status"] for phase in phases] == ["failed", "passed"]
    else:
        assert phases[1]["status"] == "blocked"
        if defect == "reappeared":
            assert len(phases[1]["gate"]["remaining"]) == 3


@pytest.mark.parametrize("pin", [
    "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub", "azext_iot_dps_test_phase", "azext_iot_dps_run_uid",
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


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_unsupported_entry_rejects_before_credentials_artifacts_or_execution(tmp_path, mocker, capsys, platform):
    reader = mocker.Mock()
    execute = mocker.Mock()
    output = tmp_path / "must-not-exist"
    mocker.patch.object(sys, "argv", [
        "run_dps_phases.py", "--subscription", SUB, "--resource-group", GROUP, "--output", str(output),
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
def test_linux_read_timer_is_bounded_and_restored_on_all_exit_paths(mocker, fails):
    previous = object()
    timer = SimpleNamespace(
        SIGALRM="alarm", ITIMER_REAL="real",
        signal=mocker.Mock(return_value=previous), setitimer=mocker.Mock(),
    )
    mocker.patch.dict(RUNNER["require_linux"].__globals__, sys=SimpleNamespace(platform="linux"), signal=timer)
    with pytest.raises(ValueError) if fails else nullcontext():
        with RUNNER["bounded_read"]():
            if fails:
                raise ValueError("synthetic body failure")
    assert timer.setitimer.call_args_list == [mocker.call("real", RUNNER["READ_SECONDS"]), mocker.call("real", 0)]
    assert timer.signal.call_count == 2
    assert timer.signal.call_args == mocker.call("alarm", previous)
    with pytest.raises(RUNNER["PhaseError"], match="exceeded"):
        timer.signal.call_args_list[0].args[1](None, None)


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
