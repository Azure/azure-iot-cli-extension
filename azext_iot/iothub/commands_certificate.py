# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.certificate import CertificateProvider
from knack.log import get_logger

logger = get_logger(__name__)


def certificate_root_authority_show(
    cmd,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None
):
    resource = CertificateProvider(
        cmd=cmd,
        hub_name=hub_name,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return resource.iot_hub_certificate_root_authority_show()


def certificate_root_authority_set(
    cmd,
    ca_version,
    hub_name=None,
    resource_group_name=None,
    login=None,
    auth_type_dataplane=None,
    yes=False
):
    resource = CertificateProvider(
        cmd=cmd,
        hub_name=hub_name,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return resource.iot_hub_certificate_root_authority_set(
        ca_version=ca_version,
        yes=yes
    )
