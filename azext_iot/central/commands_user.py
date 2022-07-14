# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Optional
from azext_iot.central.providers import CentralUserProvider
from azext_iot.sdk.central.ga_2022_05_31.models import User


def create_user(
    cmd,
    app_id: str,
    assignee: str,
    role: str,
    email: Optional[str] = None,
    tenant_id: Optional[str] = None,
    object_id: Optional[str] = None,
) -> User:
    provider = CentralUserProvider(cmd=cmd, app_id=app_id)

    if email:
        return provider.create_email_user(
            assignee=assignee,
            email=email,
            role=role,
        )

    return provider.create_service_principal(
        assignee=assignee,
        tenant_id=tenant_id,
        object_id=object_id,
        role=role,
    )


def update_user(
    cmd,
    app_id: str,
    assignee: str,
    roles: Optional[str] = None,
    email: Optional[str] = None,
    tenant_id: Optional[str] = None,
    object_id: Optional[str] = None,
) -> User:
    provider = CentralUserProvider(cmd=cmd, app_id=app_id)

    if email:
        return provider.update_email_user(
            assignee=assignee,
            email=email,
            roles=roles,
        )

    return provider.update_service_principal(
        assignee=assignee,
        tenant_id=tenant_id,
        object_id=object_id,
        roles=roles,
    )


def list_users(
    cmd,
    app_id: str,
) -> List[User]:
    provider = CentralUserProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def get_user(
    cmd,
    app_id: str,
    assignee: str,
) -> User:
    provider = CentralUserProvider(cmd=cmd, app_id=app_id)
    return provider.get(assignee=assignee)


def delete_user(
    cmd,
    app_id: str,
    assignee: str,
):
    provider = CentralUserProvider(cmd=cmd, app_id=app_id)
    return provider.delete(assignee=assignee)
