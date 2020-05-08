# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re
import yaml

from azext_iot.monitor.base_classes import AbstractBaseEventsHandler
from azext_iot.monitor.parsers.common_parser import CommonParser


class CommonHandler(AbstractBaseEventsHandler):
    """
    Handles messages as they are read from egress event hub.
    Use this handler if you aren't sure which handler is right for you.

    Args:
        device_id       (str)   only process messages sent by this device
        devices         (list)  only process messages sent by these devices
        interface_name  (str)   expected interface name of pnp device
        content_type    (str)   assumed content type (utf-8, ascii, etc)
        properties      (list)  list of properties to extract from message headers
        output          (str)   output format (json, yaml, etc)
    """

    def __init__(
        self,
        device_id: str,
        devices: list,
        interface_name: str,
        content_type: str,
        properties: list,
        output: str,
    ):
        super(CommonHandler, self).__init__()
        self.device_id = device_id
        self.devices = devices
        self.interface_name = interface_name
        self.content_type = content_type
        self.properties = properties
        self.output = output

    def parse_message(self, message):
        parser = CommonParser()
        device_id = parser.parse_device_id(message)

        if not self._should_process_device(device_id, self.device_id, self.devices):
            return

        parsed_message = parser.parse_message(
            message,
            properties=self.properties,
            interface_name=self.interface_name,
            content_type=self.content_type,
        )

        if self.output.lower() == "json":
            dump = json.dumps(parsed_message, indent=4)
        else:
            dump = yaml.safe_dump(parsed_message, default_flow_style=False)

        print(dump, flush=True)

    def _should_process_device(self, origin_device_id, device_id, devices):
        if device_id and device_id != origin_device_id:
            if "*" in device_id or "?" in device_id:
                regex = (
                    re.escape(device_id).replace("\\*", ".*").replace("\\?", ".") + "$"
                )
                if not re.match(regex, origin_device_id):
                    return False
            else:
                return False
        if devices and origin_device_id not in devices:
            return False

        return True
