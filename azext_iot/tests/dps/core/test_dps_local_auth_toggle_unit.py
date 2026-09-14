# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
import inspect
import json
from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.tests.dps import _phase, _phase_receipts as receipts, _phase_runtime as runtime
from azext_iot.tests.dps import conftest as fixtures
from azext_iot.tests.dps.core import test_dps_disable_local_auth_int as live

UID = "b" * 32
SUB = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for key, value in {
        _phase.PHASE_ENV: _phase.LOCAL_AUTH_TOGGLE,
        receipts.DIRECTORY_ENV: str(tmp_path),
        receipts.RUN_UID_ENV: UID,
        receipts.SUBSCRIPTION_ENV: SUB,
        receipts.RESOURCE_GROUP_ENV: "group",
    }.items():
        monkeypatch.setenv(key, value)
    for name in ("azext_iot_testdps", "azext_iot_testdps_hub", "azext_iot_testhub"):
        monkeypatch.setattr(fixtures.settings.env, name, None)
    monkeypatch.setattr(fixtures, "ENTITY_RG", "group")
    return tmp_path


def _items():
    assert live.pytestmark.mark.name == _phase.LOCAL_AUTH_TOGGLE_MARKER
    return [
        SimpleNamespace(
            nodeid="azext_iot/tests/dps/core/test_dps_disable_local_auth_int.py::" + name,
            get_closest_marker=lambda marker: live.pytestmark if marker == _phase.LOCAL_AUTH_TOGGLE_MARKER else None,
        )
        for name, value in vars(live).items() if name.startswith("test_") and inspect.isfunction(value)
    ]


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS, _phase.LOCAL_AUTH_TOGGLE])
def test_actual_toggle_definitions_match_manifest_and_do_not_enter_other_phases(monkeypatch, mocker, phase):
    from azext_iot.tests.dps.core.test_dps_phase_unit import _regular_items, _sas_items

    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    toggle = _items()
    assert {_phase.normalize_nodeid(item.nodeid) for item in toggle} == _phase.expected_nodeids(_phase.LOCAL_AUTH_TOGGLE)
    items = _regular_items() + _sas_items() + toggle
    _phase.select_items(mocker.Mock(), items)
    assert {_phase.normalize_nodeid(item.nodeid) for item in items} == _phase.expected_nodeids(phase)
    assert all((item in items) == (phase == _phase.LOCAL_AUTH_TOGGLE) for item in toggle)


def test_default_selection_never_runs_policy_toggles(monkeypatch, mocker):
    monkeypatch.delenv(_phase.PHASE_ENV, raising=False)
    items = _items()
    _phase.select_items(mocker.Mock(), items)
    assert not items


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unexpected", "empty"])
def test_toggle_requires_exact_three_cases(isolated, mocker, defect):
    items = _items()
    if defect == "missing":
        items.pop()
    elif defect == "duplicate":
        items.append(items[0])
    elif defect == "unexpected":
        items[0].nodeid += "_unexpected"
    else:
        items = []
    with pytest.raises(pytest.UsageError, match="requires exactly 3 cases"):
        _phase.select_items(mocker.Mock(), items)


@pytest.mark.parametrize("workers", [1, 7, "auto"])
def test_parallel_toggle_rejected_before_fixture_setup(isolated, mocker, workers):
    config = mocker.Mock()
    config.getoption.return_value = workers
    with pytest.raises(pytest.UsageError, match="serially"):
        _phase.configure(config)


@pytest.mark.parametrize("stage", ["setup", "call", "teardown"])
def test_requested_toggle_skip_is_failure(isolated, stage):
    item = _items()[0]
    report = pytest.TestReport(
        nodeid=item.nodeid, location=("test.py", 1, "toggle"), keywords={}, outcome="skipped",
        longrepr=("test.py", 1, "missing prerequisite"), when=stage,
    )
    _phase.require_requested_coverage(item, report)
    assert report.failed


@pytest.mark.parametrize("kind", ["h", "nh", "hub"])
def test_toggle_rejects_other_resource_kinds(isolated, kind):
    with pytest.raises(RuntimeError, match="run UID/kind"):
        receipts.before_create("borrowed", "group", UID + "-local-auth-toggle", kind)
    assert not list(isolated.glob("owned-*.json"))


@pytest.mark.parametrize("defect", ["receipt", "regular", "pin", "shared", "hub"])
def test_toggle_provisioning_fails_before_acquire_or_cloud_work(isolated, mocker, monkeypatch, defect):
    acquire = mocker.patch.object(fixtures, "_shared_acquire")
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    if defect == "receipt":
        for name in (receipts.DIRECTORY_ENV, receipts.RUN_UID_ENV, receipts.SUBSCRIPTION_ENV, receipts.RESOURCE_GROUP_ENV):
            monkeypatch.delenv(name)
    elif defect == "regular":
        monkeypatch.setenv(_phase.PHASE_ENV, _phase.REGULAR)
    elif defect == "pin":
        monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps", "external")
    with pytest.raises(pytest.UsageError, match="owned|isolated"):
        if defect in ("shared", "hub", "pin"):
            fixtures._iot_dps_provisioner(
                SimpleNamespace(config=SimpleNamespace()),
                iot_hub={"name": "borrowed"} if defect == "hub" else None,
                managed_kind=None if defect == "shared" else "dla",
            )
        else:
            next(fixtures.provisioned_iot_dps_local_auth_module.__wrapped__(SimpleNamespace()))
    acquire.assert_not_called()
    invoke.assert_not_called()


def test_toggle_creation_keeps_receipts_true_policy_grants_and_no_broad_gc(isolated, mocker):
    uid = UID + "-local-auth-toggle"
    mocker.patch.object(fixtures, "_timestamp", return_value="stamp")
    name = f"{fixtures.INT_TEST_DPS_PREFIX}-stamp-{uid[:8]}-dla"
    resource = {
        "id": f"/subscriptions/{SUB}/resourceGroups/group/providers/Microsoft.Devices/provisioningServices/{name}",
        "name": name, "tags": {"intTest": "true", "runUid": uid, "kind": "dla"},
        "properties": {"disableLocalAuth": True, "provisioningState": "Succeeded"},
    }
    mocker.patch.object(fixtures, "_find_dps_by_name", return_value=None)
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.return_value = resource
    grant = mocker.patch.object(fixtures, "assign_iot_dps_dataplane_rbac_role")
    mocker.patch.object(fixtures, "_unlink_all_hubs")
    gc = mocker.patch.object(fixtures, "_gc_stale_resources_once")
    actual = fixtures._create_managed_dps(uid, "dla", None, disable_local_auth=True)
    assert actual == (name, resource)
    assert "--disable-local-auth true" in invoke.call_args.args[0]
    assert invoke.call_args.kwargs == {"capture_stderr": True}
    grant.assert_called_once_with(resource)
    gc.assert_not_called()
    assert json.loads((isolated / "created-dla.json").read_text())["create_completed"] is True
    with pytest.raises(RuntimeError, match="repeat"):
        fixtures._create_managed_dps(uid, "dla", None, disable_local_auth=True)
    assert invoke.call_count == 1


def test_serial_worker_installs_cooperative_cleanup_signal(isolated, mocker):
    config = mocker.Mock(spec=["pluginmanager", "add_cleanup"])
    session = SimpleNamespace(config=config)
    require_linux = mocker.patch.object(runtime, "require_linux")
    signals = SimpleNamespace(
        Signals={"SIGUSR1": mocker.sentinel.stop_signal},
        signal=mocker.Mock(return_value=mocker.sentinel.previous_handler),
    )
    mocker.patch.object(runtime, "signal", signals)
    runtime.start_worker(session)
    require_linux.assert_called_once_with()
    config.pluginmanager.register.assert_called_once()
    assert len(list(isolated.glob("worker-*.json"))) == 1
    plugin = config.pluginmanager.register.call_args.args[0]
    signals.signal.assert_called_once_with(mocker.sentinel.stop_signal, plugin.stop)
    config.add_cleanup.assert_called_once()
    config.add_cleanup.call_args.args[0]()
    assert signals.signal.call_args.args == (mocker.sentinel.stop_signal, mocker.sentinel.previous_handler)
    assert signals.signal.call_count == 2
    plugin.cleaning = True
    plugin.stop()
    assert "cleanup" in session.shouldstop


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_serial_worker_rejects_non_linux_before_setup(isolated, mocker, platform):
    config = mocker.Mock(spec=["pluginmanager", "add_cleanup"])
    mocker.patch.object(runtime, "sys", SimpleNamespace(platform=platform))
    signals = SimpleNamespace(Signals={}, signal=mocker.Mock())
    mocker.patch.object(runtime, "signal", signals)
    write = mocker.patch.object(receipts, "write")
    with pytest.raises(pytest.UsageError, match="requires Linux"):
        runtime.start_worker(SimpleNamespace(config=config))
    config.pluginmanager.register.assert_not_called()
    config.add_cleanup.assert_not_called()
    signals.signal.assert_not_called()
    write.assert_not_called()
    assert not list(isolated.glob("worker-*.json"))


@pytest.mark.parametrize("failure", [
    CLIError("invalid arguments"), CLIError("unrelated device 1401"),
    HttpResponseError(message="backend", status_code=500),
])
def test_unrelated_error_cannot_satisfy_expected_sas_denial(mocker, failure):
    mocker.patch.object(live, "_invoke", side_effect=failure)
    with pytest.raises(AssertionError, match="unrelated"):
        live._assert_service_sas_denied("iot dps enrollment list")


@pytest.mark.parametrize("failure", [CLIError("(401) Unauthorized"), CLIError("(403) Forbidden")])
def test_expected_sas_authentication_failure_is_specific(mocker, failure):
    mocker.patch.object(live, "_invoke", side_effect=failure)
    live._assert_service_sas_denied("iot dps enrollment list")


@pytest.mark.parametrize("failed_enable", [False, True])
def test_toggle_fixture_restores_disabled_policy_after_failed_or_successful_enable(mocker, failed_enable):
    invoke = mocker.patch.object(live, "_invoke")
    if failed_enable:
        invoke.side_effect = [CLIError("enable failed"), mocker.Mock()]
    resource = {"name": "owned", "resourceGroup": "group"}
    fixture = live.local_auth_dps.__wrapped__(resource)
    if failed_enable:
        with pytest.raises(CLIError, match="enable failed"):
            next(fixture)
    else:
        assert next(fixture) is resource
        fixture.close()
    assert [call.args[0].rsplit(" ", 1)[-1] for call in invoke.call_args_list] == ["false", "true"]


def test_live_toggle_matrix_exercises_all_auth_modes_in_each_policy_state(mocker):
    state = {"disabled": False}
    seen = []
    resource = {
        "name": "owned", "resourceGroup": "group", "connectionString": "unit-cstring",
        "dps": {"tags": {"intTest": "true"}},
    }

    def invoke(command):
        if command.startswith("iot dps update"):
            state["disabled"] = command.endswith("true")
        else:
            seen.append((state["disabled"], command))
            if state["disabled"] and "--auth-type login" not in command:
                raise CLIError("(401) Unauthorized")
        return SimpleNamespace(success=lambda: True, as_json=lambda: deepcopy(resource))

    mocker.patch.object(live, "_invoke", side_effect=invoke)
    live.test_dps_disable_local_auth_dataplane(resource)
    assert [disabled for disabled, _ in seen] == [False] * 3 + [True] * 3 + [False] * 3
    for offset in (0, 3, 6):
        commands = [command for _, command in seen[offset:offset + 3]]
        assert "--auth-type login" in commands[0]
        assert "--auth-type key" in commands[1]
        assert "--login unit-cstring" in commands[2]
