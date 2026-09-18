# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline focused-controller proofs; no live collection or resource provisioning."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import runpy
import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest
from coverage import CoverageData
from tox.config.loader import str_convert as tox_convert

from azext_iot.tests import _focused_live as focused
from azext_iot.tests import _focused_live_plugin as dps_plugin
from azext_iot.tests import _hub_phase_runner as hub
from azext_iot.tests import _hub_suite_plugin as plugin
from azext_iot.tests import _dps_phase_runner as dps
from azext_iot.tests.dps import _phase, _phase_receipts, _phase_runtime
from azext_iot.tests.iothub import _sas_phase as sas
from azext_iot.tests.test_hub_phase_runner_unit import Reader as HubReader, execute_factory, ownership
from azext_iot.tests.test_dps_phase_runner_unit import Reader as DpsReader, _execution, SUB, GROUP, RUN as FULL_DPS_RUN

ROOT = Path(__file__).resolve().parents[2]
GATE = runpy.run_path(str(ROOT / "azext_iot/tests/_evaluate_test_results.py"))


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for key in (
        focused.ENV, focused.DPS_ARGS_ENV, "azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub",
        "azext_iot_teststorageaccount", "azext_iot_teststoragecontainer", "azext_iot_dps_test_phase",
        "azext_iot_dps_run_uid", "azext_iot_dps_phase_receipts", "azext_iot_dps_junit", "azext_iot_dps_workers",
        "azext_iot_dps_coverage_file", "COVERAGE_FILE",
        "azext_iot_hub_auth_phase", "AZEXT_IOT_HUB_SUITE", "AZEXT_IOT_HUB_PHASE",
        "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    ):
        monkeypatch.delenv(key, raising=False)


def nodes(suite, phase):
    if suite == "DPS":
        return sorted(focused.DPS_PREFIX + node for node in dps.MANIFEST["expected_nodeids"](phase))
    return list(hub.selection()["nodes"](suite, phase))


@pytest.mark.parametrize("suite,phase", [
    ("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas"),
    ("DPS", "regular"), ("DPS", "service-sas"), ("DPS", "local-auth-toggle"),
])
def test_selection_is_explicit_exact_branch_known_and_canonical(suite, phase):
    available = nodes(suite, phase)
    assert focused.select(suite) is None
    assert focused.select(suite, phase, available[::-1])["requestedNodes"] == available
    selected = focused.select(suite, phase, [available[-1]])
    assert selected["requestedNodes"] == [available[-1]]
    assert focused.from_environment({focused.ENV: json.dumps(selected)}, suite, phase) == selected
    for requested in ([], [available[0], available[0]], ["-k"], ["../" + available[0]],
                      [available[0].split("::")[0]], [available[0] + "[unknown]"]):
        with pytest.raises(ValueError):
            focused.select(suite, phase, requested)
    with pytest.raises(ValueError):
        focused.select(suite, None, [available[0]])


@pytest.mark.parametrize("suite,phase,node", [
    ("HubControl", "regular",
     "azext_iot/tests/iothub/core/test_iothub_discovery_int.py::TestIoTHubDiscovery::test_iothub_targets"),
    ("HubData", "linked-metadata",
     "azext_iot/tests/iothub/metadata/test_hub_metadata_int.py::test_linked_metadata_state_and_service_bulk_portability"),
    ("DPS", "regular", "azext_iot/tests/dps/device_registration/test_iot_device_registration_int.py::"
     "test_register_and_issue_certificate_contract[default]"),
])
def test_excluded_or_separately_opted_in_nodes_are_not_debug_authority(suite, phase, node):
    with pytest.raises(ValueError):
        focused.select(suite, phase, [node])


def test_auth_phase_and_changed_manifest_envelopes_cannot_be_reused():
    selection = focused.select("HubData", "sas", nodes("HubData", "sas")[:1])
    with pytest.raises(ValueError, match="phase mismatch"):
        focused.from_environment({focused.ENV: json.dumps(selection)}, "HubData", "entra")
    selection["manifestSha256"] = "stale"
    with pytest.raises(ValueError, match="checkout"):
        focused.from_environment({focused.ENV: json.dumps(selection)}, "HubData", "sas")


@pytest.mark.parametrize("evidence", [None, [], "debug", 1])
def test_malformed_provenance_cannot_qualify_either_mode(evidence):
    assert not focused.matches(evidence, None)
    assert not focused.matches(evidence, focused.select("HubData", "sas", nodes("HubData", "sas")[:1]))


@pytest.mark.parametrize("suite,phase", [("HubControl", "regular"), ("HubData", "sas"), ("DPS", "regular")])
@pytest.mark.parametrize("defect", ["unknown", "wrong-phase", "duplicate", "no-phase", "no-node", "pytest-filter"])
def test_real_controller_cli_rejects_before_test_or_azure_imports(tmp_path, suite, phase, defect):
    node = nodes(suite, phase)[0]
    debug = ["--debug-phase", phase, "--debug-node", node]
    if defect == "unknown":
        debug[-1] += "-unknown"
    elif defect == "wrong-phase":
        debug[1] = "service-sas" if suite != "DPS" else "sas"
    elif defect == "duplicate":
        debug += ["--debug-node", node]
    elif defect == "no-phase":
        debug = debug[2:]
    elif defect == "no-node":
        debug = debug[:2]
    else:
        debug += ["-k", "anything"]
    script = ROOT / ("azext_iot/tests/_dps_phase_runner.py" if suite == "DPS" else "azext_iot/tests/_hub_phase_runner.py")
    output = tmp_path / "must-not-exist"
    arguments = ["--subscription", SUB, "--resource-group", GROUP, "--region", "centraluseuap", "--output", str(output)]
    if suite != "DPS":
        arguments += ["--suite", suite]
    marker = tmp_path / "imported"
    proof = (
        "import builtins,runpy,socket,sys\nfrom pathlib import Path\n"
        "def forbidden(*args,**kwargs):\n    raise AssertionError('Offline CLI proof attempted network')\n"
        "socket.socket.connect=forbidden\nsocket.socket.connect_ex=forbidden\nsocket.getaddrinfo=forbidden\n"
        "original=builtins.__import__\n"
        "def checked(name,*args,**kwargs):\n"
        "    if name.startswith(('azure','azext_iot','pytest')):\n"
        f"        Path({str(marker)!r}).write_text(name)\n        raise AssertionError('Unexpected test/Azure import')\n"
        "    return original(name,*args,**kwargs)\n"
        "builtins.__import__=checked\nsys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n"
    )
    completed = subprocess.run([sys.executable, "-I", "-c", proof, str(script), *arguments, *debug],
                               capture_output=True, text=True, check=False, timeout=30)
    assert completed.returncode != 0
    assert not marker.exists(), completed.stdout + completed.stderr
    assert not output.exists()


def _damage(receipt, expected, defect):
    if defect == "missing-stage":
        del receipt["reports"][expected[0]]["teardown"]
    elif defect == "duplicate-stage":
        receipt["reports"][expected[0]]["call"].append("passed")
    elif defect == "skip":
        receipt["reports"][expected[0]]["call"] = ["skipped"]
    elif defect == "duplicate-node":
        receipt["collected"].append(expected[0])
    elif defect == "provenance":
        receipt.pop("debug")
    elif defect == "malformed-stages":
        receipt["reports"] = list(expected)


def run_hub(tmp_path, monkeypatch, suite, phase, *, defect=None, whole=False, reader=None):
    chosen = nodes(suite, phase) if whole else nodes(suite, phase)[-1:]
    full_execute, calls = execute_factory()
    captured = []

    def execute(command, env, log, runtime, cleanup, cancelled):
        captured.append(env)
        debug = json.loads(env[focused.ENV])
        expected = debug["requestedNodes"]
        assert command[-len(expected):] == expected
        report = Path(env["COVERAGE_FILE"]).with_name("coverage.xml")
        assert f"--cov-report=xml:{report}" in command
        result = full_execute(command, env, log, runtime, cleanup, cancelled)
        path = Path(env["AZEXT_IOT_HUB_RECEIPT"])
        receipt = hub.read_json(path)
        receipt.update(expected=expected, collected=expected[:],
                       reports={node: receipt["reports"][node] for node in expected}, **focused.provenance(debug))
        _damage(receipt, expected, defect)
        ownership.write(path, receipt)
        path = Path(env["AZEXT_IOT_HUB_OWNERSHIP"])
        evidence = hub.read_json(path)
        if phase == "sas":
            evidence.update(passed=expected, **focused.provenance(debug))
        elif defect == "observer":
            evidence["violations"] = ["Observed resource no longer belongs to this phase"]
        elif defect == "uncertain":
            next(iter(evidence["resources"].values()))["uncertain"] = True
        ownership.write(path, evidence)
        if defect in ("timed_out", "interrupted"):
            result[defect] = True
        return result

    output = tmp_path / "hub-phases"
    with monkeypatch.context() as patch:
        patch.setattr(dps, "require_linux", lambda: None)
        patch.setattr(hub.signal, "signal", lambda *_: None)
        result = hub.run(suite, ownership.SUBSCRIPTION, ownership.GROUP, ownership.REGION, output,
                         arm=reader or HubReader(), execute=execute, base={"PYTHONPATH": "inherited-dependencies"},
                         debug_phase=phase, debug_nodes=chosen)
    return result, hub.read_json(output / "hub-phases.json"), output, calls, captured


@pytest.mark.parametrize("suite,phase", [("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas")])
@pytest.mark.parametrize("whole", [False, True])
def test_hub_debug_success_is_not_full_qualification(tmp_path, monkeypatch, suite, phase, whole):
    result, summary, output, calls, captured = run_hub(tmp_path, monkeypatch, suite, phase, whole=whole)
    assert result == 0 and calls == [phase]
    assert captured[0]["COVERAGE_FILE"] == str(output / phase / ".coverage")
    assert summary["status"] == "debug-passed" and summary["qualifiesFullSuite"] is False
    assert summary["runnerSeconds"] == dict(hub.BUDGETS[suite])[phase] + hub.CLEANUP + hub.RESERVE
    assert hub.evaluate_hub_phases(output, debug=True) == {"passed": True, "errors": []}
    assert not hub.evaluate_hub_phases(output)["passed"]
    summary["status"] = "passed"
    for key in ("mode", "debug", "qualifiesFullSuite"):
        summary.pop(key)
    ownership.write(output / "hub-phases.json", summary)
    assert not hub.evaluate_hub_phases(output)["passed"]


@pytest.mark.parametrize("defect", [
    "missing-stage", "duplicate-stage", "skip", "duplicate-node", "provenance", "observer", "uncertain",
    "malformed-stages", "timed_out", "interrupted",
])
def test_hub_debug_preserves_stage_ownership_and_no_replay_failures(tmp_path, monkeypatch, defect):
    reader = HubReader()
    result, summary, output, _, _ = run_hub(tmp_path, monkeypatch, "HubControl", "regular", defect=defect, reader=reader)
    assert result == 1 and summary["status"] == "debug-failed"
    assert not hub.evaluate_hub_phases(output, debug=True)["passed"]
    assert all(method == "GET" for method, *_ in reader.calls)
    if defect == "observer":
        assert "ownership boundary violation" in hub.read_json(output / "regular/cleanup.json")["errors"]
        assert not reader.calls


def run_dps(tmp_path, monkeypatch, phase, *, defect=None, whole=False, reader=None, chosen=None):
    if chosen is None:
        chosen = nodes("DPS", phase) if whole else nodes("DPS", phase)[:1]
    captured = []

    def execute(command, env, log, runtime, cleanup, cancelled):
        captured.append(env)
        assert Path.cwd() == ROOT
        assert env["azext_iot_dps_workers"] == "0"
        debug = json.loads(env[focused.ENV])
        expected = debug["requestedNodes"]
        assert shlex.split(env[focused.DPS_ARGS_ENV])[-len(expected):] == expected
        report = Path(env["azext_iot_dps_coverage_file"]).with_name("coverage.xml")
        assert f"--cov-report=xml:{report}" in shlex.split(env[focused.DPS_ARGS_ENV])
        assert (runtime, cleanup) == {name: (run, clean) for name, run, clean in dps.PHASES}[phase]
        # Reuse the existing fake ARM/JUnit producer, then retain only the requested collection.
        regular_env = dict(env, azext_iot_dps_workers="0" if phase == "local-auth-toggle" else "7")
        result = _execution(command, regular_env, log, runtime, cleanup, cancelled)
        directory = Path(env["azext_iot_dps_phase_receipts"])
        short = [dps.MANIFEST["normalize_nodeid"](node) for node in expected]
        for path in directory.glob("selection-*.json"):
            path.write_text(json.dumps({"selected": len(short), "nodeids": sorted(short), **focused.provenance(debug)}))
        tree = ET.parse(env["azext_iot_dps_junit"])
        for case in list(tree.getroot()):
            if dps.MANIFEST["junit_nodeid"](case) not in short:
                tree.getroot().remove(case)
        tree.write(env["azext_iot_dps_junit"])
        receipt = plugin.PhaseReceipt("DPS", phase, expected, directory / "pytest.json", env["azext_iot_dps_run_uid"],
                                      debug=debug)
        receipt.data.update(collected=expected[:], finished=True, exitstatus=0, errors=[],
                            reports={node: {stage: ["passed"] for stage in ("setup", "call", "teardown")}
                                     for node in expected})
        _damage(receipt.data, expected, defect)
        receipt.write()
        if defect == "uncertain":
            for path in directory.glob("created-*.json"):
                path.unlink()
        if defect in ("timed_out", "interrupted"):
            result[defect] = True
        return result

    with monkeypatch.context() as patch:
        patch.setattr(dps.signal, "signal", lambda *_: None)
        result = dps.run(SUB, GROUP, tmp_path / "dps-phases", reader or DpsReader(), execute=execute,
                         debug_phase=phase, debug_nodes=chosen)
    return result, hub.read_json(tmp_path / "dps-phases.json"), captured


@pytest.mark.parametrize("phase", ["regular", "service-sas", "local-auth-toggle"])
@pytest.mark.parametrize("whole", [False, True])
def test_dps_debug_phase_keeps_ownership_cleanup_and_never_qualifies(tmp_path, monkeypatch, phase, whole):
    result, summary, captured = run_dps(tmp_path, monkeypatch, phase, whole=whole)
    assert result == 0 and summary["status"] == "debug-passed"
    assert [value["name"] for value in summary["phases"]] == [phase]
    assert summary["baseline"]["resources"] == DpsReader().resources
    assert summary["runner_seconds"] <= dps.RUNNER_SECONDS
    assert summary["phases"][0]["cleanup"]["complete"] is True
    assert summary["phases"][0]["results"]["stage_errors"] == []
    assert captured[0]["azext_iot_dps_test_phase"] == phase
    assert captured[0]["azext_iot_dps_coverage_file"] == str(tmp_path / "dps-phases" / phase / ".coverage")
    assert GATE["evaluate_dps_phases"](tmp_path)
    assert "UNSAFE_CAPTURED_CREDENTIAL" not in (tmp_path / "dps-phases" / phase / "junit.xml").read_text()


@pytest.mark.parametrize("phase", ["regular", "service-sas", "local-auth-toggle"])
@pytest.mark.parametrize("count", [10, 1000])
def test_preview_debug_keeps_cleanup_and_nonqualification_without_quota(tmp_path, monkeypatch, phase, count):
    result, summary, captured = run_dps(
        tmp_path, monkeypatch, phase, reader=DpsReader(count),
    )
    assert result == 0
    assert summary["qualifiesFullSuite"] is False
    assert len(captured) == 1
    assert GATE["evaluate_dps_phases"](tmp_path)
    assert summary["phases"][0]["cleanup"]["complete"]
    assert len(summary["phases"][0]["cleanup"]["inventory_ids"]) == count


@pytest.mark.parametrize("defect", [
    "missing-stage", "duplicate-stage", "skip", "duplicate-node", "provenance", "uncertain",
    "malformed-stages", "timed_out", "interrupted",
])
def test_dps_debug_cannot_hide_incomplete_stages_or_uncertain_creates(tmp_path, monkeypatch, defect):
    result, summary, _ = run_dps(tmp_path, monkeypatch, "regular", defect=defect)
    assert result == 1 and summary["status"] == "debug-failed"
    if defect == "uncertain":
        assert summary["phases"][0]["cleanup"]["complete"] is False
    else:
        assert summary["phases"][0]["cleanup"]["complete"] is True


@pytest.mark.parametrize("suite,phase", [("HubData", "entra"), ("DPS", "regular")])
def test_debug_ignores_foreign_resource_count_but_never_qualifies(tmp_path, monkeypatch, suite, phase):
    if suite == "DPS":
        result, summary, captured = run_dps(tmp_path, monkeypatch, phase, reader=DpsReader(1000))
        assert GATE["evaluate_dps_phases"](tmp_path)
    else:
        result, summary, output, _, captured = run_hub(tmp_path, monkeypatch, suite, phase, reader=HubReader(1000))
        assert not hub.evaluate_hub_phases(output)["passed"]
    assert result == 0 and summary["status"] == "debug-passed"
    assert len(captured) == 1


@pytest.mark.parametrize("selection", ["full", "empty-full", "regular", "service-sas", "local-auth-toggle"])
def test_all_dps_selections_run_without_quota_but_only_full_evidence_qualifies(tmp_path, monkeypatch, selection):
    if selection in ("full", "empty-full"):
        execute = Mock(side_effect=_execution)
        result = FULL_DPS_RUN(
            SUB, GROUP, tmp_path / "dps-phases", DpsReader(1000), execute=execute,
            debug_nodes=[] if selection == "empty-full" else None,
        )
        summary = hub.read_json(tmp_path / "dps-phases.json")
        assert execute.call_count == 3
        assert not GATE["evaluate_dps_phases"](tmp_path)
    else:
        phase = selection if selection in ("service-sas", "local-auth-toggle") else "regular"
        chosen = nodes("DPS", phase)[:1]
        result, summary, captured = run_dps(tmp_path, monkeypatch, phase, chosen=chosen, reader=DpsReader(1000))
        assert len(captured) == 1
        assert GATE["evaluate_dps_phases"](tmp_path)
    assert result == 0
    assert len(summary["baseline"]["resources"]) == 1000


@pytest.mark.parametrize("defect", ["empty", "duplicate", "unknown", "no-phase", "wrong-phase"])
def test_invalid_debug_is_rejected_before_inventory_or_launch(tmp_path, defect):
    phase, chosen = "regular", nodes("DPS", "regular")[:1]
    if defect == "empty":
        chosen = []
    elif defect == "duplicate":
        chosen.append(chosen[0])
    elif defect == "unknown":
        chosen.append(chosen[0] + "-unknown")
    elif defect == "no-phase":
        phase = None
    else:
        phase = "service-sas"
    reader, execute = Mock(), Mock()
    with pytest.raises(ValueError):
        dps.run(SUB, GROUP, tmp_path / "must-not-exist", reader, execute=execute,
                debug_phase=phase, debug_nodes=chosen)
    reader.inventory.assert_not_called()
    execute.assert_not_called()
    assert not (tmp_path / "must-not-exist").exists()


@pytest.mark.parametrize("defect", ["empty", "suite", "phase", "manifest", "nodes", "duplicate"])
def test_debug_selection_cannot_trust_a_forged_or_stale_envelope(defect):
    debug = focused.select("DPS", "regular", nodes("DPS", "regular")[:1])
    if defect == "empty":
        debug = {}
    elif defect == "nodes":
        debug["requestedNodes"] = []
    elif defect == "duplicate":
        debug["requestedNodes"].append(debug["requestedNodes"][0])
    else:
        field = "manifestSha256" if defect == "manifest" else defect
        debug[field] = "foreign"
    with pytest.raises(ValueError):
        focused.from_environment({focused.ENV: json.dumps(debug)}, "DPS", "regular")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
@pytest.mark.parametrize("suite,phase", [
    ("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas"),
    ("DPS", "regular"), ("DPS", "service-sas"), ("DPS", "local-auth-toggle"),
])
def test_fake_debug_execution_is_portable_but_public_entry_remains_linux_only(
    tmp_path, monkeypatch, platform, suite, phase,
):
    monkeypatch.setattr(dps, "sys", SimpleNamespace(platform=platform, executable=sys.executable))
    if suite == "DPS":
        assert run_dps(tmp_path, monkeypatch, phase)[0] == 0
    else:
        assert run_hub(tmp_path, monkeypatch, suite, phase)[0] == 0
    with pytest.raises(dps.PhaseError, match="requires Linux"):
        dps.require_linux()

    output = tmp_path / "public-must-not-exist"
    arguments = [
        "controller", "--subscription", ownership.SUBSCRIPTION, "--resource-group", ownership.GROUP,
        "--region", ownership.REGION,
        "--debug-phase", phase, "--debug-node", nodes(suite, phase)[0], "--output", str(output),
    ]
    if suite != "DPS":
        arguments += ["--suite", suite]
    monkeypatch.setattr(sys, "argv", arguments)
    readers = Mock(side_effect=AssertionError("Public non-Linux entry attempted ARM setup"))
    timers = Mock(side_effect=AssertionError("Public non-Linux entry attempted OS timers"))
    monkeypatch.setattr(dps, "ArmReader", readers)
    monkeypatch.setattr(dps, "bounded_read", timers)
    monkeypatch.setattr(hub, "helper", readers)
    assert (dps.main() if suite == "DPS" else hub.main()) == 1
    readers.assert_not_called()
    timers.assert_not_called()
    assert not output.exists()


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_existing_full_dps_fake_execution_remains_portable(tmp_path, monkeypatch, platform):
    monkeypatch.setitem(FULL_DPS_RUN.__globals__, "sys",
                        SimpleNamespace(platform=platform, executable=sys.executable))
    with monkeypatch.context() as patch:
        patch.setattr(dps.signal, "signal", lambda *_: None)
        assert FULL_DPS_RUN(SUB, GROUP, tmp_path / "dps-phases", DpsReader(), execute=_execution) == 0
    assert not GATE["evaluate_dps_phases"](tmp_path)
    with pytest.raises(FULL_DPS_RUN.__globals__["PhaseError"], match="requires Linux"):
        FULL_DPS_RUN.__globals__["require_linux"]()


def test_dps_selection_and_receipts_use_same_exact_debug_subset(tmp_path, monkeypatch):
    phase = "regular"
    chosen = nodes("DPS", phase)[:1]
    debug = focused.select("DPS", phase, chosen)
    monkeypatch.setenv(focused.ENV, json.dumps(debug))
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    items = [
        SimpleNamespace(nodeid=node, path=Path(node.partition("::")[0]), get_closest_marker=lambda _: None)
        for node in chosen
    ]
    _phase.select_items(Mock(), items)
    with pytest.raises(pytest.UsageError, match="exactly"):
        _phase.select_items(Mock(), items * 2)
    with pytest.raises(pytest.UsageError, match="exactly"):
        _phase.select_items(Mock(), [])
    for key, value in {
        _phase_receipts.DIRECTORY_ENV: str(tmp_path), _phase_receipts.RUN_UID_ENV: "a" * 32,
        _phase_receipts.SUBSCRIPTION_ENV: SUB, _phase_receipts.RESOURCE_GROUP_ENV: GROUP,
    }.items():
        monkeypatch.setenv(key, value)
    _phase_receipts.selected(SimpleNamespace(), items)
    assert dps.selection_count(tmp_path, phase, debug=debug) == 1
    with pytest.raises(dps.PhaseError):
        dps.selection_count(tmp_path, phase)
    session = SimpleNamespace(config=Mock(spec=["pluginmanager", "add_cleanup"]))
    stop_signal, previous_handler = object(), object()
    signals = SimpleNamespace(Signals={"SIGUSR1": stop_signal}, signal=Mock(return_value=previous_handler))
    platform_guard = Mock()
    monkeypatch.setattr(_phase_runtime, "require_linux", platform_guard)
    monkeypatch.setattr(_phase_runtime, "signal", signals)
    _phase_runtime.start_worker(session)
    platform_guard.assert_called_once_with()
    worker = session.config.pluginmanager.register.call_args.args[0]
    assert isinstance(worker, _phase_runtime.WorkerStop)
    session.config.pluginmanager.register.assert_called_once_with(worker, "dps-worker-stop")
    signals.signal.assert_called_once_with(stop_signal, worker.stop)
    receipt = hub.read_json(tmp_path / f"worker-{os.getpid()}.json")
    assert receipt["ready"] is True and receipt["pid"] == os.getpid()
    session.config.add_cleanup.assert_called_once()
    session.config.add_cleanup.call_args.args[0]()
    assert signals.signal.call_count == 2
    signals.signal.assert_called_with(stop_signal, previous_handler)


def test_dps_plugin_rejects_unvalidated_selection_before_receipt_or_test_imports(monkeypatch, tmp_path, mocker):
    monkeypatch.setenv("azext_iot_dps_test_phase", "regular")
    monkeypatch.setenv(focused.ENV, json.dumps({"suite": "DPS", "phase": "regular", "requestedNodes": ["unknown"]}))
    receipt = mocker.patch.object(dps_plugin, "PhaseReceipt")
    with pytest.raises(pytest.UsageError, match="unknown"):
        dps_plugin.pytest_load_initial_conftests(Mock(), None, [])
    receipt.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("uncertain", [False, True])
def test_sas_second_guard_and_original_provisioning_work_without_upload_case(tmp_path, monkeypatch, uncertain):
    chosen = [sas.NODES[1]]
    debug = focused.select("HubData", "sas", chosen)
    for key, value in {
        focused.ENV: json.dumps(debug), "AZEXT_IOT_HUB_SUITE": "HubData", "AZEXT_IOT_HUB_PHASE": "sas",
        "azext_iot_hubsas_subscription": SUB, "azext_iot_hubsas_receipt": str(tmp_path / "sas.json"),
        "AZURE_TEST_RUN_LIVE": "True",
    }.items():
        monkeypatch.setenv(key, value)
    config = SimpleNamespace(args=chosen, getoption=lambda _name, default=None: default, getini=lambda _: False)
    sas.validate_selection(config)
    runtime = sas.HubSasPhase(config, "hub", "storage", GROUP, "centraluseuap")
    assert hub.read_json(runtime.path)["debug"] == debug
    target = {"id": runtime.ids["hub"], "properties": {"disableLocalAuth": False}}
    reads = iter([None, None, None, None, target, {"id": runtime.ids["role"]}])
    monkeypatch.setattr(runtime, "read", lambda _: next(reads))
    command = Mock(return_value={"user": {"name": "caller"}})
    monkeypatch.setattr(runtime, "command", command)
    monkeypatch.setattr(sas, "sleep", Mock())
    scenario = SimpleNamespace(_testMethodName="test_device_messaging", cmd=Mock(), _create_hub=Mock())
    scenario.cmd.return_value.get_output_in_json.return_value = {"connectionString": "offline-storage"}
    if uncertain:
        command.side_effect = RuntimeError("Uncertain create")
        with pytest.raises(RuntimeError, match="Uncertain create"):
            runtime.provision(scenario)
        with pytest.raises(sas.HubSasError, match="not be replayed"):
            runtime.provision(scenario)
        assert command.call_count == 1
        return
    assert runtime.provision(scenario) is target
    assert runtime.provision(scenario) is target
    scenario._create_hub.assert_called_once()
    assert command.call_count == 3
    assert scenario.storage_cstring == "offline-storage"
    runtime.pytest_collection_modifyitems([SimpleNamespace(nodeid=chosen[0])])
    with pytest.raises(pytest.UsageError):
        runtime.pytest_collection_modifyitems([SimpleNamespace(nodeid=node) for node in sas.NODES])
    runtime.passed = set(chosen)
    runtime.absent = set(runtime.ids)
    runtime.sent = {"PUT " + value.casefold() for value in runtime.ids.values()}
    session = SimpleNamespace(exitstatus=0)
    runtime.check_results(session)
    assert session.exitstatus == 0


@pytest.mark.parametrize("evidence", ["summary", "phase", "selection", "junit", "stages"])
def test_full_dps_gate_refuses_debug_marker_even_with_all_original_cases(tmp_path, monkeypatch, evidence):
    with monkeypatch.context() as patch:
        patch.setattr(dps.signal, "signal", lambda *_: None)
        assert FULL_DPS_RUN(SUB, GROUP, tmp_path / "dps-phases", DpsReader(), execute=_execution) == 0
    assert not GATE["evaluate_dps_phases"](tmp_path)
    summary_path = tmp_path / "dps-phases.json"
    summary = hub.read_json(summary_path)
    if evidence == "summary":
        summary["mode"] = "debug"
    elif evidence == "phase":
        summary["phases"][0]["mode"] = "debug"
        ownership.write(tmp_path / "dps-phases/regular/result.json", summary["phases"][0])
    elif evidence == "selection":
        path = next((tmp_path / "dps-phases/regular/receipts").glob("selection-*.json"))
        value = hub.read_json(path)
        value["mode"] = "debug"
        ownership.write(path, value)
    elif evidence == "stages":
        ownership.write(tmp_path / "dps-phases/regular/receipts/pytest.json", {"mode": "debug"})
    else:
        path = tmp_path / "dps-phases/regular/junit.xml"
        tree = ET.parse(path)
        tree.getroot().set("mode", "debug")
        tree.write(path)
    ownership.write(summary_path, summary)
    assert GATE["evaluate_dps_phases"](tmp_path)


def tox_commands(output):
    return [tox_convert.StrConvert.to_command(line.strip()).args
            for line in output.splitlines() if line.startswith("  ")]


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_tox_rendered_commands_preserve_native_paths_and_quoting(monkeypatch, platform):
    root = r"C:\repo with spaces" if platform == "win32" else "/repo with spaces"
    arguments = [
        "python", root + "/azext_iot/tests/_hub_phase_runner.py", "--output", root + "/debug output",
        "--debug-node", "azext_iot/tests/example_int.py::test_case[parameter]",
    ]
    rendered = subprocess.list2cmdline(arguments) if platform == "win32" else shlex.join(arguments)
    monkeypatch.setattr(tox_convert, "sys", SimpleNamespace(platform=platform))
    assert tox_commands("[testenv]\ncommands =\n  " + rendered) == [arguments]


@pytest.mark.parametrize("service,phase", [("HubControl", "regular"), ("HubData", "sas"), ("DPS", "regular")])
def test_real_tox_configuration_preserves_install_and_routes_only_controller_selection(
    tmp_path, monkeypatch, service, phase,
):
    monkeypatch.setenv("azext_iot_hub_subscription", ownership.SUBSCRIPTION)
    environment = dict(os.environ)
    arguments = []
    if service == "DPS":
        _, _, captured = run_dps(tmp_path, monkeypatch, phase)
        environment.update(captured[0])
        expected = json.loads(environment[focused.ENV])["requestedNodes"]
    else:
        expected = nodes(service, phase)[-1:]
        arguments = ["--", "--debug-phase", phase, "--debug-node", expected[0],
                     "--output", str(tmp_path / "debug-output")]
    completed = subprocess.run(
        [sys.executable, "-m", "tox", "c", "-c", str(ROOT / "tox.ini"), "--workdir", str(tmp_path / "tox"),
         "-e", service + "-int", "-k", "commands", *arguments],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    commands = tox_commands(completed.stdout)
    installation = next(command for command in commands if command[:2] == ["pip", "install"])
    assert installation[-1] == "." and "--target" in installation
    assert Path(installation[installation.index("--target") + 1]).parts[-2:] == ("azure-cli-extensions", "azure-iot")
    launch = commands[-1]
    if service == "DPS":
        assert launch[:3] == ["python", "-m", "pytest"] and "-k" not in launch
        assert launch[launch.index("-p") + 1] == "azext_iot.tests._focused_live_plugin"
        assert expected[0] in launch and "./azext_iot/tests/dps" not in launch
        assert launch[launch.index("-n") + 1] == "0"
    else:
        assert launch[0] == "python" and Path(launch[1]) == ROOT / "azext_iot/tests/_hub_phase_runner.py"
        assert launch[launch.index("--debug-node") + 1] == expected[0]
        assert launch[launch.index("--debug-phase") + 1] == phase
        assert launch[launch.index("--subscription") + 1] == ownership.SUBSCRIPTION


@pytest.mark.parametrize("script", ["_hub_phase_runner.py", "_dps_phase_runner.py"])
def test_public_controller_help_needs_no_prepared_extension(script):
    completed = subprocess.run(
        [sys.executable, "-I", str(ROOT / "azext_iot/tests" / script), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--debug-node" in completed.stdout and "--debug-phase" in completed.stdout


def test_dps_outer_tox_environment_only_prepares_controller(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "tox", "c", "-c", str(ROOT / "tox.ini"), "--workdir", str(tmp_path / "tox"),
         "-e", "DPS-phases", "-k", "commands", "commands_pre", "deps"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    lines = completed.stdout.splitlines()
    assert "commands = " in lines and "commands_pre = " in lines
    assert "  ." in lines and "  azure-cli" in lines


def test_dps_tox_loads_early_plugin_from_checkout_not_testless_wheel(tmp_path):
    installed = tmp_path / "extension"
    (installed / "azext_iot").mkdir(parents=True)
    (installed / "azext_iot/__init__.py").write_text("", encoding="utf-8")
    scripts = tmp_path / "bin"
    scripts.mkdir()
    console = scripts / "pytest-entrypoint.py"
    console.write_text(
        "from pytest import console_main\nraise SystemExit(console_main())\n", encoding="utf-8",
    )
    guard = tmp_path / "guard"
    guard.mkdir()
    network_attempt = tmp_path / "network-attempt"
    (guard / "sitecustomize.py").write_text(
        "import socket\nfrom pathlib import Path\n"
        "def forbidden(*args, **kwargs):\n"
        f"    Path({str(network_attempt)!r}).write_text('denied')\n"
        "    raise AssertionError('Bootstrap regression attempted network')\n"
        "socket.socket.connect = forbidden\n"
        "socket.socket.connect_ex = forbidden\n"
        "socket.getaddrinfo = forbidden\n",
        encoding="utf-8",
    )
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    # Preserve interpreter dependencies, but reproduce tox's testless extension
    # preceding the checkout when a console entrypoint supplies sys.path[0].
    dependencies = [os.path.abspath(path) for path in sys.path if Path(path).resolve() != ROOT]
    environment = dict(
        os.environ, PYTHONPATH=os.pathsep.join(dict.fromkeys([str(guard), str(installed), *dependencies])),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="", PYTEST_PLUGINS="", PYTHONDONTWRITEBYTECODE="1",
        AZURE_CONFIG_DIR=str(tmp_path / "profile"), AZURE_TEST_RUN_LIVE="False",
        AZURE_CORE_COLLECT_TELEMETRY="0", AZURE_CORE_CHECK_VERSION="no",
        azext_iot_dps_test_phase="local-auth-toggle", azext_iot_dps_phase_receipts=str(tmp_path / "receipts"),
    )
    environment[focused.ENV] = json.dumps({
        "suite": "DPS", "phase": "local-auth-toggle", "requestedNodes": ["unknown"],
    })
    arguments = [
        "-c", str(config), "--rootdir", str(ROOT), "--confcutdir", str(ROOT),
        "-p", "azext_iot.tests._focused_live_plugin", "--help",
    ]
    baseline = subprocess.run(
        [sys.executable, str(console), *arguments], cwd=ROOT, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert baseline.returncode != 0
    assert "No module named 'azext_iot.tests'" in baseline.stderr
    rendered = subprocess.run(
        [sys.executable, "-m", "tox", "c", "-c", str(ROOT / "tox.ini"),
         "--workdir", str(tmp_path / "tox"), "-e", "DPS-int", "-k", "commands"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    launch = tox_commands(rendered.stdout)[-1]
    prefix = [sys.executable, str(console)] if launch[0] == "pytest" else [sys.executable, *launch[1:3]]
    result = subprocess.run(
        [*prefix, *arguments], cwd=ROOT, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )
    # The actual launcher must reach the real early selection guard, not import
    # a test module, collect scenarios or provision anything.
    assert result.returncode == 4, result.stdout + result.stderr
    assert "Debug selection contains unknown, excluded or out-of-phase nodes" in result.stderr
    assert not network_attempt.exists()
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("outcome", ["passed", "skipped", "teardown-failed"])
def test_real_pytest_process_records_exact_debug_stages_and_refuses_skip(tmp_path, outcome):
    module = tmp_path / "test_local.py"
    module.write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def resource():\n"
        "    yield\n"
        + ("    raise AssertionError('teardown failure')\n" if outcome == "teardown-failed" else "")
        + "def test_requested(resource):\n"
        + ("    pytest.skip('unavailable')\n" if outcome == "skipped" else "    assert True\n"),
        encoding="utf-8",
    )
    path = tmp_path / "pytest.json"
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    # Reuse the existing synthetic-plugin proof's socket guard and isolated pytest configuration.
    proof = r'''
import json
import os
import socket
import sys
import urllib3
def forbidden(*args, **kwargs):
    raise AssertionError("Offline plugin proof attempted network")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.getaddrinfo = forbidden
from azext_iot.tests import _focused_live as focused
selection = {"suite": "DPS", "phase": "regular", "requestedNodes": ["test_local.py::test_requested"]}
focused.select = lambda *args: selection
os.environ[focused.ENV] = json.dumps(selection)
import pytest
sys.exit(pytest.main([
    "-p", "azext_iot.tests._focused_live_plugin", "-c", "pytest.ini",
    "--rootdir", ".", "--confcutdir", ".", "-q", "test_local.py::test_requested",
]))
'''
    environment = dict(
        os.environ, PYTHONPATH=os.pathsep.join(dict.fromkeys([str(ROOT), *map(os.path.abspath, sys.path)])),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        azext_iot_dps_phase_receipts=str(tmp_path), azext_iot_dps_run_uid="a" * 32,
        azext_iot_dps_test_phase="regular", AZURE_CONFIG_DIR=str(tmp_path / "profile"),
        AZURE_TEST_RUN_LIVE="False",
    )
    completed = subprocess.run(
        [sys.executable, "-c", proof], cwd=tmp_path, env=environment,
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert completed.returncode == (0 if outcome == "passed" else 1), completed.stdout + completed.stderr
    receipt = hub.read_json(path)
    assert receipt["mode"] == "debug" and receipt["qualifiesFullSuite"] is False
    assert receipt["collected"] == receipt["expected"] == ["test_local.py::test_requested"]
    assert receipt["finished"] is True
    assert bool(receipt["errors"]) == (outcome != "passed")


def coverage_process(directory, module, arguments, environment):
    """Run real tox config/synthetic pytest, never live plugins, under a private socket guard."""
    private = dict(os.environ, **environment)
    for key in tuple(private):
        if key.startswith(("PYTEST_", "COV_CORE_", "TOX_", "COVERAGE_")) and key != "COVERAGE_FILE":
            private.pop(key)
    private.update(
        AZURE_CONFIG_DIR=str(directory / "private-cli"), AZURE_TEST_RUN_LIVE="False",
        AZURE_CORE_COLLECT_TELEMETRY="0", AZURE_CORE_CHECK_VERSION="no", AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no",
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_ADDOPTS="", PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=os.pathsep.join(dict.fromkeys(map(os.path.abspath, sys.path))),
    )
    proof = """
import runpy
import socket
import sys
def forbidden(*args, **kwargs):
    raise AssertionError("Offline coverage proof attempted network")
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.getaddrinfo = forbidden
module = sys.argv.pop(1)
sys.argv[0] = module
runpy.run_module(module, run_name="__main__")
"""
    return subprocess.run(
        [sys.executable, "-c", proof, module, *arguments], cwd=directory, env=private,
        capture_output=True, text=True, check=False, timeout=40,
    )


def dps_tox_coverage_environment(directory, environment, service="DPS"):
    """Inspect the actual repository tox factor/env expansion without creating an environment."""
    rendered = coverage_process(directory, "tox", [
        "c", "-c", str(ROOT / "tox.ini"), "--workdir", str(directory / "tox"),
        "-e", service + "-int", "-k", "set_env",
    ], environment)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    return dict(
        line.strip().split("=", 1) for line in rendered.stdout.splitlines()
        if line.startswith("  ") and "=" in line
    )


@pytest.mark.parametrize("service", ["HubControl", "DPS"])
@pytest.mark.parametrize("existing_branch", [False, True], ids=["existing-statements", "existing-branches"])
def test_real_debug_coverage_is_fresh_concurrent_and_does_not_combine_shared_database(
    tmp_path, monkeypatch, service, existing_branch,
):
    workspace = tmp_path / "synthetic checkout"
    workspace.mkdir()
    (workspace / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (workspace / "coverage.ini").write_text(
        f"[run]\nbranch = {not existing_branch}\n", encoding="utf-8",
    )
    (workspace / "sample.py").write_text(
        "def choose(value):\n    if value:\n        return 1\n    return 0\n", encoding="utf-8",
    )
    (workspace / "test_sample.py").write_text(
        "from sample import choose\n"
        "def test_body():\n    assert choose(True) == 1\n    print('BODY_PASSED')\n", encoding="utf-8",
    )
    shared = workspace / ".coverage"
    baseline = CoverageData(basename=str(shared))
    if existing_branch:
        baseline.add_arcs({str(workspace / "sample.py"): [(-1, 1), (1, -1)]})
    else:
        baseline.add_lines({str(workspace / "sample.py"): [1]})
    baseline.write()
    original = shared.read_bytes()
    shared_xml = workspace / "coverage.xml"
    shared_xml.write_bytes(b"<coverage existing='preserve-user-report' />")
    original_xml = shared_xml.read_bytes()
    arguments = [
        "-c", str(workspace / "pytest.ini"), "--rootdir", str(workspace), "--confcutdir", str(workspace),
        "-p", "pytest_cov.plugin", "-p", "no:cacheprovider", "-q", "-s", "test_sample.py::test_body",
        "--cov=sample", "--cov-append", "--cov-config", str(workspace / "coverage.ini"), "--cov-report=",
    ]
    # Demonstrate the real old bug: the body passes, then pytest-cov's combine fails.
    old = coverage_process(workspace, "pytest", arguments, {"COVERAGE_FILE": str(shared)})
    assert old.returncode == 3, old.stdout + old.stderr
    assert "BODY_PASSED" in old.stdout
    assert "Can't combine" in old.stdout + old.stderr
    assert shared.read_bytes() == original

    destinations = []
    reports = []
    for index in range(2):
        output = tmp_path / f"debug output {index}"
        if service == "DPS":
            result, _, captured = run_dps(output, monkeypatch, "regular")
            assert result == 0
            managed = captured[0]["azext_iot_dps_coverage_file"]
            expanded = dps_tox_coverage_environment(output, captured[0])
            assert expanded["COVERAGE_FILE"] == managed
            destination = Path(expanded["COVERAGE_FILE"])
            assert destination == output / "dps-phases" / "regular" / ".coverage"
            rendered = coverage_process(output, "tox", [
                "c", "-c", str(ROOT / "tox.ini"), "--workdir", str(output / "tox"),
                "-e", "DPS-int", "-k", "commands",
            ], captured[0])
            assert rendered.returncode == 0, rendered.stdout + rendered.stderr
            command = tox_commands(rendered.stdout)[-1]
        else:
            result, _, _, _, captured = run_hub(output, monkeypatch, service, "regular")
            assert result == 0
            destination = Path(captured[0]["COVERAGE_FILE"])
            assert destination == output / "hub-phases" / "regular" / ".coverage"
            command = hub.command(
                service, "regular", debug=json.loads(captured[0][focused.ENV]), folder=destination.parent,
            )
        report_options = [value for value in command if value.startswith("--cov-report=")]
        assert report_options == [f"--cov-report=xml:{destination.with_name('coverage.xml')}"]
        reports.append(report_options[0])
        assert destination.is_absolute() and not destination.exists()
        destinations.append(destination)
    assert len(set(destinations)) == 2

    # Both synthetic pytest processes run at once from the same checkout, as local
    # debug controllers can. They must never combine each other's or the old data.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                coverage_process, workspace, "pytest", [*arguments[:-1], report], {"COVERAGE_FILE": str(destination)},
            )
            for destination, report in zip(destinations, reports)
        ]
        for future in futures:
            result = future.result(timeout=50)
            assert result.returncode == 0, result.stdout + result.stderr
            assert "BODY_PASSED" in result.stdout and "1 passed" in result.stdout
    for destination in destinations:
        measured = CoverageData(basename=str(destination))
        measured.read()
        assert measured.has_arcs() is not existing_branch
        source = next(name for name in measured.measured_files() if Path(name) == workspace / "sample.py")
        assert measured.lines(source)
        xml = ET.parse(destination.with_name("coverage.xml")).getroot()
        assert xml.tag == "coverage" and int(xml.get("lines-covered")) > 0
    assert shared.read_bytes() == original
    assert shared_xml.read_bytes() == original_xml


@pytest.mark.parametrize("suite,phase", [("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas")])
def test_hub_debug_overrides_ambient_coverage_without_changing_full_mode(tmp_path, suite, phase):
    base = {"COVERAGE_FILE": str(tmp_path / "existing-user-coverage")}
    folder = tmp_path / "unique debug output" / phase
    debug = focused.select(suite, phase, nodes(suite, phase)[:1])
    full = hub.environment(base, suite, phase, folder, "run-id", SUB, GROUP)
    isolated_env = hub.environment(base, suite, phase, folder, "run-id", SUB, GROUP, debug=debug)
    assert base["COVERAGE_FILE"] == full["COVERAGE_FILE"]
    assert isolated_env["COVERAGE_FILE"] == str(folder / ".coverage")
    assert "COVERAGE_FILE" not in hub.environment({}, suite, phase, folder, "run-id", SUB, GROUP)
    for mode in (None, debug):
        command = hub.command(suite, phase, debug=mode)
        assert "--cov=azext_iot" in command and "--cov-append" in command
        assert command[command.index("--cov-config") + 1] == str(ROOT / ".coveragerc")
        assert "--no-cov" not in command
    assert not folder.exists()  # Environment construction cannot erase/create coverage.


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("ambient", ["", "ambient-coverage"])
def test_dps_rejects_ambient_managed_coverage_before_inventory_or_execution(tmp_path, monkeypatch, debug, ambient):
    monkeypatch.setenv("azext_iot_dps_coverage_file", ambient)
    reader, execute = Mock(reads=[]), Mock()
    with monkeypatch.context() as patch:
        patch.setattr(dps.signal, "signal", lambda *_: None)
        result = dps.run(
            SUB, GROUP, tmp_path / "dps-phases", reader, execute=execute,
            debug_phase="regular" if debug else None, debug_nodes=nodes("DPS", "regular")[:1] if debug else None,
        )
    assert result == 1
    reader.inventory.assert_not_called()
    execute.assert_not_called()
    assert hub.read_json(tmp_path / "dps-phases.json")["error"]["type"] == "PhaseError"


def test_dps_full_mode_keeps_global_coverage_and_ignores_unmanaged_ambient_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COVERAGE_FILE", str(tmp_path / "must-not-use"))
    captured = []

    def execute(command, env, *args):
        captured.append(env)
        return _execution(command, env, *args)

    with monkeypatch.context() as patch:
        patch.setattr(dps.signal, "signal", lambda *_: None)
        assert dps.run(SUB, GROUP, tmp_path / "dps-phases", DpsReader(), execute=execute) == 0
    assert len(captured) == 3
    for environment in captured:
        assert "azext_iot_dps_coverage_file" not in environment
        assert dps_tox_coverage_environment(tmp_path, environment)["COVERAGE_FILE"] == ".coverage"
    assert not (tmp_path / "must-not-use").exists()


@pytest.mark.parametrize("service", ["HubControl", "HubData", "ADR", "ADU"])
def test_dps_coverage_bridge_does_not_expand_other_tox_services(tmp_path, service):
    expanded = dps_tox_coverage_environment(tmp_path, {
        "azext_iot_hub_subscription": SUB,
        "azext_iot_dps_coverage_file": str(tmp_path / "managed dps only"),
        "COVERAGE_FILE": str(tmp_path / "unmanaged ambient"),
    }, service=service)
    assert "COVERAGE_FILE" not in expanded


@pytest.mark.parametrize("service", ["HubControl", "DPS"])
def test_real_full_coverage_still_appends_prior_phase_data_to_checkout_default(tmp_path, service):
    shared = tmp_path / ".coverage"
    earlier = str(tmp_path / "earlier_phase.py")
    baseline = CoverageData(basename=str(shared))
    baseline.add_lines({earlier: [1]})
    baseline.write()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "coverage.ini").write_text("[run]\nbranch = False\n", encoding="utf-8")
    (tmp_path / "test_current.py").write_text("def test_body():\n    assert True\n", encoding="utf-8")
    if service == "DPS":
        environment = {"COVERAGE_FILE": dps_tox_coverage_environment(tmp_path, {})["COVERAGE_FILE"]}
        assert environment["COVERAGE_FILE"] == ".coverage"
    else:
        environment = hub.environment({}, service, "regular", tmp_path / "full-phase", "run", SUB, GROUP)
        assert "COVERAGE_FILE" not in environment
    result = coverage_process(tmp_path, "pytest", [
        "-c", str(tmp_path / "pytest.ini"), "--rootdir", str(tmp_path), "--confcutdir", str(tmp_path),
        "-p", "pytest_cov.plugin", "-p", "no:cacheprovider", "-q", "test_current.py::test_body",
        "--cov=test_current", "--cov-append", "--cov-config", str(tmp_path / "coverage.ini"), "--cov-report=",
    ], environment)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = CoverageData(basename=str(shared))
    combined.read()
    assert combined.has_arcs() is False
    assert combined.lines(earlier) == [1]
    current = next(name for name in combined.measured_files() if Path(name) == tmp_path / "test_current.py")
    assert combined.lines(current)


@pytest.mark.parametrize("service,phase", [
    ("HubControl", "regular"), ("HubData", "entra"), ("HubData", "sas"),
    ("DPS", "regular"), ("DPS", "service-sas"), ("DPS", "local-auth-toggle"),
])
@pytest.mark.parametrize("debug", [False, True], ids=["full-300s", "debug-no-periodic-dumps"])
def test_effective_faulthandler_options_keep_deadlines_and_failure_tracebacks(
    tmp_path, monkeypatch, service, phase, debug,
):
    if service == "DPS":
        environment = {}
        if debug:
            result, _, captured = run_dps(tmp_path, monkeypatch, phase)
            assert result == 0
            environment = captured[0]
        rendered = coverage_process(tmp_path, "tox", [
            "c", "-c", str(ROOT / "tox.ini"), "--workdir", str(tmp_path / "tox"),
            "-e", "DPS-int", "-k", "commands",
        ], environment)
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        command = tox_commands(rendered.stdout)[-1]
    else:
        selection = focused.select(service, phase, nodes(service, phase)[:1]) if debug else None
        command = hub.command(service, phase, debug=selection)
    dumps = [
        value for previous, value in zip(command, command[1:])
        if previous == "-o" and value.startswith("faulthandler_timeout=")
    ]
    expected = 0 if debug else 300
    assert dumps == (
        ["faulthandler_timeout=300", "faulthandler_timeout=0"] if service == "DPS" and debug
        else [f"faulthandler_timeout={expected}"]
    )
    assert "--timeout=900" in command
    assert "--integration-progress-interval=60" in command
    assert not {"no:timeout", "no:faulthandler", "--tb=no"}.intersection(command)
    if not debug:
        reports = [value for value in command if value.startswith("--cov-report")]
        assert reports == ([] if service == "DPS" else ["--cov-report="])

    # Let real pytest parse the ordered options, not just a hand-written last-wins
    # approximation. Collect only synthetic local tests; keep real timeout plugin
    # enabled and demonstrate that an ordinary failing test still has its traceback.
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_diagnostics.py").write_text(
        "def test_effective_options(pytestconfig):\n"
        f"    assert float(pytestconfig.getini('faulthandler_timeout')) == {expected}\n"
        "    assert pytestconfig.getoption('timeout') == 900\n"
        "def test_failure():\n    raise AssertionError('FAILURE_TRACEBACK_PRESERVED')\n",
        encoding="utf-8",
    )
    result = coverage_process(tmp_path, "pytest", [
        "-c", str(tmp_path / "pytest.ini"), "--rootdir", str(tmp_path), "--confcutdir", str(tmp_path),
        "-p", "pytest_timeout", "-p", "no:cacheprovider", "--timeout=900",
        *[argument for value in dumps for argument in ("-o", value)], "-q", "test_diagnostics.py",
    ], {})
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed, 1 passed" in result.stdout, result.stdout + result.stderr
    assert "AssertionError: FAILURE_TRACEBACK_PRESERVED" in result.stdout
