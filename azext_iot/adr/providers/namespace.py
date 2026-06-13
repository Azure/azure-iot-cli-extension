# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import MutuallyExclusiveArgumentError
from knack.log import get_logger
from rich.console import Console

from azext_iot.adr.common import (
    DEFAULT_NS_POLICY_NAME,
    DEFAULT_NS_POLICY_CERT_KEY_TYPE,
    DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS,
    IdentityType,
)
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.common.utility import wait_for_terminal_state

console = Console()
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
        enable_certificate_management: Optional[bool] = None,
        policy_name: Optional[str] = None,
        certificate_key_type: Optional[str] = None,
        certificate_subject: Optional[str] = None,
        certificate_validity_days: Optional[int] = None,
        **kwargs,
    ):
        # If any policy arguments provided, create policy
        should_create_credential_policy = any([
            enable_certificate_management,
            policy_name,
            certificate_key_type,
            certificate_subject,
            certificate_validity_days,
        ])

        if should_create_credential_policy:
            # user provided policy inputs but enable is strictly false
            if enable_certificate_management is False:
                raise MutuallyExclusiveArgumentError(
                    "Cannot create a custom policy if `--enable-certificate-management` is false."
                )

            # Set defaults for certificate parameters if not provided
            if certificate_key_type is None:
                certificate_key_type = DEFAULT_NS_POLICY_CERT_KEY_TYPE
            if certificate_validity_days is None:
                certificate_validity_days = DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS

        if not location:
            location = self._ensure_location(self.cmd.cli_ctx, resource_group_name, location)

        namespace_resource = {"location": location}

        # Default system assigned identity
        namespace_resource["identity"] = {"type": IdentityType.system_assigned.value}

        if tags:
            namespace_resource["tags"] = tags

        # TODO - CMS Preview - support messaging endpoints create

        with console.status(f"Creating namespace {namespace_name}..."):
            poller = self.client.namespaces.begin_create_or_replace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                resource=namespace_resource,
            )
            namespace_result = wait_for_terminal_state(poller, **kwargs)

        # TODO - CMS Preview - create response does not include resource group
        if not namespace_result.get("resourceGroup"):
            namespace_result["resourceGroup"] = resource_group_name

        if should_create_credential_policy:
            try:
                from azext_iot.adr.providers.credential import CredentialProvider

                credential_provider = CredentialProvider(self.cmd)
                credential_provider.create(
                    namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, **kwargs
                )
            except Exception as e:
                logger.error("Error creating default namespace credential: %s", str(e))

            try:
                from azext_iot.adr.providers.policy import PolicyProvider

                policy_provider = PolicyProvider(self.cmd)
                policy_provider.create(
                    policy_name=policy_name or DEFAULT_NS_POLICY_NAME,
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=location,
                    certificate_key_type=certificate_key_type,
                    certificate_subject=certificate_subject,
                    certificate_validity_days=certificate_validity_days,
                    **kwargs,
                )
            except Exception as e:
                logger.error("Error creating credential policy: %s", str(e))

        return namespace_result

    def show(self, namespace_name: str, resource_group_name: str):
        return self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

    def list(self, resource_group_name: Optional[str] = None):
        if resource_group_name:
            result = self.client.namespaces.list_by_resource_group(resource_group_name=resource_group_name)
        else:
            result = self.client.namespaces.list_by_subscription()
        return list(result)

    def delete(self, namespace_name: str, resource_group_name: str, **kwargs):
        logger.warning(
            "All child resources (credentials, policies, devices) under namespace '%s' will be deleted.",
            namespace_name,
        )
        logger.warning(
            "Deletion will fail if there are DPS or IoT Hub instances linked to this namespace. Unlink them first."
        )
        with console.status(f"Deleting namespace {namespace_name}..."):
            poller = self.client.namespaces.begin_delete(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            return wait_for_terminal_state(poller, **kwargs)

    def update(self, namespace_name: str, resource_group_name: str, tags: Optional[Dict[str, str]] = None, **kwargs):
        properties = {}
        if tags is not None:
            properties["tags"] = tags

        # TODO - CMS Preview - support messaging endpoints update

        with console.status(f"Updating namespace {namespace_name}..."):
            poller = self.client.namespaces.begin_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                properties=properties,
            )
            result = wait_for_terminal_state(poller, **kwargs)
            return result
