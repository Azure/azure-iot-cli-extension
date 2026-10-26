# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.common._azure import parse_iot_hub_connection_string
from azext_iot.common.shared import AuthenticationTypeDataplane


@pytest.fixture
def get_mgmt_client(mocker, fixture_cmd):
    patched_get_raw_token = mocker.patch(
        "azure.cli.core._profile.Profile.get_raw_token"
    )
    patched_get_raw_token.return_value = (
        mocker.MagicMock(name="creds"),
        mocker.MagicMock(name="subscription"),
        mocker.MagicMock(name="tenant"),
    )
    patch = mocker.patch("azext_iot._factory.iot_hub_service_factory")
    patch.return_value = None

    return patch


class TestIoTHubDiscovery:
    @pytest.mark.parametrize("disable_local_auth", [True, False, None])
    @pytest.mark.parametrize("monitor_events", [True, False])
    @pytest.mark.parametrize("auth_type", ["key", "login"])
    def test_local_auth_check_only_for_event_monitoring(
        self, mocker, fixture_cmd, disable_local_auth, monitor_events, auth_type
    ):
        discovery = IotHubDiscovery(cmd=fixture_cmd)
        resource = {
            "name": "myhub",
            "properties": {
                "hostName": "myhub.azure-devices.net",
                "disableLocalAuth": disable_local_auth,
                "eventHubEndpoints": {
                    "events": {
                        "endpoint": "sb://events.servicebus.windows.net/",
                        "path": "myhub",
                        "partitionCount": 2,
                        "partitionIds": ["0", "1"],
                    }
                },
            },
            "resourcegroup": "myrg",
            "location": "eastus",
            "sku": {"tier": "Standard"},
        }
        mocker.patch.object(discovery, "find_resource", return_value=resource)
        find_policy = mocker.patch.object(
            discovery, "find_policy",
            return_value={"keyName": "iothubowner", "primaryKey": "primary", "secondaryKey": "secondary"},
        )
        target_args = {
            "resource_name": "myhub",
            "resource_group_name": "myrg",
            "auth_type": auth_type,
            "include_events": True,
            "monitor_events": monitor_events,
        }

        if monitor_events and disable_local_auth is True:
            with pytest.raises(InvalidArgumentValueError, match="disableLocalAuth=true"):
                discovery.get_target(**target_args)
            find_policy.assert_not_called()
            return

        target = discovery.get_target(**target_args)
        assert target["entity"] == "myhub.azure-devices.net"
        assert target["events"]["partition_ids"] == ["0", "1"]

    def test_get_target_by_cstring(self, fixture_cmd, get_mgmt_client):
        discovery = IotHubDiscovery(cmd=fixture_cmd)

        fake_login = (
            "HostName=CoolIoTHub.azure-devices.net;SharedAccessKeyName=iothubowner;"
            "SharedAccessKey=AB+c/+5nm2XpDXcffhnGhnxz/TVF4m5ag7AuVIGwchj="
        )
        parsed_fake_login = parse_iot_hub_connection_string(fake_login)

        target = discovery.get_target(
            resource_name=None, resource_group_name=None, login=fake_login
        )

        # Ensure no ARM calls are made
        assert get_mgmt_client.call_count == 0

        assert target["cs"] == fake_login
        assert target["entity"] == parsed_fake_login["HostName"]
        assert target["policy"] == parsed_fake_login["SharedAccessKeyName"]
        assert target["primarykey"] == parsed_fake_login["SharedAccessKey"]

        target = discovery.get_target_by_cstring(fake_login)

        # Ensure no ARM calls are made
        assert get_mgmt_client.call_count == 0

        assert target["cs"] == fake_login
        assert target["entity"] == parsed_fake_login["HostName"]
        assert target["policy"] == parsed_fake_login["SharedAccessKeyName"]
        assert target["primarykey"] == parsed_fake_login["SharedAccessKey"]

    def test_get_target_by_hostname(self, fixture_cmd, get_mgmt_client):
        discovery = IotHubDiscovery(cmd=fixture_cmd)

        fake_name = "COOLIoTHub"
        fake_hostname = f"{fake_name}.azure-devices-provisioning.net"
        fake_rg = "COOLRG"

        target = discovery.get_target(
            resource_name=fake_hostname,
            resource_group_name=fake_rg,
            auth_type=AuthenticationTypeDataplane.login.value
        )

        # Ensure no ARM calls are made
        assert get_mgmt_client.call_count == 0

        assert target["entity"] == fake_hostname
        assert target["name"] == fake_name
        assert target["policy"] == AuthenticationTypeDataplane.login.value
        assert target["primarykey"] == AuthenticationTypeDataplane.login.value
        assert target["secondarykey"] == AuthenticationTypeDataplane.login.value
        assert target["cmd"] == fixture_cmd

        target = discovery.get_target(
            resource_name=fake_hostname,
            resource_group_name=None,
            auth_type=AuthenticationTypeDataplane.login.value
        )

        # Ensure no ARM calls are made
        assert get_mgmt_client.call_count == 0

        assert AuthenticationTypeDataplane.login.value in target["cs"]
        assert target["entity"] == fake_hostname
        assert target["name"] == fake_name
        assert target["policy"] == AuthenticationTypeDataplane.login.value
        assert target["primarykey"] == AuthenticationTypeDataplane.login.value
        assert target["secondarykey"] == AuthenticationTypeDataplane.login.value
        assert target["cmd"] == fixture_cmd

    def test_get_target_by_eh_connection_string(self, fixture_cmd, get_mgmt_client):
        """An Event Hub connection string passed as --login is parsed directly without ARM."""
        discovery = IotHubDiscovery(cmd=fixture_cmd)

        fake_eh_cs = (
            "Endpoint=sb://cooliothub.servicebus.windows.net/;"
            "SharedAccessKeyName=iothubowner;"
            "SharedAccessKey=AB+c/+5nm2XpDXcffhnGhnxz/TVF4m5ag7AuVIGwchj=;"
            "EntityPath=cooliothub"
        )

        target = discovery.get_target(
            resource_name=None, resource_group_name=None, login=fake_eh_cs
        )

        # Ensure no ARM calls are made
        assert get_mgmt_client.call_count == 0

        assert target["cs"] == fake_eh_cs
        assert target["entity"] == "eventhub"
        assert target["name"] == "eventhub"
        assert target["policy"] == ""
        assert target["primarykey"] == ""
        # Endpoint resolution is deferred to EventTargetBuilder — no 'events' key here
        assert "events" not in target
