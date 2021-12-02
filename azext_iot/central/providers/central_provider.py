# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger

logger = get_logger(__name__)


class CentralProvider:
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        """
        Base provider for IoT Central operations

        Args:
            cmd: command passed into az
            app_id: name of app (used for forming request URL)
            api_version: API version (appendend to request URL)
            token: (OPTIONAL) authorization token to fetch API token details from IoTC.
                MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
                Useful in scenarios where user doesn't own the app
                therefore AAD token won't work, but a SAS token generated by owner will
        """
        self._cmd = cmd
        self._app_id = app_id
        self._token = token
        self._api_version = api_version