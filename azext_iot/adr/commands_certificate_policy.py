# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from knack.log import get_logger

from azext_iot.adr.providers.certificate_policy import CertificatePolicyProvider

logger = get_logger(__name__)


def adr_ca_policy_create(
    cmd,
    certificate_policy_name: str,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    validity_days: int,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    **kwargs,
):
    provider = CertificatePolicyProvider(cmd)
    return provider.create(
        certificate_policy_name=certificate_policy_name,
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        validity_days=validity_days,
        location=location,
        tags=tags,
        **kwargs,
    )


def adr_ca_policy_show(
    cmd,
    certificate_policy_name: str,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = CertificatePolicyProvider(cmd)
    return provider.show(
        certificate_policy_name=certificate_policy_name,
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_ca_policy_list(cmd, certificate_authority_name: str, namespace_name: str, resource_group_name: str):
    provider = CertificatePolicyProvider(cmd)
    return provider.list(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_ca_policy_update(
    cmd,
    certificate_policy_name: str,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    validity_days: Optional[int] = None,
    **kwargs,
):
    provider = CertificatePolicyProvider(cmd)
    return provider.update(
        certificate_policy_name=certificate_policy_name,
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        tags=tags,
        validity_days=validity_days,
        **kwargs,
    )


def adr_ca_policy_delete(
    cmd,
    certificate_policy_name: str,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    **kwargs,
):
    provider = CertificatePolicyProvider(cmd)
    return provider.delete(
        certificate_policy_name=certificate_policy_name,
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        **kwargs,
    )
