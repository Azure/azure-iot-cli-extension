# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exercise registry commands through the global loader and the current SDK wire contract."""

import json
import logging
import shlex
from copy import deepcopy
from functools import partial
from io import StringIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cli.core import MainCommandsLoader
from azure.cli.core.azclierror import (
    InvalidArgumentValueError, MutuallyExclusiveArgumentError, RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.core.polling import LROPoller

from azext_iot.adr import commands_wait
from azext_iot.adr.providers.registry_device import RegistryDeviceProvider
from azext_iot.common.utility import wait_for_terminal_state
from azext_iot.tests.adr import test_adr_registry_device_unit as provider_tests
from azext_iot.tests.adr import test_adr_sdk_unit as sdk_tests
from azext_iot.tests.adr import test_adr_validation_scenarios_unit as validation_tests


registry_device_provider = provider_tests.registry_device_provider
wire_client = sdk_tests.wire_client
offline_cli = validation_tests.offline_cli
NAMESPACE_URL = sdk_tests.NAMESPACE_URL


SCOPE = "--ns namespace -g rg"
DEVICE = {
    "name": "device", "location": "centraluseuap",
    "properties": {"externalDeviceId": "external", "enablementState": "Enabled", "provisioningState": "Succeeded"},
}
PROFILE = {"name": "profile", "properties": {"authenticationType": "SymmetricKey"}}
PREFIX = "iot adr ns registry-device"


@pytest.mark.parametrize("command,group,method,result,kwargs", [
    ("show --name device", "registry_devices", "get", DEVICE, {"registry_device_name": "device"}),
    ("list", "registry_devices", "list_by_namespace", [DEVICE], {}),
    ("auth show --rdn device --apn profile", "registry_device_authentication_profiles", "get", PROFILE,
     {"registry_device_name": "device", "authentication_profile_name": "profile", "logging_enable": False}),
    ("auth list --rdn device", "registry_device_authentication_profiles", "list_by_device", [PROFILE],
     {"registry_device_name": "device", "logging_enable": False}),
    ("attribute show --dn device --an attr", "registry_device_attributes", "get",
     {"name": "attr", "properties": {"reportedBy": "User"}}, {"registry_device_name": "device", "attribute_name": "attr"}),
    ("attribute list --dn device", "registry_device_attributes", "list_by_device",
     [{"name": "attr", "properties": {"reportedBy": "User"}}], {"registry_device_name": "device"}),
    ("capability show --registry-device-name device --cn hub", "registry_device_capabilities", "get",
     {"name": "hub", "properties": {"capabilityType": "Microsoft.IoTHub"}},
     {"registry_device_name": "device", "capability_name": "hub"}),
    ("capability list --registry-device-name device", "registry_device_capabilities", "list_by_device",
     [{"name": "hub", "properties": {"capabilityType": "Microsoft.IoTHub"}}], {"registry_device_name": "device"}),
])
@pytest.mark.parametrize("output_format", ["json", "table"])
def test_global_parser_read_commands(offline_cli, mocker, command, group, method, result, kwargs, output_format):
    client = Mock()
    operation = getattr(getattr(client, group), method)
    operation.return_value = result
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    output = StringIO()
    assert offline_cli.invoke(shlex.split(f"{PREFIX} {command} {SCOPE} -o {output_format}"), out_file=output) == 0
    operation.assert_called_once_with(resource_group_name="rg", namespace_name="namespace", **kwargs)
    if output_format == "json":
        assert json.loads(output.getvalue()) == result
    else:
        assert "Name" in output.getvalue()
        assert (result[0] if isinstance(result, list) else result)["name"] in output.getvalue()


def test_all_restored_commands_are_preview(offline_cli):
    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns"])
    restored = [command for name, command in table.items() if name.startswith(PREFIX)]
    assert len(restored) == 17
    assert all(command.command_kwargs["is_preview"] for command in restored)


@pytest.mark.parametrize("operation,expected", [
    ("create --location centraluseuap --ext-id external --enablement-state Disabled --tags x=y",
     {"resource": {"location": "centraluseuap", "tags": {"x": "y"},
                   "properties": {"externalDeviceId": "external", "enablementState": "Disabled"}}}),
    ("update --manufacturer '' --tags", {"properties": {"properties": {"manufacturer": ""}, "tags": {}}}),
    ("delete --yes", {}),
])
@pytest.mark.parametrize("no_wait", [False, True])
def test_global_parser_mutations(offline_cli, mocker, operation, expected, no_wait):
    client = Mock()
    verb = operation.split()[0]
    method = {"create": "begin_create_or_replace", "update": "begin_update", "delete": "begin_delete"}[verb]
    sdk_operation = getattr(client.registry_devices, method)
    wait = mocker.patch("azext_iot.adr.providers.registry_device.RegistryDeviceProvider._wait", return_value=None)
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    command = f"{PREFIX} {operation} --dn device {SCOPE}" + (" --no-wait" if no_wait else "")
    assert offline_cli.invoke(shlex.split(command), out_file=StringIO()) == 0
    sdk_operation.assert_called_once_with(
        registry_device_name="device", resource_group_name="rg", namespace_name="namespace", **expected
    )
    assert wait.call_args.args[0] is sdk_operation.return_value
    assert wait.call_args.kwargs == {"no_wait": no_wait}


@pytest.mark.parametrize("arguments,error", [
    ("show", RequiredArgumentMissingError),
    ("show -n device --external-device-id external", MutuallyExclusiveArgumentError),
    ("update -n device", RequiredArgumentMissingError),
    ("attribute create --rdn device -n attr --properties null", InvalidArgumentValueError),
    ("attribute create --rdn device -n attr --properties false", InvalidArgumentValueError),
])
def test_global_parser_validation(offline_cli, arguments, error):
    # Azure CLI routes CLI errors into its result; network guards in offline_cli
    # ensure invalid input never reaches a credential or HTTP transport.
    assert offline_cli.invoke(shlex.split(f"{PREFIX} {arguments} {SCOPE}"), out_file=StringIO()) != 0
    assert isinstance(offline_cli.result.error, error)


@pytest.mark.parametrize("properties", [
    {"null": None, "false": False, "zero": 0, "empty": "", "array": [], "object": {}},
    {"reportedBy": None}, {},
])
def test_attribute_json_values_are_not_truthiness_filtered(registry_device_provider, properties):
    original = deepcopy(properties)
    registry_device_provider.attribute_create("attr", "device", "namespace", "rg", properties=properties)
    call = registry_device_provider.client.registry_device_attributes.create_or_replace.call_args
    assert call.kwargs["resource"] == {"properties": {**properties, "reportedBy": "User"}}
    assert properties == original


@pytest.mark.parametrize("child,method,args,sdk_method", [
    ("registry_devices", "show", ("device", "namespace", "rg"), "get"),
    ("registry_devices", "list", ("namespace", "rg"), "list_by_namespace"),
    ("registry_devices", "create", ("device", "namespace", "rg", "centraluseuap"), "begin_create_or_replace"),
    ("registry_devices", "delete", ("device", "namespace", "rg"), "begin_delete"),
    ("registry_device_authentication_profiles", "auth_list", ("device", "namespace", "rg"), "list_by_device"),
    ("registry_device_authentication_profiles", "auth_show", ("profile", "device", "namespace", "rg"), "get"),
    ("registry_device_attributes", "attribute_list", ("device", "namespace", "rg"), "list_by_device"),
    ("registry_device_attributes", "attribute_show", ("software-update", "device", "namespace", "rg"), "get"),
    ("registry_device_attributes", "attribute_create", ("attr", "device", "namespace", "rg"), "create_or_replace"),
    ("registry_device_attributes", "attribute_delete", ("attr", "device", "namespace", "rg"), "delete"),
    ("registry_device_capabilities", "capability_list", ("device", "namespace", "rg"), "list_by_device"),
    ("registry_device_capabilities", "capability_show", ("hub", "device", "namespace", "rg"), "get"),
])
def test_sdk_errors_are_not_hidden(registry_device_provider, child, method, args, sdk_method):
    error = HttpResponseError("permission denied")
    operation = getattr(getattr(registry_device_provider.client, child), sdk_method)
    operation.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        getattr(registry_device_provider, method)(*args)
    assert caught.value is error
    assert operation.call_count == 1


@pytest.mark.parametrize("method,sdk_method,authentication_type", [
    ("auth_show_keys", "list_keys", "SymmetricKey"),
    ("auth_revoke_certs", "begin_revoke_certificates", "CertificateAuthoritySignedX509Certificate"),
])
def test_auth_action_errors_are_not_replayed(registry_device_provider, method, sdk_method, authentication_type):
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = {"properties": {"authenticationType": authentication_type}}
    operation = getattr(operations, sdk_method)
    error = HttpResponseError("action failed")
    operation.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        getattr(registry_device_provider, method)("profile", "device", "namespace", "rg")
    assert caught.value is error
    assert operation.call_count == 1


@pytest.mark.parametrize("auth", [False, True])
@pytest.mark.parametrize("options", [
    {}, {"exists": True}, {"created": True}, {"updated": True}, {"custom": "name == 'profile'"},
])
def test_wait_uses_exact_sdk_getter_and_lifecycle(registry_device_provider, mocker, auth, options):
    mocker.patch.object(commands_wait, "RegistryDeviceProvider", return_value=registry_device_provider)
    resource = {"name": "profile", "properties": {"provisioningState": "Succeeded"}}
    getter = (registry_device_provider.client.registry_device_authentication_profiles.get if auth
              else registry_device_provider.client.registry_devices.get)
    getter.return_value = resource
    function = commands_wait.adr_registry_device_auth_wait if auth else commands_wait.adr_registry_device_wait
    args = ({"authentication_profile_name": "profile", "registry_device_name": "device"} if auth
            else {"registry_device_name": "device"})
    result = function(Mock(cli_ctx=Mock()), namespace_name="namespace", resource_group_name="rg",
                      timeout=1, interval=1, **args, **options)
    assert result is None
    getter.assert_called_once_with(
        namespace_name="namespace", resource_group_name="rg", **args, **({"logging_enable": False} if auth else {})
    )


@pytest.mark.parametrize("auth", [False, True])
def test_wait_deleted_uses_sdk_404(registry_device_provider, mocker, auth):
    mocker.patch.object(commands_wait, "RegistryDeviceProvider", return_value=registry_device_provider)
    getter = (registry_device_provider.client.registry_device_authentication_profiles.get if auth
              else registry_device_provider.client.registry_devices.get)
    getter.side_effect = ResourceNotFoundError("gone")
    getter.side_effect.status_code = 404
    function = commands_wait.adr_registry_device_auth_wait if auth else commands_wait.adr_registry_device_wait
    args = ({"authentication_profile_name": "profile", "registry_device_name": "device"} if auth
            else {"registry_device_name": "device"})
    assert function(Mock(cli_ctx=Mock()), namespace_name="namespace", resource_group_name="rg",
                    timeout=1, interval=1, deleted=True, **args) is None


def test_real_sdk_pagination_and_external_id_lookup(wire_client, mocked_response, fixture_cmd, mocker):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    url = NAMESPACE_URL + "/registryDevices"
    next_url = url + "?api-version=2026-11-02-preview&continuationToken=second"
    mocked_response.add("GET", url, json={"value": [{"name": "other"}], "nextLink": next_url})
    mocked_response.add("GET", next_url, json={"value": [DEVICE]})
    assert provider.show(namespace_name="namespace", resource_group_name="rg", external_device_id="external") == DEVICE
    assert len(mocked_response.calls) == 2
    assert mocked_response.calls[1].request.url == next_url


def test_real_sdk_auth_metadata_redacts_keys_and_disables_logging(
    wire_client, mocked_response, fixture_cmd, mocker, caplog,
):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    profile = deepcopy(PROFILE)
    profile["properties"]["symmetricKey"] = {"primaryKey": "secret-one", "secondaryKey": "secret-two"}
    url = NAMESPACE_URL + "/registryDevices/device/authenticationProfiles"
    mocked_response.add("GET", url + "/profile", json=profile)
    mocked_response.add("GET", url, json={"value": [profile]})
    caplog.set_level(logging.DEBUG)
    assert provider.auth_show("profile", "device", "namespace", "rg") == PROFILE
    assert provider.auth_list("device", "namespace", "rg") == [PROFILE]
    assert "secret-one" not in caplog.text
    assert "secret-two" not in caplog.text
    assert profile["properties"]["symmetricKey"]["primaryKey"] == "secret-one"


@pytest.mark.parametrize("method,args,kwargs,verb,suffix,status,body,result", [
    ("create", ("device", "namespace", "rg"), {"location": "centraluseuap"}, "PUT", "", 200,
     {"location": "centraluseuap", "properties": {"enablementState": "Enabled"}}, DEVICE),
    ("update", ("device", "namespace", "rg"), {"manufacturer": "", "tags": {}}, "PATCH", "", 200,
     {"tags": {}, "properties": {"manufacturer": ""}}, DEVICE),
    ("delete", ("device", "namespace", "rg"), {}, "DELETE", "", 204, None, None),
    ("attribute_create", ("attr", "device", "namespace", "rg"), {}, "PUT", "/attributes/attr", 200,
     {"properties": {"reportedBy": "User"}}, {"name": "attr", "properties": {"reportedBy": "User"}}),
    ("attribute_delete", ("attr", "device", "namespace", "rg"), {}, "DELETE", "/attributes/attr", 204, None, None),
    ("capability_show", ("hub", "device", "namespace", "rg"), {}, "GET", "/capabilities/hub", 200, None,
     {"name": "hub", "properties": {"capabilityType": "Microsoft.IoTHub"}}),
])
def test_current_sdk_wire_shapes(
    wire_client, mocked_response, fixture_cmd, mocker, method, args, kwargs, verb, suffix, status, body, result,
):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    mocked_response.add(verb, NAMESPACE_URL + "/registryDevices/device" + suffix, status=status, json=result)
    assert getattr(provider, method)(*args, **kwargs) == result
    assert len(mocked_response.calls) == 1
    request = mocked_response.calls[0].request
    assert parse_qs(urlsplit(request.url).query) == {"api-version": ["2026-11-02-preview"]}
    if body is not None:
        assert json.loads(request.body) == body
    else:
        assert not request.body


@pytest.mark.parametrize("method,authentication_type,action,response", [
    ("auth_show_keys", "SymmetricKey", "listKeys",
     {"symmetricKey": {"primaryKey": "test-secret-one", "secondaryKey": "test-secret-two"}}),
    ("auth_revoke_certs", "CertificateAuthoritySignedX509Certificate", "revokeCertificates", None),
])
def test_current_sdk_auth_actions(
    wire_client, mocked_response, fixture_cmd, mocker, method, authentication_type, action, response, caplog,
):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    url = NAMESPACE_URL + "/registryDevices/device/authenticationProfiles/profile"
    mocked_response.add("GET", url, json={"name": "profile", "properties": {"authenticationType": authentication_type}})
    mocked_response.add("POST", url + "/" + action, status=204 if response is None else 200, json=response)
    caplog.set_level(logging.DEBUG)
    assert getattr(provider, method)("profile", "device", "namespace", "rg") == response
    assert [call.request.method for call in mocked_response.calls] == ["GET", "POST"]
    assert "test-secret-one" not in caplog.text
    assert "test-secret-two" not in caplog.text
    for call in mocked_response.calls:
        assert parse_qs(urlsplit(call.request.url).query) == {"api-version": ["2026-11-02-preview"]}
        assert not call.request.body


@pytest.mark.parametrize("child,path", [
    ("auth", "authenticationProfiles"), ("attribute", "attributes"), ("capability", "capabilities"),
])
def test_current_sdk_child_pagination(wire_client, mocked_response, fixture_cmd, mocker, child, path):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    url = NAMESPACE_URL + "/registryDevices/device/" + path
    next_url = url + "?api-version=2026-11-02-preview&continuationToken=second"
    mocked_response.add("GET", url, json={"value": [{"name": "one"}], "nextLink": next_url})
    mocked_response.add("GET", next_url, json={"value": [{"name": "two"}]})
    assert getattr(provider, child + "_list")("device", "namespace", "rg") == [{"name": "one"}, {"name": "two"}]
    assert len(mocked_response.calls) == 2
    assert mocked_response.calls[1].request.url == next_url


def test_current_factory_contract(offline_cli):
    from azext_iot._factory import adr_service_factory
    from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient

    client = adr_service_factory(offline_cli)
    assert isinstance(client, DeviceRegistryMgmtClient)
    assert client._config.api_version == "2026-11-02-preview"
    assert client._config.base_url == "https://centraluseuap.management.azure.com"
    for name in ("registry_devices", "registry_device_attributes",
                 "registry_device_authentication_profiles", "registry_device_capabilities"):
        assert callable(getattr(client, name).get)
    for name in ("registry_device_authentication_profiles", "registry_device_capabilities"):
        assert not hasattr(getattr(client, name), "create_or_replace")
        assert not hasattr(getattr(client, name), "begin_create_or_replace")


@pytest.mark.parametrize("arguments,group,method,result,kwargs", [
    ("attribute create --rdn device -n attr --properties '{\"value\":false}'", "registry_device_attributes",
     "create_or_replace", {"name": "attr"},
     {"registry_device_name": "device", "attribute_name": "attr",
      "resource": {"properties": {"value": False, "reportedBy": "User"}}}),
    ("attribute delete --rdn device -n attr --yes", "registry_device_attributes", "delete", None,
     {"registry_device_name": "device", "attribute_name": "attr"}),
    ("auth show-keys --rdn device -n profile", "registry_device_authentication_profiles", "list_keys",
     {"symmetricKey": {"primaryKey": "explicit-secret"}},
     {"registry_device_name": "device", "authentication_profile_name": "profile", "logging_enable": False}),
    ("auth wait --rdn device -n profile --interval 1 --timeout 1", "registry_device_authentication_profiles", "get",
     PROFILE, {"registry_device_name": "device", "authentication_profile_name": "profile", "logging_enable": False}),
    ("wait -n device --created --interval 1 --timeout 1", "registry_devices", "get", DEVICE,
     {"registry_device_name": "device"}),
    ("wait --ext-id external --exists --interval 1 --timeout 1", "registry_devices", "list_by_namespace", [DEVICE], {}),
])
def test_global_parser_child_mutations_keys_and_waits(offline_cli, mocker, arguments, group, method, result, kwargs):
    client = provider_tests._spec_adr_client()
    operation = getattr(getattr(client, group), method)
    client.registry_device_authentication_profiles.get.return_value = PROFILE
    operation.return_value = result
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    output = StringIO()
    assert offline_cli.invoke(shlex.split(f"{PREFIX} {arguments} {SCOPE}"), out_file=output) == 0
    operation.assert_called_once_with(resource_group_name="rg", namespace_name="namespace", **kwargs)
    if " wait " not in " " + arguments and not arguments.startswith("wait") and result is not None:
        assert json.loads(output.getvalue()) == result


@pytest.mark.parametrize("no_wait", [False, True])
def test_global_parser_revoke_confirmation_and_no_wait(offline_cli, mocker, no_wait):
    client = provider_tests._spec_adr_client()
    client.registry_device_authentication_profiles.get.return_value = {
        "properties": {"authenticationType": "CertificateAuthoritySignedX509Certificate"},
    }
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    wait = mocker.patch("azext_iot.adr.providers.registry_device.RegistryDeviceProvider._wait", return_value=None)
    args = f"{PREFIX} auth revoke-certs --rdn device -n profile --yes {SCOPE}" + (" --no-wait" if no_wait else "")
    assert offline_cli.invoke(shlex.split(args), out_file=StringIO()) == 0
    client.registry_device_authentication_profiles.begin_revoke_certificates.assert_called_once_with(
        registry_device_name="device", authentication_profile_name="profile", namespace_name="namespace",
        resource_group_name="rg",
    )
    assert wait.call_args.kwargs == {"no_wait": no_wait}


def test_partial_pagination_error_does_not_return_incomplete_result(registry_device_provider):
    error = HttpResponseError("next page unavailable")

    def pages():
        yield DEVICE
        raise error

    registry_device_provider.client.registry_devices.list_by_namespace.return_value = pages()
    with pytest.raises(HttpResponseError) as raised:
        registry_device_provider.show(namespace_name="namespace", resource_group_name="rg", external_device_id="external")
    assert raised.value is error


def test_update_does_not_swallow_submission_or_poller_failure(registry_device_provider):
    error = HttpResponseError("patch failed")
    operation = registry_device_provider.client.registry_devices.begin_update
    operation.side_effect = error
    with pytest.raises(HttpResponseError) as raised:
        registry_device_provider.update("device", "namespace", "rg", tags={})
    assert raised.value is error
    operation.side_effect = None
    poller = operation.return_value
    poller.done.return_value = True
    poller.result.side_effect = error
    with pytest.raises(HttpResponseError) as raised:
        registry_device_provider.update("device", "namespace", "rg", tags={})
    assert raised.value is error


def test_auth_metadata_never_mutates_sdk_objects(registry_device_provider):
    original = {
        "name": "profile",
        "properties": {"authenticationType": "SymmetricKey", "symmetricKey": {"primaryKey": "private-test-value"}},
    }
    expected = deepcopy(original)
    operations = registry_device_provider.client.registry_device_authentication_profiles
    operations.get.return_value = original
    operations.list_by_device.return_value = iter([original])
    for metadata in (
        registry_device_provider.auth_show("profile", "device", "namespace", "rg"),
        registry_device_provider.auth_list("device", "namespace", "rg")[0],
    ):
        assert metadata is not original
        assert metadata["properties"] == {"authenticationType": "SymmetricKey"}
    assert original == expected
    operations.list_keys.assert_not_called()


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("workaround", [False, True])
def test_registry_revoke_202_uses_current_sdk_poller_and_location(
    wire_client, mocked_response, fixture_cmd, mocker, no_wait, workaround,
):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    mocker.patch(
        "azext_iot.adr.providers.base.wait_for_terminal_state", partial(wait_for_terminal_state, wait_sec=0)
    )
    provider = RegistryDeviceProvider(fixture_cmd)
    url = NAMESPACE_URL + "/registryDevices/device/authenticationProfiles/profile"
    location = NAMESPACE_URL + "/operationResults/registry-revoke"
    mocked_response.add("GET", url, json={
        "name": "profile", "properties": {"authenticationType": "CertificateAuthoritySignedX509Certificate"},
    })
    mocked_response.add("POST", url + "/revokeCertificates", status=202, headers={"Location": location, "Retry-After": "0"})
    mocked_response.add("GET", location, status=204)
    begin = mocker.spy(wire_client.registry_device_authentication_profiles, "begin_revoke_certificates")
    result = provider.auth_revoke_certs("profile", "device", "namespace", "rg", no_wait=no_wait)
    assert isinstance(begin.spy_return, LROPoller)
    if no_wait:
        assert result is begin.spy_return
    else:
        assert result is None
    # Drain the SDK's native background poller before tearing down HTTP mocks.
    begin.spy_return.result()
    assert sum(call.request.method == "POST" for call in mocked_response.calls) == 1
    assert any(call.request.url == location for call in mocked_response.calls)
    assert sum(urlsplit(call.request.url).path == urlsplit(url).path for call in mocked_response.calls) == 1
