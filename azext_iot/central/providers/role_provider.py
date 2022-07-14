# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List

from azure.cli.core.azclierror import ResourceNotFoundError
from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import Role


class CentralRoleProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().roles

        # Cache
        self._roles = {}

    def list(self) -> List[Role]:
        try:
            roles = self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._roles.update({role.id: role for role in roles})

        return roles

    def get(
        self,
        role_id,
    ) -> Role:
        # Try cache
        role = self._roles.get(role_id)

        if not role:
            try:
                role = self.sdk.get(role_id=role_id)
            except CloudError as e:
                handle_service_exception(e)

        if not role:
            raise ResourceNotFoundError("No role found with id: '{}'.".format(role_id))

        # Update cache
        self._roles[role_id] = role

        return role
