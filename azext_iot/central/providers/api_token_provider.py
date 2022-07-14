# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List

from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.ga_2022_05_31.models import ApiToken


class CentralApiTokenProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk = self.get_sdk().api_tokens

    def create(
        self,
        token_id: str,
        role: str,
        org_id: str,
    ) -> ApiToken:
        payload = {
            "roles": [
                {"role": role},
            ],
        }

        if org_id:
            payload["roles"][0]["organization"] = org_id

        try:
            return self.sdk.create(token_id=token_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

    def list(self) -> List[ApiToken]:
        try:
            return self.sdk.list()
        except CloudError as e:
            handle_service_exception(e)

    def get(
        self,
        token_id: str,
    ) -> ApiToken:
        try:
            return self.sdk.get(token_id=token_id)
        except CloudError as e:
            handle_service_exception(e)

    def delete(
        self,
        token_id: str,
    ):
        try:
            return self.sdk.remove(token_id=token_id)
        except CloudError as e:
            handle_service_exception(e)
