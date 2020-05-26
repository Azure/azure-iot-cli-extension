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
from azext_iot.monitor.models.arguments import CommonHandlerArguments


class CommonHandler(AbstractBaseEventsHandler):
    def __init__(self, common_handler_args: CommonHandlerArguments):
        super(CommonHandler, self).__init__()
        self._common_handler_args = common_handler_args

    def parse_message(self, message):
        parser = CommonParser(
            message=message,
            common_parser_args=self._common_handler_args.common_parser_args,
        )

        if not self._should_process_device(parser.device_id):
            return

        if not self._should_process_interface(parser.interface_name):
            return

        if not self._should_process_module(parser.module_id):
            return

        result = parser.parse_message()

        if self._common_handler_args.output.lower() == "json":
            dump = json.dumps(result, indent=4)
        else:
            dump = yaml.safe_dump(result, default_flow_style=False)

        print(dump, flush=True)

    def _should_process_device(self, device_id):
        expected_device_id = self._common_handler_args.device_id
        expected_devices = self._common_handler_args.devices

        if expected_device_id and expected_device_id != device_id:
            if "*" in expected_device_id or "?" in expected_device_id:
                regex = (
                    re.escape(expected_device_id)
                    .replace("\\*", ".*")
                    .replace("\\?", ".")
                    + "$"
                )
                if not re.match(regex, device_id):
                    return False
            else:
                return False

        if expected_devices and device_id not in expected_devices:
            return False

        return True

    def _should_process_interface(self, interface_name):
        expected_interface_name = self._common_handler_args.interface_name

        # if no filter is specified, then process all interfaces
        if not expected_interface_name:
            return True

        # only process if the expected and actual interface name match
        return expected_interface_name == interface_name

    def _should_process_module(self, module_id):
        expected_module_id = self._common_handler_args.module_id

        # if no filter is specified, then process all modules
        if not expected_module_id:
            return True

        if expected_module_id and expected_module_id != module_id:
            if "*" in expected_module_id or "?" in expected_module_id:
                regex = (
                    re.escape(expected_module_id)
                    .replace("\\*", ".*")
                    .replace("\\?", ".")
                    + "$"
                )
                if not re.match(regex, module_id):
                    return False
            else:
                return False
        return True
