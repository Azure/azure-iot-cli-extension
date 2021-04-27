# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
import responses
import pytest
import json
import os

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azure.cli.core.commands import AzCliCommand
from azure.cli.core.mock import DummyCli
from azext_iot.tests.generators import generate_generic_id

path_get_device_connection = "azext_iot.operations.hub.iot_get_device_connection_string"
path_iot_hub_service_factory = "azext_iot._factory.iot_hub_service_factory"
path_service_client = "msrest.service_client.ServiceClient.send"
path_ghcs = "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target"
path_discovery_init = (
    "azext_iot.iothub.providers.discovery.IotHubDiscovery._initialize_client"
)
path_sas = "azext_iot._factory.SasTokenAuthentication"
path_mqtt_device_client = "azext_iot.operations._mqtt.mqtt_device_client.create_from_connection_string"
path_iot_hub_monitor_events_entrypoint = (
    "azext_iot.operations.hub._iot_hub_monitor_events"
)
hub_entity = "myhub.azure-devices.net"

instance_name = generate_generic_id()
hostname = "{}.subdomain.domain".format(instance_name)

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


# Sets current working directory to the directory of the executing file
@pytest.fixture()
def set_cwd(request):
    os.chdir(os.path.dirname(os.path.abspath(str(request.fspath))))


@pytest.fixture()
def fixture_cmd(mocker):
    cli = DummyCli()
    cli.loader = mocker.MagicMock()
    cli.loader.cli_ctx = cli

    def test_handler1():
        pass

    return AzCliCommand(cli.loader, "iot-extension command", test_handler1)


@pytest.fixture()
def fixture_device_connection(mocker):
    get_connection_string = mocker.patch(path_get_device_connection)
    get_connection_string.return_value = {"connectionString": "test_device_conn_string"}
    return get_connection_string


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
    mocker.patch(path_iot_hub_service_factory)
    mocker.patch(path_discovery_init)

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
    client = mocker.patch(path_mqtt_device_client)
    return client


@pytest.fixture()
def mqttclient_generic_error(mocker, fixture_ghcs, fixture_sas):
    mqtt_client = mocker.patch(path_mqtt_device_client)
    mqtt_client().connect.side_effect = Exception("something happened")
    return mqtt_client


@pytest.fixture()
def fixture_monitor_events_entrypoint(mocker):
    return mocker.patch(path_iot_hub_monitor_events_entrypoint)


# TODO: To be deprecated asap. Leverage mocked_response fixture for this functionality.
def build_mock_response(
    mocker=None, status_code=200, payload=None, headers=None, **kwargs
):
    try:
        from unittest.mock import MagicMock
    except:
        from mock import MagicMock

    response = (
        mocker.MagicMock(name="response") if mocker else MagicMock(name="response")
    )
    response.status_code = status_code
    del response.context
    del response._attribute_map
    del response.body

    # This is a cludge. Supports {} or [] payload.
    if payload is not None:
        _payload_str = json.dumps(payload) if not isinstance(payload, str) else payload
        response.text.return_value = _payload_str
        response.text = _payload_str
        response.internal_response.json.return_value = json.loads(_payload_str)
    else:
        response.text.return_value = ""
        response.text = ""

    headers_get_side_effect = kwargs.get("headers_get_side_effect")
    if headers_get_side_effect:
        response.headers.get.side_effect = headers_get_side_effect
        response.internal_response.headers.get.side_effect = headers_get_side_effect
    else:
        response.headers = headers if headers else {}
        response.internal_response.headers = headers if headers else {}

    return response


def get_context_path(base_path, *paths):
    base_path = os.path.dirname(os.path.abspath(base_path))
    if paths:
        return os.path.join(base_path, *paths)

    return base_path


''' TODO: Possibly expand for future use
fake_oauth_response = responses.Response(
    method=responses.POST,
    url=re.compile("https://login.microsoftonline.com/(.+)/oauth2/token"),
    body=json.dumps({
        "token_type": "Bearer",
        "scope": "user_impersonation",
        "expires_in": "90000",
        "ext_expires_in": "90000",
        "expires_on": "979778250",
        "not_before": "979739250",
        "resource": "localhost",
        "access_token": "totally_fake_access_token",
        "refresh_token": "totally_fake_refresh_token",
        "foci": "1"
    }),
    status=200,
    content_type="application/json",
)
'''


@pytest.fixture
def mocked_response():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture(params=[400, 401, 500])
def service_client_generic_errors(mocked_response, fixture_ghcs, request):
    def error_callback(_):
        return (
            request.param,
            {"Content-Type": "application/json; charset=utf-8"},
            json.dumps({"error": "something failed"}),
        )

    any_endpoint = r"^https:\/\/.+"
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_callback(
            callback=error_callback, method=responses.GET, url=re.compile(any_endpoint)
        )
        rsps.add_callback(
            callback=error_callback, method=responses.PUT, url=re.compile(any_endpoint)
        )
        rsps.add_callback(
            callback=error_callback, method=responses.POST, url=re.compile(any_endpoint)
        )
        rsps.add_callback(
            callback=error_callback,
            method=responses.DELETE,
            url=re.compile(any_endpoint),
        )
        rsps.add_callback(
            callback=error_callback,
            method=responses.PATCH,
            url=re.compile(any_endpoint),
        )
        yield rsps


@pytest.fixture()
def fixture_mock_aics_token(mocker):
    patch = mocker.patch(
        "azext_iot.product.providers.auth.AICSAuthentication.generate_token"
    )
    patch.return_value = "Bearer token"
    return patch


@pytest.fixture
def fixture_dt_client(mocker, fixture_cmd):
    from azext_iot.sdk.digitaltwins.controlplane import AzureDigitalTwinsManagementClient
    from azext_iot.sdk.digitaltwins.dataplane import AzureDigitalTwinsAPI
    from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication

    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )

    control_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.digitaltwins_service_factory"
    )
    control_plane_patch.return_value = AzureDigitalTwinsManagementClient(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        subscription_id="00000000-0000-0000-0000-000000000000",
    )

    data_plane_patch = mocker.patch(
        "azext_iot.digitaltwins.providers.base.DigitalTwinsProvider.get_sdk"
    )

    data_plane_patch.return_value = AzureDigitalTwinsAPI(
        credentials=DigitalTwinAuthentication(
            fixture_cmd, "00000000-0000-0000-0000-000000000000"
        ),
        base_url="https://{}/".format(hostname)
    )

    return control_plane_patch, data_plane_patch
