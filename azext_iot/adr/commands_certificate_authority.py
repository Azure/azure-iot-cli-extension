# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from knack.log import get_logger

from azext_iot.adr.providers.certificate_authority import CertificateAuthorityProvider

logger = get_logger(__name__)


def adr_ca_create(
    cmd,
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
    provider = CertificateAuthorityProvider(cmd)
    return provider.create(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        certificate_authority_type=certificate_authority_type,
        issuer_type=issuer_type,
        issuer_certificate_authority_name=issuer_certificate_authority_name,
        key_type=key_type,
        location=location,
        tags=tags,
        **kwargs,
    )


def adr_ca_show(cmd, certificate_authority_name: str, namespace_name: str, resource_group_name: str):
    provider = CertificateAuthorityProvider(cmd)
    return provider.show(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_ca_list(cmd, namespace_name: str, resource_group_name: str):
    provider = CertificateAuthorityProvider(cmd)
    return provider.list(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_ca_update(
    cmd,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
    **kwargs,
):
    provider = CertificateAuthorityProvider(cmd)
    return provider.update(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        tags=tags,
        **kwargs,
    )


def adr_ca_delete(cmd, certificate_authority_name: str, namespace_name: str, resource_group_name: str, **kwargs):
    provider = CertificateAuthorityProvider(cmd)
    return provider.delete(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        **kwargs,
    )


def adr_ca_activate(
    cmd,
    certificate_authority_name: str,
    namespace_name: str,
    resource_group_name: str,
    certificate_chain_file: str,
    **kwargs,
):
    from azext_iot.common.utility import read_file_content

    certificate_chain = read_file_content(certificate_chain_file)
    provider = CertificateAuthorityProvider(cmd)
    return provider.activate(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        certificate_chain=certificate_chain,
        **kwargs,
    )


def adr_ca_revoke(cmd, certificate_authority_name: str, namespace_name: str, resource_group_name: str, **kwargs):
    provider = CertificateAuthorityProvider(cmd)
    return provider.revoke(
        certificate_authority_name=certificate_authority_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        **kwargs,
    )
