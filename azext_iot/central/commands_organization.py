# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.preview import CentralOrganizationProviderPreview
from azext_iot.central.models.enum import ApiVersion


def get_org(
    cmd,
    app_id: str,
    org_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
):
    provider = CentralOrganizationProviderPreview(cmd=cmd, app_id=app_id, token=token)

    return provider.get_organization(
        org_id=org_id, central_dns_suffix=central_dns_suffix
    )


def list_orgs(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
):
    provider = CentralOrganizationProviderPreview(cmd=cmd, app_id=app_id, token=token)

    return provider.list_organizations(central_dns_suffix=central_dns_suffix)


def create_org(
    cmd,
    app_id: str,
    org_id: str,
    org_name=None,
    parent_org=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
):
    provider = CentralOrganizationProviderPreview(cmd=cmd, app_id=app_id, token=token)
    return provider.create_organization(
        org_id=org_id,
        org_name=org_name,
        parent_org=parent_org,
        central_dns_suffix=central_dns_suffix,
    )
