# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Configuration CLI/provider bodies through the maintained bridge and real SDK."""

from copy import deepcopy
import inspect
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
from azure.cli.core import AzCommandsLoader
from azure.cli.core.azclierror import BadRequestError
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser
from azure.core.credentials import AzureKeyCredential
from msrest.exceptions import SerializationError

from azext_iot import IoTExtCommandsLoader
from azext_iot.iothub._authentication import HubAuthenticationPolicy
from azext_iot.iothub._client import HubClient
from azext_iot.iothub.common import HubAspects
from azext_iot.iothub.providers.state import StateProvider
from azext_iot.operations import hub
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, ENDPOINT, RecordingTransport


SAMPLES = Path(__file__).parent
CREATE_COMMANDS = ["iot hub configuration create", "iot edge deployment create"]
CONTENT_FILES = {
    "device": "test_adm_device_content.json",
    "module": "test_adm_module_content.json",
    "edge": "test_edge_deployment.json",
    "layered": "test_edge_deployment_layered.json",
    "state-setup": "test_adm_device_content.json",
}


@pytest.fixture(scope="module")
def configuration_parser():
    cli_ctx = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli_ctx.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    loader.command_table = {name: loader.command_table[name] for name in CREATE_COMMANDS}
    cli_ctx.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    for name in CREATE_COMMANDS:
        loader.load_arguments(name)
        AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli_ctx)
    parser.load_command_table(loader)
    return parser


@pytest.fixture(params=["Bearer unit-token", "SharedAccessSignature offline"], ids=["oauth", "sas"])
def configuration_client(mocker, request):
    credential = AzureKeyCredential(request.param)
    transport = RecordingTransport()
    sdk = IotHubGatewayServiceAPIs(
        credential, endpoint=ENDPOINT, transport=transport,
        authentication_policy=HubAuthenticationPolicy(credential, ENDPOINT),
    )
    client = HubClient(sdk, ["configuration"])
    mocker.patch.object(hub.SdkResolver, "get_sdk", return_value=client)
    discovery = mocker.patch.object(hub, "IotHubDiscovery").return_value
    discovery.get_target.return_value = {"entity": "hub.unit.invalid"}
    yield client, transport, credential.key
    client.close()


def _assert_request(transport, authorization, expected, if_match=None):
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.method == "PUT"
    assert urlsplit(request.url)._replace(query="").geturl() == ENDPOINT + "/configurations/config"
    assert parse_qs(urlsplit(request.url).query) == {"api-version": [API]}
    assert request.headers["Content-Type"] == "application/json; charset=utf-8"
    assert request.headers["Authorization"] == authorization
    assert request.headers.get("If-Match") == if_match
    assert "If-None-Match" not in request.headers
    body = json.loads(request.body)
    assert body == expected
    if "priority" in body:
        assert type(body["priority"]) is int


@pytest.mark.parametrize("scenario", CONTENT_FILES)
@pytest.mark.parametrize("priority", ["7", "0", None], ids=["explicit", "zero", "default"])
@pytest.mark.parametrize("status", [200, 201, 400])
def test_parsed_configuration_create_wire(
    mocker, configuration_parser, configuration_client, scenario, priority, status,
):
    """Include the live configuration/deployment and state-setup command inputs."""
    _, transport, authorization = configuration_client
    edge = scenario in ("edge", "layered")
    command = CREATE_COMMANDS[1 if edge else 0]
    content = json.loads((SAMPLES / CONTENT_FILES[scenario]).read_text())
    condition = "tags.bar=12" if scenario == "state-setup" else "tags.building=9 and tags.environment='test'"
    if scenario == "module":
        condition = "from devices.modules where tags.building=9"
    flags = [
        "--deployment-id" if edge else "--config-id", "CONFIG", "--hub-name", "hub",
        "--content", json.dumps(content), "--target-condition", condition,
        "--labels", '{"key0":"value0"}',
    ]
    if priority is not None:
        flags += ["--priority", priority]
    if scenario == "layered":
        flags += ["--layered"]
    metrics = {}
    if scenario == "state-setup":
        flags += ["--metrics", str(SAMPLES / "test_config_generic_metrics.json")]
        metrics = json.loads((SAMPLES / "test_config_generic_metrics.json").read_text())["metrics"]
    namespace = configuration_parser.parse_args(command.split() + flags)
    # The CLI historically passes explicit priorities as strings to the SDK serializer.
    assert namespace.priority == (priority if priority is not None else 0)
    operation = hub.iot_edge_deployment_create if edge else hub.iot_hub_configuration_create
    arguments = {
        name: getattr(namespace, name) for name in inspect.signature(operation).parameters
        if name != "cmd" and hasattr(namespace, name)
    }
    expected = {
        "id": "config", "schemaVersion": "2.0", "labels": {"key0": "value0"},
        # The sample's sibling $schema annotation is not a modeled content property.
        "content": {key: value for key, value in content["content"].items() if key != "$schema"},
        "metrics": metrics, "targetCondition": condition,
        "etag": "*", "priority": int(priority) if priority is not None else 0,
    }
    error = {"Message": "ErrorCode:ArgumentInvalid;BadRequest", "ExceptionMessage": "Tracking ID:offline-config"}
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/configurations/config", json=error if status == 400 else expected, status=status)
        if status == 400:
            with pytest.raises(BadRequestError, match="ArgumentInvalid") as observed:
                operation(cmd=mocker.Mock(), **arguments)
            assert "offline-config" in str(observed.value)
        else:
            assert operation(cmd=mocker.Mock(), **arguments) == expected
        _assert_request(transport, authorization, expected)
        assert len(network.calls) == 1


@pytest.mark.parametrize("priority", ["12", 12, "0", 0, None])
@pytest.mark.parametrize("etag", [None, "current-etag"])
def test_configuration_update_wire_keeps_nulls_and_if_match(mocker, configuration_client, priority, etag):
    _, transport, authorization = configuration_client
    parameters = {
        "id": "config", "schemaVersion": "2.0", "priority": priority, "targetCondition": "tags.site='a'",
        "labels": {"remove": None, "priority": "user-string"},
        "content": {
            "deviceContent": {"properties.desired": {"remove": None, "priority": "user-string", "etag": "*"}},
            "moduleContent": None,
        },
        "metrics": {"queries": {"count": "select count() from devices", "remove": None}, "results": None},
    }
    original = deepcopy(parameters)
    expected = deepcopy(parameters)
    del expected["content"]["moduleContent"]
    del expected["metrics"]["results"]
    if priority is None:
        del expected["priority"]
    else:
        expected["priority"] = int(priority)
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/configurations/config", json=expected)
        assert hub.iot_hub_configuration_update(
            cmd=mocker.Mock(), config_id="config", parameters=parameters, etag=etag,
        ) == expected
        _assert_request(transport, authorization, expected, if_match=f'"{etag or "*"}"')
    assert parameters == original


@pytest.mark.parametrize("priority", ["7", 7])
@pytest.mark.parametrize("scenario", ["device", "module", "edge", "layered"])
def test_state_configuration_restore_uses_real_builder(configuration_client, priority, scenario):
    _, transport, authorization = configuration_client
    content = json.loads((SAMPLES / CONTENT_FILES[scenario]).read_text())["content"]
    content.pop("$schema", None)
    condition = "from devices.modules where tags.site='a'" if scenario == "module" else "tags.site='a'"
    snapshot = {
        "id": "config", "content": content, "priority": priority, "targetCondition": condition,
        "labels": {"site": "a"}, "metrics": {"queries": {"count": "select count() from devices"}},
    }
    group = "edgeDeployments" if scenario in ("edge", "layered") else "admConfigurations"
    configurations = {"admConfigurations": {}, "edgeDeployments": {}}
    configurations[group]["config"] = snapshot
    original = deepcopy(configurations)
    provider = StateProvider.__new__(StateProvider)
    provider.target = {"entity": "hub.unit.invalid"}
    expected = dict(snapshot, schemaVersion="2.0", priority=7, etag="*")
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/configurations/config", json=expected)
        provider.upload_hub_from_dict({"configurations": configurations}, [HubAspects.Configurations.value])
        _assert_request(transport, authorization, expected)
    assert configurations == original


@pytest.mark.parametrize("priority", ["not-an-integer", "1.5", {}, []])
@pytest.mark.parametrize("caller", ["create", "update", "positional-adapter"])
def test_invalid_priority_fails_before_transport(mocker, configuration_client, priority, caller):
    client, transport, _ = configuration_client
    with pytest.raises(SerializationError):
        if caller == "create":
            hub._iot_hub_configuration_create(
                {"entity": "hub.unit.invalid"}, "config", '{"deviceContent":{}}', priority=priority,
            )
        elif caller == "update":
            hub.iot_hub_configuration_update(
                cmd=mocker.Mock(), config_id="config", parameters={
                    "id": "config", "schemaVersion": "2.0", "labels": {}, "content": {"deviceContent": {}},
                    "metrics": {"queries": {}}, "targetCondition": "", "priority": priority,
                },
            )
        else:
            client.configuration.create_or_update("config", {"priority": priority})
    assert not transport.requests


def test_configuration_projection_does_not_coerce_user_dictionary_values(configuration_client):
    client, transport, authorization = configuration_client
    snapshot = {
        "id": "config", "priority": "7", "schemaVersion": "2.0", "etag": "body-etag",
        "content": {"modulesContent": {"module": {"properties.desired": {
            "priority": "007", "status": None, "etag": None, "reported": {"remove": None},
        }}}},
        "metrics": {"queries": {"remove": None}, "results": {"count": 0}},
        "systemMetrics": {"results": {"count": 1}},
        "labels": {"priority": "007", "remove": None},
    }
    original = deepcopy(snapshot)
    expected = dict(snapshot, priority=7)
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/configurations/config", json=expected)
        assert client.configuration.create_or_update("config", snapshot, if_match='"header-etag"') == expected
        _assert_request(transport, authorization, expected, if_match='"header-etag"')
    assert snapshot == original
