# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Sequential actual CLI invocations; no live Profile, credentials or network.

One CLI/config, ARM/token mock lifetime and uninterrupted native/wire recording
span all phases. CLI invocation objects and service clients have their normal
per-command lifetimes. These are auth-transition evidence, not a live 401 fix.
"""

import base64
import hashlib
import hmac
from io import StringIO
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import responses
from azure.cli.core import MainCommandsLoader
from azure.cli.core.azclierror import UnauthorizedError
from azure.cli.core.mock import DummyCli
from azure.core.exceptions import ClientAuthenticationError

from azext_iot import IoTExtCommandsLoader
from azext_iot.common.shared import GatewayVersion
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, RecordingTransport
from azext_iot.tests.iothub.test_preview_authorization_wire_unit import SUBSCRIPTION


SAS_KEYS = {
    mode: base64.b64encode(f"offline-switch-{mode}-key".encode()).decode()
    for mode in ("key", "cstring")
}
POLICIES = {"key": "iothubowner", "cstring": "offline-cstring-owner"}
TWIN = "/digitaltwins/device"
ROOT = TWIN + "/commands/reboot"
COMPONENT = TWIN + "/components/thermostat1/commands/report"


class _PnpCommandsLoader(MainCommandsLoader):
    """Reuse the normal MainCommandsLoader invocation path, with local registration only."""

    def load_command_table(self, args):
        loader = IoTExtCommandsLoader(self.cli_ctx)
        self.command_table = {
            name: command for name, command in loader.load_command_table(args).items()
            if name.startswith("iot hub digital-twin ")
        }
        self.cmd_to_loader_map = {name: [loader] for name in self.command_table}
        return self.command_table


@pytest.fixture(params=[False, True], ids=["classic", "split-host"])
def switching_cli(request, mocker, monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_EXTENSION_DIR", str(tmp_path / "extensions"))
    monkeypatch.setenv("AZURE_CORE_COLLECT_TELEMETRY", "false")
    monkeypatch.setenv("AZURE_EXTENSION_USE_DYNAMIC_INSTALL", "no")
    monkeypatch.setenv("AZURE_DEFAULTS_IOTHUB-DATA-AUTH-TYPE", "key")
    monkeypatch.setattr("azure.cli.core._config.GLOBAL_CONFIG_DIR", str(tmp_path))
    # Fake the complete OAuth Profile boundary; any other real Profile construction fails.
    profile = mocker.patch("azext_iot.common.auth.Profile", autospec=True)
    guards = [
        mocker.patch(target, side_effect=AssertionError("unexpected live Profile or socket access"))
        for target in ("azure.cli.core._profile.Profile.__init__", "socket.socket.connect", "socket.create_connection")
    ]
    token = profile.return_value.get_raw_token
    token.side_effect = lambda **_: (
        ("Bearer", f"offline-switch-token-{token.call_count}", {}), SUBSCRIPTION, "offline-tenant",
    )
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
        return_value={"keyName": POLICIES["key"], "primaryKey": SAS_KEYS["key"], "secondaryKey": SAS_KEYS["key"]},
    )
    clients, native = [], []

    def client(**kwargs):
        transport = RecordingTransport()
        transport.requests = native
        sdk = IotHubGatewayServiceAPIs(transport=transport, **kwargs)
        clients.append(sdk)
        return sdk

    mocker.patch("azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs", side_effect=client)
    runtime = SimpleNamespace(
        cli=DummyCli(commands_loader_cls=_PnpCommandsLoader), hostname=hostname, native=native,
        find_resource=find_resource, find_policy=find_policy, profile=profile, token=token,
        phase=None, denied=None, twin={"target": 20}, commands=[],
    )

    def respond(http_request):
        path = urlsplit(http_request.url).path
        if http_request.method == "GET":
            return 200, {}, json.dumps(runtime.twin)
        if http_request.method == "PATCH":
            patch = json.loads(http_request.body)
            assert patch == [{"op": "replace", "path": "/target", "value": patch[0]["value"]}]
            runtime.twin["target"] = patch[0]["value"]
            return 202, {}, ""
        assert http_request.method == "POST" and path in (ROOT, COMPONENT)
        if runtime.phase == "login" and runtime.denied == path:
            return 401, {}, json.dumps({
                "Message": json.dumps({
                    "errorCode": 401002, "message": "Unauthorized access",
                    "trackingId": "offline-switch-401", "timestampUtc": "2026-09-13T21:51:44Z",
                }),
                "ExceptionMessage": "",
            })
        return 200, {"x-ms-command-statuscode": "200"}, json.dumps({"received": json.loads(http_request.body)})

    try:
        with responses.RequestsMock() as network:
            runtime.network = network
            for method, path in (("GET", TWIN), ("PATCH", TWIN), ("POST", ROOT), ("POST", COMPONENT)):
                network.add_callback(
                    method, "https://" + hostname + path, callback=respond, content_type="application/json",
                )
            yield runtime
    finally:
        for sdk in clients:
            sdk.close()
        for guard in guards:
            guard.assert_not_called()


def _invoke(runtime, mode, arguments):
    auth = ["--auth-type", mode] if mode != "cstring" else [
        "--login",
        f"HostName={runtime.hostname};SharedAccessKeyName={POLICIES[mode]};SharedAccessKey={SAS_KEYS[mode]}",
    ]
    command = ["iot", "hub", "digital-twin", *arguments, "-d", "device", "-n", "unit-hub", "-g", "unit-rg", *auth]
    runtime.commands.append((mode, arguments))
    output = StringIO()
    code = runtime.cli.invoke(command, out_file=output)
    if code == 0:
        assert runtime.cli.result.error is None
        assert json.loads(output.getvalue()) == runtime.cli.result.result
    else:
        assert not output.getvalue().strip()
    return code, runtime.cli.result


def _assert_wire(runtime, mode, start, expected, token_start):
    requests = [call.request for call in runtime.network.calls[start:]]
    assert len(runtime.native) == len(runtime.network.calls)
    assert len(requests) == len(expected)
    for index, (actual, native, (method, path, body)) in enumerate(
        zip(requests, runtime.native[start:], expected), 1,
    ):
        parsed = urlsplit(actual.url)
        assert actual.method == native.method == method
        assert parsed.scheme == "https" and parsed.hostname == runtime.hostname and parsed.path == path
        assert actual.url == native.url
        query = {"api-version": [API]}
        if method == "POST":
            query.update(connectTimeoutInSeconds=["15"], responseTimeoutInSeconds=["30"])
        assert parse_qs(parsed.query) == query
        if body is not None:
            assert json.loads(actual.body) == body
            content_type = "application/json; charset=utf-8" if method == "POST" else "application/json"
            assert actual.headers["Content-Type"] == content_type
        authorization = actual.headers["Authorization"]
        assert authorization == native.headers["Authorization"]
        if mode == "login":
            assert authorization == f"Bearer offline-switch-token-{token_start + index}"
        else:
            assert authorization.startswith("SharedAccessSignature ")
            fields = parse_qs(authorization.removeprefix("SharedAccessSignature "))
            assert fields["sr"] == [runtime.hostname]
            assert fields["skn"] == [POLICIES[mode]]
            to_sign = f"{quote(runtime.hostname, safe='')}\n{fields['se'][0]}".encode()
            digest = hmac.new(base64.b64decode(SAS_KEYS[mode]), to_sign, hashlib.sha256).digest()
            assert fields["sig"] == [base64.b64encode(digest).decode()]
    if mode == "login":
        assert runtime.token.call_count == token_start + len(expected)
        for call in runtime.token.call_args_list[token_start:]:
            assert call.args == () and call.kwargs == {"subscription": None, "resource": "https://iothubs.azure.net"}
        # Actual CLI invocation deliberately shallow-copies cli_ctx for each job.
        for call in runtime.profile.call_args_list[token_start:]:
            assert call.kwargs["cli_ctx"].config is runtime.cli.config
    else:
        assert runtime.token.call_count == token_start


def _phase(runtime, mode):
    runtime.phase = mode
    start, token_start = len(runtime.network.calls), runtime.token.call_count
    lookup_start = runtime.find_resource.call_count, runtime.find_policy.call_count
    commands_start = len(runtime.commands)
    code, result = _invoke(runtime, mode, ["show"])
    assert code == 0 and result.result == runtime.twin
    patch = [{"op": "replace", "path": "/target", "value": runtime.twin["target"] + 1}]
    code, result = _invoke(runtime, mode, ["update", "--patch", json.dumps(patch)])
    assert code == 0 and result.result == {"target": patch[0]["value"]}
    expected = [("GET", TWIN, None), ("PATCH", TWIN, patch), ("GET", TWIN, None)]
    for path, name, payload, component in (
        (ROOT, "reboot", 0, None), (COMPONENT, "report", {"value": None, "label": "unit"}, "thermostat1"),
    ):
        code, result = _invoke(runtime, mode, [
            "invoke-command", "--cn", name, "--payload", json.dumps(payload), "--cto", "15", "--rto", "30",
            *(["--component-path", component] if component else []),
        ])
        expected.append(("POST", path, payload))
        if mode == "login" and runtime.denied == path:
            assert code == 1 and isinstance(result.error, UnauthorizedError)
            assert "401002" in str(result.error) and "offline-switch-401" in str(result.error)
            assert result.result is None
            break
        assert code == 0 and result.result == {"payload": {"received": payload}, "status": "200"}
    _assert_wire(runtime, mode, start, expected, token_start)
    command_count = len(runtime.commands) - commands_start
    assert runtime.find_resource.call_count == lookup_start[0] + (command_count if mode != "cstring" else 0)
    assert runtime.find_policy.call_count == lookup_start[1] + (command_count if mode == "key" else 0)


@pytest.mark.parametrize("denied", [None, ROOT, COMPONENT], ids=["success", "root-401", "component-401"])
def test_actual_cli_key_login_cstring_transition(switching_cli, denied):
    runtime = switching_cli
    runtime.denied = denied
    for mode in ("key", "login", "cstring"):
        _phase(runtime, mode)
    assert list(dict.fromkeys(mode for mode, _ in runtime.commands)) == ["key", "login", "cstring"]
    assert len(runtime.commands) == (11 if denied == ROOT else 12)
    assert len(runtime.network.calls) == (14 if denied == ROOT else 15)


def test_login_token_failure_does_not_reuse_prior_sas_or_poison_cstring(switching_cli):
    runtime = switching_cli
    _phase(runtime, "key")
    start = len(runtime.network.calls)
    lookup_start = runtime.find_policy.call_count
    runtime.phase = "login"
    runtime.token.side_effect = ClientAuthenticationError("offline token acquisition failed")
    code, result = _invoke(runtime, "login", ["show"])
    assert code == 1 and isinstance(result.error, ClientAuthenticationError)
    assert "offline token acquisition failed" in str(result.error)
    assert result.result is None
    runtime.token.assert_called_once_with(subscription=None, resource="https://iothubs.azure.net")
    assert len(runtime.network.calls) == len(runtime.native) == start
    assert runtime.find_policy.call_count == lookup_start
    _phase(runtime, "cstring")
    assert runtime.token.call_count == 1
