# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from rich.console import Console

from azext_iot.adr.common import (
    DEFAULT_NS_POLICY_CERT_KEY_TYPE,
    DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS,
    POLICY_PARENT_RESOURCE_NOT_FOUND_MSG,
)
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.common.utility import wait_for_terminal_state

console = Console()
logger = get_logger(__name__)


class PolicyProvider(ADRProvider):
    def __init__(self, cmd):
        super(PolicyProvider, self).__init__(cmd)

    def create(
        self,
        policy_name: str,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        certificate_key_type: Optional[str] = None,
        certificate_subject: Optional[str] = None,
        certificate_validity_days: Optional[int] = None,
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

        policy_resource = {"location": location}

        if tags:
            policy_resource["tags"] = tags

        # Build certificate configuration, for service defaults MUST be empty object
        properties = {}

        # If user provides custom values, create custom policy cert object
        if certificate_key_type or certificate_subject or certificate_validity_days:
            certificate_config = {}
            # Set defaults for required parameters if not provided
            if certificate_key_type is None:
                certificate_key_type = DEFAULT_NS_POLICY_CERT_KEY_TYPE
            if certificate_validity_days is None:
                certificate_validity_days = DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS

            ca_config = {"keyType": certificate_key_type}
            if certificate_subject:
                ca_config["subject"] = certificate_subject
            certificate_config["certificateAuthorityConfiguration"] = ca_config
            certificate_config["leafCertificateConfiguration"] = {"validityPeriodInDays": certificate_validity_days}
            properties["certificate"] = certificate_config

        policy_resource["properties"] = properties

        with console.status(f"Creating policy '{policy_name}' for namespace {namespace_name}..."):
            poller = self.client.policies.begin_create_or_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                policy_name=policy_name,
                resource=policy_resource,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def show(self, policy_name: str, namespace_name: str, resource_group_name: str):
        # Ensure namespace exists
        self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

        try:
            return self.client.policies.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                policy_name=policy_name,
            )
        except HttpResponseError as e:
            if e.status_code == 404 and "ParentResourceNotFound" in str(e):
                raise ResourceNotFoundError(
                    POLICY_PARENT_RESOURCE_NOT_FOUND_MSG.format(
                        namespace_name=namespace_name, resource_group_name=resource_group_name
                    )
                )
            raise

    def list(self, namespace_name: str, resource_group_name: str):
        # Ensure namespace exists
        self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

        try:
            return list(
                self.client.policies.list_by_resource_group(
                    resource_group_name=resource_group_name,
                    namespace_name=namespace_name,
                )
            )
        except HttpResponseError as e:
            if e.status_code == 404 and "ParentResourceNotFound" in str(e):
                raise ResourceNotFoundError(
                    POLICY_PARENT_RESOURCE_NOT_FOUND_MSG.format(
                        namespace_name=namespace_name, resource_group_name=resource_group_name
                    )
                )
            raise

    def delete(self, policy_name: str, namespace_name: str, resource_group_name: str, **kwargs):
        with console.status(f"Deleting policy '{policy_name}' from namespace {namespace_name}..."):
            poller = self.client.policies.begin_delete(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                policy_name=policy_name,
            )
            return wait_for_terminal_state(poller, **kwargs)

    def update(
        self,
        policy_name: str,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        certificate_validity_days: Optional[int] = None,
        **kwargs,
    ):
        resource = self.show(
            policy_name=policy_name, namespace_name=namespace_name, resource_group_name=resource_group_name
        )
        if tags:
            resource["tags"] = tags

        properties = resource["properties"]
        if certificate_validity_days:
            properties["certificate"]["leafCertificateConfiguration"][
                "validityPeriodInDays"
            ] = certificate_validity_days
        resource["properties"] = properties

        with console.status(f"Updating policy '{policy_name}' for namespace {namespace_name}..."):
            poller = self.client.policies.begin_create_or_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                policy_name=policy_name,
                resource=resource,
            )
            return wait_for_terminal_state(poller, **kwargs)
