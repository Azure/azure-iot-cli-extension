# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import Optional

from azure.cli.core.azclierror import ResourceNotFoundError
from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import FileUpload


class CentralFileUploadProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().file_uploads

        # Cache
        self._fileupload = {}

    def get(self) -> FileUpload:
        # Try cache
        if not self._fileupload:
            try:
                fileupload = self.sdk.get()
            except CloudError as e:
                handle_service_exception(e)

            if not fileupload:
                raise ResourceNotFoundError("No file upload account found")

            # Update cache
            self._fileupload = fileupload

        return self._fileupload

    def delete(self) -> FileUpload:
        try:
            result = self.sdk.remove()
        except CloudError as e:
            handle_service_exception(e)

        # Delete cache
        self._fileupload = {}
        return result

    def create(
        self,
        connection_string: str,
        container: str,
        account: Optional[str] = None,
        sasTtl: Optional[str] = None,
    ):
        payload = {
            "connectionString": connection_string,
            "container": container
        }

        if account:
            payload["account"] = account
        if sasTtl:
            payload["sasTtl"] = sasTtl

        try:
            result = self.sdk.create(body=payload)
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._fileupload = result
        return self._fileupload

    def update(
        self,
        connection_string: Optional[str] = None,
        container: Optional[str] = None,
        account: Optional[str] = None,
        sasTtl: Optional[str] = None,
    ):
        payload = {}

        if connection_string:
            payload["connectionString"] = connection_string
        if container:
            payload["container"] = container
        if account:
            payload["account"] = account
        if sasTtl:
            payload["sasTtl"] = sasTtl

        try:
            result = self.sdk.update(body=payload)
        except CloudError as e:
            handle_service_exception(e)
        
        # Update cache
        self._fileupload = result
        return self._fileupload
