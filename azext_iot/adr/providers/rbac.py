# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from typing import Optional, Dict

from azext_iot.common.embedded_cli import EmbeddedCLI
from knack.log import get_logger
from azure.cli.core.azclierror import CLIInternalError, AzureResponseError
from azure.cli.core.commands.client_factory import get_subscription_id

logger = get_logger(__name__)

# Constants for ADR RBAC operations
IOT_HUB_RP_APP_ID = "0aab4033-4ad9-4b0b-9934-542334eceffb"
ADR_CUSTOM_ROLE_NAME = "ADR Integration Role"
USER_IDENTITY_NAME = "{namespace}-user-identity"


class RbacProvider(object):
    """Provider for managing ADR RBAC operations including custom roles and assignments."""

    def __init__(self, cmd, subscription_id: Optional[str] = None):
        self.cli = EmbeddedCLI()
        self.cmd = cmd
        self.subscription_id = subscription_id or get_subscription_id(self.cmd.cli_ctx)

    # RBAC Utility Methods

    def assign_sp_role(self, role: str, scope: str, principal_id: str) -> bool:
        """
        Assign a role to a service principal.

        Args:
            role: The role to assign (name or ID)
            scope: The scope/resource ID for the assignment
            principal_id: The principal ID (object ID) of the service principal

        Returns:
            bool: True if assignment succeeded, False if failed
        """
        logger.debug(f"Assigning role '{role}' to principal '{principal_id}' at scope '{scope}'")

        role_command = (
            "role assignment create --role '{}' --assignee-object-id '{}' "
            "--assignee-principal-type ServicePrincipal --scope '{}'".format(role, principal_id, scope)
        )

        role_op = self.cli.invoke(role_command)
        if not role_op.success():
            logger.error(f"Failed to assign role: {role_op.get_error()}")
            return False

        logger.debug(f"Successfully assigned role '{role}' to principal '{principal_id}'")
        return True

    def create_user_identity(self, identity_name: str, resource_group_name: str, location: str) -> Dict:
        """
        Create a user-assigned managed identity.

        Args:
            identity_name: Name for the user-assigned identity
            resource_group_name: Resource group to create the identity in
            location: Azure region for the identity

        Returns:
            dict: The created identity resource
        """
        logger.debug(f"Creating user-assigned managed identity: {identity_name}")

        identity_command = "identity create --name '{}' --resource-group '{}' --location '{}'".format(
            identity_name, resource_group_name, location
        )

        identity_op = self.cli.invoke(identity_command)
        if not identity_op.success():
            logger.error(f"Failed to create user-assigned identity: {identity_op.get_error()}")
            raise AzureResponseError(f"Identity creation failed: {identity_op.get_error()}")

        identity_result = identity_op.as_json()
        logger.info(f"Successfully created user-assigned managed identity: {identity_name}")
        logger.debug(f"Identity Principal ID: {identity_result.get('principalId')}")

        return identity_result

    def create_custom_role_definition(
        self, name: str, role_definition: Dict, overwrite: Optional[bool] = False
    ) -> Dict:
        """
        Create or update a custom role definition.

        Args:
            name: Name of the custom role
            role_definition: The role definition
            overwrite: Whether to overwrite an existing role

        Returns:
            dict: The resulting role definition
        """
        logger.debug(f"Creating/updating custom role: {name}")

        # Convert role definition to JSON string
        role_json = json.dumps(role_definition)

        # Check if role exists
        list_command = f"role definition list --custom-role-only --query \"[?roleName=='{name}']\""
        list_op = self.cli.invoke(list_command)

        if list_op.success() and list_op.as_json():
            if not overwrite:
                logger.warning(f"Role '{name}' already exists, not updating.")
                return list_op.as_json()[0]  # Return existing role
            # Update existing role
            existing_role = list_op.as_json()[0]
            role_definition["Id"] = existing_role["name"]  # Add ID for update
            role_json = json.dumps(role_definition)

            op = self.cli.invoke(f"role definition update --role-definition '{role_json}'")
            action = "Updated"
        else:
            # Create new role
            op = self.cli.invoke(f"role definition create --role-definition '{role_json}'")
            action = "Created"

        if not op.success():
            logger.error(f"Failed to {action.lower()} custom role '{name}': {op.get_error()}")
            raise AzureResponseError(f"Role {action.lower()} failed: {op.get_error()}")

        logger.info(f"{action} custom role: {name}")
        return op.as_json()

    # ADR Custom Role
    def get_adr_custom_role_definition(self, resource_group_name: str) -> Dict:
        """Get the standard ADR custom role definition."""
        return {
            "Name": ADR_CUSTOM_ROLE_NAME,
            "Description": "Custom role for Device Registry operations with specific permissions for IoT Hub integration",
            "Actions": [
                "Microsoft.DeviceRegistry/namespaces/read",
                "Microsoft.DeviceRegistry/namespaces/write",
                "Microsoft.DeviceRegistry/namespaces/devices/read",
                "Microsoft.DeviceRegistry/namespaces/devices/write",
                "Microsoft.DeviceRegistry/namespaces/assets/read",
                "Microsoft.DeviceRegistry/namespaces/assets/write",
            ],
            "AssignableScopes": [f"/subscriptions/{self.subscription_id}/resourceGroups/{resource_group_name}"],
        }

    # ADR custom permission configuration entry point
    def configure_adr_user_identity_and_rbac(
        self,
        namespace: Dict,
    ) -> None:
        """
        Configure RBAC for ADR operations - creates user identity and assigns roles.

        This is the main entry point for ADR RBAC configuration.
        Always creates a user identity as `{namespace_name}-user-identity` and assigns roles.

        Args:
            namespace: Namespace properties dict containing 'id', 'name', 'location', 'resourceGroup', 'identity.principalId'

        Returns:
            dict: Created identity resource
        """
        # Extract properties from namespace dict
        namespace_resource_id = namespace["id"]
        namespace_name = namespace["name"]
        resource_group_name = namespace["resourceGroup"]
        location = namespace["location"]

        try:
            # 1. Create custom role definition for ADR operations if it doesn't exist
            role_definition = self.get_adr_custom_role_definition(resource_group_name)
            created_role = self.create_custom_role_definition(
                name=ADR_CUSTOM_ROLE_NAME, role_definition=role_definition
            )

            # Use role ID for assignments to avoid name resolution issues
            custom_role_id = created_role.get("id") or created_role.get("name")
            if not custom_role_id:
                raise AzureResponseError("Failed to get role ID from created custom role")

            # 2. Create a user identity as `{namespace_name}-identity` in same RG and location
            identity_name = USER_IDENTITY_NAME.format(namespace=namespace_name)
            logger.info(f"Creating ADR user identity: {identity_name}")

            identity_result = self.create_user_identity(
                identity_name=identity_name, resource_group_name=resource_group_name, location=location
            )
            user_identity_principal_id = identity_result.get("principalId")

            if not user_identity_principal_id:
                raise AzureResponseError("Failed to get principal ID from created identity")

            # Resource Group scope for broader permissions
            rg_scope = f"/subscriptions/{self.subscription_id}/resourceGroups/{resource_group_name}"

            # 3. Assign custom role to user identity and IoT Hub RP
            for scope in [rg_scope, namespace_resource_id]:
                logger.info(f"Assigning custom role to identity for {scope}")
                self.assign_sp_role(role=custom_role_id, scope=scope, principal_id=user_identity_principal_id)

                logger.info(f"Assigning Contributor role to IoT Hub RP for {scope}")
                self.assign_sp_role(role="Contributor", scope=scope, principal_id=IOT_HUB_RP_APP_ID)

            logger.info("Successfully configured ADR RBAC")
            return

        except Exception as e:
            error_msg = f"Failed to configure ADR RBAC: {e}"
            logger.error(error_msg)
            raise CLIInternalError(error_msg)
