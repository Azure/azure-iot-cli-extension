# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.product.providers.auth import AICSAuthentication
from azext_iot.sdk.product import AICSAPI
from azext_iot.product.shared import BASE_URL
from azext_iot.constants import VERSION as cli_version, USER_AGENT

__all__ = ["aics_service_factory", "AICSServiceProvider"]


def aics_service_factory(cmd, base_url):
    creds = AICSAuthentication(cmd=cmd, base_url=base_url or BASE_URL)
    api = AICSAPI(base_url=base_url or BASE_URL, credentials=creds)

    api.config.add_user_agent(USER_AGENT)
    api.config.add_user_agent("azcli/aics/{}".format(cli_version))

    return api


class AICSServiceProvider(object):
    def __init__(self, cmd, base_url):
        assert cmd
        self.cmd = cmd
        self.base_url = base_url

    def get_mgmt_sdk(self):
        return aics_service_factory(self.cmd, self.base_url)
