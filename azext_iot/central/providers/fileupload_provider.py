# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azure.cli.core.azclierror import ResourceNotFoundError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.ga_2022_07_31 import FileUploadGa

logger = get_logger(__name__)


class CentralFileUploadProvider:
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        """
        Provider for fileuploads APIs

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
        self._fileupload = {}

    def get_fileupload(
        self,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> FileUploadGa:
        # get or add to cache
        if not self._fileupload:
            fileupload = central_services.file_upload.get_fileupload(
                cmd=self._cmd,
                app_id=self._app_id,
                token=self._token,
                api_version=self._api_version,
                central_dns_suffix=central_dns_suffix,
            )

            if not fileupload:
                raise ResourceNotFoundError("No file upload account found")

            self._fileupload = fileupload

        return self._fileupload

    def delete_fileupload(
        self,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> FileUploadGa:
        # get or add to cache
        res = central_services.file_upload.delete_fileupload(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dns_suffix,
        )

        return res

    def create_fileupload(
        self,
        connection_string,
        container,
        account,
        sasTtl,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        # get or add to cache
        res = central_services.file_upload.createorupdate_fileupload(
            cmd=self._cmd,
            app_id=self._app_id,
            connection_string=connection_string,
            container=container,
            account=account,
            sasTtl=sasTtl,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        return res

    def update_fileupload(
        self,
        connection_string,
        container,
        account,
        sasTtl,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        # get or add to cache
        res = central_services.file_upload.createorupdate_fileupload(
            cmd=self._cmd,
            app_id=self._app_id,
            connection_string=connection_string,
            container=container,
            account=account,
            sasTtl=sasTtl,
            update=True,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        return res
