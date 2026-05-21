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
)
from azext_iot.core.custom import _resolve_linked_hub_hostname, _warn_mixed_endpoint_types, _linked_hub_hostname


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


class TestLinkedHubCreateDuplicateGuard:
    """Bug-bash #7 — reject re-linking the same hub under a different hostname type or auth method."""

    @pytest.fixture
    def mock_deps_factory(self, mocker):
        """Returns a factory that builds the mock_deps with a configurable pre-existing iotHubs list."""
        def _factory(existing_hubs, hub_get_response=None):
            mocker.patch("azext_iot.core.custom.iot_hub_service_factory")
            mocker.patch("azext_iot.core.custom.iot_hub_get", return_value=hub_get_response or {
                "properties": {"deviceHostName": "hub.device.azure-devices.net", "hostName": "hub.azure-devices.net"},
                "location": "eastus2euap",
                "resourcegroup": "test-rg",
            })
            mocker.patch("azext_iot.core.custom.iot_hub_policy_get", return_value={
                "keyName": "iothubowner", "primaryKey": "testkey"
            })
            mocker.patch("azext_iot.core.custom._ensure_dps_resource_group_name", return_value="test-rg")
            mocker.patch("azext_iot.core.custom.iot_dps_get", return_value={
                "identity": {"type": "SystemAssigned,UserAssigned"},
                "properties": {"iotHubs": list(existing_hubs)},
            })
            mocker.patch("azext_iot.core.custom.LongRunningOperation")
            mocker.patch("azext_iot.core.custom.iot_dps_linked_hub_list", return_value=list(existing_hubs))
            mock_client = mocker.MagicMock()
            return mock_client
        return _factory

    def test_duplicate_rejected_same_hostname_type_mi(self, fixture_cmd, mock_deps_factory):
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory([{"name": "hub.device.azure-devices.net"}])
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned"
            )

    def test_duplicate_rejected_cross_hostname_type_classic_then_device(self, fixture_cmd, mock_deps_factory):
        """Hub previously linked as classic — re-linking as --hostname-type device must be rejected."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory([{"name": "hub.azure-devices.net"}])
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned",
                hostname_type="device"
            )

    def test_duplicate_rejected_cross_hostname_type_device_then_classic(self, fixture_cmd, mock_deps_factory):
        """Hub previously linked as device — re-linking as classic must be rejected."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory([{"hostName": "hub.device.azure-devices.net"}])
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned",
                hostname_type="classic"
            )

    def test_duplicate_rejected_cs_then_mi(self, fixture_cmd, mock_deps_factory):
        """Hub previously linked via CS — re-linking via MI must be rejected."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        existing = [{
            "connectionString": "HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k",
        }]
        client = mock_deps_factory(existing)
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned"
            )

    def test_duplicate_rejected_mi_then_cs(self, fixture_cmd, mock_deps_factory, mocker):
        """Hub previously linked via MI — re-linking via CS must be rejected."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        mocker.patch("azext_iot.core.custom.iot_hub_get_stats")
        client = mock_deps_factory([{"hostName": "hub.device.azure-devices.net"}])
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                connection_string="HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k",
                location="eastus2euap",
            )

    def test_duplicate_rejected_cs_same_hostname(self, fixture_cmd, mock_deps_factory):
        """Hub previously linked via CS — re-linking via CS with the same hostname must be rejected."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        existing = [{
            "connectionString": "HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k1",
        }]
        client = mock_deps_factory(existing)
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                connection_string="HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=k2",
                location="eastus2euap",
            )

    def test_different_hub_allowed(self, fixture_cmd, mock_deps_factory, mocker):
        """Linking a different hub does not collide with an existing link."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory(
            existing_hubs=[{"name": "hub.device.azure-devices.net"}],
            hub_get_response={
                "properties": {"deviceHostName": "other.device.azure-devices.net", "hostName": "other.azure-devices.net"},
                "location": "eastus2euap",
                "resourcegroup": "test-rg",
            },
        )
        # Should not raise the duplicate guard. We don't assert success because the surrounding
        # path makes management-plane calls we don't fully mock; we only assert the dup-guard
        # error message is NOT raised.
        try:
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="other", authentication_type="SystemAssigned"
            )
        except InvalidArgumentValueError as ex:
            assert "already linked" not in str(ex)

    def test_empty_existing_allowed(self, fixture_cmd, mock_deps_factory):
        """First link onto an empty DPS does not trigger the guard."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory([])
        try:
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
                hub_name="hub", authentication_type="SystemAssigned"
            )
        except InvalidArgumentValueError as ex:
            assert "already linked" not in str(ex)

    def test_dup_guard_short_name_case_insensitive(self, fixture_cmd, mock_deps_factory):
        """Short-name comparison is case-insensitive."""
        from azext_iot.core.custom import iot_dps_linked_hub_create
        client = mock_deps_factory([{"name": "HUB.azure-devices.net"}])
        with pytest.raises(InvalidArgumentValueError, match="already linked"):
            iot_dps_linked_hub_create(
                cmd=fixture_cmd, client=client, dps_name="dps",
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


class TestLinkedHubHostname:
    """Tests for the _linked_hub_hostname helper used by both the mixed-endpoint warning
    and the duplicate-link guard."""

    def test_hostname_from_hostname_key(self):
        assert _linked_hub_hostname({"hostName": "hub.device.azure-devices.net"}) == "hub.device.azure-devices.net"

    def test_hostname_from_connection_string(self):
        entry = {"connectionString": "HostName=hub.azure-devices.net;SharedAccessKeyName=k;SharedAccessKey=v"}
        assert _linked_hub_hostname(entry) == "hub.azure-devices.net"

    def test_hostname_from_name_key(self):
        assert _linked_hub_hostname({"name": "hub.service.azure-devices.net"}) == "hub.service.azure-devices.net"

    def test_hostname_prefers_hostName_over_connection_string(self):
        entry = {
            "hostName": "primary.device.azure-devices.net",
            "connectionString": "HostName=secondary.azure-devices.net;SharedAccessKey=v",
        }
        assert _linked_hub_hostname(entry) == "primary.device.azure-devices.net"

    def test_hostname_missing_returns_empty(self):
        assert _linked_hub_hostname({}) == ""
        assert _linked_hub_hostname({"hostName": None, "connectionString": None, "name": None}) == ""

    def test_hostname_cs_with_no_hostname_field(self):
        entry = {"connectionString": "SharedAccessKeyName=k;SharedAccessKey=v"}
        assert _linked_hub_hostname(entry) == ""

    def test_hostname_cs_case_insensitive(self):
        entry = {"connectionString": "hostname=hub.azure-devices.net;SharedAccessKey=v"}
        assert _linked_hub_hostname(entry) == "hub.azure-devices.net"
