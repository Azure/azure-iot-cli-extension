# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from urllib.parse import parse_qs

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.operations.hub import _iot_build_sas_token_from_cs


@pytest.mark.parametrize("casing", [str, str.lower, str.upper, str.swapcase])
@pytest.mark.parametrize("scope", ["hub", "device", "module"])
def test_offline_sas_connection_string_names_are_case_insensitive(mocker, casing, scope):
    discovery = mocker.patch.object(IotHubDiscovery, "get_target")
    parts = {"HostName": "MyHub.azure-devices.net", "SharedAccessKey": "VGVzdEtleQ=="}
    uri = parts["HostName"]
    if scope == "hub":
        parts["SharedAccessKeyName"] = "MyPolicy"
    else:
        parts["DeviceId"] = "MyDevice"
        uri += "/devices/MyDevice"
        if scope == "module":
            parts["ModuleId"] = "MyModule"
            uri += "/modules/MyModule"
    connection_string = ";".join(f"{casing(key)}={value}" for key, value in parts.items())
    token = _iot_build_sas_token_from_cs(connection_string, duration=1234)
    assert token.uri == uri
    assert token.key == parts["SharedAccessKey"]
    assert token.policy == parts.get("SharedAccessKeyName")
    assert token.expiry == 1234
    assert parse_qs(token.generate_sas_token(absolute=True).split(" ", 1)[1])["sr"] == [uri]
    discovery.assert_not_called()


@pytest.mark.parametrize("connection_string", [
    "hostname=hub;deviceid=device",
    "hostname=hub;sharedaccesskey=VGVzdEtleQ==",
    "hostname=hub;moduleid=module;sharedaccesskey=VGVzdEtleQ==",
])
def test_offline_sas_missing_required_properties_still_fails(connection_string):
    with pytest.raises(InvalidArgumentValueError, match="not in a supported format"):
        _iot_build_sas_token_from_cs(connection_string)


@pytest.mark.parametrize("prefix", ["", "https://", "HTTP://"])
@pytest.mark.parametrize("rg_keyword", ["resource_group_name", "rg"])
def test_classic_fqdn_with_explicit_rg_resolves_arm_metadata(mocker, prefix, rg_keyword):
    discovery = IotHubDiscovery(mocker.Mock())
    resource = {
        "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/MyHub",
        "name": "MyHub", "resourcegroup": "rg", "location": "centraluseuap", "sku": {"tier": "Standard"},
        "properties": {
            "hostName": "MyHub.azure-devices.net",
            "serviceHostName": "MyHub.service.azure-devices.net",
            "deviceHostName": "MyHub.device.azure-devices.net",
            "iotHubDetails": {"gatewayVersion": "v2"},
        },
    }
    find = mocker.patch.object(discovery, "find_resource", return_value=resource)
    policies = mocker.patch.object(discovery, "find_policy")
    target = discovery.get_target(
        f"{prefix}MyHub.azure-devices.net", auth_type="login", **{rg_keyword: "rg"}
    )
    find.assert_called_once_with(resource_name="MyHub", rg="rg")
    policies.assert_not_called()
    assert target["deviceHostName"] == resource["properties"]["deviceHostName"]
    assert target["serviceHostName"] == resource["properties"]["serviceHostName"]
    assert target["policy"] == "login"


@pytest.mark.parametrize("hostname,rg", [
    ("MyHub.azure-devices.net", None),
    ("MyHub.service.azure-devices.net", None),
    ("MyHub.service.azure-devices.net", "rg"),
    ("MyHub.device.azure-devices.net", "rg"),
])
def test_unscoped_or_split_fqdn_login_remains_arm_free(mocker, hostname, rg):
    discovery = IotHubDiscovery(mocker.Mock())
    find = mocker.patch.object(discovery, "find_resource")
    target = discovery.get_target(hostname, resource_group_name=rg, auth_type="login")
    find.assert_not_called()
    assert target["entity"] == hostname


def test_connection_string_override_remains_arm_free_even_with_rg(mocker):
    discovery = IotHubDiscovery(mocker.Mock())
    find = mocker.patch.object(discovery, "find_resource")
    connection_string = "HostName=MyHub.azure-devices.net;SharedAccessKeyName=policy;SharedAccessKey=VGVzdEtleQ=="
    target = discovery.get_target("MyHub.azure-devices.net", "rg", login=connection_string, auth_type="login")
    find.assert_not_called()
    assert target["cs"] == connection_string
