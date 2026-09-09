# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Any, Dict, Optional

from azure.cli.core.azclierror import CLIInternalError, InvalidArgumentValueError
from knack.log import get_logger
from rich.console import Console

from azext_iot._factory import adr_service_factory
from azext_iot.common.utility import process_json_arg, wait_for_terminal_state

__all__ = ["ADRProvider", "parse_json_object"]

logger = get_logger(__name__)
console = Console()


def parse_json_object(value: Any, argument_name: str) -> Dict[str, Any]:
    """Accept the extension's inline JSON and JSON-file argument forms."""
    if isinstance(value, str):
        try:
            value = process_json_arg(value, argument_name)
        except CLIInternalError as error:
            raise InvalidArgumentValueError(
                f"{argument_name} must be a valid JSON object or a path to a JSON file."
            ) from error
    if not isinstance(value, dict):
        raise InvalidArgumentValueError(
            f"{argument_name} must be a JSON object or a path to a JSON file."
        )
    return value


class ADRProvider(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.client = adr_service_factory(cmd.cli_ctx)

    def _wait(self, poller, status_message: str, **kwargs):
        if kwargs.pop("no_wait", False):
            return poller
        with console.status(status_message):
            return wait_for_terminal_state(poller, **kwargs)

    def _ensure_location(self, cli_ctx, resource_group_name: str, location: Optional[str] = None):
        if location:
            return location

        # Get resource group location as fallback
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.mgmt.resource import ResourceManagementClient

        resource_client = get_mgmt_service_client(cli_ctx, ResourceManagementClient)
        rg = resource_client.resource_groups.get(resource_group_name)
        return rg.location
