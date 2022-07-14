# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.identity import AzureCliCredential

from azext_iot.constants import USER_AGENT
from azext_iot.sdk.central.ga_2022_05_31 import AzureIoTCentral
from azext_iot.sdk.central.preview_2022_06_30 import AzureIoTCentral as AzureIoTCentralPreview


class IoTCentralProvider(object):
    def __init__(self, cmd, app_id, token=None):
        assert cmd
        assert app_id

        self.cmd = cmd
        self.app_id = app_id
        self.token = token

        # AzureCliCredential does not take any parameters, 
        # instead relying on the Azure CLI authenticated user to authenticate.
        self.cred = AzureCliCredential()

    # IoT Central latest GA version sdk
    def get_sdk(self) -> AzureIoTCentral:
        client = AzureIoTCentral(
            subdomain=self.app_id,
            credential=self.cred,
        )

        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client

    # IoT Central latest preview version sdk
    def get_sdk_preview(self) -> AzureIoTCentralPreview:
        client = AzureIoTCentralPreview(
            subdomain=self.app_id,
            credential=self.cred,
        )

        try:
            client._config.user_agent_policy.add_user_agent(USER_AGENT)
        except Exception:
            pass

        return client
