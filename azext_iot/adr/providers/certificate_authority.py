# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import ArgumentUsageError, RequiredArgumentMissingError
from azure.cli.core.commands.client_factory import get_subscription_id

from azext_iot.adr.common import (
    DEFAULT_NS_CA_KEY_TYPE,
    CertificateAuthorityIssuerType,
    CertificateAuthorityType,
    compose_namespace_child_arm_id,
)
from azext_iot.adr.providers.base import ADRProvider

_CA_CHILD_TYPE = "certificateAuthorities"


class CertificateAuthorityProvider(ADRProvider):
    def __init__(self, cmd):
        super(CertificateAuthorityProvider, self).__init__(cmd)

    def create(
        self,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        certificate_authority_type: str,
        issuer_type: Optional[str] = None,
        issuer_certificate_authority_name: Optional[str] = None,
        key_type: Optional[str] = None,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ):
        location = self._resolve_location(namespace_name, resource_group_name, location)

        properties = {
            "certificateAuthorityType": certificate_authority_type,
            "keyType": key_type or DEFAULT_NS_CA_KEY_TYPE,
        }
        if certificate_authority_type == CertificateAuthorityType.root.value:
            if issuer_type or issuer_certificate_authority_name:
                raise ArgumentUsageError(
                    "--issuer-type and --issuer-ca-name are only valid when --type ICA."
                )
        elif certificate_authority_type == CertificateAuthorityType.ica.value:
            if not issuer_type:
                raise RequiredArgumentMissingError("--issuer-type is required when --type ICA.")
            issuer = {"issuerType": issuer_type}
            if issuer_type == CertificateAuthorityIssuerType.microsoft.value:
                if not issuer_certificate_authority_name:
                    raise RequiredArgumentMissingError(
                        "--issuer-ca-name is required when --issuer-type Microsoft."
                    )
                issuer["certificateAuthorityResourceId"] = compose_namespace_child_arm_id(
                    subscription_id=get_subscription_id(self.cmd.cli_ctx),
                    resource_group_name=resource_group_name,
                    namespace_name=namespace_name,
                    child_type=_CA_CHILD_TYPE,
                    child_name=issuer_certificate_authority_name,
                )
            elif issuer_type == CertificateAuthorityIssuerType.external.value:
                if issuer_certificate_authority_name:
                    raise ArgumentUsageError(
                        "--issuer-ca-name cannot be used when --issuer-type External."
                    )
            else:
                raise ArgumentUsageError(
                    "--issuer-type must be either Microsoft or External."
                )
            properties["issuer"] = issuer
        else:
            raise ArgumentUsageError("--type must be either Root or ICA.")

        resource = {
            "location": location,
            "properties": properties,
        }
        if tags is not None:
            resource["tags"] = tags

        poller = self.client.certificate_authorities.begin_create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
            resource=resource,
        )
        return self._wait(
            poller,
            f"Creating certificate authority '{certificate_authority_name}' on namespace {namespace_name}...",
            **kwargs,
        )

    def show(self, certificate_authority_name: str, namespace_name: str, resource_group_name: str):
        return self.client.certificate_authorities.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
        )

    def list(self, namespace_name: str, resource_group_name: str):
        return list(
            self.client.certificate_authorities.list_by_namespace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
        )

    def update(
        self,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ):
        if tags is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --tags to update the certificate authority."
            )

        properties: dict = {"tags": tags}

        no_wait = kwargs.pop("no_wait", False)
        poller = self.client.certificate_authorities.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
            properties=properties,
        )
        if no_wait:
            return poller
        self._wait(
            poller,
            f"Updating certificate authority '{certificate_authority_name}' on namespace {namespace_name}...",
            **kwargs,
        )
        # Update contract: the LRO body may be incomplete, so return a fresh GET of the resource.
        return self.show(
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )

    def delete(self, certificate_authority_name: str, namespace_name: str, resource_group_name: str, **kwargs):
        poller = self.client.certificate_authorities.begin_delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
        )
        return self._wait(
            poller,
            f"Deleting certificate authority '{certificate_authority_name}' from namespace {namespace_name}...",
            **kwargs,
        )

    def activate(
        self,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        certificate_chain: str,
        **kwargs,
    ):
        self._validate_action_issuer(
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            expected_issuer_type=CertificateAuthorityIssuerType.external.value,
            action="activate",
        )
        body = {"certificateChain": certificate_chain}
        poller = self.client.certificate_authorities.begin_activate(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
            body=body,
        )
        return self._wait(
            poller,
            f"Activating certificate authority '{certificate_authority_name}' on namespace {namespace_name}...",
            **kwargs,
        )

    def revoke(self, certificate_authority_name: str, namespace_name: str, resource_group_name: str, **kwargs):
        self._validate_action_issuer(
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            expected_issuer_type=CertificateAuthorityIssuerType.microsoft.value,
            action="revoke",
        )
        poller = self.client.certificate_authorities.begin_revoke_and_rotate(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            certificate_authority_name=certificate_authority_name,
        )
        return self._wait(
            poller,
            f"Revoking certificate authority '{certificate_authority_name}' on namespace {namespace_name}...",
            **kwargs,
        )

    def _validate_action_issuer(
        self,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        expected_issuer_type: str,
        action: str,
    ):
        certificate_authority = self.show(
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )
        properties = (certificate_authority or {}).get("properties") or {}
        issuer_type = (properties.get("issuer") or {}).get("issuerType")
        if (
            properties.get("certificateAuthorityType") != CertificateAuthorityType.ica.value
            or issuer_type != expected_issuer_type
        ):
            raise ArgumentUsageError(
                f"Certificate authority '{certificate_authority_name}' cannot be {action}d. "
                f"The {action} operation requires an ICA with issuerType '{expected_issuer_type}'."
            )
