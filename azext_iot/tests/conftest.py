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
from azext_iot.common.shared import DeviceAuthApiType

# Patch paths
path_get_device = "azext_iot.operations.hub._iot_device_show"
path_iot_hub_service_factory = "azext_iot._factory.iot_hub_service_factory"
path_service_client = "msrest.service_client.ServiceClient.send"
path_ghcs = "azext_iot.iothub.providers.discovery.IotHubDiscovery.get_target"
path_discovery_init = (
    "azext_iot.iothub.providers.discovery.IotHubDiscovery._initialize_client"
)
path_sas = "azext_iot._factory.SasTokenAuthentication"
path_mqtt_device_client_cs = (
    "azure.iot.device.IoTHubDeviceClient.create_from_connection_string"
)
path_mqtt_device_client_x509 = (
    "azure.iot.device.IoTHubDeviceClient.create_from_x509_certificate"
)
path_iot_hub_monitor_events_entrypoint = (
    "azext_iot.operations.hub._iot_hub_monitor_events"
)
path_iot_device_show = "azext_iot.operations.hub._iot_device_show"
path_device_messaging_iot_device_show = (
    "azext_iot.iothub.providers.device_messaging._iot_device_show"
)
path_update_device_twin = "azext_iot.operations.hub._iot_device_twin_update"
hub_entity = "myhub.azure-devices.net"
path_iot_service_provisioning_factory = (
    "azext_iot._factory.iot_service_provisioning_factory"
)
path_gdcs = "azext_iot.dps.providers.discovery.DPSDiscovery.get_target"
path_discovery_dps_init = (
    "azext_iot.dps.providers.discovery.DPSDiscovery._initialize_client"
)

instance_name = generate_generic_id()
hostname = "{}.subdomain.domain".format(instance_name)

# Mock Iot Hub Target
mock_target = {}
mock_target["entity"] = hub_entity
mock_target["primarykey"] = "rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["secondarykey"] = "aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_target["policy"] = "iothubowner"
mock_target["subscription"] = "5952cff8-bcd1-4235-9554-af2c0348bf23"
mock_target["location"] = "westus2"
mock_target["sku_tier"] = "Standard"
mock_target["resourcegroup"] = "myresourcegroup"

# Mock Iot DPS Target
mock_dps_target = {}
mock_dps_target["cs"] = "HostName=mydps;SharedAccessKeyName=name;SharedAccessKey=value"
mock_dps_target["entity"] = "mydps"
mock_dps_target["primarykey"] = "rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_dps_target["secondarykey"] = "aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo="
mock_dps_target["policy"] = "provisioningserviceowner"
mock_dps_target["subscription"] = "5952cff8-bcd1-4235-9554-af2c0348bf23"

mock_symmetric_key_attestation = {
    "type": "symmetricKey",
    "symmetricKey": {"primaryKey": "primary_key", "secondaryKey": "secondary_key"},
}

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
def fixture_device(mocker):
    get_device = mocker.patch(path_get_device)
    get_device.return_value = {
        "deviceId": "Test_Device_1",
        "generationId": "637534345627501371",
        "etag": "ODgxNTgwOA==",
        "connectionState": "Connected",
        "status": "enabled",
        "statusReason": None,
        "connectionStateUpdatedTime": "2021-05-12T08:48:08.7205939Z",
        "statusUpdatedTime": "0001-01-01T00:00:00Z",
        "lastActivityTime": "2021-05-12T08:48:07.6903807Z",
        "cloudToDeviceMessageCount": 0,
        "authentication": {
            "symmetricKey": {"primaryKey": "TestKey1", "secondaryKey": "TestKey2"},
            "x509Thumbprint": {"primaryThumbprint": None, "secondaryThumbprint": None},
            "type": "sas",
        },
        "capabilities": {"iotEdge": False},
        "hub": "test-iot-hub.azure-devices.net",
    }
    return get_device


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
def mqttclient_cs(mocker, fixture_ghcs, fixture_sas):
    client = mocker.patch(path_mqtt_device_client_cs)
    return client


@pytest.fixture()
def mqttclient_x509(mocker, fixture_ghcs, fixture_sas):
    client = mocker.patch(path_mqtt_device_client_x509)
    return client


@pytest.fixture()
def mqttclient_generic_error(mocker, fixture_ghcs, fixture_sas):
    MQTTProvider = mocker.patch(path_mqtt_device_client_cs)
    MQTTProvider().connect.side_effect = Exception("something happened")
    return MQTTProvider


@pytest.fixture()
def fixture_monitor_events_entrypoint(mocker):
    return mocker.patch(path_iot_hub_monitor_events_entrypoint)


@pytest.fixture()
def fixture_update_device_twin(mocker):
    return mocker.patch(path_update_device_twin)


@pytest.fixture()
def fixture_iot_device_show_sas(mocker):
    device = mocker.patch(path_iot_device_show)
    device.return_value = {
        "authentication": {
            "symmetricKey": {"primaryKey": "test_pk", "secondaryKey": "test_sk"},
            "type": DeviceAuthApiType.sas.value,
            "x509Thumbprint": {"primaryThumbprint": None, "secondaryThumbprint": None},
        },
        "capabilities": {"iotEdge": False},
        "cloudToDeviceMessageCount": 0,
        "connectionState": "Disconnected",
        "connectionStateUpdatedTime": "2021-05-27T00:36:11.2861732Z",
        "deviceId": "Test_Device_1",
        "etag": "ODgxNTgwOA==",
        "generationId": "637534345627501371",
        "hub": "test-iot-hub.azure-devices.net",
        "lastActivityTime": "2021-05-27T00:18:16.3154299Z",
        "status": "enabled",
        "statusReason": None,
        "statusUpdatedTime": "0001-01-01T00:00:00Z",
    }
    return device


@pytest.fixture()
def fixture_device_messaging_iot_device_show_sas(mocker):
    device = mocker.patch(path_device_messaging_iot_device_show)
    device.return_value = {
        "authentication": {
            "symmetricKey": {"primaryKey": "test_pk", "secondaryKey": "test_sk"},
            "type": DeviceAuthApiType.sas.value,
            "x509Thumbprint": {"primaryThumbprint": None, "secondaryThumbprint": None},
        },
        "capabilities": {"iotEdge": False},
        "cloudToDeviceMessageCount": 0,
        "connectionState": "Disconnected",
        "connectionStateUpdatedTime": "2021-05-27T00:36:11.2861732Z",
        "deviceId": "Test_Device_1",
        "etag": "ODgxNTgwOA==",
        "generationId": "637534345627501371",
        "hub": "test-iot-hub.azure-devices.net",
        "lastActivityTime": "2021-05-27T00:18:16.3154299Z",
        "status": "enabled",
        "statusReason": None,
        "statusUpdatedTime": "0001-01-01T00:00:00Z",
    }
    return device


# TODO: To be deprecated asap. Leverage mocked_response fixture for this functionality.
def build_mock_response(
    mocker=None, status_code=200, payload=None, headers=None, **kwargs
):
    try:
        from unittest.mock import MagicMock
    except ImportError:
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


""" TODO: Possibly expand for future use
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
"""


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
    from azext_iot.sdk.digitaltwins.controlplane import (
        AzureDigitalTwinsManagementClient,
    )
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
        base_url="https://{}/".format(hostname),
    )

    return control_plane_patch, data_plane_patch


def pytest_addoption(parser):
    parser.addoption("--api-version", action="store", default=None)


# DPS Fixtures
@pytest.fixture()
def fixture_gdcs(mocker):
    gdcs = mocker.patch(path_gdcs)
    gdcs.return_value = mock_dps_target
    mocker.patch(path_iot_service_provisioning_factory)
    mocker.patch(path_discovery_dps_init)

    return gdcs


@pytest.fixture()
def fixture_dps_sas(mocker):
    r = SasTokenAuthentication(
        mock_dps_target["entity"],
        mock_dps_target["policy"],
        mock_dps_target["primarykey"],
    )
    sas = mocker.patch(path_sas)
    sas.return_value = r


@pytest.fixture
def patch_certificate_open(mocker):
    patch = mocker.patch("azext_iot.operations.dps.open_certificate")
    patch.return_value = ""
    return patch


@pytest.fixture
def patch_create_edge_root_cert(mocker):
    patch = mocker.patch(
        "azext_iot.iothub.providers.helpers.edge_device_config.create_self_signed_certificate",
    )
    patch.return_value = {
        "certificate": "root_certificate",
        "privateKey": "root_private_key",
        "thumbprint": "root_thumbprint",
    }
    return patch
