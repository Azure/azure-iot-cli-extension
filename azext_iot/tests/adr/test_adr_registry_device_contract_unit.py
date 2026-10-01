# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exercise registry commands through the global loader and the current SDK wire contract."""

import json
import shlex
from io import StringIO
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cli.core import MainCommandsLoader
from azure.cli.core.azclierror import (
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from azext_iot.adr import commands_wait
from azext_iot.adr.providers.registry_device import RegistryDeviceProvider
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
PREFIX = "iot adr ns device"


@pytest.mark.parametrize("command,group,method,result,kwargs", [
    ("show --name device", "registry_devices", "get", DEVICE, {"registry_device_name": "device"}),
    ("list", "registry_devices", "list_by_namespace", [DEVICE], {}),
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


def test_registry_device_commands_are_ga(offline_cli):
    table = MainCommandsLoader(offline_cli).load_command_table(["iot", "adr", "ns"])
    restored = [command for name, command in table.items() if name.startswith(PREFIX)]
    assert len(restored) == 6
    assert all(not command.command_kwargs["is_preview"] for command in restored)


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
])
def test_global_parser_validation(offline_cli, arguments, error):
    # Azure CLI routes CLI errors into its result; network guards in offline_cli
    # ensure invalid input never reaches a credential or HTTP transport.
    assert offline_cli.invoke(shlex.split(f"{PREFIX} {arguments} {SCOPE}"), out_file=StringIO()) != 0
    assert isinstance(offline_cli.result.error, error)


@pytest.mark.parametrize("child,method,args,sdk_method", [
    ("registry_devices", "show", ("device", "namespace", "rg"), "get"),
    ("registry_devices", "list", ("namespace", "rg"), "list_by_namespace"),
    ("registry_devices", "create", ("device", "namespace", "rg", "centraluseuap"), "begin_create_or_replace"),
    ("registry_devices", "delete", ("device", "namespace", "rg"), "begin_delete"),
])
def test_sdk_errors_are_not_hidden(registry_device_provider, child, method, args, sdk_method):
    error = HttpResponseError("permission denied")
    operation = getattr(getattr(registry_device_provider.client, child), sdk_method)
    operation.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        getattr(registry_device_provider, method)(*args)
    assert caught.value is error
    assert operation.call_count == 1


@pytest.mark.parametrize("options", [
    {}, {"exists": True}, {"created": True}, {"updated": True}, {"custom": "name == 'profile'"},
])
def test_wait_uses_exact_sdk_getter_and_lifecycle(registry_device_provider, mocker, options):
    mocker.patch.object(commands_wait, "RegistryDeviceProvider", return_value=registry_device_provider)
    resource = {"name": "profile", "properties": {"provisioningState": "Succeeded"}}
    getter = registry_device_provider.client.registry_devices.get
    getter.return_value = resource
    function = commands_wait.adr_registry_device_wait
    args = {"registry_device_name": "device"}
    result = function(Mock(cli_ctx=Mock()), namespace_name="namespace", resource_group_name="rg",
                      timeout=1, interval=1, **args, **options)
    assert result is None
    getter.assert_called_once_with(
        namespace_name="namespace", resource_group_name="rg", **args
    )


def test_wait_deleted_uses_sdk_404(registry_device_provider, mocker):
    mocker.patch.object(commands_wait, "RegistryDeviceProvider", return_value=registry_device_provider)
    getter = registry_device_provider.client.registry_devices.get
    getter.side_effect = ResourceNotFoundError("gone")
    getter.side_effect.status_code = 404
    function = commands_wait.adr_registry_device_wait
    args = {"registry_device_name": "device"}
    assert function(Mock(cli_ctx=Mock()), namespace_name="namespace", resource_group_name="rg",
                    timeout=1, interval=1, deleted=True, **args) is None


def test_real_sdk_pagination_and_external_id_lookup(wire_client, mocked_response, fixture_cmd, mocker):
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)
    url = NAMESPACE_URL + "/registryDevices"
    next_url = url + "?api-version=2026-11-01&continuationToken=second"
    mocked_response.add("GET", url, json={"value": [{"name": "other"}], "nextLink": next_url})
    mocked_response.add("GET", next_url, json={"value": [DEVICE]})
    assert provider.show(namespace_name="namespace", resource_group_name="rg", external_device_id="external") == DEVICE
    assert len(mocked_response.calls) == 2
    assert mocked_response.calls[1].request.url == next_url


@pytest.mark.parametrize("method,args,kwargs,verb,suffix,status,body,result", [
    ("create", ("device", "namespace", "rg"), {"location": "centraluseuap"}, "PUT", "", 200,
     {"location": "centraluseuap", "properties": {"enablementState": "Enabled"}}, DEVICE),
    ("update", ("device", "namespace", "rg"), {"manufacturer": "", "tags": {}}, "PATCH", "", 200,
     {"tags": {}, "properties": {"manufacturer": ""}}, DEVICE),
    ("delete", ("device", "namespace", "rg"), {}, "DELETE", "", 204, None, None),
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
    assert parse_qs(urlsplit(request.url).query) == {"api-version": ["2026-11-01"]}
    if body is not None:
        assert json.loads(request.body) == body
    else:
        assert not request.body


def test_current_factory_contract(offline_cli):
    from azext_iot._factory import adr_service_factory
    from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient

    client = adr_service_factory(offline_cli)
    assert isinstance(client, DeviceRegistryMgmtClient)
    assert client._config.api_version == "2026-11-01"
    assert client._config.base_url == "https://management.azure.com"
    assert callable(client.registry_devices.get)
    for name in ("registry_device_attributes", "registry_device_authentication_profiles", "registry_device_capabilities"):
        assert not hasattr(client, name)


@pytest.mark.parametrize("arguments,group,method,result,kwargs", [
    ("wait -n device --created --interval 1 --timeout 1", "registry_devices", "get", DEVICE,
     {"registry_device_name": "device"}),
    ("wait --ext-id external --exists --interval 1 --timeout 1", "registry_devices", "list_by_namespace", [DEVICE], {}),
])
def test_global_parser_registry_device_waits(offline_cli, mocker, arguments, group, method, result, kwargs):
    client = provider_tests._spec_adr_client()
    operation = getattr(getattr(client, group), method)
    operation.return_value = result
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
    output = StringIO()
    assert offline_cli.invoke(shlex.split(f"{PREFIX} {arguments} {SCOPE}"), out_file=output) == 0
    operation.assert_called_once_with(resource_group_name="rg", namespace_name="namespace", **kwargs)
    if " wait " not in " " + arguments and not arguments.startswith("wait") and result is not None:
        assert json.loads(output.getvalue()) == result


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
