# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.rbac import RbacProvider, ADR_CUSTOM_ROLE_NAME, IOT_HUB_RP_APP_ID, USER_IDENTITY_NAME


class TestRbacProvider(object):
    """Test RbacProvider class methods."""

    @pytest.fixture()
    def fixture_cmd(self):
        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()
        return mock_cmd

    @pytest.fixture()
    def fixture_rbac_provider(self, fixture_cmd):
        with patch("azext_iot.adr.providers.rbac.get_subscription_id", return_value="test-subscription-id"), patch(
            "azext_iot.adr.providers.rbac.EmbeddedCLI"
        ) as mock_cli_class:
            mock_cli = Mock()
            mock_cli_class.return_value = mock_cli
            provider = RbacProvider(fixture_cmd, "test-subscription-id")
            provider.cli = mock_cli
            return provider

    def test_assign_sp_role(self, fixture_rbac_provider):
        """Test successful service principal role assignment."""
        mock_operation = Mock()
        mock_operation.success.return_value = True
        fixture_rbac_provider.cli.invoke.return_value = mock_operation

        role = "Contributor"
        scope = "/subscriptions/test-sub/resourceGroups/test-rg"
        principal_id = "test-principal-id"

        result = fixture_rbac_provider.assign_sp_role(role, scope, principal_id)

        assert result is True
        expected_command = (
            "role assignment create --role 'Contributor' --assignee-object-id 'test-principal-id' "
            "--assignee-principal-type ServicePrincipal --scope '/subscriptions/test-sub/resourceGroups/test-rg'"
        )
        fixture_rbac_provider.cli.invoke.assert_called_once_with(expected_command)

    def test_create_user_identity(self, fixture_rbac_provider):
        """Test successful user-assigned managed identity creation."""
        mock_operation = Mock()
        mock_operation.success.return_value = True
        mock_identity_data = {
            "id": (
                "/subscriptions/test-sub/resourceGroups/test-rg/"
                "providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-identity"
            ),
            "name": "test-identity",
            "principalId": "test-principal-id",
            "clientId": "test-client-id",
            "location": "eastus",
        }
        mock_operation.as_json.return_value = mock_identity_data
        fixture_rbac_provider.cli.invoke.return_value = mock_operation

        result = fixture_rbac_provider.create_user_identity(
            identity_name="test-identity", resource_group_name="test-rg", location="eastus"
        )

        assert result == mock_identity_data
        expected_command = "identity create --name 'test-identity' --resource-group 'test-rg' --location 'eastus'"
        fixture_rbac_provider.cli.invoke.assert_called_once_with(expected_command)

    @pytest.mark.parametrize(
        "existing_role, overwrite, should_update",
        [
            (None, False, False),  # No existing role, create new
            ([{"name": "role-id", "roleName": "ADR Integration Role"}], False, False),  # Existing role, don't overwrite
            ([{"name": "role-id", "roleName": "ADR Integration Role"}], True, True),  # Existing role, overwrite
        ],
    )
    def test_create_custom_role_definition(self, fixture_rbac_provider, existing_role, overwrite, should_update):
        """Test custom role definition creation and update scenarios."""
        role_definition = {
            "Name": "Test Role",
            "Description": "Test role description",
            "Actions": ["Microsoft.Test/read"],
            "AssignableScopes": ["/subscriptions/test-sub"],
        }

        # Mock the list operation to check for existing role
        mock_list_operation = Mock()
        if existing_role:
            mock_list_operation.success.return_value = True
            mock_list_operation.as_json.return_value = existing_role
        else:
            mock_list_operation.success.return_value = True
            mock_list_operation.as_json.return_value = []

        # Mock the create/update operation
        mock_crud_operation = Mock()
        mock_crud_operation.success.return_value = True
        expected_result = {"name": "role-id", "roleName": "Test Role"}
        mock_crud_operation.as_json.return_value = expected_result

        # Setup CLI invoke behavior
        def cli_invoke_side_effect(command):
            if "role definition list" in command:
                return mock_list_operation
            elif "role definition" in command:
                return mock_crud_operation
            return Mock()

        fixture_rbac_provider.cli.invoke.side_effect = cli_invoke_side_effect

        result = fixture_rbac_provider.create_custom_role_definition("Test Role", role_definition, overwrite)

        if existing_role and not overwrite:
            # Should return the existing role when not overwriting
            assert result == existing_role[0]
        else:
            # Should return the new/updated role
            assert result == expected_result

        # Verify correct CLI calls
        expected_list_command = "role definition list --custom-role-only --query \"[?roleName=='Test Role']\""

        if existing_role and not overwrite:
            # Should only call list, return existing role
            assert fixture_rbac_provider.cli.invoke.call_count == 1
            assert existing_role[0] == result
        elif existing_role and overwrite:
            # Should call list and update
            assert fixture_rbac_provider.cli.invoke.call_count == 2
            calls = fixture_rbac_provider.cli.invoke.call_args_list
            assert expected_list_command in calls[0][0][0]
            assert "role definition update" in calls[1][0][0]
        else:
            # Should call list and create
            assert fixture_rbac_provider.cli.invoke.call_count == 2
            calls = fixture_rbac_provider.cli.invoke.call_args_list
            assert expected_list_command in calls[0][0][0]
            assert "role definition create" in calls[1][0][0]

    def test_get_adr_custom_role_definition(self, fixture_rbac_provider):
        """Test ADR custom role definition generation."""
        role_def = fixture_rbac_provider.get_adr_custom_role_definition("test-rg")

        assert role_def["Name"] == ADR_CUSTOM_ROLE_NAME
        assert "Microsoft.DeviceRegistry/namespaces/read" in role_def["Actions"]
        assert "Microsoft.DeviceRegistry/namespaces/write" in role_def["Actions"]
        assert "Microsoft.DeviceRegistry/namespaces/devices/read" in role_def["Actions"]
        assert "/subscriptions/test-subscription-id/resourceGroups/test-rg" in role_def["AssignableScopes"]

    def test_configure_adr_user_identity_and_rbac(self, fixture_rbac_provider):
        """Test successful ADR RBAC configuration."""
        namespace = {
            "id": "/subscriptions/test-sub/resourceGroups/test-rg/providers/Microsoft.DeviceRegistry/namespaces/test-namespace",
            "name": "test-namespace",
            "location": "eastus",
            "resourceGroup": "test-rg",
            "identity": {"principalId": "namespace-principal-id"},
        }

        mock_role_result = {"id": "custom-role-id", "name": "custom-role-id"}
        mock_identity_result = {"principalId": "user-identity-principal-id"}

        with patch.object(
            fixture_rbac_provider, "create_custom_role_definition", return_value=mock_role_result
        ) as mock_create_role, patch.object(
            fixture_rbac_provider, "create_user_identity", return_value=mock_identity_result
        ) as mock_create_identity, patch.object(
            fixture_rbac_provider, "assign_sp_role", return_value=True
        ) as mock_assign_role:

            # Act
            fixture_rbac_provider.configure_adr_user_identity_and_rbac(namespace)

            # Assert
            # Verify custom role creation
            mock_create_role.assert_called_once_with(
                name=ADR_CUSTOM_ROLE_NAME,
                role_definition=fixture_rbac_provider.get_adr_custom_role_definition("test-rg"),
            )

            # Verify user identity creation
            expected_identity_name = USER_IDENTITY_NAME.format(namespace="test-namespace")
            mock_create_identity.assert_called_once_with(
                identity_name=expected_identity_name, resource_group_name="test-rg", location="eastus"
            )

            # Verify role assignments (should be called 4 times total)
            assert mock_assign_role.call_count == 4

            # Check the role assignment calls
            rg_scope = "/subscriptions/test-subscription-id/resourceGroups/test-rg"
            namespace_scope = namespace["id"]

            expected_calls = [
                # Custom role to user identity
                {"role": "custom-role-id", "scope": rg_scope, "principal_id": "user-identity-principal-id"},
                {"role": "custom-role-id", "scope": namespace_scope, "principal_id": "user-identity-principal-id"},
                # Contributor role to IoT Hub RP
                {"role": "Contributor", "scope": rg_scope, "principal_id": IOT_HUB_RP_APP_ID},
                {"role": "Contributor", "scope": namespace_scope, "principal_id": IOT_HUB_RP_APP_ID},
            ]

            for call_info in expected_calls:
                mock_assign_role.assert_any_call(
                    role=call_info["role"], scope=call_info["scope"], principal_id=call_info["principal_id"]
                )
