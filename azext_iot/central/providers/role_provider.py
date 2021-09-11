# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Union
from knack.util import CLIError
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.v1 import RoleV1
from azext_iot.central.models.v1_1_preview import RoleV1_1_preview
from azext_iot.central.models.preview import RolePreview

logger = get_logger(__name__)


class CentralRoleProvider:
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        """
        Provider for roles APIs

        Args:
            cmd: command passed into az
            app_id: name of app (used for forming request URL)
            api_version: API version (appendend to request URL)
            token: (OPTIONAL) authorization token to fetch device details from IoTC.
                MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
                Useful in scenarios where user doesn't own the app
                therefore AAD token won't work, but a SAS token generated by owner will
        """
        self._cmd = cmd
        self._app_id = app_id
        self._token = token
        self._api_version = api_version
        self._roles = {}

    def list_roles(
        self, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> List[Union[RoleV1, RoleV1_1_preview, RolePreview]]:
        roles = central_services.role.list_roles(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        self._roles.update({role.id: role for role in roles})

        return roles

    def get_role(
        self,
        role_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> Union[RoleV1, RoleV1_1_preview, RolePreview]:
        # get or add to cache
        role = self._roles.get(role_id)
        if not role:
            role = central_services.role.get_role(
                cmd=self._cmd,
                app_id=self._app_id,
                role_id=role_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=self._api_version,
            )
            self._roles[role_id] = role

        if not role:
            raise CLIError("No role found with id: '{}'.".format(role_id))

        return role
