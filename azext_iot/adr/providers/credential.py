# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from knack.log import get_logger

from azext_iot.adr.providers.base import ADRProvider

logger = get_logger(__name__)


class CredentialProvider(ADRProvider):
    def __init__(self, cmd):
        super(CredentialProvider, self).__init__(cmd)

    def create(
        self,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        """Create credential for an ADR namespace."""
        if not location:
            location = self._ensure_location(self.cmd.cli_ctx, resource_group_name, location)

        credentials_resource = {"location": location}

        if tags:
            credentials_resource["tags"] = tags

        try:
            logger.info(
                "Creating credential for ADR namespace '%s' in resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            result = self.client.credentials.begin_create_or_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                resource=credentials_resource,
            )

            logger.info("Successfully created credentials for ADR namespace '%s'", namespace_name)
            return result

        except Exception as e:
            logger.error("Failed to create credentials: %s", str(e))
            raise

    def show(self, namespace_name: str, resource_group_name: str):
        """Show credentials for an ADR namespace."""
        try:
            return self.client.credentials.get(resource_group_name=resource_group_name, namespace_name=namespace_name)
        except Exception as e:
            logger.error("Failed to get credentials: %s", str(e))
            raise

    def delete(self, namespace_name: str, resource_group_name: str):
        """Delete credentials for an ADR namespace."""
        try:
            logger.info(
                "Deleting credentials for ADR namespace '%s' from resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            return self.client.credentials.begin_delete(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
        except Exception as e:
            logger.error("Failed to delete credentials: %s", str(e))
            raise

    def synchronize(self, namespace_name: str, resource_group_name: str):
        """Synchronize credentials for an ADR namespace."""
        try:
            logger.info(
                "Synchronizing credentials for ADR namespace '%s' in resource group '%s'",
                namespace_name,
                resource_group_name,
            )
            return self.client.credentials.begin_synchronize(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
        except Exception as e:
            logger.error("Failed to synchronize credentials: %s", str(e))
            raise
