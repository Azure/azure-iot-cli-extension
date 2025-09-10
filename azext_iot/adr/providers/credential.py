# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import TYPE_CHECKING, Dict, Optional

from knack.log import get_logger
from rich.console import Console

from azext_iot.adr.providers.base import ADRProvider
from azext_iot.common.utility import wait_for_terminal_state

if TYPE_CHECKING:
    from azure.core.polling import LROPoller

console = Console()
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
        **kwargs
    ):
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

        with console.status(f"Creating credentials for namespace {namespace_name}..."):
            poller = self.client.credentials.begin_create_or_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                resource=credentials_resource,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def show(self, namespace_name: str, resource_group_name: str):
        return self.client.credentials.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

    def delete(self, namespace_name: str, resource_group_name: str, **kwargs):
        with console.status(f"Deleting credentials for namespace {namespace_name}..."):
            poller = self.client.credentials.begin_delete(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            return wait_for_terminal_state(poller, **kwargs)

    def synchronize(self, namespace_name: str, resource_group_name: str, **kwargs):
        with console.status(f"Synchronizing credentials for namespace {namespace_name}..."):
            poller: LROPoller = self.client.credentials.begin_synchronize(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            result = wait_for_terminal_state(poller, **kwargs)
            poller_status = poller.status()
            if poller_status == "Succeeded":
                console.print(f"Successfully synchronized credentials for namespace '{namespace_name}'", style="green")
            else:
                console.print(f"Synchronization completed with a status of: '{poller_status}'", style="yellow")
        return result
