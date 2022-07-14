# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Optional
from azext_iot.central.providers import CentralOrganizationProvider
from azext_iot.sdk.central.ga_2022_05_31.models import Organization


def get_org(
    cmd,
    app_id: str,
    org_id: str,
) -> Organization:
    provider = CentralOrganizationProvider(cmd=cmd, app_id=app_id)
    return provider.get(org_id=org_id)


def delete_org(
    cmd,
    app_id: str,
    org_id: str,
) -> Organization:
    provider = CentralOrganizationProvider(cmd=cmd, app_id=app_id)
    return provider.delete(org_id=org_id)


def list_orgs(
    cmd,
    app_id: str,
) -> List[Organization]:
    provider = CentralOrganizationProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def create_org(
    cmd,
    app_id: str,
    org_id: str,
    org_name: Optional[str] = None,
    parent_org: Optional[str] = None,
) -> Organization:
    provider = CentralOrganizationProvider(cmd=cmd, app_id=app_id)
    return provider.create(
        org_id=org_id,
        org_name=org_name,
        parent_org=parent_org,
    )


def update_org(
    cmd,
    app_id: str,
    org_id: str,
    org_name: Optional[str] = None,
    parent_org: Optional[str] = None,
) -> Organization:
    provider = CentralOrganizationProvider(cmd=cmd, app_id=app_id)
    return provider.update(
        org_id=org_id,
        org_name=org_name,
        parent_org=parent_org,
    )
