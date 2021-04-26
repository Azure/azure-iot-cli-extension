# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.sdk.digitaltwins.controlplane import AzureDigitalTwinsManagementClient
from azext_iot.sdk.digitaltwins.controlplane.models import ErrorResponseException
from msrestazure.azure_exceptions import CloudError
from azext_iot.constants import USER_AGENT

__all__ = [
    "digitaltwins_service_factory",
    "DigitalTwinsResourceManager",
    "CloudError",
    "ErrorResponseException",
]


def digitaltwins_service_factory(cli_ctx, *_) -> AzureDigitalTwinsManagementClient:
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        AzureDigitalTwinsManagementClient: Top level client instance.
    """
    from azure.cli.core.commands.client_factory import get_mgmt_service_client

    return get_mgmt_service_client(cli_ctx, AzureDigitalTwinsManagementClient)


class DigitalTwinsResourceManager(object):
    def __init__(self, cmd):
        assert cmd
        self.cmd = cmd

    def get_mgmt_sdk(self):
        client = digitaltwins_service_factory(self.cmd.cli_ctx)
        client.config.add_user_agent(USER_AGENT)
        return client
