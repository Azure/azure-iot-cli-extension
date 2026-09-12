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
from azure.cli.core.azclierror import CLIInternalError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError as AzureResourceNotFoundError
from filelock import FileLock, Timeout
from knack.util import CLIError

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.core import custom
from azext_iot.sdk.iothub.mgmt import IotHubClient
from azext_iot.tests.dps import DPS_SERVICE_AUTH_PARAMS
from azext_iot.tests.dps import conftest as dps_fixtures
from azext_iot.tests.dps.device_registration import check_hub_device
from azext_iot.tests import helpers


@pytest.mark.parametrize("fill_role_definition_name", [None, True, False])
def test_role_assignment_listing_can_skip_unused_role_names(mocker, fill_role_definition_name):
    cli = mocker.patch.object(helpers, "cli")
    assignments = [{"principalId": "principal", "roleDefinitionId": "/roles/role"}]
    cli.invoke.return_value.as_json.return_value = assignments
    options = {} if fill_role_definition_name is None else {
        "fill_role_definition_name": fill_role_definition_name,
    }

    assert helpers.get_role_assignments("/scope", assignee="principal", role="role", **options) is assignments

    command = cli.invoke.call_args.args[0]
    assert '--scope "/scope"' in command
    assert '--assignee "principal"' in command
    assert '--role "role"' in command
    assert ("--fill-role-definition-name false" in command) is (fill_role_definition_name is False)
    assert "--fill-principal-name" not in command


@pytest.mark.parametrize("managed_identity", [False, True])
def test_required_grant_surfaces_original_cli_error_without_waiting(mocker, managed_identity):
    error = HttpResponseError(
        message="AuthorizationFailed: Microsoft.Authorization/roleAssignments/write at scope /resource-id"
    )
    embedded = EmbeddedCLI()
    embedded.az_cli = mocker.Mock()
    embedded.az_cli.invoke.return_value = 1
    embedded.az_cli.result.error = error
    mocker.patch.object(helpers, "cli", embedded)
    mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    helper_sleep = mocker.patch.object(helpers, "sleep")
    fixture_sleep = mocker.patch.object(dps_fixtures, "sleep")
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {
        "user": {"name": "principal"}, "identity": {"principalId": "principal"},
    }

    with pytest.raises(HttpResponseError) as raised:
        if managed_identity:
            dps_fixtures._enable_dps_hub_identity("dps", {"hub": {"id": "/resource-id"}})
        else:
            dps_fixtures._assign_current_user_role(dps_fixtures.DPS_USER_ROLE, "/resource-id")

    assert raised.value is error
    helper_sleep.assert_not_called()
    fixture_sleep.assert_not_called()
    embedded.az_cli.invoke.assert_called_once()


@pytest.mark.parametrize("principal_field", ["name", "principalId", "principalName"])
def test_required_grant_reuses_visible_assignment(mocker, principal_field):
    lookup = mocker.patch.object(helpers, "get_role_assignments", return_value=[{principal_field: "principal"}])
    cli = mocker.patch.object(helpers, "cli")
    sleep = mocker.patch.object(helpers, "sleep")
    helpers.assign_role_assignment("role", "/scope", "principal")
    lookup.assert_called_once_with(scope="/scope", role="role", fill_role_definition_name=False)
    cli.invoke.assert_not_called()
    sleep.assert_not_called()


def test_required_grant_preserves_cli_role_assignment_exists_race(mocker):
    from azure.cli.command_modules.role import custom as role_commands

    existing = {"principalId": "principal"}
    error = HttpResponseError(message="(RoleAssignmentExists) The role assignment already exists.")
    error.status_code = 409
    error.error = SimpleNamespace(code="RoleAssignmentExists")
    mocker.patch.object(role_commands, "_resolve_object_id_and_type", return_value=("principal", "ServicePrincipal"))
    create = mocker.patch.object(role_commands, "_create_role_assignment", side_effect=error)
    lookup = mocker.patch.object(role_commands, "list_role_assignments", return_value=[existing])
    visible = mocker.patch.object(helpers, "get_role_assignments", side_effect=[[], [existing]])
    cli = mocker.patch.object(helpers, "cli")

    def invoke(_command, capture_stderr):
        assert capture_stderr is True
        assert role_commands.create_role_assignment(
            SimpleNamespace(cli_ctx=None), "role", "/scope", assignee="principal"
        ) == existing
        return SimpleNamespace(success=lambda: True, as_json=lambda: existing)

    cli.invoke.side_effect = invoke
    sleep = mocker.patch.object(helpers, "sleep")
    helpers.assign_role_assignment("role", "/scope", "principal", max_tries=1, wait=2)
    assert visible.call_count == 2
    create.assert_called_once()
    lookup.assert_called_once()
    sleep.assert_called_once_with(2)


def test_required_grant_visibility_accepts_resolved_object_id(mocker):
    mocker.patch.object(helpers, "get_role_assignments", side_effect=[[], [{"principalId": "object-id"}]])
    cli = mocker.patch.object(helpers, "cli")
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.return_value = {"principalId": "object-id"}
    sleep = mocker.patch.object(helpers, "sleep")
    helpers.assign_role_assignment("role", "/scope", "principal-alias", max_tries=1, wait=1)
    cli.invoke.assert_called_once()
    sleep.assert_called_once_with(1)


def test_required_grant_visibility_exhaustion_is_not_success(mocker):
    visible = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    cli = mocker.patch.object(helpers, "cli")
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.return_value = {"principalId": "principal"}
    sleep = mocker.patch.object(helpers, "sleep")
    with pytest.raises(CLIInternalError, match="scope.*not visible"):
        helpers.assign_role_assignment("role", "/scope", "principal", max_tries=2, wait=1)
    assert visible.call_count == 3
    assert cli.invoke.call_count == sleep.call_count == 2
    assert all(call.kwargs["capture_stderr"] is True for call in cli.invoke.call_args_list)


def test_required_grant_nonzero_exit_without_exception_fails(mocker):
    mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    cli = mocker.patch.object(helpers, "cli")
    cli.invoke.return_value.success.return_value = False
    cli.invoke.return_value.get_error.return_value = None
    cli.invoke.return_value.error_code = 2
    sleep = mocker.patch.object(helpers, "sleep")
    with pytest.raises(CLIInternalError, match="scope.*exit code 2"):
        helpers.assign_role_assignment("role", "/scope", "principal")
    sleep.assert_not_called()


def _owned_test_resource(name, kind, run_uid="test-run"):
    return {
        "id": "/resource-id", "name": name, "location": "centraluseuap",
        "properties": {"disableLocalAuth": True},
        "tags": {"intTest": "true", "runUid": run_uid, "kind": kind},
    }


@pytest.mark.parametrize("stage", ["create", "role", "link", "unlink"])
@pytest.mark.parametrize("error_type", [CLIError, pytest.fail.Exception, KeyboardInterrupt])
def test_new_dps_setup_failure_cleans_only_owned_resource(mocker, stage, error_type):
    error = error_type("setup failure")
    kind = "nh" if stage == "unlink" else "h"
    name = f"{dps_fixtures.INT_TEST_DPS_PREFIX}-timestamp-test-run-{kind}"
    mocker.patch.object(dps_fixtures, "_timestamp", return_value="timestamp")
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = _owned_test_resource(name, kind)
    find = mocker.patch.object(dps_fixtures, "_find_dps_by_name", return_value=_owned_test_resource(name, kind))
    delete = mocker.patch.object(dps_fixtures, "_delete_dps")
    role = mocker.patch.object(dps_fixtures, "assign_iot_dps_dataplane_rbac_role")
    link = mocker.patch.object(dps_fixtures, "_link_hub")
    unlink = mocker.patch.object(dps_fixtures, "_unlink_all_hubs")
    {"create": cli.invoke, "role": role, "link": link, "unlink": unlink}[stage].side_effect = error

    with pytest.raises(error_type) as raised:
        dps_fixtures._create_managed_dps("test-run", kind, None if kind == "nh" else {"name": "hub"})

    assert raised.value is error
    find.assert_called_once_with(name)
    delete.assert_called_once_with(name)


@pytest.mark.parametrize("tags", [
    {}, {"intTest": "true", "runUid": "other-run", "kind": "h"},
    {"intTest": "true", "runUid": "test-run", "kind": "nh"},
])
def test_failed_setup_cleanup_does_not_delete_unowned_resources(mocker, caplog, tags):
    resource = {**_owned_test_resource("resource", "h"), "tags": tags}
    find, delete = mocker.Mock(return_value=resource), mocker.Mock()
    dps_fixtures._cleanup_created_resource("resource", "test-run", "h", find, delete)
    delete.assert_not_called()
    assert "ownership does not match" in caplog.text


def test_failed_setup_cleanup_handles_absent_resource(mocker):
    find, delete = mocker.Mock(return_value=None), mocker.Mock()
    dps_fixtures._cleanup_created_resource("resource", "test-run", "h", find, delete)
    delete.assert_not_called()


def test_cleanup_failure_retains_original_setup_error(mocker):
    original, cleanup_error = CLIError("grant denied"), CLIError("delete denied")
    name = f"{dps_fixtures.INT_TEST_DPS_PREFIX}-timestamp-test-run-nh"
    mocker.patch.object(dps_fixtures, "_timestamp", return_value="timestamp")
    mocker.patch.object(dps_fixtures, "cli").invoke.side_effect = original
    mocker.patch.object(dps_fixtures, "_find_dps_by_name", return_value=_owned_test_resource(name, "nh"))
    mocker.patch.object(dps_fixtures, "_delete_dps", side_effect=cleanup_error)
    with pytest.raises(CLIError) as raised:
        dps_fixtures._create_managed_dps("test-run", "nh", None)
    assert raised.value is cleanup_error
    assert raised.value.__context__ is original


@pytest.mark.parametrize("kind", ["h", "hub"])
def test_new_resource_state_write_failure_is_cleaned(mocker, monkeypatch, tmp_path, kind):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    resource = _owned_test_resource("resource", kind)
    create, find = mocker.Mock(return_value=("resource", resource)), mocker.Mock(return_value=resource)
    mocker.patch.object(dps_fixtures, "_write_state", side_effect=OSError("state write failed"))
    delete = mocker.patch.object(dps_fixtures, "_delete_hub" if kind == "hub" else "_delete_dps")
    with pytest.raises(OSError, match="state write failed"):
        dps_fixtures._shared_acquire("test-run", kind, create, find)
    delete.assert_called_once_with("resource")


@pytest.mark.parametrize("kind", ["nh", "hub"])
@pytest.mark.parametrize("refcount", [1, 2])
def test_post_acquire_failure_releases_only_its_reference(mocker, monkeypatch, tmp_path, kind, refcount):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps", None)
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps_hub", None)
    mocker.patch.object(dps_fixtures, "_get_run_uid", return_value="test-run")
    mocker.patch.object(dps_fixtures, "_gc_stale_resources_once")
    resource = _owned_test_resource("resource", kind)
    mocker.patch.object(dps_fixtures, "_shared_acquire", return_value=resource)
    mocker.patch.object(dps_fixtures, "_find_hub_by_name" if kind == "hub" else "_find_dps_by_name", return_value=resource)
    error = pytest.fail.Exception("setup timed out before yield")
    mocker.patch.object(dps_fixtures, "_assert_local_auth_policy", side_effect=error)
    delete = mocker.patch.object(dps_fixtures, "_delete_hub" if kind == "hub" else "_delete_dps")
    _, path = dps_fixtures._state_paths("test-run", kind)
    dps_fixtures._write_state(path, {"name": "resource", "refcount": refcount})
    provision = dps_fixtures._iot_hubs_provisioner if kind == "hub" else dps_fixtures._iot_dps_provisioner
    with pytest.raises(pytest.fail.Exception) as raised:
        provision(mocker.Mock())
    assert raised.value is error
    if refcount == 1:
        delete.assert_called_once_with("resource")
        assert not Path(path).exists()
    else:
        delete.assert_not_called()
        assert dps_fixtures._read_state(path)["refcount"] == 1


@pytest.mark.parametrize("kind", ["nh", "hub"])
def test_pinned_setup_failure_never_deletes_resource(mocker, monkeypatch, kind):
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps", "external")
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps_hub", "external")
    mocker.patch.object(
        dps_fixtures, "_find_hub_by_name" if kind == "hub" else "_find_dps_by_name",
        return_value=_owned_test_resource("external", kind, "other-run"),
    )
    mocker.patch.object(dps_fixtures, "_assert_local_auth_policy", side_effect=CLIError("setup denied"))
    release = mocker.patch.object(dps_fixtures, "_shared_release")
    delete = mocker.patch.object(dps_fixtures, "_delete_hub" if kind == "hub" else "_delete_dps")
    provision = dps_fixtures._iot_hubs_provisioner if kind == "hub" else dps_fixtures._iot_dps_provisioner
    with pytest.raises(CLIError, match="setup denied"):
        provision(SimpleNamespace(config=SimpleNamespace()))
    release.assert_not_called()
    delete.assert_not_called()


@pytest.mark.parametrize("location", [None, "", "sentinel", "centraluseuap", "eastus"])
def test_dps_fixture_location_setting(monkeypatch, mocker, location):
    monkeypatch.setenv("azext_iot_testrg", "unit-test-rg")
    if location is None:
        monkeypatch.delenv("azext_iot_dps_test_location", raising=False)
    else:
        monkeypatch.setenv("azext_iot_dps_test_location", location)
    cli = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")

    fixture_globals = runpy.run_path(str(Path(dps_fixtures.__file__)))

    assert fixture_globals["ENTITY_LOCATION"] == (location if location not in (None, "", "sentinel") else "westus")
    assert fixture_globals["ENTITY_RG"] == "unit-test-rg"
    cli.return_value.invoke.assert_not_called()


@pytest.mark.parametrize("iot_hub", [None, {"name": "existing-hub"}])
@pytest.mark.parametrize("location", ["centraluseuap", "eastus"])
def test_dps_fixture_creates_in_configured_region(monkeypatch, mocker, iot_hub, location):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"properties": {"disableLocalAuth": True}}
    mocker.patch.object(dps_fixtures, "assign_iot_dps_dataplane_rbac_role")
    mocker.patch.object(dps_fixtures, "_link_hub")
    mocker.patch.object(dps_fixtures, "_unlink_all_hubs")
    mocker.patch.object(dps_fixtures, "sleep")
    monkeypatch.setattr(dps_fixtures, "ENTITY_LOCATION", location)
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")

    dps_fixtures._create_managed_dps("test-run", "h" if iot_hub else "nh", iot_hub)

    cli.invoke.assert_called_once()
    command = cli.invoke.call_args.args[0]
    assert command.startswith("iot dps create ")
    assert f"--location {location}" in command
    assert "--resource-group unit-test-rg" in command
    assert "--disable-local-auth true" in command
    if iot_hub:
        assert "hubname=existing-hub" in command


def test_dps_hub_fixture_creates_in_canary_region_without_local_auth(monkeypatch, mocker):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {
        "id": "/hub-id", "name": "test-hub", "location": "centraluseuap",
        "properties": {"disableLocalAuth": True},
    }
    mocker.patch.object(dps_fixtures, "_assign_current_user_role")
    mocker.patch.object(dps_fixtures, "_find_hub_by_name", return_value=None)
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")
    monkeypatch.setattr(dps_fixtures, "HUB_TEST_LOCATION", "centraluseuap")
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps_hub", "test-hub")

    dps_fixtures._create_managed_hub("test-run", "hub")

    cli.invoke.assert_called_once()
    command = cli.invoke.call_args.args[0]
    assert command.startswith("iot hub create ")
    assert "--location centraluseuap" in command
    assert "--disable-local-auth true" in command
    assert "-g unit-test-rg" in command


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_dps_fixture_known_resource_lookup_does_not_list(monkeypatch, mocker, kind):
    cli = mocker.patch.object(dps_fixtures, "cli")
    factory = mocker.patch.object(dps_fixtures, "iot_hub_service_factory")
    target = {"name": "known-target"}
    cli.invoke.return_value.as_json.return_value = target
    operations = factory.return_value.iot_hub_resource
    operations.get.return_value = target
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")

    assert getattr(dps_fixtures, f"_find_{kind}_by_name")("known-target") is target
    if kind == "hub":
        factory.assert_called_once_with(cli.az_cli)
        operations.get.assert_called_once_with(resource_group_name="unit-test-rg", resource_name="known-target")
        operations.check_name_availability.assert_not_called()
        operations.list_by_subscription.assert_not_called()
        operations.list_by_resource_group.assert_not_called()
        cli.invoke.assert_not_called()
    else:
        cli.invoke.assert_called_once_with(
            "iot dps show -n known-target -g unit-test-rg", capture_stderr=True
        )
        factory.assert_not_called()


@pytest.mark.parametrize("error_type", [ResourceNotFoundError, AzureResourceNotFoundError])
def test_dps_fixture_lookup_only_treats_not_found_as_absent(mocker, error_type):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.side_effect = error_type("not found")

    assert dps_fixtures._find_dps_by_name("missing-target") is None


_HUB_LOOKUP_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_HUB_LOOKUP_URL = (
    f"https://management.azure.com/subscriptions/{_HUB_LOOKUP_SUBSCRIPTION}"
    "/resourceGroups/unit-test-rg/providers/Microsoft.Devices/IotHubs/missing-hub"
)


@pytest.fixture
def hub_lookup_sdk(mocker):
    credential = mocker.Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    with IotHubClient(credential, _HUB_LOOKUP_SUBSCRIPTION, retry_total=0) as client:
        factory = mocker.patch.object(dps_fixtures, "iot_hub_service_factory", return_value=client)
        yield client, factory


@pytest.mark.parametrize("recovery", ["env-pinned", "shared-state"])
def test_dps_missing_hub_recovery_bypasses_actual_cli_not_found(
    fixture_cmd, hub_lookup_sdk, mocked_response, mocker, monkeypatch, tmp_path, recovery
):
    client, factory = hub_lookup_sdk
    mocker.patch.object(custom, "_ensure_resource_group_existence", return_value=True)
    availability = mocker.patch.object(
        client.iot_hub_resource, "check_name_availability", return_value={"nameAvailable": True}
    )
    # Reproduce the actual handler path: this is knack CLIError, NOT either
    # ResourceNotFoundError caught by the old `iot hub show` fixture lookup.
    with pytest.raises(CLIError, match="An IotHub 'missing-hub'.*was not found") as not_found:
        custom.iot_hub_get(fixture_cmd, client, "missing-hub", "unit-test-rg")
    assert type(not_found.value) is CLIError

    mocked_response.add(
        "GET", _HUB_LOOKUP_URL, status=404,
        json={"error": {"code": "ResourceNotFound", "message": "Hub does not exist."}},
    )
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")
    monkeypatch.setattr(dps_fixtures, "HUB_TEST_LOCATION", "centraluseuap")
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(
        dps_fixtures.settings.env, "azext_iot_testdps_hub", "missing-hub" if recovery == "env-pinned" else None
    )
    mocker.patch.object(dps_fixtures, "_timestamp", return_value="20260101000000")
    mocker.patch.object(dps_fixtures, "_assign_current_user_role")
    request = SimpleNamespace(config=SimpleNamespace(workerinput={"testrunuid": "unit-run"}))
    created_name = "missing-hub"
    if recovery == "shared-state":
        _, state_path = dps_fixtures._state_paths("unit-run", "hub")
        dps_fixtures._write_state(state_path, {"name": "missing-hub", "refcount": 1})
        created_name = f"{dps_fixtures.INT_TEST_HUB_PREFIX}-20260101000000-unit-run"
    created = {
        "id": "/created-hub-id", "name": created_name, "location": "centraluseuap",
        "properties": {"disableLocalAuth": True},
    }
    cli = mocker.patch.object(dps_fixtures, "cli")
    create_response = mocker.Mock()
    create_response.as_json.return_value = created

    def invoke(command, **_):
        if command.startswith("iot hub show "):
            raise not_found.value
        assert command.startswith(f"iot hub create -n {created_name} ")
        return create_response

    cli.invoke.side_effect = invoke

    if recovery == "env-pinned":
        with pytest.raises(CLIInternalError, match="Supplied Hub.*was not found"):
            dps_fixtures._iot_hubs_provisioner(request)
        cli.invoke.assert_not_called()
        factory.assert_called_once_with(cli.az_cli)
        assert len(mocked_response.calls) == 1
        return

    result = dps_fixtures._iot_hubs_provisioner(request)

    assert result["hub"] is created
    factory.assert_called_once_with(cli.az_cli)
    cli.invoke.assert_called_once()
    availability.assert_called_once()
    assert len(mocked_response.calls) == 1
    assert mocked_response.calls[0].request.method == "GET"
    assert mocked_response.calls[0].request.url.split("?")[0] == _HUB_LOOKUP_URL
    if recovery == "shared-state":
        assert dps_fixtures._read_state(state_path) == {"name": created_name, "refcount": 1}


@pytest.mark.parametrize("status,code", [
    (401, "Unauthorized"), (403, "AuthorizationFailed"), (500, "InternalServerError"), (502, "ProviderError"),
])
def test_dps_hub_lookup_propagates_real_sdk_non_404_errors(
    hub_lookup_sdk, mocked_response, mocker, monkeypatch, status, code
):
    _, factory = hub_lookup_sdk
    cli = mocker.patch.object(dps_fixtures, "cli")
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")
    mocked_response.add("GET", _HUB_LOOKUP_URL, status=status, json={"error": {"code": code, "message": "Failure"}})

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._find_hub_by_name("missing-hub")

    assert raised.value.status_code == status
    factory.assert_called_once_with(cli.az_cli)
    cli.invoke.assert_not_called()
    assert len(mocked_response.calls) == 1


def test_dps_hub_lookup_does_not_treat_factory_failure_as_missing(mocker):
    error = _http_error(404, "NotFound")
    mocker.patch.object(dps_fixtures, "iot_hub_service_factory", side_effect=error)

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._find_hub_by_name("missing-hub")

    assert raised.value is error


def _http_error(status=502, code="ProviderError"):
    error = HttpResponseError("test service failure")
    error.status_code = status
    error.error = SimpleNamespace(code=code)
    return error


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("status,code", [(502, "ProviderError"), (403, "AuthorizationFailed")])
def test_dps_fixture_lookup_does_not_hide_service_errors(mocker, kind, status, code):
    cli = mocker.patch.object(dps_fixtures, "cli")
    error = _http_error(status, code)
    if kind == "hub":
        factory = mocker.patch.object(dps_fixtures, "iot_hub_service_factory")
        factory.return_value.iot_hub_resource.get.side_effect = error
    else:
        cli.invoke.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        getattr(dps_fixtures, f"_find_{kind}_by_name")("known-target")
    assert raised.value is error


def test_dps_hub_list_raises_original_pagination_error(mocker):
    cli = mocker.patch.object(dps_fixtures, "cli")
    error = _http_error()
    cli.invoke.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._list_hubs()

    assert raised.value is error
    assert cli.invoke.call_args.kwargs["capture_stderr"] is True
    cli.invoke.return_value.as_json.assert_not_called()


def test_dps_gc_defers_only_hub_orphan_discovery_for_confirmed_502(mocker, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    dps_list = mocker.patch.object(dps_fixtures, "_list_dps", return_value=[])
    hub_list = mocker.patch.object(dps_fixtures, "_list_hubs", side_effect=_http_error())
    delete_hub = mocker.patch.object(dps_fixtures, "_delete_hub")

    dps_fixtures._gc_stale_resources_once("run")
    dps_fixtures._gc_stale_resources_once("run")

    dps_list.assert_called_once()
    hub_list.assert_called_once()
    delete_hub.assert_not_called()
    assert "HTTP 502 ProviderError" in caplog.text
    assert "No partial list" in caplog.text


@pytest.mark.parametrize("status,code", [
    (500, "ProviderError"), (503, "ProviderError"), (403, "AuthorizationFailed"),
    (502, "OtherError"), (502, None),
])
def test_dps_gc_propagates_other_hub_list_failures(mocker, monkeypatch, tmp_path, status, code):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    mocker.patch.object(dps_fixtures, "_list_dps", return_value=[])
    error = _http_error(status, code)
    mocker.patch.object(dps_fixtures, "_list_hubs", side_effect=error)

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._gc_stale_resources_once("run")
    assert raised.value is error
    assert not list(tmp_path.glob("*.done"))


def test_dps_gc_does_not_mask_cli_errors(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    mocker.patch.object(dps_fixtures, "_list_dps", return_value=[])
    error = CLIInternalError("unrelated failure mentioning 502 ProviderError")
    mocker.patch.object(dps_fixtures, "_list_hubs", side_effect=error)

    with pytest.raises(CLIInternalError) as raised:
        dps_fixtures._gc_stale_resources_once("run")
    assert raised.value is error


def test_dps_gc_does_not_apply_hub_workaround_to_dps_list(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    error = _http_error()
    mocker.patch.object(dps_fixtures, "_list_dps", side_effect=error)
    hub_list = mocker.patch.object(dps_fixtures, "_list_hubs")

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._gc_stale_resources_once("run")
    assert raised.value is error
    hub_list.assert_not_called()


def test_dps_gc_does_not_apply_list_workaround_to_hub_deletion(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    mocker.patch.object(dps_fixtures, "_list_dps", return_value=[])
    mocker.patch.object(dps_fixtures, "_list_hubs", return_value=[{
        "name": f"{dps_fixtures.INT_TEST_HUB_PREFIX}-expired",
        "tags": {"intTest": "true", "runUid": "old-run", "createdEpoch": "0"},
    }])
    error = _http_error()
    mocker.patch.object(dps_fixtures, "_delete_hub", side_effect=error)

    with pytest.raises(HttpResponseError) as raised:
        dps_fixtures._gc_stale_resources_once("run")
    assert raised.value is error
    assert not list(tmp_path.glob("*.done"))


@pytest.mark.parametrize("device_hostname", [None, "test-hub.device.azure-devices.net"])
def test_dps_linked_hostname_uses_resource_not_connection_string(device_hostname):
    properties = {"hostName": "test-hub.azure-devices.net", "deviceHostName": device_hostname}
    assert dps_fixtures._hub_link_host_name({"hub": {"properties": properties}}) == (
        device_hostname or properties["hostName"]
    )


def test_dps_fixture_grants_managed_identity_hub_data_access(monkeypatch, mocker):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"identity": {"principalId": "dps-principal"}}
    events = []
    assign_role = mocker.patch.object(
        dps_fixtures, "assign_role_assignment", side_effect=lambda **_: events.append("assign")
    )
    mocker.patch.object(dps_fixtures, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))
    monkeypatch.setattr(dps_fixtures, "ENTITY_RG", "unit-test-rg")

    dps_fixtures._enable_dps_hub_identity("test-dps", {"hub": {"id": "/hub-id"}})

    cli.invoke.assert_called_once_with(
        "iot dps identity assign --name test-dps -g unit-test-rg --system-assigned",
        capture_stderr=True,
    )
    assign_role.assert_called_once_with(
        role="IoT Hub Data Contributor", scope="/hub-id", assignee="dps-principal",
        max_tries=dps_fixtures.MAX_RBAC_ASSIGNMENT_TRIES,
    )
    assert events == ["assign", ("wait", 60)]


@pytest.mark.parametrize("role", [dps_fixtures.DPS_USER_ROLE, dps_fixtures.HUB_USER_ROLE])
def test_dps_fixture_waits_after_assigning_caller_data_role(mocker, role):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"user": {"name": "caller"}}
    events = []
    assign_role = mocker.patch.object(
        dps_fixtures, "assign_role_assignment", side_effect=lambda **_: events.append("assign")
    )
    mocker.patch.object(dps_fixtures, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))

    dps_fixtures._assign_current_user_role(role, "/resource-id")

    assign_role.assert_called_once_with(
        role=role, scope="/resource-id", assignee="caller",
        max_tries=dps_fixtures.MAX_RBAC_ASSIGNMENT_TRIES,
    )
    assert events == ["assign", ("wait", 60)]


@pytest.mark.parametrize("managed_identity", [False, True])
def test_dps_fixture_does_not_retry_or_hide_role_assignment_errors(mocker, managed_identity):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {
        "user": {"name": "caller"}, "identity": {"principalId": "dps-principal"},
    }
    error = _http_error(403, "AuthorizationFailed")
    assign_role = mocker.patch.object(dps_fixtures, "assign_role_assignment", side_effect=error)
    sleep = mocker.patch.object(dps_fixtures, "sleep")

    with pytest.raises(HttpResponseError) as raised:
        if managed_identity:
            dps_fixtures._enable_dps_hub_identity("test-dps", {"hub": {"id": "/hub-id"}})
        else:
            dps_fixtures._assign_current_user_role(dps_fixtures.DPS_USER_ROLE, "/dps-id")

    assert raised.value is error
    assign_role.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("linked_hub", [None, {"name": "hub"}])
def test_dps_managed_fixture_waits_before_finishing_setup(mocker, linked_hub):
    cli = mocker.patch.object(dps_fixtures, "cli")
    target = {"id": "/dps-id", "properties": {"disableLocalAuth": True}}
    cli.invoke.return_value.as_json.side_effect = [target, {"user": {"name": "caller"}}]
    events = []
    mocker.patch.object(dps_fixtures, "assign_role_assignment", side_effect=lambda **_: events.append("assign"))
    mocker.patch.object(dps_fixtures, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))
    mocker.patch.object(dps_fixtures, "_link_hub", side_effect=lambda *_: events.append("link"))
    mocker.patch.object(dps_fixtures, "_unlink_all_hubs", side_effect=lambda *_: events.append("unlink"))

    _, resource = dps_fixtures._create_managed_dps("run", "h" if linked_hub else "nh", linked_hub)

    assert resource is target
    assert events == ["assign", ("wait", 60), "link" if linked_hub else "unlink"]


def test_dps_pinned_no_hub_fixture_waits_before_returning(mocker, monkeypatch):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"user": {"name": "caller"}}
    target = {"name": "pinned-dps", "id": "/dps-id", "properties": {"disableLocalAuth": True}}
    mocker.patch.object(dps_fixtures, "_find_dps_by_name", return_value=target)
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps", "pinned-dps")
    events = []
    mocker.patch.object(dps_fixtures, "assign_role_assignment", side_effect=lambda **_: events.append("assign"))
    mocker.patch.object(dps_fixtures, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))
    mocker.patch.object(dps_fixtures, "_unlink_all_hubs", side_effect=lambda *_: events.append("unlink"))

    result = dps_fixtures._iot_dps_provisioner(SimpleNamespace(config=SimpleNamespace()))

    assert result["dps"] is target
    assert events == ["assign", ("wait", 60), "unlink"]


def test_dps_hub_fixture_waits_after_granting_caller_role(mocker, monkeypatch):
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.as_json.return_value = {"user": {"name": "caller"}}
    target = {
        "name": "pinned-hub", "id": "/hub-id", "location": "centraluseuap",
        "properties": {"disableLocalAuth": True},
    }
    mocker.patch.object(dps_fixtures, "_find_hub_by_name", return_value=target)
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps_hub", "pinned-hub")
    monkeypatch.setattr(dps_fixtures, "HUB_TEST_LOCATION", "centraluseuap")
    events = []
    mocker.patch.object(dps_fixtures, "assign_role_assignment", side_effect=lambda **_: events.append("assign"))
    mocker.patch.object(dps_fixtures, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))

    result = dps_fixtures._iot_hubs_provisioner(SimpleNamespace(config=SimpleNamespace()))

    assert result["hub"] is target
    assert events == ["assign", ("wait", 60)]


@pytest.mark.parametrize("existing_auth", [None, "KeyBased", "SystemAssigned"])
def test_dps_fixture_links_with_managed_identity(mocker, existing_auth):
    cli = mocker.patch.object(dps_fixtures, "cli")
    hostname = "test-hub.device.azure-devices.net"
    cli.invoke.return_value.as_json.return_value = (
        [{"name": hostname, "authenticationType": existing_auth}] if existing_auth else []
    )
    enable_identity = mocker.patch.object(dps_fixtures, "_enable_dps_hub_identity")
    hub = {"name": "test-hub", "rg": "hub-rg", "hub": {"properties": {"deviceHostName": hostname}}}

    assert dps_fixtures._link_hub("test-dps", hub) == hostname

    enable_identity.assert_called_once_with("test-dps", hub)
    commands = [call.args[0] for call in cli.invoke.call_args_list]
    assert all("connection-string" not in command for command in commands)
    if existing_auth == "SystemAssigned":
        assert len(commands) == 1
    else:
        command = commands[-1]
        assert "--authentication-type SystemAssigned" in command
        if existing_auth:
            assert command.startswith("iot dps linked-hub update ")
            assert f"--linked-hub {hostname}" in command
        else:
            assert command.startswith("iot dps linked-hub create ")
            assert "--hub-name test-hub --hub-resource-group hub-rg" in command


def test_dps_fixture_uses_no_service_connection_strings(mocker, monkeypatch):
    cli = mocker.patch.object(dps_fixtures, "cli")
    mocker.patch.object(dps_fixtures, "_gc_stale_resources_once")
    target = {"name": "test-dps", "properties": {"disableLocalAuth": True}}
    mocker.patch.object(dps_fixtures, "_shared_acquire", return_value=target)
    monkeypatch.setattr(dps_fixtures.settings.env, "azext_iot_testdps", None)

    result = dps_fixtures._iot_dps_provisioner(SimpleNamespace(config=SimpleNamespace()))

    assert result["dps"] is target
    assert result["connectionString"] is None
    assert result["iotHub"] is None
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("local_auth_disabled", [None, False, True])
def test_dps_fixture_requires_compliant_supplied_resource(local_auth_disabled):
    target = {"name": "supplied", "properties": {"disableLocalAuth": local_auth_disabled}}
    if local_auth_disabled:
        dps_fixtures._assert_local_auth_policy(target)
    else:
        with pytest.raises(AssertionError, match="disableLocalAuth=true"):
            dps_fixtures._assert_local_auth_policy(target)


@pytest.mark.parametrize("device_auth,key,thumbprint", [
    ("sas", "device-key", None), ("selfSigned", None, "device-thumbprint"),
])
def test_dps_hub_device_checks_use_entra_not_hub_policy(mocker, device_auth, key, thumbprint):
    cli = mocker.Mock()
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.return_value = {
        "authentication": {
            "type": device_auth, "symmetricKey": {"primaryKey": key},
            "x509Thumbprint": {"primaryThumbprint": thumbprint},
        },
    }

    check_hub_device(cli, "device-id", device_auth, {"name": "hub", "rg": "hub-rg"}, key, thumbprint)

    cli.invoke.assert_called_once_with(
        "iot hub device-identity show -n hub -g hub-rg -d device-id --auth-type login"
    )


def test_dps_service_auth_matrix_marks_only_service_sas():
    assert [case.id for case in DPS_SERVICE_AUTH_PARAMS] == ["key", "login", "cstring"]
    for case in DPS_SERVICE_AUTH_PARAMS:
        assert case.values == ((case.id,),)
        if case.id == "login":
            assert not case.marks
        else:
            assert len(case.marks) == 1
            assert case.marks[0].name == "dps_service_sas"


@pytest.mark.parametrize("module_name,case_count", [
    ("enrollment.test_iot_dps_enrollment_int", 3),
    ("enrollment_group.test_iot_dps_enrollment_group_int", 3),
    ("device_registration.test_iot_device_registration_individual_int", 4),
    ("device_registration.test_iot_device_registration_group_int", 4),
])
def test_dps_lifecycle_auth_cases_are_collected_independently(mocker, module_name, case_count):
    # Import only: do not execute integration fixtures or tests. In particular,
    # a deselected service-key phase must not remove the login device-attestation phase.
    cli = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")
    module_path = Path(dps_fixtures.__file__).parent.joinpath(*module_name.split(".")).with_suffix(".py")
    module = SimpleNamespace(**runpy.run_path(str(module_path)))
    cases = [
        function for name, function in inspect.getmembers(module, inspect.isfunction)
        if name.startswith("test_") and "auth_phases" in inspect.signature(function).parameters
    ]
    assert len(cases) == case_count
    for case in cases:
        marks = [mark for mark in case.pytestmark if mark.name == "parametrize"]
        assert len(marks) == 1
        mark = marks[0]
        assert mark.args == ("auth_phases", DPS_SERVICE_AUTH_PARAMS)
        fixture_marks = [mark.args for mark in case.pytestmark if mark.name == "usefixtures"]
        assert fixture_marks == (
            [("exclusive_iot_dps_no_hub",)] if case.__name__ == "test_dps_device_registration_unlinked_hub" else []
        )
    cli.return_value.invoke.assert_not_called()


def test_dps_linked_hub_coverage_keeps_managed_identity_cases_active(mocker):
    cli = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI")
    module_path = Path(dps_fixtures.__file__).parent / "core/test_dps_linked_hub_int.py"
    module = SimpleNamespace(**runpy.run_path(str(module_path)))
    for name in (
        "test_linked_hub_create_auto_hostname", "test_linked_hub_create_classic_hostname",
        "test_linked_hub_create_device_hostname", "test_linked_hub_list_shows_hostname",
    ):
        marks = getattr(module, name).pytestmark
        assert len(marks) == 1
        assert marks[0].name == "usefixtures"
        assert marks[0].args == ("dps_linked_hub_identity", "exclusive_iot_dps_no_hub")
    sas_marks = module.test_linked_hub_create_keybased_then_switch_to_mi.pytestmark
    assert [mark.name for mark in sas_marks] == ["usefixtures", "dps_service_sas"]
    assert sas_marks[0].args == ("dps_linked_hub_identity", "exclusive_iot_dps_no_hub")
    cli.return_value.invoke.assert_not_called()


@pytest.fixture
def no_hub_isolation(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(dps_fixtures.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(dps_fixtures, "DPS_NO_HUB_LOCK_TIMEOUT_SECONDS", 0)
    cli = mocker.patch.object(dps_fixtures, "cli")
    cli.invoke.return_value.success.return_value = True
    cli.invoke.return_value.as_json.return_value = []
    requests = [
        SimpleNamespace(config=SimpleNamespace(workerinput={"testrunuid": "same-run", "workerid": worker}))
        for worker in ("gw1", "gw6")
    ]
    return requests, {"name": "no-hub-dps", "resourceGroup": "rg"}, cli


def test_no_hub_usage_excludes_other_workers_and_identity_setup(mocker, no_hub_isolation):
    requests, resource, cli = no_hub_isolation
    fixture = dps_fixtures.exclusive_iot_dps_no_hub.__wrapped__
    identity = mocker.patch.object(dps_fixtures, "_enable_dps_hub_identity")
    first = fixture(requests[0], resource)
    assert next(first) is resource
    try:
        with pytest.raises(Timeout):
            next(fixture(requests[1], resource))
        with pytest.raises(Timeout):
            dps_fixtures.dps_linked_hub_identity.__wrapped__(requests[1], resource, {})
        identity.assert_not_called()
        assert cli.invoke.call_count == 1
        # The usage lock must not prevent reference-count setup/teardown.
        state_lock, _ = dps_fixtures._state_paths("same-run", "nh")
        with FileLock(state_lock, timeout=0):
            pass
    finally:
        first.close()

    def enable(*_):
        with pytest.raises(Timeout):
            with dps_fixtures._no_hub_usage_lock(requests[0]):
                pytest.fail("Identity setup did not hold the shared usage lock.")

    identity.side_effect = enable
    dps_fixtures.dps_linked_hub_identity.__wrapped__(requests[1], resource, {})
    identity.assert_called_once_with(resource["name"], {})
    second = fixture(requests[1], resource)
    assert next(second) is resource
    second.close()
    assert cli.invoke.call_count == 4


@pytest.mark.parametrize("error_type", [RuntimeError, pytest.fail.Exception, KeyboardInterrupt])
def test_no_hub_usage_releases_after_failure_and_timeout(no_hub_isolation, error_type):
    requests, resource, cli = no_hub_isolation
    fixture = dps_fixtures.exclusive_iot_dps_no_hub.__wrapped__(requests[0], resource)
    error = error_type("test interrupted")
    assert next(fixture) is resource

    def check_while_locked(*_args, **_kwargs):
        with pytest.raises(Timeout):
            with dps_fixtures._no_hub_usage_lock(requests[1]):
                pytest.fail("Postcondition ran after releasing the usage lock.")
        return cli.invoke.return_value

    cli.invoke.side_effect = check_while_locked
    with pytest.raises(error_type) as raised:
        fixture.throw(error)
    assert raised.value is error
    assert cli.invoke.call_count == 2
    with dps_fixtures._no_hub_usage_lock(requests[1]):
        pass


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("links", [[{"name": "unexpected-hub", "connectionString": "do-not-log"}], None, {}])
def test_no_hub_usage_rejects_nonempty_or_invalid_link_state(no_hub_isolation, phase, links):
    requests, resource, cli = no_hub_isolation
    cli.invoke.return_value.as_json.side_effect = [links] if phase == "before" else [[], links]
    fixture = dps_fixtures.exclusive_iot_dps_no_hub.__wrapped__(requests[0], resource)
    if phase == "after":
        assert next(fixture) is resource
    with pytest.raises(AssertionError, match=f"no linked hubs {phase}") as raised:
        if phase == "before":
            next(fixture)
        else:
            fixture.close()
    assert "do-not-log" not in str(raised.value)
    assert all("linked-hub list" in call.args[0] and call.kwargs["capture_stderr"]
               for call in cli.invoke.call_args_list)
    with dps_fixtures._no_hub_usage_lock(requests[1]):
        pass


@pytest.mark.parametrize("failure", ["exception", "exit"])
def test_no_hub_usage_does_not_hide_link_read_failures(no_hub_isolation, failure):
    requests, resource, cli = no_hub_isolation
    error = HttpResponseError("AuthorizationFailed")
    if failure == "exception":
        cli.invoke.side_effect = error
    else:
        cli.invoke.return_value.success.return_value = False
        cli.invoke.return_value.error_code = 2
    with pytest.raises(HttpResponseError if failure == "exception" else CLIInternalError) as raised:
        next(dps_fixtures.exclusive_iot_dps_no_hub.__wrapped__(requests[0], resource))
    if failure == "exception":
        assert raised.value is error
    cli.invoke.assert_called_once()
    with dps_fixtures._no_hub_usage_lock(requests[1]):
        pass


@pytest.mark.parametrize("failure", ["exception", "exit"])
def test_linked_hub_cleanup_surfaces_failure(mocker, failure):
    cli = mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI").return_value
    module_path = Path(dps_fixtures.__file__).parent / "core/test_dps_linked_hub_int.py"
    module = SimpleNamespace(**runpy.run_path(str(module_path)))
    error = HttpResponseError("AuthorizationFailed")
    if failure == "exception":
        cli.invoke.side_effect = error
    else:
        cli.invoke.return_value.success.return_value = False
        cli.invoke.return_value.error_code = 2
    with pytest.raises(HttpResponseError if failure == "exception" else CLIInternalError) as raised:
        module._cleanup_linked_hub("dps", "rg", "owned-hub")
    if failure == "exception":
        assert raised.value is error
    cli.invoke.assert_called_once_with(
        "iot dps linked-hub delete --dps-name dps -g rg --linked-hub owned-hub", capture_stderr=True,
    )
