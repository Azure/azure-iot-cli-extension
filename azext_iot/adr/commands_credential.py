# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from knack.log import get_logger

from azext_iot.adr.providers.credential import CredentialProvider

logger = get_logger(__name__)


def adr_credential_create(cmd, namespace_name: str, resource_group_name: str, tags: Optional[Dict[str, str]] = None):
    provider = CredentialProvider(cmd)
    return provider.create(namespace_name=namespace_name, resource_group_name=resource_group_name, tags=tags)


def adr_credential_show(cmd, namespace_name: str, resource_group_name: str):
    provider = CredentialProvider(cmd)
    return provider.show(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_credential_delete(cmd, namespace_name: str, resource_group_name: str):
    provider = CredentialProvider(cmd)
    return provider.delete(namespace_name=namespace_name, resource_group_name=resource_group_name)


def adr_credential_synchronize(cmd, namespace_name: str, resource_group_name: str):
    provider = CredentialProvider(cmd)
    return provider.synchronize(namespace_name=namespace_name, resource_group_name=resource_group_name)
