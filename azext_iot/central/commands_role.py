# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import Union, List
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralRoleProvider
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.models.preview import RolePreview
from azext_iot.central.models.v1_1_preview import RoleV1_1_preview
from azext_iot.central.models.v1 import RoleV1

RoleType = Union[RoleV1, RoleV1_1_preview, RolePreview]


def get_role(
    cmd,
    app_id: str,
    role_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> RoleType:
    provider = CentralRoleProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_role(role_id=role_id, central_dns_suffix=central_dns_suffix)


def list_roles(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.ga_2022_05_31.value,
) -> List[RoleType]:
    provider = CentralRoleProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_roles(central_dns_suffix=central_dns_suffix)
