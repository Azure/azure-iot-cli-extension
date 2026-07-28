# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azext_iot.core.custom import _resolve_linked_hub_hostname, _warn_mixed_endpoint_types


class TestResolveLinkedHubHostname:
    def test_device_with_tls13(self):
        hub = {"properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub, "device") == "hub.device.azure-devices.net"

    def test_device_errors_on_v1_hub(self):
        hub = {"properties": {"hostName": "hub.azure-devices.net"}, "name": "hub"}
        with pytest.raises(InvalidArgumentValueError, match="device hostname is not available"):
            _resolve_linked_hub_hostname(hub, "device")

    def test_auto_fallback_to_classic(self):
        hub = {"properties": {"hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub, "auto") == "hub.azure-devices.net"

    def test_auto_uses_device_when_available(self):
        hub = {"properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub, "auto") == "hub.device.azure-devices.net"

    def test_classic(self):
        hub = {"properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub, "classic") == "hub.azure-devices.net"

    def test_default_is_auto(self):
        hub = {"properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub) == "hub.device.azure-devices.net"
        hub_v1 = {"properties": {"hostName": "hub.azure-devices.net"}}
        assert _resolve_linked_hub_hostname(hub_v1) == "hub.azure-devices.net"


class TestLinkedHubCreateValidation:
    @pytest.fixture
    def mock_deps(self, mocker):
        mocker.patch("azext_iot.core.custom.iot_hub_service_factory")
        mocker.patch("azext_iot.core.custom.iot_hub_get", return_value={
            "properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"},
            "location": "eastus2euap",
            "resourcegroup": "test-rg",
        })
        mocker.patch("azext_iot.core.custom.iot_hub_policy_get", return_value={
            "keyName": "iothubowner", "primaryKey": "testkey"
        })
        mocker.patch("azext_iot.core.custom._ensure_dps_resource_group_name", return_value="test-rg")
        mock_dps = {
            "identity": {"type": "SystemAssigned,UserAssigned"},
            "properties": {"iotHubs": []},
        }
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value=mock_dps)
        mock_client = mocker.MagicMock()
        mock_client.iot_dps_resource.begin_create_or_update.return_value = mocker.MagicMock()
        mocker.patch("azext_iot.core.custom.LongRunningOperation")
        mocker.patch("azext_iot.core.custom.iot_dps_linked_hub_list", return_value=[])
        return mock_client

    def test_mi_requires_hub_name(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        with pytest.raises(RequiredArgumentMissingError, match="--hub-name"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                authentication_type="SystemAssigned"
            )

    def test_user_assigned_requires_identity(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        with pytest.raises(RequiredArgumentMissingError, match="--user-assigned-identity"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="hub", authentication_type="UserAssigned"
            )

    def test_service_hostname_rejected(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        with pytest.raises(InvalidArgumentValueError, match="Service hostname"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                connection_string="HostName=hub.service.azure-devices.net;SharedAccessKeyName=x;SharedAccessKey=y"
            )

    def test_mi_system_assigned_not_enabled(self, fixture_cmd, mock_deps, mocker):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": {"type": "None"},
            "properties": {"iotHubs": []},
        })
        with pytest.raises(InvalidArgumentValueError, match="System-assigned managed identity is not enabled"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned"
            )

    def test_mi_with_connection_string_rejected(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        with pytest.raises(MutuallyExclusiveArgumentError, match="--connection-string cannot be used with --authentication-type"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned",
                connection_string="HostName=hub.azure-devices.net;SharedAccessKeyName=x;SharedAccessKey=y"
            )

    def test_mi_null_identity_on_dps(self, fixture_cmd, mock_deps, mocker):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": None,
            "properties": {"iotHubs": []},
        })
        with pytest.raises(InvalidArgumentValueError, match="System-assigned managed identity is not enabled"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned"
            )


class TestMixedEndpointWarning:
    def test_no_warning_all_device(self, caplog):
        hubs = [
            {"name": "hub1.device.azure-devices.net"},
            {"name": "hub2.device.azure-devices.net"},
        ]
        _warn_mixed_endpoint_types(hubs)
        assert "mixed hostname types" not in caplog.text

    def test_no_warning_all_classic(self, caplog):
        hubs = [
            {"name": "hub1.azure-devices.net"},
            {"name": "hub2.azure-devices.net"},
        ]
        _warn_mixed_endpoint_types(hubs)
        assert "mixed hostname types" not in caplog.text

    def test_warning_on_mixed(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            hubs = [
                {"name": "hub1.device.azure-devices.net"},
                {"name": "hub2.azure-devices.net"},
            ]
            _warn_mixed_endpoint_types(hubs)
            assert "mixed hostname types" in caplog.text

    def test_warning_on_mixed_with_connection_string(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            hubs = [
                {"name": "hub1.device.azure-devices.net"},
                {"connectionString": "HostName=hub2.azure-devices.net;SharedAccessKeyName=x;SharedAccessKey=y"},
            ]
            _warn_mixed_endpoint_types(hubs)
            assert "mixed hostname types" in caplog.text

    def test_no_warning_single_hub(self, caplog):
        hubs = [{"name": "hub1.device.azure-devices.net"}]
        _warn_mixed_endpoint_types(hubs)
        assert "mixed hostname types" not in caplog.text

    def test_no_warning_empty(self, caplog):
        _warn_mixed_endpoint_types([])
        assert "mixed hostname types" not in caplog.text


class TestFindLinkedHubEntry:
    HUBS_GWV2 = [{"name": "myhub.device.azure-devices.net", "authenticationType": "SystemAssigned"}]
    HUBS_CLASSIC = [{"name": "myhub.azure-devices.net", "authenticationType": "KeyBased"}]
    HUBS_DUPLICATE = [
        {"name": "myhub.device.azure-devices.net"},
        {"name": "myhub.azure-devices.net"},
        {"name": "other.azure-devices.net"},
    ]

    def test_hub_name_matches_gwv2_entry(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        result = _find_linked_hub_entry(self.HUBS_GWV2, hub_name="myhub")
        assert result["name"] == "myhub.device.azure-devices.net"

    def test_hub_name_matches_classic_entry(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        result = _find_linked_hub_entry(self.HUBS_CLASSIC, hub_name="myhub")
        assert result["name"] == "myhub.azure-devices.net"

    def test_hub_name_not_found(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        with pytest.raises(ResourceNotFoundError, match="No linked hub found"):
            _find_linked_hub_entry(self.HUBS_GWV2, hub_name="missing")

    def test_hub_name_duplicate_errors_with_hint(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        with pytest.raises(InvalidArgumentValueError, match="Multiple linked-hub entries"):
            _find_linked_hub_entry(self.HUBS_DUPLICATE, hub_name="myhub")

    def test_hub_name_prefix_does_not_overmatch(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        hubs = [{"name": "myhub2.azure-devices.net"}]
        with pytest.raises(ResourceNotFoundError, match="No linked hub found"):
            _find_linked_hub_entry(hubs, hub_name="myhub")

    def test_linked_hub_exact_match(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        result = _find_linked_hub_entry(
            self.HUBS_DUPLICATE, linked_hub="myhub.device.azure-devices.net")
        assert result["name"] == "myhub.device.azure-devices.net"

    def test_linked_hub_case_insensitive(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        result = _find_linked_hub_entry(
            self.HUBS_GWV2, linked_hub="MYHUB.DEVICE.AZURE-DEVICES.NET")
        assert result["name"] == "myhub.device.azure-devices.net"

    def test_linked_hub_not_found(self):
        from azext_iot.core.custom import _find_linked_hub_entry
        with pytest.raises(ResourceNotFoundError, match="does not exist"):
            _find_linked_hub_entry(self.HUBS_GWV2, linked_hub="ghost.azure-devices.net")


class TestLinkedHubUpdate:
    @pytest.fixture
    def existing_entries(self):
        return [
            {
                "name": "myhub.azure-devices.net",
                "hostName": "myhub.azure-devices.net",
                "authenticationType": "KeyBased",
                "connectionString": (
                    "HostName=myhub.azure-devices.net;"
                    "SharedAccessKeyName=iothubowner;SharedAccessKey=existing-key"
                ),
                "location": "eastus2euap",
                "allocationWeight": 1,
                "applyAllocationPolicy": True,
            }
        ]

    @pytest.fixture
    def mock_deps(self, mocker, existing_entries):
        mocker.patch("azext_iot.core.custom.iot_hub_service_factory")
        mocker.patch("azext_iot.core.custom.iot_hub_get", return_value={
            "name": "myhub",
            "properties": {
                "deviceHostName": "myhub.device.azure-devices.net",
                "hostName": "myhub.azure-devices.net",
            },
            "location": "eastus2euap",
            "resourcegroup": "test-rg",
        })
        mocker.patch("azext_iot.core.custom.iot_hub_policy_get", return_value={
            "keyName": "iothubowner", "primaryKey": "fresh-key"
        })
        mocker.patch("azext_iot.core.custom._ensure_dps_resource_group_name", return_value="test-rg")
        mock_dps = {
            "identity": {"type": "SystemAssigned,UserAssigned"},
            "properties": {"iotHubs": existing_entries},
        }
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value=mock_dps)
        mocker.patch("azext_iot.core.custom.LongRunningOperation")
        mocker.patch("azext_iot.core.custom.iot_dps_linked_hub_get", side_effect=lambda *a, **kw: existing_entries[0])
        mock_client = mocker.MagicMock()
        mock_client.iot_dps_resource.begin_create_or_update.return_value = mocker.MagicMock()
        return mock_client

    def test_requires_identifier(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(RequiredArgumentMissingError, match="--hub-name"):
            iot_dps_linked_hub_update(cmd=fixture_cmd, client=mock_deps, dps_name="dps")

    def test_rejects_both_identifiers(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(MutuallyExclusiveArgumentError, match="not both"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", linked_hub="myhub.azure-devices.net",
            )

    def test_user_assigned_requires_identity(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(RequiredArgumentMissingError, match="--user-assigned-identity"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", authentication_type="UserAssigned",
            )

    def test_uami_alone_errors(self, fixture_cmd, mock_deps):
        """--user-assigned-identity without --authentication-type UserAssigned must error,
        not silently ignore the UAMI."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(MutuallyExclusiveArgumentError, match="--user-assigned-identity only applies"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub",
                user_assigned_identity="/subscriptions/x/.../myuami",
            )

    def test_uami_with_keybased_errors(self, fixture_cmd, mock_deps):
        """--user-assigned-identity + --authentication-type KeyBased is contradictory; must error."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(MutuallyExclusiveArgumentError, match="--user-assigned-identity only applies"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", authentication_type="KeyBased",
                user_assigned_identity="/subscriptions/x/.../myuami",
            )

    def test_mi_rejects_connection_string(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(MutuallyExclusiveArgumentError, match="--connection-string cannot be used"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", authentication_type="SystemAssigned",
                connection_string="HostName=x;SharedAccessKeyName=y;SharedAccessKey=z",
            )

    def test_cs_on_existing_mi_link_errors(self, fixture_cmd, mock_deps, mocker):
        """Providing --connection-string on an existing MI link without changing auth must error,
        not silently no-op (Copilot review finding)."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        mi_entries = [{
            "name": "myhub.device.azure-devices.net",
            "hostName": "myhub.device.azure-devices.net",
            "authenticationType": "SystemAssigned",
            "connectionString": "",
        }]
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": {"type": "SystemAssigned"},
            "properties": {"iotHubs": mi_entries},
        })
        with pytest.raises(MutuallyExclusiveArgumentError, match="only applies to KeyBased"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub",
                connection_string="HostName=myhub.device.azure-devices.net;SharedAccessKeyName=k;SharedAccessKey=v",
            )

    def test_cs_on_keybased_link_rotates_key(self, fixture_cmd, mock_deps, existing_entries):
        """Providing --connection-string on an existing KeyBased link (without other changes)
        must actually apply the CS — used for key rotation."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        new_cs = "HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=rotated-key"
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", connection_string=new_cs,
        )
        assert existing_entries[0]["connectionString"] == new_cs

    def test_dotless_linked_hub_treated_as_hub_name(self, fixture_cmd, mock_deps, existing_entries):
        """Backward compat: --linked-hub myhub (dotless) routes to the hub-name fuzzy match path."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            linked_hub="myhub", allocation_weight=5,
        )
        assert existing_entries[0]["allocationWeight"] == 5

    def test_no_mutation_params_errors(self, fixture_cmd, mock_deps):
        """Identifier alone (no mutation flags) must error rather than issuing a no-op PUT
        that could clobber concurrent changes."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(RequiredArgumentMissingError, match="at least one update parameter"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps", hub_name="myhub",
            )

    def test_keybased_refresh_preserves_existing_policy(self, fixture_cmd, mock_deps, existing_entries, mocker):
        """Re-fetching the key on a KeyBased link must reuse the EXISTING policy (e.g., 'service'
        for least-privilege setups) — must not silently downgrade to iothubowner."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        existing_entries[0]["connectionString"] = (
            "HostName=myhub.azure-devices.net;"
            "SharedAccessKeyName=service;SharedAccessKey=existing-key"
        )
        policy_spy = mocker.patch(
            "azext_iot.core.custom.iot_hub_policy_get",
            return_value={"keyName": "service", "primaryKey": "rotated-service-key"},
        )

        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", authentication_type="KeyBased",
        )

        assert policy_spy.call_args.args[2] == "service", (
            f"Expected policy 'service' to be preserved, got {policy_spy.call_args.args[2]!r}"
        )
        assert "SharedAccessKeyName=service" in existing_entries[0]["connectionString"]

    def test_keybased_with_linked_hub_auto_fetches(self, fixture_cmd, mock_deps, existing_entries):
        """--linked-hub + --auth-type KeyBased (no CS) derives the hub short name to auto-fetch the key."""
        from azext_iot.core.custom import iot_dps_linked_hub_update
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            linked_hub="myhub.azure-devices.net", authentication_type="KeyBased",
        )
        assert existing_entries[0]["authenticationType"] == "KeyBased"
        assert "fresh-key" in existing_entries[0]["connectionString"]

    def test_mi_not_enabled_errors(self, fixture_cmd, mock_deps, mocker):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": {"type": "None"},
            "properties": {"iotHubs": [{
                "name": "myhub.azure-devices.net",
                "hostName": "myhub.azure-devices.net",
                "authenticationType": "KeyBased",
                "connectionString": "HostName=myhub.azure-devices.net;SharedAccessKeyName=k;SharedAccessKey=v",
            }]},
        })
        with pytest.raises(InvalidArgumentValueError, match="System-assigned managed identity is not enabled"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", authentication_type="SystemAssigned",
            )

    def test_service_hostname_in_cs_rejected(self, fixture_cmd, mock_deps):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        with pytest.raises(InvalidArgumentValueError, match="Service hostname"):
            iot_dps_linked_hub_update(
                cmd=fixture_cmd, client=mock_deps, dps_name="dps",
                hub_name="myhub", authentication_type="KeyBased",
                connection_string="HostName=myhub.service.azure-devices.net;SharedAccessKeyName=k;SharedAccessKey=v",
            )

    def test_allocation_only_preserves_auth_and_hostname(self, fixture_cmd, mock_deps, existing_entries):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", allocation_weight=5,
        )
        entry = existing_entries[0]
        assert entry["allocationWeight"] == 5
        assert entry["authenticationType"] == "KeyBased"
        assert entry["name"] == "myhub.azure-devices.net"

    def test_keybased_to_system_assigned(self, fixture_cmd, mock_deps, existing_entries):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", authentication_type="SystemAssigned",
        )
        entry = existing_entries[0]
        assert entry["authenticationType"] == "SystemAssigned"
        assert entry["connectionString"] == ""
        assert "selectedUserAssignedIdentityResourceId" not in entry

    def test_system_assigned_to_keybased_auto_fetches_key(self, fixture_cmd, mock_deps, mocker):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        mi_entries = [{
            "name": "myhub.azure-devices.net",
            "hostName": "myhub.azure-devices.net",
            "authenticationType": "SystemAssigned",
            "connectionString": "",
        }]
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": {"type": "SystemAssigned,UserAssigned"},
            "properties": {"iotHubs": mi_entries},
        })
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", authentication_type="KeyBased",
        )
        entry = mi_entries[0]
        assert entry["authenticationType"] == "KeyBased"
        assert "fresh-key" in entry["connectionString"]
        assert "myhub.azure-devices.net" in entry["connectionString"]

    def test_uami_to_different_uami(self, fixture_cmd, mock_deps, mocker):
        from azext_iot.core.custom import iot_dps_linked_hub_update
        uami_old = "/subscriptions/x/resourcegroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/old"
        uami_new = "/subscriptions/x/resourcegroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/new"
        ua_entries = [{
            "name": "myhub.device.azure-devices.net",
            "hostName": "myhub.device.azure-devices.net",
            "authenticationType": "UserAssigned",
            "selectedUserAssignedIdentityResourceId": uami_old,
            "connectionString": "",
        }]
        mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
            "identity": {"type": "SystemAssigned,UserAssigned"},
            "properties": {"iotHubs": ua_entries},
        })
        iot_dps_linked_hub_update(
            cmd=fixture_cmd, client=mock_deps, dps_name="dps",
            hub_name="myhub", authentication_type="UserAssigned",
            user_assigned_identity=uami_new,
        )
        assert ua_entries[0]["selectedUserAssignedIdentityResourceId"] == uami_new
