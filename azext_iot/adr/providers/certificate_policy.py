# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import (
    CA_PARENT_RESOURCE_NOT_FOUND_MSG,
    CertificateAuthorityType,
)
from azext_iot.adr.providers.base import ADRProvider


_MIN_VALIDITY_DAYS = 7
_MAX_VALIDITY_DAYS = 90


class CertificatePolicyProvider(ADRProvider):
    def __init__(self, cmd):
        super(CertificatePolicyProvider, self).__init__(cmd)

    def _handle_parent_not_found(self, e, certificate_authority_name, namespace_name, resource_group_name):
        # Translate the backend's opaque "ParentResourceNotFound" 404 (missing certificate
        # authority) into a friendly error via the shared base helper.
        self._raise_if_parent_not_found(
            e,
            CA_PARENT_RESOURCE_NOT_FOUND_MSG.format(
                certificate_authority_name=certificate_authority_name,
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
            ),
        )

    def _validate_issuing_ca(
        self,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        try:
            certificate_authority = self.client.certificate_authorities.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                certificate_authority_name=certificate_authority_name,
            )
        except HttpResponseError as error:
            if error.status_code == 404:
                raise ResourceNotFoundError(
                    CA_PARENT_RESOURCE_NOT_FOUND_MSG.format(
                        certificate_authority_name=certificate_authority_name,
                        namespace_name=namespace_name,
                        resource_group_name=resource_group_name,
                    )
                ) from error
            raise

        properties = (certificate_authority or {}).get("properties") or {}
        certificate_authority_type = properties.get("certificateAuthorityType")
        if certificate_authority_type != CertificateAuthorityType.ica.value:
            actual_type = certificate_authority_type or "unknown"
            raise InvalidArgumentValueError(
                f"Certificate policy creation requires an issuing certificate authority "
                f"with type 'ICA', but '{certificate_authority_name}' has type "
                f"'{actual_type}'. Create an ICA under a Root CA and pass its name "
                "with --ca-name."
            )

    @staticmethod
    def _validate_validity_days(validity_days: int):
        if not _MIN_VALIDITY_DAYS <= validity_days <= _MAX_VALIDITY_DAYS:
            raise InvalidArgumentValueError(
                f"--validity-days must be between {_MIN_VALIDITY_DAYS} and "
                f"{_MAX_VALIDITY_DAYS} days, inclusive. Received {validity_days}."
            )

    def create(
        self,
        certificate_policy_name: str,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        validity_days: int,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        **kwargs,
    ):
        self._validate_validity_days(validity_days)
        self._validate_issuing_ca(
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )
        location = self._resolve_location(namespace_name, resource_group_name, location)

        resource = {
            "location": location,
            "properties": {"certificate": {"validityPeriodInDays": validity_days}},
        }
        if tags is not None:
            resource["tags"] = tags

        no_wait = kwargs.pop("no_wait", False)
        try:
            poller = self.client.certificate_policies.begin_create_or_replace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                certificate_authority_name=certificate_authority_name,
                certificate_policy_name=certificate_policy_name,
                resource=resource,
            )
        except HttpResponseError as e:
            self._handle_parent_not_found(
                e, certificate_authority_name, namespace_name, resource_group_name
            )

        return self._wait(
            poller,
            f"Creating certificate policy '{certificate_policy_name}' on certificate authority "
            f"{certificate_authority_name}...",
            no_wait=no_wait,
            **kwargs,
        )

    def show(
        self,
        certificate_policy_name: str,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        try:
            return self.client.certificate_policies.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                certificate_authority_name=certificate_authority_name,
                certificate_policy_name=certificate_policy_name,
            )
        except HttpResponseError as e:
            self._handle_parent_not_found(e, certificate_authority_name, namespace_name, resource_group_name)

    def list(self, certificate_authority_name: str, namespace_name: str, resource_group_name: str):
        try:
            return list(
                self.client.certificate_policies.list_by_certificate_authority(
                    resource_group_name=resource_group_name,
                    namespace_name=namespace_name,
                    certificate_authority_name=certificate_authority_name,
                )
            )
        except HttpResponseError as e:
            self._handle_parent_not_found(e, certificate_authority_name, namespace_name, resource_group_name)

    def update(
        self,
        certificate_policy_name: str,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        validity_days: Optional[int] = None,
        **kwargs,
    ):
        if tags is None and validity_days is None:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --tags or --validity-days "
                "to update the certificate policy."
            )

        if validity_days is not None:
            self._validate_validity_days(validity_days)

        properties = {}
        if tags is not None:
            properties["tags"] = tags
        if validity_days is not None:
            properties["properties"] = {
                "certificate": {
                    "validityPeriodInDays": validity_days,
                }
            }

        no_wait = kwargs.pop("no_wait", False)
        try:
            poller = self.client.certificate_policies.begin_update(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                certificate_authority_name=certificate_authority_name,
                certificate_policy_name=certificate_policy_name,
                properties=properties,
            )
        except HttpResponseError as e:
            self._handle_parent_not_found(e, certificate_authority_name, namespace_name, resource_group_name)

        if no_wait:
            return poller
        self._wait(
            poller,
            f"Updating certificate policy '{certificate_policy_name}' on certificate authority "
            f"{certificate_authority_name}...",
            **kwargs,
        )
        # Update contract: the LRO body may be incomplete, so return a fresh GET of the resource.
        return self.show(
            certificate_policy_name=certificate_policy_name,
            certificate_authority_name=certificate_authority_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
        )

    def delete(
        self,
        certificate_policy_name: str,
        certificate_authority_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        no_wait = kwargs.pop("no_wait", False)
        try:
            poller = self.client.certificate_policies.begin_delete(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                certificate_authority_name=certificate_authority_name,
                certificate_policy_name=certificate_policy_name,
            )
        except HttpResponseError as e:
            self._handle_parent_not_found(e, certificate_authority_name, namespace_name, resource_group_name)

        if no_wait:
            return poller
        return self._wait(
            poller,
            f"Deleting certificate policy '{certificate_policy_name}' from certificate authority "
            f"{certificate_authority_name}...",
            **kwargs,
        )
