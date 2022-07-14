# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List

from azext_iot.central.providers import CentralRoleProvider
from azext_iot.sdk.central.ga_2022_05_31.models import Role


def get_role(
    cmd,
    app_id: str,
    role_id: str,
) -> Role:
    provider = CentralRoleProvider(cmd=cmd, app_id=app_id)
    return provider.get(role_id=role_id)


def list_roles(
    cmd,
    app_id: str,
) -> List[Role]:
    provider = CentralRoleProvider(cmd=cmd, app_id=app_id)
    return provider.list()
