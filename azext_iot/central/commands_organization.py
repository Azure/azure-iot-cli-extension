# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralOrganizationProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.v1_1_preview import OrganizationV1_1_preview


def get_org(
    cmd,
    app_id: str,
    org_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> OrganizationV1_1_preview:
    provider = CentralOrganizationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_organization(
        org_id=org_id, central_dns_suffix=central_dns_suffix
    )


def delete_org(
    cmd,
    app_id: str,
    org_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> OrganizationV1_1_preview:
    provider = CentralOrganizationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.delete_organization(
        org_id=org_id, central_dns_suffix=central_dns_suffix
    )


def list_orgs(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[OrganizationV1_1_preview]:
    provider = CentralOrganizationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_organizations(central_dns_suffix=central_dns_suffix)


def create_org(
    cmd,
    app_id: str,
    org_id: str,
    org_name=None,
    parent_org=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> OrganizationV1_1_preview:
    provider = CentralOrganizationProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.create_organization(
        org_id=org_id,
        org_name=org_name,
        parent_org=parent_org,
        central_dns_suffix=central_dns_suffix,
    )
