# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
import json
import os

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azure.cli.core.commands import AzCliCommand
from azure.cli.core.mock import DummyCli

path_iot_hub_service_factory = "azext_iot.common._azure.iot_hub_service_factory"
path_service_client = "msrest.service_client.ServiceClient.send"
path_ghcs = "azext_iot.operations.hub.get_iot_hub_connection_string"
path_sas = "azext_iot._factory.SasTokenAuthentication"
path_mqtt_client = "azext_iot.operations._mqtt.mqtt.Client"
path_iot_hub_monitor_events_entrypoint = (
    "azext_iot.operations.hub._iot_hub_monitor_events"
)
hub_entity = "myhub.azure-devices.net"

mock_target = {}
mock_target["entity"] = hub_entity
mock_target["primarykey"] = "rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["secondarykey"] = "aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["policy"] = "iothubowner"
mock_target["subscription"] = "5952cff8-bcd1-4235-9554-af2c0348bf23"
mock_target["location"] = "westus2"
mock_target["sku_tier"] = "Standard"
mock_target["resourcegroup"] = "myresourcegroup"


generic_cs_template = "HostName={};SharedAccessKeyName={};SharedAccessKey={}"


def generate_cs(
    hub=hub_entity,
    policy=mock_target["policy"],
    key=mock_target["primarykey"],
    lower_case=False,
):
    result = generic_cs_template.format(hub, policy, key)
    return result.lower() if lower_case else result


@pytest.fixture()
def fixture_cmd2(mocker):
    cli = DummyCli()
    cli.loader = mocker.MagicMock()
    cli.loader.cli_ctx = cli

    def test_handler1():
        pass

    return AzCliCommand(cli.loader, 'iot-extension command', test_handler1)


# Sets current working directory to the directory of the executing file
@pytest.fixture()
def set_cwd(request):
    os.chdir(os.path.dirname(os.path.abspath(str(request.fspath))))


@pytest.fixture()
def fixture_cmd(mocker):
    # Placeholder for later use
    mocker.patch(path_iot_hub_service_factory)
    cmd = mocker.MagicMock(name="cli cmd context")
    return cmd


@pytest.fixture()
def fixture_events_uamqp_sendclient(mocker):
    from azext_iot.operations.events3._events import uamqp
    return mocker.patch.object(uamqp, "SendClient", autospec=True)


@pytest.fixture()
def fixture_service_client_generic(mocker, fixture_ghcs, fixture_sas):
    service_client = mocker.patch(path_service_client)
    return service_client


@pytest.fixture(params=[400, 401, 500])
def serviceclient_generic_error(mocker, fixture_ghcs, fixture_sas, request):
    service_client = mocker.patch(path_service_client)
    service_client.return_value = build_mock_response(
        mocker, request.param, {"error": "something failed"}
    )
    return service_client


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker.patch(path_ghcs)
    ghcs.return_value = mock_target
    return ghcs


@pytest.fixture()
def fixture_sas(mocker):
    r = SasTokenAuthentication(
        mock_target["entity"], mock_target["policy"], mock_target["primarykey"]
    )
    sas = mocker.patch(path_sas)
    sas.return_value = r
    return sas


@pytest.fixture(params=[{"etag": None}, {}])
def serviceclient_generic_invalid_or_missing_etag(
    mocker, fixture_ghcs, fixture_sas, request
):
    service_client = mocker.patch(path_service_client)
    service_client.return_value = build_mock_response(mocker, 200, request.param)
    return service_client


@pytest.fixture()
def mqttclient(mocker, fixture_ghcs, fixture_sas):
    client = mocker.patch(path_mqtt_client)
    mock_conn = mocker.patch("azext_iot.operations._mqtt.mqtt_client_wrap.is_connected")
    mock_conn.return_value = True
    return client


@pytest.fixture()
def mqttclient_generic_error(mocker, fixture_ghcs, fixture_sas):
    mqtt_client = mocker.patch(path_mqtt_client)
    mqtt_client().connect.side_effect = Exception("something happened")
    return mqtt_client


@pytest.fixture()
def fixture_monitor_events_entrypoint(mocker):
    return mocker.patch(path_iot_hub_monitor_events_entrypoint)


def build_mock_response(mocker, status_code=200, payload=None, headers=None, raw=False):
    response = mocker.MagicMock(name="response")
    response.status_code = status_code
    del response.context
    del response._attribute_map

    if raw:
        response.text = payload
    else:
        response.text.return_value = json.dumps(payload)

    if headers:
        response.headers = headers
    return response


def get_context_path(base_path, *paths):
    base_path = os.path.dirname(os.path.abspath(base_path))
    if paths:
        return os.path.join(base_path, *paths)

    return base_path
