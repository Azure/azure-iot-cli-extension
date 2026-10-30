# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import ForbiddenError, UnauthorizedError
from azure.core.exceptions import HttpResponseError
from azext_iot.dps.providers.discovery import DPSDiscovery
from azext_iot.common._azure import parse_iot_dps_connection_string
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
    patch = mocker.patch("azext_iot._factory.iot_service_provisioning_factory")
    patch.return_value = None

    return patch


class TestDPSDiscovery:
    @pytest.mark.parametrize("status,kind", [(401, UnauthorizedError), (403, ForbiddenError)])
    @pytest.mark.parametrize("resource_group", [None, "test-rg"])
    def test_bulk_targets_skip_translated_authorization_errors(
        self, mocker, fixture_cmd, caplog, status, kind, resource_group
    ):
        discovery = DPSDiscovery(cmd=fixture_cmd)
        resources = [
            {"name": name, "id": f"/subscriptions/sub/resourceGroups/test-rg/"
             f"providers/Microsoft.Devices/provisioningServices/{name}"}
            for name in ("accessible-first", "denied", "accessible-last")
        ]
        mocker.patch.object(discovery, "get_resources", return_value=resources)
        denied = HttpResponseError("AuthorizationFailed")
        denied.status_code = status
        first, last = {"entity": "first"}, {"entity": "last"}
        target = mocker.patch(
            "azext_iot.common.base_discovery.BaseDiscovery.get_target",
            side_effect=[first, denied, last],
        )

        assert discovery.get_targets(resource_group_name=resource_group, auth_type="key") == [first, last]
        assert target.call_count == 3
        assert "Could not access denied" in caplog.text
        assert "AuthorizationFailed" in caplog.text
        target.side_effect = denied
        with pytest.raises(kind) as raised:
            discovery.get_target("denied", "test-rg", auth_type="key")
        assert raised.value.__cause__ is denied

    @pytest.mark.parametrize("error", [UnauthorizedError("Subscription denied"), RuntimeError("Listing failed")])
    def test_bulk_targets_propagate_subscription_enumeration_errors(self, mocker, fixture_cmd, error):
        discovery = DPSDiscovery(cmd=fixture_cmd)
        mocker.patch.object(discovery, "get_resources", side_effect=error)
        with pytest.raises(type(error)) as raised:
            discovery.get_targets(auth_type="key")
        assert raised.value is error

    def test_bulk_targets_propagate_unexpected_target_errors(self, mocker, fixture_cmd):
        discovery = DPSDiscovery(cmd=fixture_cmd)
        mocker.patch.object(discovery, "get_resources", return_value=[{"name": "dps"}])
        error = RuntimeError("Unexpected target failure")
        mocker.patch("azext_iot.common.base_discovery.BaseDiscovery.get_target", side_effect=error)
        with pytest.raises(RuntimeError) as raised:
            discovery.get_targets(resource_group_name="test-rg", auth_type="key")
        assert raised.value is error

    def test_get_target_by_cstring(self, fixture_cmd, get_mgmt_client):
        discovery = DPSDiscovery(cmd=fixture_cmd)

        fake_login = (
            "HostName=COOLDPS.azure-devices-provisioning.net;"
            "SharedAccessKeyName=provisioningserviceowner;"
            "SharedAccessKey=AB+c/+5nm2XpDXcffhnGhnxz/TVF4m5ag7AuVIGwchj="
        )
        parsed_fake_login = parse_iot_dps_connection_string(fake_login)

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
        discovery = DPSDiscovery(cmd=fixture_cmd)

        fake_name = "COOLDPS"
        fake_hostname = f"{fake_name}.azure-devices-provisioning.net"
        fake_rg = "COOLRG"

        target = discovery.get_target(
            resource_name=fake_hostname,
            resource_group_name=fake_rg,
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
