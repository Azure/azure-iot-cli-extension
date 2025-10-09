# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import TYPE_CHECKING, Dict, Optional

from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from rich.console import Console

from azext_iot.adr.common import CREDENTIAL_NOT_FOUND_MSG
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
        **kwargs,
    ):
        if not location:
            namespace = self.client.namespaces.get(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            location = namespace.get("location")
            if not location:
                raise AzureResponseError(
                    "Error attempting to determine location from parent Namespace: "
                    "Namespace does not contain a location property."
                )

        credentials_resource = {"location": location, "properties": {}}

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
        # Check if parent namespace exists, will 404 if not
        self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

        # Show friendly error if credential doesn't exist
        try:
            return self.client.credentials.get(resource_group_name=resource_group_name, namespace_name=namespace_name)
        except HttpResponseError as e:
            if e.status_code == 404:
                raise ResourceNotFoundError(
                    CREDENTIAL_NOT_FOUND_MSG.format(
                        namespace_name=namespace_name, resource_group_name=resource_group_name
                    )
                )
            raise

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
                logger.warning(f"Synchronization completed with a status of: '{poller_status}'")
            return result
