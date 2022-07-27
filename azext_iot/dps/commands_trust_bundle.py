# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from knack.log import get_logger
from azext_iot.dps.providers.trust_bundle import TrustBundleProvider

logger = get_logger(__name__)


def create_trust_bundle(
    cmd,
    trust_bundle_id: str,
    trusted_certificates: str,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    trust_bundle_provider = TrustBundleProvider(
        cmd=cmd,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    trust_bundle_provider.create(trust_bundle_id=trust_bundle_id, certificates=trusted_certificates)

def update_trust_bundle(
    cmd,
    trust_bundle_id: str,
    trusted_certificates: str,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    trust_bundle_provider = TrustBundleProvider(
        cmd=cmd,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    trust_bundle_provider.update(trust_bundle_id=trust_bundle_id, certificates=trusted_certificates)

def show_trust_bundle(
    cmd,
    trust_bundle_id: str,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    trust_bundle_provider = TrustBundleProvider(
        cmd=cmd,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    trust_bundle_provider.get(trust_bundle_id=trust_bundle_id)

def list_trust_bundles(
    cmd,
    with_certificate_data: bool = False,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    trust_bundle_provider = TrustBundleProvider(
        cmd=cmd,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    
    trust_bundle_provider.list(with_certificate_data=with_certificate_data)

def delete_trust_bundle(
    cmd,
    trust_bundle_id: str,
    dps_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None,
):
    trust_bundle_provider = TrustBundleProvider(
        cmd=cmd,
        dps_name=dps_name,
        resource_group_name=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
    )
    trust_bundle_provider.delete(trust_bundle_id=trust_bundle_id)