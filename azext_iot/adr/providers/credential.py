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
            # TODO - CMS Preview - fetch location from the existing namespace
            namespace = self.client.namespaces.get(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            location = namespace.get("location")
        # fallback to RG location
        location = self._ensure_location(self.cmd.cli_ctx, resource_group_name, location)

        credentials_resource = {"location": location}

        if tags:
            credentials_resource["tags"] = tags

        return self.client.credentials.begin_create_or_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            resource=credentials_resource,
        )

    def show(self, namespace_name: str, resource_group_name: str):
        """Show credentials for an ADR namespace."""
        return self.client.credentials.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

    def delete(self, namespace_name: str, resource_group_name: str):
        """Delete credentials for an ADR namespace."""
        return self.client.credentials.begin_delete(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )

    def synchronize(self, namespace_name: str, resource_group_name: str):
        """Synchronize credentials for an ADR namespace."""
        return self.client.credentials.begin_synchronize(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )
