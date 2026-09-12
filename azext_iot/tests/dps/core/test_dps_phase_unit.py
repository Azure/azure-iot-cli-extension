# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import inspect
import runpy
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import CLIInternalError

from azext_iot.tests.dps import _phase
from azext_iot.tests.dps import conftest as fixtures


def _item(nodeid, service_sas=False):
    return SimpleNamespace(
        nodeid="azext_iot/tests/dps/" + nodeid,
        get_closest_marker=lambda name: pytest.mark.dps_service_sas if (
            service_sas and name == _phase.SERVICE_SAS_MARKER
        ) else None,
    )


def _sas_items():
    return [_item(nodeid, True) for nodeid in sorted(_phase.SERVICE_SAS_NODEIDS)]


def _regular_items():
    return [_item(nodeid) for nodeid in sorted(_phase.expected_nodeids(_phase.REGULAR))]


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
def test_pending_cross_service_certificate_tests_are_not_wired_into_these_phases(monkeypatch, mocker, phase):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    certificates = [_item(f"certificate.py::{name}[login]") for name in _phase.PENDING_CERTIFICATE_TESTS]
    items = _regular_items() + _sas_items() + certificates
    _phase.select_items(mocker.Mock(), items)
    assert not any(item in items for item in certificates)


@pytest.mark.parametrize("nodeid", [
    "certificate.py::test_dps_enrollment_adr_certificate_reference_round_trip",
    "certificate.py::test_dps_enrollment_group_adr_certificate_reference_round_trip",
    "certificate.py::test_register_and_issue_certificate_contract[default]",
    "certificate.py::test_register_and_issue_certificate_contract[deadline]",
])
def test_default_invocation_preserves_existing_manual_certificate_selection(monkeypatch, mocker, nodeid):
    monkeypatch.delenv(_phase.PHASE_ENV, raising=False)
    certificate = _item(nodeid)
    items = [certificate]
    config = mocker.Mock()
    _phase.select_items(config, items)
    assert items == [certificate]
    config.hook.pytest_deselected.assert_not_called()


@pytest.mark.parametrize("phase", ["", "sas", "certificate", "REGULAR", "unknown"])
def test_unknown_phase_is_an_error_before_setup(monkeypatch, mocker, phase):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    config = mocker.Mock()
    with pytest.raises(pytest.UsageError, match="Unknown azext_iot_dps_test_phase"):
        _phase.configure(config)
    config.addinivalue_line.assert_not_called()


def test_default_phase_preserves_disabled_local_auth(monkeypatch):
    monkeypatch.delenv(_phase.PHASE_ENV, raising=False)
    assert _phase.get_phase() == _phase.REGULAR
    assert _phase.local_auth_disabled() is True


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
def test_phase_selects_exact_marked_capability_not_device_credentials(monkeypatch, mocker, phase):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    regular = _regular_items()
    sas = _sas_items()
    items = regular + sas
    config = mocker.Mock()
    _phase.select_items(config, items)
    assert items == (regular if phase == _phase.REGULAR else sas)
    config.hook.pytest_deselected.assert_called_once_with(
        items=sas if phase == _phase.REGULAR else regular
    )


@pytest.mark.parametrize("invalid_selection", ["empty", "filtered", "unexpected", "duplicate"])
def test_requested_sas_phase_cannot_succeed_with_missing_or_extra_cases(monkeypatch, mocker, invalid_selection):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    items = _sas_items()
    if invalid_selection == "empty":
        items = []
    elif invalid_selection == "filtered":
        items.pop()
    elif invalid_selection == "unexpected":
        items[-1] = _item("other.py::unexpected", True)
    else:
        items.append(items[0])
    config = mocker.Mock()
    with pytest.raises(pytest.UsageError, match="requires exactly 29 cases"):
        _phase.select_items(config, items)
    config.hook.pytest_deselected.assert_not_called()


@pytest.mark.parametrize("defect", ["five", "duplicate", "replacement", "empty"])
def test_explicit_regular_phase_requires_exact_branch_identities(monkeypatch, mocker, defect):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.REGULAR)
    items = _regular_items()
    if defect == "five":
        items = items[:5]
    elif defect == "duplicate":
        items[-1] = items[0]
    elif defect == "replacement":
        items[-1] = _item("test_other_int.py::test_other")
    else:
        items = []
    with pytest.raises(pytest.UsageError, match="regular phase requires exactly"):
        _phase.select_items(mocker.Mock(), items)


@pytest.mark.parametrize("stage", ["setup", "call", "teardown"])
def test_explicit_regular_phase_converts_skips_to_failures(monkeypatch, stage):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.REGULAR)
    item = _regular_items()[0]
    report = pytest.TestReport(
        nodeid=item.nodeid, location=("test.py", 1, "regular"), keywords={}, outcome="skipped",
        longrepr=("test.py", 1, "missing prerequisite"), when=stage,
    )
    _phase.require_requested_coverage(item, report)
    assert report.failed


def test_real_shared_lifecycle_marks_match_exact_sas_manifest(mocker):
    # Import test definitions only; no integration fixtures or commands execute.
    embedded = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")
    root = Path(fixtures.__file__).parent
    actual = set()
    modules = {nodeid.partition("::")[0] for nodeid in _phase.SERVICE_SAS_NODEIDS}
    for module_name in modules:
        module = runpy.run_path(str(root / module_name))
        for name, function in module.items():
            if not name.startswith("test_") or not inspect.isfunction(function):
                continue
            marks = getattr(function, "pytestmark", [])
            if any(mark.name == _phase.SERVICE_SAS_MARKER for mark in marks):
                actual.add(f"{module_name}::{name}")
            for mark in marks:
                if mark.name == "parametrize" and mark.args[0] == "auth_phases":
                    for param in mark.args[1]:
                        assert not any(m.name in {"skip", "skipif"} for m in param.marks)
                        if any(m.name == _phase.SERVICE_SAS_MARKER for m in param.marks):
                            actual.add(f"{module_name}::{name}[{param.id}]")
    assert actual == _phase.SERVICE_SAS_NODEIDS
    assert len(actual) == 29
    embedded.return_value.invoke.assert_not_called()


@pytest.mark.parametrize("phase,marked,skipped,expected", [
    (_phase.REGULAR, True, True, "failed"),
    (_phase.SERVICE_SAS, False, True, "skipped"),
    (_phase.SERVICE_SAS, True, False, "passed"),
    (_phase.SERVICE_SAS, True, True, "failed"),
])
def test_requested_sas_skip_is_a_failure(monkeypatch, phase, marked, skipped, expected):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    report = SimpleNamespace(
        skipped=skipped, outcome="skipped" if skipped else "passed",
        longrepr="Missing GWv2 prerequisite", wasxfail="old unconditional skip",
    )
    _phase.require_requested_coverage(_item("test", marked), report)
    assert report.outcome == expected
    if expected == "failed":
        assert "cannot be skipped" in report.longrepr
        assert "Missing GWv2 prerequisite" in report.longrepr
        assert not hasattr(report, "wasxfail")


@pytest.mark.parametrize("stage", ["setup", "call", "teardown"])
def test_sas_hook_turns_real_pytest_skip_report_into_failure(monkeypatch, stage):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    item = _sas_items()[0]
    report = pytest.TestReport(
        nodeid=item.nodeid, location=("test.py", 1, "requested_sas"), keywords={},
        outcome="skipped", longrepr=("test.py", 1, "Skipped: missing prerequisite"), when=stage,
    )
    hook = fixtures.pytest_runtest_makereport(item)
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: report))
    assert report.failed
    assert not report.skipped
    assert "Requested service-sas coverage cannot be skipped" in report.longrepr


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
@pytest.mark.parametrize("policy", [True, False, None, "false"])
def test_resource_policy_must_match_the_requested_phase(monkeypatch, phase, policy):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    resource = {"name": "supplied", "properties": {"disableLocalAuth": policy}}
    expected = phase == _phase.REGULAR
    if policy is expected:
        fixtures._assert_local_auth_policy(resource)
    else:
        with pytest.raises(AssertionError, match=f"disableLocalAuth={str(expected).lower()}"):
            fixtures._assert_local_auth_policy(resource)


@pytest.mark.parametrize("kind", ["dps", "hub"])
@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
def test_missing_supplied_resource_never_causes_creation(monkeypatch, mocker, phase, kind):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps", "supplied")
    monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps_hub", "supplied")
    mocker.patch.object(fixtures, f"_find_{kind}_by_name", return_value=None)
    cli = mocker.patch.object(fixtures, "cli")
    grant = mocker.patch.object(fixtures, "_assign_current_user_role")
    provisioner = fixtures._iot_dps_provisioner if kind == "dps" else fixtures._iot_hubs_provisioner
    with pytest.raises(CLIInternalError, match="fixtures will not create a supplied resource"):
        provisioner(SimpleNamespace(config=SimpleNamespace()))
    cli.invoke.assert_not_called()
    grant.assert_not_called()


@pytest.mark.parametrize("kind", ["dps", "hub"])
def test_sas_rejects_supplied_dla_true_before_any_mutation(monkeypatch, mocker, kind):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps", "supplied")
    monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps_hub", "supplied")
    target = {"name": "supplied", "properties": {"disableLocalAuth": True}}
    mocker.patch.object(fixtures, f"_find_{kind}_by_name", return_value=target)
    cli = mocker.patch.object(fixtures, "cli")
    grant = mocker.patch.object(fixtures, "_assign_current_user_role")
    keys = mocker.patch.object(fixtures, "_dps_service_connection_string")
    provisioner = fixtures._iot_dps_provisioner if kind == "dps" else fixtures._iot_hubs_provisioner
    with pytest.raises(AssertionError, match="disableLocalAuth=false"):
        provisioner(SimpleNamespace(config=SimpleNamespace()))
    cli.invoke.assert_not_called()
    grant.assert_not_called()
    keys.assert_not_called()


@pytest.mark.parametrize("kind", ["dps", "hub"])
def test_managed_sas_creation_explicitly_enables_local_auth(monkeypatch, mocker, kind):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    cli = mocker.patch.object(fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"properties": {"disableLocalAuth": False}}
    grant = mocker.patch.object(fixtures, "assign_iot_dps_dataplane_rbac_role")
    mocker.patch.object(fixtures, "_unlink_all_hubs")
    if kind == "dps":
        fixtures._create_managed_dps("run-service-sas", "nh", None)
    else:
        fixtures._create_managed_hub("run-service-sas", "hub")
    command = cli.invoke.call_args.args[0]
    assert "--disable-local-auth false" in command
    assert "authPhase=service-sas" in command
    assert "runUid=run-service-sas" in command
    grant.assert_not_called()


def test_sas_fixture_state_cannot_reuse_regular_phase_resources(monkeypatch):
    request = SimpleNamespace(config=SimpleNamespace(workerinput={"testrunuid": "same-run"}))
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.REGULAR)
    regular_uid = fixtures._get_run_uid(request)
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    sas_uid = fixtures._get_run_uid(request)
    assert regular_uid == "same-run"
    assert sas_uid == "same-run-service-sas"
    assert fixtures._state_paths(regular_uid, "h") != fixtures._state_paths(sas_uid, "h")


def _dps_resource():
    return {
        "name": "isolated-dps",
        "id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg/"
              "providers/Microsoft.Devices/provisioningServices/isolated-dps",
        "properties": {
            "disableLocalAuth": False,
            "serviceOperationsHostName": "isolated-dps.azure-devices-provisioning.net",
        },
    }


@pytest.mark.parametrize("missing", ["id", "hostname"])
def test_sas_credential_missing_prerequisite_fails_before_key_lookup(mocker, missing):
    resource = _dps_resource()
    if missing == "id":
        resource.pop("id")
    else:
        resource["properties"].pop("serviceOperationsHostName")
    factory = mocker.patch.object(fixtures, "iot_service_provisioning_factory")
    with pytest.raises(CLIInternalError, match="requires a DPS ARM ID and serviceOperationsHostName"):
        fixtures._dps_service_connection_string(resource)
    factory.assert_not_called()


@pytest.mark.parametrize("policy", [None, {}, {"keyName": "owner"}, {"primaryKey": "synthetic-unit-key"}])
def test_sas_missing_service_policy_key_is_not_a_skip_or_credential_dump(mocker, policy):
    factory = mocker.patch.object(fixtures, "iot_service_provisioning_factory")
    factory.return_value.iot_dps_resource.list_keys_for_key_name.return_value = policy
    with pytest.raises(CLIInternalError, match="requires a usable DPS service-policy credential") as error:
        fixtures._dps_service_connection_string(_dps_resource())
    assert "synthetic-unit-key" not in str(error.value)


def test_sas_connection_string_uses_sdk_and_explicit_resource_subscription(mocker):
    factory = mocker.patch.object(fixtures, "iot_service_provisioning_factory")
    factory.return_value.iot_dps_resource.list_keys_for_key_name.return_value = {
        "keyName": "provisioningserviceowner", "primaryKey": "synthetic-unit-key",
    }
    cli = mocker.patch.object(fixtures, "cli")
    result = fixtures._dps_service_connection_string(_dps_resource())
    assert result == (
        "HostName=isolated-dps.azure-devices-provisioning.net;"
        "SharedAccessKeyName=provisioningserviceowner;SharedAccessKey=synthetic-unit-key"
    )
    factory.assert_called_once_with(cli.az_cli, subscription_id="00000000-0000-0000-0000-000000000001")
    factory.return_value.iot_dps_resource.list_keys_for_key_name.assert_called_once_with(
        provisioning_service_name="isolated-dps", resource_group_name=fixtures.ENTITY_RG,
        key_name="provisioningserviceowner",
    )
    cli.invoke.assert_not_called()


def test_sas_fixture_returns_connection_string_without_regular_gc_or_dps_grants(monkeypatch, mocker):
    monkeypatch.setenv(_phase.PHASE_ENV, _phase.SERVICE_SAS)
    monkeypatch.setattr(fixtures.settings.env, "azext_iot_testdps", None)
    target = _dps_resource()
    mocker.patch.object(fixtures, "_shared_acquire", return_value=target)
    keys = mocker.patch.object(fixtures, "_dps_service_connection_string", return_value="synthetic-connection")
    gc = mocker.patch.object(fixtures, "_gc_stale_resources_once")
    grant = mocker.patch.object(fixtures, "assign_iot_dps_dataplane_rbac_role")
    result = fixtures._iot_dps_provisioner(SimpleNamespace(config=SimpleNamespace()))
    assert result["connectionString"] == "synthetic-connection"
    keys.assert_called_once_with(target)
    gc.assert_not_called()
    grant.assert_not_called()


@pytest.mark.parametrize("identity", [None, {}, {"type": "SystemAssigned"}])
def test_link_identity_prerequisite_fails_before_grant_or_wait(mocker, identity):
    mocker.patch.object(fixtures, "cli").invoke.return_value.as_json.return_value = {"identity": identity}
    grant = mocker.patch.object(fixtures, "assign_role_assignment")
    sleep = mocker.patch.object(fixtures, "sleep")
    with pytest.raises(CLIInternalError, match="require a system-assigned identity principalId"):
        fixtures._enable_dps_hub_identity("isolated-dps", {"hub": {"id": "/hub"}})
    grant.assert_not_called()
    sleep.assert_not_called()


@pytest.mark.parametrize("phase", [_phase.REGULAR, _phase.SERVICE_SAS])
def test_gwv2_prerequisite_is_an_error_for_requested_sas_not_a_skip(monkeypatch, mocker, phase):
    monkeypatch.setenv(_phase.PHASE_ENV, phase)
    embedded = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")
    embedded.return_value.invoke.return_value.as_json.return_value = {"properties": {}}
    module = runpy.run_path(str(Path(fixtures.__file__).parent / "core/test_dps_linked_hub_int.py"))
    expected = pytest.fail.Exception if phase == _phase.SERVICE_SAS else pytest.skip.Exception
    with pytest.raises(expected, match="GWv2"):
        module["_require_gwv2_hub"]({"name": "hub", "rg": "rg"})
