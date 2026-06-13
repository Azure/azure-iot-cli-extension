# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import MagicMock

import azext_iot.dps.providers.discovery as subject
from azext_iot.dps.providers.discovery import DPSDiscovery


def _disc():
    disc = DPSDiscovery.__new__(DPSDiscovery)
    disc.cmd = MagicMock()
    disc.client = None
    disc.sub_id = "sub"
    return disc


def test_init():
    disc = DPSDiscovery(cmd=MagicMock())
    assert disc.necessary_rights_set == subject.PRIVILEDGED_ACCESS_RIGHTS_SET


def test_initialize_client_with_cli_ctx(mocker):
    disc = _disc()
    factory = mocker.patch.object(subject, "iot_service_provisioning_factory")
    mocker.patch.object(subject, "get_subscription_id", return_value="sub")
    disc._initialize_client()
    assert disc.client is factory.return_value.iot_dps_resource
    assert disc.client.get_keys_for_key_name == disc.client.list_keys_for_key_name


def test_initialize_client_without_cli_ctx():
    disc = DPSDiscovery.__new__(DPSDiscovery)
    disc.client = None

    class FakeClient:
        def list_keys_for_key_name(self):
            return []

    disc.cmd = FakeClient()
    disc._initialize_client()
    assert disc.client is disc.cmd
    assert disc.client.get_keys_for_key_name == disc.client.list_keys_for_key_name


def test_make_kwargs():
    disc = _disc()
    result = disc._make_kwargs(resource_name="myDps", extra="x")
    assert result["provisioning_service_name"] == "myDps"
    assert "resource_name" not in result
    assert result["extra"] == "x"


def test_get_target_by_cstring(mocker):
    dps_target = mocker.patch.object(subject, "DPSTarget")
    dps_target.from_connection_string.return_value.as_dict.return_value = {"entity": "x"}
    result = DPSDiscovery.get_target_by_cstring("HostName=x;SharedAccessKeyName=y;SharedAccessKey=z")
    assert result == {"entity": "x"}


def test_build_target_from_hostname():
    disc = _disc()
    target = disc._build_target_from_hostname("mydps.azure-devices-provisioning.net")
    assert target["entity"] == "mydps.azure-devices-provisioning.net"
    assert target["name"] == "mydps"
    assert target["subscription"] == "sub"
    assert target["cmd"] is disc.cmd


def test_build_target():
    disc = _disc()
    resource = {"properties": {"serviceOperationsHostName": "host", "idScope": "scope"}}
    policy = {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}
    result = disc._build_target(resource, policy, key_type="primary")
    assert result["idscope"] == "scope"
    assert result["primarykey"] == "pk"
    assert result["entity"] == "host"


def test_build_target_secondary_key():
    disc = _disc()
    resource = {"properties": {"serviceOperationsHostName": "host", "idScope": "scope"}}
    policy = {"keyName": "pol", "primaryKey": "pk", "secondaryKey": "sk"}
    result = disc._build_target(resource, policy, key_type="secondary")
    assert "sk" in result["cs"]


def test_get_id_scope(mocker):
    disc = _disc()
    mocker.patch.object(disc, "find_resource", return_value={"properties": {"idScope": "scope123"}})
    assert disc.get_id_scope("mydps") == "scope123"
