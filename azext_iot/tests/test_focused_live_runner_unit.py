# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline focused-controller proofs; no live collection or resource provisioning."""

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
    result, summary, output, calls, _ = run_hub(tmp_path, monkeypatch, suite, phase, whole=whole)
    assert result == 0 and calls == [phase]
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


def run_dps(tmp_path, monkeypatch, phase, *, defect=None, whole=False, reader=None):
    chosen = nodes("DPS", phase) if whole else nodes("DPS", phase)[:1]
    captured = []

    def execute(command, env, log, runtime, cleanup, cancelled):
        captured.append(env)
        assert Path.cwd() == ROOT
        assert env["azext_iot_dps_workers"] == "0"
        debug = json.loads(env[focused.ENV])
        expected = debug["requestedNodes"]
        assert shlex.split(env[focused.DPS_ARGS_ENV])[-len(expected):] == expected
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
def test_dps_debug_phase_keeps_admission_cleanup_and_never_qualifies(tmp_path, monkeypatch, phase, whole):
    result, summary, captured = run_dps(tmp_path, monkeypatch, phase, whole=whole)
    assert result == 0 and summary["status"] == "debug-passed"
    assert [value["name"] for value in summary["phases"]] == [phase]
    assert summary["baseline"]["capacity"]["required"] == dps.REQUIRED_SLOTS
    assert summary["runner_seconds"] <= dps.RUNNER_SECONDS
    assert summary["phases"][0]["cleanup"]["complete"] is True
    assert summary["phases"][0]["results"]["stage_errors"] == []
    assert captured[0]["azext_iot_dps_test_phase"] == phase
    assert GATE["evaluate_dps_phases"](tmp_path)
    assert "UNSAFE_CAPTURED_CREDENTIAL" not in (tmp_path / "dps-phases" / phase / "junit.xml").read_text()


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
def test_debug_does_not_reduce_conservative_capacity(tmp_path, monkeypatch, suite, phase):
    if suite == "DPS":
        result, summary, captured = run_dps(tmp_path, monkeypatch, phase, reader=DpsReader(9))
    else:
        result, summary, _, _, captured = run_hub(tmp_path, monkeypatch, suite, phase, reader=HubReader(49))
    assert result == 1 and summary["status"] == "debug-failed"
    assert not captured


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
    items = [SimpleNamespace(nodeid=node, get_closest_marker=lambda _: None) for node in chosen]
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
        assert launch[0] == "pytest" and "-k" not in launch
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
