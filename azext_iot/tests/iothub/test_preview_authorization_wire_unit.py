# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Preview authorization through the parser, discovery, provider and native HTTP pipeline.

Only ARM lookup and Profile token acquisition are mocked. Tokens and keys are synthetic.
These prove the CLI wire contract, not service-side RBAC or disabled-device behavior.
"""

import base64
from copy import deepcopy
import hashlib
import hmac
from inspect import signature
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import responses
from azure.cli.core import AzCommandsLoader
from azure.cli.core.azclierror import UnauthorizedError
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser

from azext_iot import IoTExtCommandsLoader
from azext_iot.common.shared import GatewayVersion
from azext_iot.iothub import commands_pnp_runtime
from azext_iot.operations import hub
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, RecordingTransport


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
KEY = base64.b64encode(b"offline-hub-policy-key").decode()


@pytest.fixture(scope="module")
def preview_parser():
    cli = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    names = [
        "iot hub module-identity create", "iot hub device-identity renew-key",
        *[f"iot hub digital-twin {action}" for action in ("show", "update", "invoke-command")],
    ]
    loader.command_table = {name: loader.command_table[name] for name in names}
    cli.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    for name in names:
        loader.load_arguments(name)
        AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli)
    parser.load_command_table(loader)
    return parser, cli


@pytest.fixture(params=["key", "login", "cstring"])
def mode(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["classic", "split-host"])
def runtime(request, mode, preview_parser, mocker):
    parser, cli = preview_parser
    hostname = "service.unit.invalid" if request.param else "classic.unit.invalid"
    properties = {"hostName": "classic.unit.invalid"}
    if request.param:
        properties.update({
            "serviceHostName": hostname, "deviceHostName": "device.unit.invalid",
            "iotHubDetails": {"gatewayVersion": GatewayVersion.V2.value},
        })
    resource = {
        "id": f"/subscriptions/{SUBSCRIPTION}/resourceGroups/unit-rg/providers/Microsoft.Devices/IotHubs/unit-hub",
        "name": "unit-hub", "location": "unit", "sku": {"tier": "Standard"}, "properties": properties,
    }
    find_resource = mocker.patch(
        "azext_iot.iothub.providers.discovery.IotHubDiscovery.find_resource", return_value=resource,
    )
    find_policy = mocker.patch(
        "azext_iot.iothub.providers.discovery.IotHubDiscovery.find_policy",
        return_value={"keyName": "iothubowner", "primaryKey": KEY, "secondaryKey": KEY},
    )
    profile = mocker.patch("azext_iot.common.auth.Profile", autospec=True)
    token = profile.return_value.get_raw_token
    token.side_effect = lambda **_: (("Bearer", f"offline-token-{token.call_count}", {}), SUBSCRIPTION, "offline-tenant")
    clients, transports = [], []

    def client(**kwargs):
        transport = RecordingTransport()
        result = IotHubGatewayServiceAPIs(transport=transport, **kwargs)
        clients.append(result)
        transports.append(transport)
        return result

    mocker.patch("azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs", side_effect=client)

    def invoke(handler, arguments):
        auth = ["--auth-type", mode] if mode != "cstring" else [
            "--login", f"HostName={hostname};SharedAccessKeyName=iothubowner;SharedAccessKey={KEY}",
        ]
        namespace = vars(parser.parse_args([
            "iot", "hub", *arguments, "-n", "unit-hub", "-g", "unit-rg", *auth,
        ]))
        kwargs = {name: namespace[name] for name in signature(handler).parameters if name in namespace and name != "cmd"}
        return handler(cmd=SimpleNamespace(cli_ctx=cli), **kwargs)

    yield SimpleNamespace(
        invoke=invoke, endpoint="https://" + hostname, transports=transports, hostname=hostname,
        token=token, profile=profile, cli=cli, find_policy=find_policy, find_resource=find_resource,
    )
    for item in clients:
        item.close()


def _assert_wire_auth(runtime, mode, requests):
    native = [request for transport in runtime.transports for request in transport.requests]
    assert len(native) == len(requests)
    for index, (request, native_request) in enumerate(zip(requests, native), 1):
        assert request.headers["Authorization"] == native_request.headers["Authorization"]
        assert urlsplit(request.url).hostname == runtime.hostname
        assert parse_qs(urlsplit(request.url).query)["api-version"] == [API]
        authorization = request.headers["Authorization"]
        if mode == "login":
            assert authorization == f"Bearer offline-token-{index}"
        else:
            assert authorization.startswith("SharedAccessSignature ")
            fields = parse_qs(authorization.removeprefix("SharedAccessSignature "))
            assert fields["sr"] == [runtime.hostname]
            assert fields["skn"] == ["iothubowner"]
            to_sign = f"{quote(runtime.hostname, safe='')}\n{fields['se'][0]}".encode()
            expected = base64.b64encode(hmac.new(base64.b64decode(KEY), to_sign, hashlib.sha256).digest()).decode()
            assert fields["sig"] == [expected], "The request must be signed with the Hub policy key, never a device key."
    if mode == "login":
        assert runtime.token.call_count == len(requests)
        runtime.token.assert_called_with(subscription=None, resource="https://iothubs.azure.net")
        runtime.profile.assert_called_with(cli_ctx=runtime.cli)
        runtime.find_policy.assert_not_called()
    else:
        runtime.profile.assert_not_called()
    if mode == "cstring":
        runtime.find_resource.assert_not_called()
        runtime.find_policy.assert_not_called()


@pytest.mark.parametrize("component", [None, "thermostat1"])
@pytest.mark.parametrize("payload", ["0", '""', '"unit"', '{"value":null,"other":0}', "null"])
def test_show_patch_then_invoke_preserves_auth_and_payload(runtime, mode, component, payload):
    route = "/digitaltwins/device"
    suffix = f"/components/{component}" if component else ""
    invoke_url = runtime.endpoint + route + suffix + "/commands/reboot"
    patch = [{"op": "add", "path": "/target", "value": 25}]
    with responses.RequestsMock() as network:
        network.add("GET", runtime.endpoint + route, json={"target": 25}, status=200)
        network.add("PATCH", runtime.endpoint + route, status=202)
        network.add(
            "POST", invoke_url, json={"received": json.loads(payload)}, status=200,
            headers={"x-ms-command-statuscode": "200"},
        )
        assert runtime.invoke(commands_pnp_runtime.get_digital_twin, [
            "digital-twin", "show", "-d", "device",
        ]) == {"target": 25}
        assert runtime.invoke(commands_pnp_runtime.patch_digital_twin, [
            "digital-twin", "update", "-d", "device", "--json-patch", json.dumps(patch),
        ]) == {"target": 25}
        result = runtime.invoke(commands_pnp_runtime.invoke_device_command, [
            "digital-twin", "invoke-command", "-d", "device", "--cn", "reboot",
            "--payload", payload, "--cto", "15", "--rto", "30",
            *(["--component-path", component] if component else []),
        ])
        assert result == {"payload": {"received": json.loads(payload)}, "status": "200"}
        requests = [call.request for call in network.calls]
        assert [request.method for request in requests] == ["GET", "PATCH", "GET", "POST"]
        assert json.loads(requests[1].body) == patch
        assert parse_qs(urlsplit(requests[-1].url).query) == {
            "api-version": [API], "connectTimeoutInSeconds": ["15"], "responseTimeoutInSeconds": ["30"],
        }
        assert requests[-1].headers["Content-Type"] == "application/json; charset=utf-8"
        # Existing top-level None omits the body; nested null stays JSON null.
        # Do not silently normalize falsey scalars to an object or change this compatibility contract.
        if payload == "null":
            assert requests[-1].body is None
        else:
            assert json.loads(requests[-1].body) == json.loads(payload)
        _assert_wire_auth(runtime, mode, requests)


@pytest.mark.parametrize("operation,component", [("invoke", None), ("invoke", "thermostat1"), ("module", None)])
def test_native_401002_is_not_retried_or_converted_to_another_auth(runtime, mode, component, operation):
    if operation == "invoke":
        suffix = f"/components/{component}" if component else ""
        route = f"/digitaltwins/device{suffix}/commands/reboot"
        handler = commands_pnp_runtime.invoke_device_command
        arguments = [
            "digital-twin", "invoke-command", "-d", "device", "--cn", "reboot", "--payload", "0",
            "--cto", "15", "--rto", "30",
            *(["--component-path", component] if component else []),
        ]
        method = "POST"
    else:
        route = "/devices/device/modules/module"
        handler = hub.iot_device_module_create
        arguments = ["module-identity", "create", "-d", "device", "-m", "module"]
        method = "PUT"
    with responses.RequestsMock() as network:
        if operation == "invoke":
            # Reproduce successful reads/writes followed specifically by invoke denial.
            network.add("GET", runtime.endpoint + "/digitaltwins/device", status=200, json={"target": 25})
            network.add("PATCH", runtime.endpoint + "/digitaltwins/device", status=202)
            runtime.invoke(commands_pnp_runtime.get_digital_twin, ["digital-twin", "show", "-d", "device"])
            runtime.invoke(commands_pnp_runtime.patch_digital_twin, [
                "digital-twin", "update", "-d", "device", "--json-patch",
                '[{"op":"add","path":"/target","value":25}]',
            ])
        prior_calls = len(network.calls)
        network.add(
            method, runtime.endpoint + route, status=401,
            json={"Message": '{"errorCode":401002,"message":"Unauthorized access",'
                             '"trackingId":"offline-tracking","timestampUtc":"2026-09-13T22:06:51Z"}',
                  "ExceptionMessage": ""},
        )
        with pytest.raises(UnauthorizedError, match="401002"):
            runtime.invoke(handler, arguments)
        assert len(network.calls) == prior_calls + 1
        _assert_wire_auth(runtime, mode, [call.request for call in network.calls])


@pytest.mark.parametrize("status", ["enabled", "disabled"])
def test_device_key_swap_cannot_change_module_hub_authorization(runtime, mode, status):
    identity = {
        "deviceId": "device", "status": status, "etag": "unit-etag",
        "authentication": {"type": "sas", "symmetricKey": {
            "primaryKey": "offline-device-primary", "secondaryKey": "offline-device-secondary",
        }},
        "attributes": {"owner": "device"}, "parentScopes": ["parent-scope"],
    }
    swapped = deepcopy(identity)
    swapped["authentication"]["symmetricKey"] = {
        "primaryKey": "offline-device-secondary", "secondaryKey": "offline-device-primary",
    }
    with responses.RequestsMock() as network:
        network.add("GET", runtime.endpoint + "/devices/device", status=200, json=identity)
        network.add("PUT", runtime.endpoint + "/devices/device", status=200, json=swapped)
        network.add(
            "PUT", runtime.endpoint + "/devices/device/modules/module", status=200,
            json={"deviceId": "device", "moduleId": "module"},
        )
        runtime.invoke(hub.iot_device_key_regenerate, [
            "device-identity", "renew-key", "-d", "device", "--kt", "swap",
        ])
        assert runtime.invoke(hub.iot_device_module_create, [
            "module-identity", "create", "-d", "device", "-m", "module",
        ]) == {"deviceId": "device", "moduleId": "module"}
        requests = [call.request for call in network.calls]
        assert [request.method for request in requests] == ["GET", "PUT", "PUT"]
        updated = json.loads(requests[1].body)
        for field in ("status", "authentication", "attributes", "parentScopes"):
            assert updated[field] == swapped[field]
        assert json.loads(requests[-1].body) == {
            "deviceId": "device", "moduleId": "module", "authentication": {"type": "sas", "symmetricKey": {}},
        }
        _assert_wire_auth(runtime, mode, requests)
