# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.resource import ResourceProvider
from azext_iot.digitaltwins.providers.auth import DigitalTwinAuthentication
from azext_iot.sdk.digitaltwins.dataplane import AzureDigitalTwinsAPI
from azext_iot.sdk.digitaltwins.dataplane.models import ErrorResponseException
from azext_iot.constants import DIGITALTWINS_RESOURCE_ID
from azext_iot.common.utility import valid_hostname
from knack.cli import CLIError

__all__ = ["DigitalTwinsProvider", "ErrorResponseException"]


class DigitalTwinsProvider(object):
    def __init__(self, cmd, name, rg=None):
        assert cmd
        assert name

        self.cmd = cmd
        self.name = name
        self.rg = rg
        self.resource_id = DIGITALTWINS_RESOURCE_ID
        self.rp = ResourceProvider(self.cmd)

    def _get_endpoint(self):
        host_name = None
        https_prefix = "https://"
        http_prefix = "http://"

        if self.name.lower().startswith(https_prefix):
            self.name = self.name[len(https_prefix):]
        elif self.name.lower().startswith(http_prefix):
            self.name = self.name[len(http_prefix):]

        if not all([valid_hostname(self.name), "." in self.name]):
            instance = self.rp.find_instance(name=self.name, resource_group_name=self.rg)
            host_name = instance.host_name
            if not host_name:
                raise CLIError("Instance has invalid hostName. Aborting operation...")
        else:
            host_name = self.name

        return "https://{}".format(host_name)

    def get_sdk(self):
        creds = DigitalTwinAuthentication(cmd=self.cmd, resource_id=self.resource_id)
        return AzureDigitalTwinsAPI(base_url=self._get_endpoint(), credentials=creds)
