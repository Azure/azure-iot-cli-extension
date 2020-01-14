# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot._factory import _bind_sdk


class IoTHubProvider(object):
    def __init__(self, cmd, hub_name, rg, login=None):
        self.cmd = cmd
        self.hub_name = hub_name
        self.rg = rg
        self.target = get_iot_hub_connection_string(
            cmd=self.cmd,
            hub_name=self.hub_name,
            resource_group_name=self.rg,
            login=login,
        )

    def get_sdk(self, sdk_type):
        return _bind_sdk(self.target, sdk_type)
