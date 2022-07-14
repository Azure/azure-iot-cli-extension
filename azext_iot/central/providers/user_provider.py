# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from re import search
from typing import List

from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import User
from azext_iot.central.models.enum import (
    Role,
    UserTypeV1,
    get_enum_keys,
)
from azure.cli.core.azclierror import RequiredArgumentMissingError


ROLE_PATTERN = r"([\S]+)\\\\([\S]+)"


class CentralUserProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().users

    def create_service_principal(
        self,
        assignee: str,
        tenant_id: str,
        object_id: str,
        role: str,
    ) -> User:
        if not tenant_id:
            raise RequiredArgumentMissingError("Must specify --tenant-id when adding a service principal")

        if not object_id:
            raise RequiredArgumentMissingError("Must specify --object-id when adding a service principal")

        payload = {
            "type": UserTypeV1.service_principal.value,
        }

        if role:
            payload["roles"] = self._create_roles(role)

        if tenant_id:
            payload["tenantId"] = tenant_id

        if object_id:
            payload["objectId"] = object_id

        try:
            return self.sdk.create(user_id=assignee, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def update_service_principal(
        self,
        assignee: str,
        tenant_id: str,
        object_id: str,
        roles: str,
    ) -> User:
        if not tenant_id:
            raise RequiredArgumentMissingError("Must specify --tenant-id when adding a service principal")

        if not object_id:
            raise RequiredArgumentMissingError("Must specify --object-id when adding a service principal")

        payload = {
            "type": UserTypeV1.service_principal.value,
        }

        if roles:
            payload["roles"] = self._create_roles(roles)

        if tenant_id:
            payload["tenantId"] = tenant_id

        if object_id:
            payload["objectId"] = object_id

        try:
            return self.sdk.update(user_id=assignee, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def list(self) -> List[User]:
        try:
            return self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

    def get(
        self,
        assignee: str,
    ) -> User:
        try:
            return self.sdk.get(user_id=assignee)
        except CloudError as e:
            handle_service_exception(e)

    def delete(
        self,
        assignee: str
    ):
        try:
            return self.sdk.remove(user_id=assignee)
        except CloudError as e:
            handle_service_exception(e)

    def create_email_user(
        self,
        assignee: str,
        email: str,
        role: str,
    ) -> User:
        if not email:
            raise RequiredArgumentMissingError("Must specify --email when adding a user by email")

        payload = {"type": UserTypeV1.email.value, "roles": []}

        if role:
            payload["roles"] = self._create_roles(role)

        if email:
            payload["email"] = email

        try:
            return self.sdk.create(user_id=assignee, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def update_email_user(
        self,
        assignee: str,
        email: str,
        roles: str,
    ) -> User:
        if not email:
            raise RequiredArgumentMissingError("Must specify --email when adding a user by email")

        payload = {"type": UserTypeV1.email.value, "roles": []}

        if roles:
            payload["roles"] = self._create_roles(roles)

        try:
            return self.sdk.update(user_id=assignee, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def _create_roles(self, roles: str):
        result_roles = []
        parsed_roles = roles.split(",")
        for role in parsed_roles:
            org_id = None
            match = search(ROLE_PATTERN, role)
            if match and len(match.groups()) == 2:
                # role is an org role
                org_id = match[1]
                role_id = (
                    Role[match[2]].value if match[2] in get_enum_keys(Role) else match[2]
                )
            else:
                role_id = Role[role].value if role in get_enum_keys(Role) else role

            if org_id:
                result_roles.append({"role": role_id, "organization": org_id})
            else:
                result_roles.append({"role": role_id})

        return result_roles
