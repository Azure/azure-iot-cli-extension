# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional
from knack.log import get_logger
from azext_iot.adr.common import IdentityType
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.rbac import RbacProvider


logger = get_logger(__name__)


class NamespaceProvider(ADRProvider):
    def __init__(self, cmd):
        super(NamespaceProvider, self).__init__(cmd)

    def create(
        self,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        no_credential: Optional[bool] = None,
        no_policy: Optional[bool] = None,
        policy_name: Optional[str] = None,
        certificate_key_type: Optional[str] = None,
        certificate_subject: Optional[str] = None,
        certificate_validity_days: Optional[int] = None,
    ):
        """Create an ADR namespace."""
        if not location:
            location = self._ensure_location(self.cmd.cli_ctx, resource_group_name, location)

        # Build the namespace resource
        namespace_resource = {"location": location}

        # TODO - CMS Preview - default system assigned identity
        namespace_resource["identity"] = {"type": IdentityType.system_assigned.value}

        if tags:
            namespace_resource["tags"] = tags

        # TODO - CMS Preview - support messaging endpoints create

        properties = {}
        if properties:
            namespace_resource["properties"] = properties

        try:
            logger.info(
                "Creating ADR namespace '%s' in resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            # TODO - CMS Preview - create_or_replace - should we check for existence first?
            # Create the namespace
            namespace_result = self.client.namespaces.begin_create_or_replace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                resource=namespace_resource,
            ).result()

            namespace_principal_id = namespace_result.get("identity", {}).get("principalId")
            # TODO - CMS Preview - what is up with these create responses?
            if not namespace_result.get("resourceGroup"):
                namespace_result["resourceGroup"] = resource_group_name

            # Setup ADR-IoT Hub integration with custom role and assignments
            try:
                logger.info("Setting up ADR-IoT Hub integration roles...")

                if namespace_principal_id:
                    rbac_provider = RbacProvider(self.cmd)
                    rbac_provider.configure_adr_user_identity_and_rbac(namespace=namespace_result)
                else:
                    logger.warning("Namespace principal ID not found, skipping role assignments")

            except Exception as role_error:
                logger.warning(f"Failed to setup ADR-IoT Hub integration roles: {role_error}")
                logger.warning("ADR namespace created but IoT Hub integration may require manual role setup")

            # TODO - CMS Preview - capture / log errors for credential and policy creation
            # Create credentials by default
            if not no_credential:
                from azext_iot.adr.providers.credential import CredentialProvider
                credential_provider = CredentialProvider(self.cmd)
                credential_provider.create(
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=location,
                )

            # Create policy by default
            if not no_credential and not no_policy:
                from azext_iot.adr.providers.policy import PolicyProvider
                policy_provider = PolicyProvider(self.cmd)
                policy_provider.create(
                    policy_name=policy_name,
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=location,
                    certificate_key_type=certificate_key_type,
                    certificate_subject=certificate_subject,
                    certificate_validity_days=certificate_validity_days,
                )

            logger.info("Successfully created ADR namespace '%s'", namespace_name)
            return namespace_result

        except Exception as e:
            logger.error("Failed to create ADR namespace: %s", str(e))
            raise

    def show(self, namespace_name: str, resource_group_name: str):
        """Show details of an ADR namespace."""
        try:
            return self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)
        except Exception as e:
            logger.error("Failed to get ADR namespace: %s", str(e))
            raise

    def list(self, resource_group_name: Optional[str] = None):
        """List ADR namespaces."""
        try:
            if resource_group_name:
                return list(self.client.namespaces.list_by_resource_group(resource_group_name=resource_group_name))
            else:
                return list(self.client.namespaces.list_by_subscription())
        except Exception as e:
            logger.error("Failed to list ADR namespaces: %s", str(e))
            raise

    def delete(self, namespace_name: str, resource_group_name: str):
        """Delete an ADR namespace."""
        try:
            logger.info(
                "Deleting ADR namespace '%s' from resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            return self.client.namespaces.begin_delete(resource_group_name=resource_group_name, namespace_name=namespace_name)
        except Exception as e:
            logger.error("Failed to delete ADR namespace: %s", str(e))
            raise

    def update(
        self,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
    ):
        """Update an ADR namespace."""
        properties = {}
        if tags is not None:
            properties["tags"] = tags

        # TODO - CMS Preview - support messaging endpoints update

        try:
            logger.info(
                "Updating ADR namespace '%s' in resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            return self.client.namespaces.begin_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                properties=properties,
            )
        except Exception as e:
            logger.error("Failed to update ADR namespace: %s", str(e))
            raise
