# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.preview_2022_06_30.models import QueryResponse


class CentralQueryProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str, query: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk_preview = self.get_sdk_preview().query
        self._query = query

    def run(self) -> QueryResponse:
        payload = {"query": self._query}

        try:
            response = self.sdk_preview.run(body=payload)
        except CloudError as e:
            handle_service_exception(e)

        return response
