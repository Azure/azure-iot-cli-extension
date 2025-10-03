# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from knack.log import get_logger

from azext_iot._factory import adr_service_factory

__all__ = ["ADRProvider"]

logger = get_logger(__name__)


class ADRProvider(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.client = adr_service_factory(cmd.cli_ctx)

    def _ensure_location(self, cli_ctx, resource_group_name: str, location: Optional[str] = None):
        if location:
            return location

        # Get resource group location as fallback
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.mgmt.resource import ResourceManagementClient

        resource_client = get_mgmt_service_client(cli_ctx, ResourceManagementClient)
        rg = resource_client.resource_groups.get(resource_group_name)
        return rg.location
