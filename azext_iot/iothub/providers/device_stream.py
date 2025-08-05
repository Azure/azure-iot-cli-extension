# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from knack.log import get_logger
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.iothub.common import HUB_PROVIDER

logger = get_logger(__name__)
DEVICE_STREAMS_API_VERSION = "2023-06-30-preview"


class DeviceStreamProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: str,
        rg: Optional[str] = None,
    ):
        super(DeviceStreamProvider, self).__init__(cmd, hub_name, rg)
        self.cli = EmbeddedCLI(cli_ctx=self.cmd.cli_ctx)

    def show(self) -> Optional[dict]:
        result = self.cli.invoke(
            f"resource show -n {self.target['name']} -g {self.target['resourcegroup']} "
            f"--api-version {DEVICE_STREAMS_API_VERSION} --resource-type {HUB_PROVIDER}",
            capture_stderr=True
        ).as_json()
        device_streams = result.get("properties", {}).get("deviceStreams")
        if not device_streams:
            logger.warning("Device streams are not enabled for this IoT Hub.")
        return device_streams
