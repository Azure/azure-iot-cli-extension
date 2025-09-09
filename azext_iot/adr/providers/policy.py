# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional
from knack.log import get_logger
from azext_iot.adr.providers.base import ADRProvider


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
    ):
        """Create a policy for an ADR namespace."""
        if not location:
            # TODO - CMS Preview - fetch location from the existing namespace
            namespace = self.client.namespaces.get(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            location = namespace.get("location")
        # fallback to RG location
        location = self._ensure_location(self.cmd.cli_ctx, resource_group_name, location)

        policy_resource = {"location": location}

        if tags:
            policy_resource["tags"] = tags

        # Build certificate configuration
        properties = {}

        if certificate_key_type or certificate_subject or certificate_validity_days:
            certificate_config = {}

            if certificate_key_type or certificate_subject:
                ca_config = {}
                if certificate_key_type:
                    ca_config["keyType"] = certificate_key_type
                if certificate_subject:
                    ca_config["subject"] = certificate_subject
                certificate_config["certificateAuthorityConfiguration"] = ca_config

            if certificate_validity_days:
                certificate_config["leafCertificateConfiguration"] = {"validityPeriodInDays": certificate_validity_days}

            properties["certificate"] = certificate_config

        policy_resource["properties"] = properties

        return self.client.policies.begin_create_or_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            policy_name=policy_name,
            resource=policy_resource,
        )

    def show(self, policy_name: str, namespace_name: str, resource_group_name: str):
        """Show a policy for an ADR namespace."""
        return self.client.policies.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            policy_name=policy_name,
        )

    def list(self, namespace_name: str, resource_group_name: Optional[str] = None):
        """List policies for ADR namespaces."""
        if resource_group_name:
            return list(
                self.client.policies.list_by_resource_group(
                    resource_group_name=resource_group_name,
                    namespace_name=namespace_name,
                )
            )
        else:
            return list(self.client.policies.list_by_subscription(namespace_name=namespace_name))

    def delete(self, policy_name: str, namespace_name: str, resource_group_name: str):
        """Delete a policy for an ADR namespace."""

        return self.client.policies.begin_delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            policy_name=policy_name,
        )

    def update(
        self,
        policy_name: str,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        certificate_subject: Optional[str] = None,
        certificate_validity_days: Optional[int] = None,
    ):
        """Update a policy for an ADR namespace."""
        update_payload = {}
        if tags:
            update_payload["tags"] = tags

        properties = {}
        if certificate_subject or certificate_validity_days:
            properties["certificate"] = {}
            if certificate_subject:
                ca_config = {}
                if certificate_subject:
                    ca_config["subject"] = certificate_subject
                properties["certificate"]["certificateAuthorityConfiguration"] = ca_config
            if certificate_validity_days:
                properties["certificate"]["leafCertificateConfiguration"] = {
                    "validityPeriodInDays": certificate_validity_days
                }
        if properties:
            update_payload["properties"] = properties

        # return if nothing to update
        if not update_payload:
            return

        return self.client.policies.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            policy_name=policy_name,
            properties=update_payload,
        )
