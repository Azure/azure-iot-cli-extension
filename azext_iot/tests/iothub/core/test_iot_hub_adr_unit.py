# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError, RequiredArgumentMissingError, CLIInternalError

from azext_iot.core.custom import (
    ADR_NS_IDENTITY_ROLES_FOR_HUB,
    _setup_adr_hub_role_assignments,
    _validate_and_set_adr_properties,
)
from azext_iot.sdk.iothub.mgmt.models import DeviceRegistry, IotHubProperties
from azext_iot.tests.generators import generate_generic_id

# Test constants
sub = generate_generic_id()
rg = generate_generic_id()
namespace = generate_generic_id()
hub = generate_generic_id()
identity = generate_generic_id()

sub_id = f"/subscriptions/{sub}"
rg_id = f"{sub_id}/{rg}"

namespace_id = f"{rg_id}/providers/Microsoft.DeviceRegistry/namespaces/{namespace}"
identity_id = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
hub_id = f"{rg_id}/providers/Microsoft.Devices/IotHubs/{hub}"


@pytest.mark.parametrize("namespace_id", [namespace_id, None, ""])
@pytest.mark.parametrize("identity_id", [identity_id, None, ""])
@pytest.mark.parametrize("sku", ["GEN2", "S1"])
@pytest.mark.parametrize(
    "existing_properties",
    [
        # existing properties
        DeviceRegistry(namespace_resource_id="existing_namespace_id", identity_resource_id="existing_identity_id"),
        None,
    ],
)
def test_validate_and_set_adr_properties(namespace_id, identity_id, sku, existing_properties):
    """Test ADR properties validation."""
    instance = Mock(spec=IotHubProperties)
    instance.device_registry = existing_properties

    # Test behavior based on SKU type and parameters
    if sku == "GEN2":  # Generation2 SKU
        if namespace_id and identity_id:
            # Valid Gen2 configuration
            _validate_and_set_adr_properties(
                instance=instance, sku=sku, adr_namespace_resource_id=namespace_id, adr_identity_resource_id=identity_id
            )
            assert instance.device_registry is not None
            assert instance.device_registry.namespace_resource_id == namespace_id
            assert instance.device_registry.identity_resource_id == identity_id
        else:
            # Generation2 SKU missing required parameters - should raise error
            with pytest.raises(RequiredArgumentMissingError) as exc_info:
                _validate_and_set_adr_properties(
                    instance=instance,
                    sku=sku,
                    adr_namespace_resource_id=namespace_id,
                    adr_identity_resource_id=identity_id,
                )
            assert "Generation2 IoT Hubs require both ADR namespace resource ID" in str(exc_info.value)
    else:
        if namespace_id or identity_id:
            # Non-Generation2 SKU with ADR parameters
            with pytest.raises(InvalidArgumentValueError) as exc_info:
                _validate_and_set_adr_properties(
                    instance=instance,
                    sku=sku,
                    adr_namespace_resource_id=namespace_id,
                    adr_identity_resource_id=identity_id,
                )
            assert "ADR properties are only supported for Generation2 IoT Hub SKUs" in str(exc_info.value)
        else:
            _validate_and_set_adr_properties(
                instance=instance, sku=sku, adr_namespace_resource_id=namespace_id, adr_identity_resource_id=identity_id
            )
            # Verify properties remain unchanged
            assert instance.device_registry == existing_properties


class TestSetupADRRoleAssignments(object):
    @patch("azext_iot.core.custom.logger")
    @patch("azext_iot.core.custom.assign_identity")
    @patch("azext_iot.adr.providers.namespace.NamespaceProvider")
    @patch("msrestazure.tools.parse_resource_id")
    def test_setup_hub_adr_role_assignments_success(
        self, mock_parse_resource_id, mock_namespace_provider_class, mock_assign_identity, mock_logger
    ):
        """Test successful role assignment setup."""

        mock_principal_id = generate_generic_id()
        mock_rg = generate_generic_id()
        mock_rg_id = f"/subscriptions/test/resourceGroups/{mock_rg}"
        mock_namespace = generate_generic_id()

        # Mock parse_resource_id
        mock_parse_resource_id.return_value = {"resource_group": mock_rg, "name": mock_namespace}

        # Mock namespace provider
        mock_namespace_provider = Mock()
        mock_namespace_provider_class.return_value = mock_namespace_provider
        mock_namespace_provider.show.return_value = {"identity": {"principalId": mock_principal_id}}

        # Mock assign_identity to succeed
        mock_assign_identity.return_value = None

        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()  # Add CLI context
        namespace_id = f"{mock_rg_id}/providers/Microsoft.DeviceRegistry/namespaces/{mock_namespace}"
        hub_id = f"{mock_rg_id}/providers/Microsoft.Devices/IotHubs/test-hub"

        _setup_adr_hub_role_assignments(mock_cmd, namespace_id, hub_id)

        # Verify the namespace provider was created and called correctly
        mock_namespace_provider_class.assert_called_once_with(mock_cmd)
        mock_namespace_provider.show.assert_called_once_with(mock_namespace, mock_rg)

        # Verify assign_identity was called for each role
        assert mock_assign_identity.call_count == len(ADR_NS_IDENTITY_ROLES_FOR_HUB)

        # Verify assign_identity was called with correct parameters for each role
        for call, role in zip(mock_assign_identity.call_args_list, ADR_NS_IDENTITY_ROLES_FOR_HUB):
            # Check positional arguments
            args, kwargs = call
            assert args[0] == mock_cmd.cli_ctx  # CLI context

            # Test that getter and setter functions return objects with correct principal_id
            getter_func = args[1]
            setter_func = args[2]

            getter_result = getter_func()
            assert getter_result.identity.principal_id == mock_principal_id

            setter_result = setter_func(getter_result)
            assert setter_result.identity.principal_id == mock_principal_id

            # Check keyword arguments
            assert kwargs["identity_role"] == role
            assert kwargs["identity_scope"] == hub_id

    @patch("azext_iot.core.custom.logger")
    @patch("msrestazure.tools.parse_resource_id")
    def test_setup_hub_adr_role_assignments_parse_error(self, mock_parse_resource_id, mock_logger):
        """Test role assignment setup with parse error."""
        # Mock parse_resource_id to return incomplete data
        mock_parse_resource_id.return_value = {"resource_group": None, "name": "test-namespace"}

        mock_cmd = Mock()
        namespace_id = "/invalid/resource/id"
        hub_id = "/subscriptions/test/resourceGroups/test-rg/providers/Microsoft.Devices/IotHubs/test-hub"

        _setup_adr_hub_role_assignments(mock_cmd, namespace_id, hub_id)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        assert "Failed to parse ADR namespace resource ID" in mock_logger.warning.call_args[0][0]

    @patch("azext_iot.core.custom.logger")
    @patch("azext_iot.adr.providers.namespace.NamespaceProvider")
    @patch("msrestazure.tools.parse_resource_id")
    def test_setup_hub_adr_role_assignments_no_principal_id(
        self, mock_parse_resource_id, mock_namespace_provider_class, mock_logger
    ):
        """Test role assignment setup when namespace has no principal ID."""
        # Mock parse_resource_id
        mock_rg = generate_generic_id()
        mock_namespace = generate_generic_id()
        mock_parse_resource_id.return_value = {"resource_group": mock_rg, "name": mock_namespace}
        mock_rg_id = f"/subscriptions/test/resourceGroups/{mock_rg}"

        # Mock namespace provider to return identity without principal ID
        mock_namespace_provider = Mock()
        mock_namespace_provider_class.return_value = mock_namespace_provider
        mock_namespace_provider.show.return_value = {"identity": {}}

        mock_cmd = Mock()
        namespace_id = f"{mock_rg_id}/providers/Microsoft.DeviceRegistry/namespaces/{mock_namespace}"
        hub_id = f"{mock_rg_id}/providers/Microsoft.Devices/IotHubs/test-hub"

        _setup_adr_hub_role_assignments(mock_cmd, namespace_id, hub_id)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        assert "ADR namespace does not have a system-assigned identity" in mock_logger.warning.call_args[0][0]

    @patch("azext_iot.core.custom.logger")
    @patch("azext_iot.core.custom.assign_identity")
    @patch("azext_iot.adr.providers.namespace.NamespaceProvider")
    @patch("msrestazure.tools.parse_resource_id")
    def test_setup_hub_adr_role_assignments_partial_failure(
        self, mock_parse_resource_id, mock_namespace_provider_class, mock_assign_identity, mock_logger
    ):
        """Test role assignment setup with partial failures."""

        # Mock parse_resource_id
        mock_parse_resource_id.return_value = {"resource_group": "test-rg", "name": "test-namespace"}

        # Mock namespace provider
        mock_namespace_provider = Mock()
        mock_namespace_provider_class.return_value = mock_namespace_provider
        mock_namespace_provider.show.return_value = {"identity": {"principalId": "test-principal-id"}}

        # Mock assign_identity to fail for some roles
        def assign_identity_side_effect(*args, **kwargs):
            # Fail for the first role (Contributor), succeed for others
            if mock_assign_identity.call_count == 1:
                raise CLIInternalError("Role assignment failed")
            return None

        mock_assign_identity.side_effect = assign_identity_side_effect

        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()  # Add CLI context
        namespace_id = (
            "/subscriptions/test/resourceGroups/test-rg/providers/Microsoft.DeviceRegistry/namespaces/test-namespace"
        )
        hub_id = "/subscriptions/test/resourceGroups/test-rg/providers/Microsoft.Devices/IotHubs/test-hub"

        _setup_adr_hub_role_assignments(mock_cmd, namespace_id, hub_id)

        # Verify specific warnings for failed role and command suggestions
        warning_calls = mock_logger.warning.call_args_list

        # Should have one warning for the specific role failure
        contributor_failures = [call for call in warning_calls if "Failed to assign 'Contributor' role:" in str(call)]
        assert len(contributor_failures) == 1

        # Should have warnings showing command to run for failed roles
        contributor_help = [
            call
            for call in warning_calls
            if "az role assignment create --assignee 'test-principal-id' --role 'Contributor'" in str(call)
        ]
        assert len(contributor_help) == 1

    @patch("azext_iot.core.custom.logger")
    @patch("msrestazure.tools.parse_resource_id")
    def test_setup_hub_adr_role_assignments_general_exception(self, mock_parse_resource_id, mock_logger):
        """Test role assignment setup with general exception."""
        # Mock parse_resource_id to raise an exception
        mock_parse_resource_id.side_effect = Exception("General error")

        mock_cmd = Mock()
        namespace_id = (
            "/subscriptions/test/resourceGroups/test-rg/providers/Microsoft.DeviceRegistry/namespaces/test-namespace"
        )
        hub_id = "/subscriptions/test/resourceGroups/test-rg/providers/Microsoft.Devices/IotHubs/test-hub"

        _setup_adr_hub_role_assignments(mock_cmd, namespace_id, hub_id)

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        assert "Failed to set up ADR role assignments" in mock_logger.warning.call_args[0][0]
