# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azure.cli.core.azclierror import RequiredArgumentMissingError
from azext_iot.sdk.dps.mgmt.models import (
    ManagedServiceIdentity,
    ManagedServiceIdentityType,
    UserAssignedIdentity,
)
from azext_iot.tests.generators import generate_generic_id

from azext_iot.core.custom import (
    dps_identity_assign,
    dps_identity_remove,
    dps_identity_show,
    _construct_identity_info,
)

# Test constants
dps_name = generate_generic_id()
resource_group = generate_generic_id()


# Test data
rg_id = f"/subscriptions/{generate_generic_id()}/resourceGroups/{resource_group}"
user_identity_1 = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{generate_generic_id()}"
user_identity_2 = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{generate_generic_id()}"


class TestDPSIdentityAssign(object):
    @pytest.mark.parametrize("system_assigned", [True, False])
    @pytest.mark.parametrize("user_assigned", [None, [user_identity_1], [user_identity_1, user_identity_2]])
    @patch("azext_iot.core.custom._ensure_dps_resource_group_name")
    def test_dps_identity_assign(self, mock_ensure_rg, system_assigned, user_assigned):
        """Test assigning different identity types to DPS."""
        mock_ensure_rg.return_value = resource_group

        mock_client = Mock()
        mock_dps = Mock()
        mock_dps.identity = None
        mock_client.iot_dps_resource.get.return_value = mock_dps
        mock_client.iot_dps_resource.begin_create_or_update.return_value = Mock()

        # assign identity
        dps_identity_assign(
            mock_client, dps_name=dps_name, system_assigned=system_assigned, user_assigned=user_assigned
        )

        # Determine expected type based on input combination
        if system_assigned and user_assigned:
            expected_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED
        elif system_assigned:
            expected_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED
        else:  # user_assigned only
            expected_type = ManagedServiceIdentityType.USER_ASSIGNED

        # Verify the DPS identity was set correctly
        if not system_assigned and not user_assigned:
            # no identity to set
            assert mock_dps.identity is None
        else:
            assert mock_dps.identity.type == expected_type

            if not user_assigned:
                assert mock_dps.identity.user_assigned_identities is None
            else:
                for identity in user_assigned:
                    assert identity in mock_dps.identity.user_assigned_identities

        mock_client.iot_dps_resource.begin_create_or_update.assert_called_once()

    def test_dps_identity_assign_no_arguments_raises_error(self):
        """Test that not providing any identity arguments raises an error."""
        mock_client = Mock()

        with pytest.raises(RequiredArgumentMissingError) as exc_info:
            dps_identity_assign(
                mock_client,
                dps_name="test-dps",
                resource_group_name="test-rg",
            )

        assert "Specify --system-assigned and/or --user-assigned" in str(exc_info.value)

    @patch("azext_iot.core.custom._ensure_dps_resource_group_name")
    def test_dps_identity_assign_preserves_existing_identities(self, mock_ensure_rg):
        """Test that existing identities are preserved when adding new ones."""
        mock_ensure_rg.return_value = "test-rg"

        mock_client = Mock()
        mock_dps = Mock()

        # Existing identity
        existing_user_id = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/existing-identity"
        existing_identity = ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={existing_user_id: UserAssignedIdentity()},
        )
        mock_dps.identity = existing_identity
        mock_client.iot_dps_resource.get.return_value = mock_dps
        mock_client.iot_dps_resource.begin_create_or_update.return_value = Mock()

        # Add new identity
        new_user_id = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/new-identity"

        dps_identity_assign(mock_client, dps_name="test-dps", user_assigned=[new_user_id])

        # Verify both identities are present
        assert existing_user_id in mock_dps.identity.user_assigned_identities
        assert new_user_id in mock_dps.identity.user_assigned_identities


class TestDPSIdentityRemove(object):
    @patch("azext_iot.core.custom._ensure_dps_resource_group_name")
    def test_dps_identity_remove_system_only(self, mock_ensure_rg):
        """Test removing only system identity from DPS."""
        mock_ensure_rg.return_value = "test-rg"

        mock_client = Mock()
        mock_dps = Mock()

        # Existing system identity
        existing_identity = ManagedServiceIdentity(type=ManagedServiceIdentityType.SYSTEM_ASSIGNED)
        mock_dps.identity = existing_identity
        mock_client.iot_dps_resource.get.return_value = mock_dps
        mock_client.iot_dps_resource.begin_create_or_update.return_value = Mock()

        dps_identity_remove(mock_client, dps_name="test-dps", system_assigned=True)

        # Verify no identity
        assert mock_dps.identity.type == ManagedServiceIdentityType.NONE

    @patch("azext_iot.core.custom._ensure_dps_resource_group_name")
    def test_dps_identity_remove_user_only(self, mock_ensure_rg):
        """Test removing specific user identity from DPS."""
        mock_ensure_rg.return_value = "test-rg"

        mock_client = Mock()
        mock_dps = Mock()

        # Set up existing user identities
        user_id_to_remove = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/remove-identity"
        user_id_to_keep = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/keep-identity"
        existing_identity = ManagedServiceIdentity(
            type=ManagedServiceIdentityType.USER_ASSIGNED,
            user_assigned_identities={
                user_id_to_remove: UserAssignedIdentity(),
                user_id_to_keep: UserAssignedIdentity(),
            },
        )
        mock_dps.identity = existing_identity
        mock_client.iot_dps_resource.get.return_value = mock_dps
        mock_client.iot_dps_resource.begin_create_or_update.return_value = Mock()

        dps_identity_remove(mock_client, dps_name="test-dps", user_assigned=[user_id_to_remove])

        # Verify correct identity was removed
        assert user_id_to_remove not in mock_dps.identity.user_assigned_identities
        assert user_id_to_keep in mock_dps.identity.user_assigned_identities

    @patch("azext_iot.core.custom._ensure_dps_resource_group_name")
    def test_dps_identity_remove_all_identities(self, mock_ensure_rg):
        """Test removing all identities results in NONE type."""
        mock_ensure_rg.return_value = "test-rg"

        mock_client = Mock()
        mock_dps = Mock()

        # Existing identities
        user_id = f"{rg_id}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-identity"
        existing_identity = ManagedServiceIdentity(
            type=ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED,
            user_assigned_identities={user_id: UserAssignedIdentity()},
        )
        mock_dps.identity = existing_identity
        mock_client.iot_dps_resource.get.return_value = mock_dps
        mock_client.iot_dps_resource.begin_create_or_update.return_value = Mock()

        dps_identity_remove(mock_client, dps_name="test-dps", system_assigned=True, user_assigned=[user_id])

        # Verify no identity
        assert mock_dps.identity.type == ManagedServiceIdentityType.NONE

    def test_dps_identity_remove_no_arguments_raises_error(self):
        """Test that not providing any identity arguments raises an error."""
        mock_client = Mock()

        with pytest.raises(RequiredArgumentMissingError) as exc_info:
            dps_identity_remove(
                mock_client,
                dps_name="test-dps",
                resource_group_name="test-rg",  # Provide resource group to avoid lookup
            )

        assert "Specify --system-assigned and/or --user-assigned" in str(exc_info.value)

    def test_dps_identity_show(self):
        """Test showing DPS identity."""
        mock_client = Mock()
        mock_dps = Mock()

        expected_identity = ManagedServiceIdentity(type=ManagedServiceIdentityType.USER_ASSIGNED)
        mock_dps.identity = expected_identity
        mock_client.iot_dps_resource.get.return_value = mock_dps

        result = dps_identity_show(mock_client, dps_name="test-dps", resource_group_name="test-rg")

        assert result == expected_identity
        mock_client.iot_dps_resource.get.assert_called_once_with(
            resource_group_name="test-rg", provisioning_service_name="test-dps"
        )


class TestConstructIdentityInfo(object):
    @pytest.mark.parametrize("enable_system", [True, False])
    @pytest.mark.parametrize("user_identities", [None, [user_identity_1], [user_identity_1, user_identity_2]])
    def test_construct_identity_info(self, enable_system, user_identities):
        """Test constructing different identity configurations."""
        result = _construct_identity_info(enable_system_identity=enable_system, user_identities=user_identities)

        # Determine expected behavior based on input combination
        if not enable_system and not user_identities:
            # No identities - should return None
            assert result is None
            return

        # Determine expected type
        if enable_system and user_identities:
            expected_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED
        elif enable_system:
            expected_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED
        else:  # user_identities only
            expected_type = ManagedServiceIdentityType.USER_ASSIGNED

        assert result.type == expected_type

        if user_identities:
            assert len(result.user_assigned_identities) == len(user_identities)
            for identity_id in user_identities:
                assert identity_id in result.user_assigned_identities
                assert isinstance(result.user_assigned_identities[identity_id], UserAssignedIdentity)
        else:
            assert result.user_assigned_identities is None
