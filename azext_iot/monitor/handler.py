# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re

from azext_iot.monitor.parser import MessageParser


def parse_message(msg, device_id, properties, continuous_output):
    parser = MessageParser()
    origin_device_id = parser.parse_device_id(msg)

    if not _should_process_device(origin_device_id, device_id):
        return

    parsed_message = parser.parse_message(msg, properties)

    if continuous_output:
        print(json.dumps(parsed_message, indent=4))

    return parsed_message


def _should_process_device(origin_device_id, device_id):
    if device_id and device_id != origin_device_id:
        if "*" in device_id or "?" in device_id:
            regex = re.escape(device_id).replace("\\*", ".*").replace("\\?", ".") + "$"
            if not re.match(regex, origin_device_id):
                return False
        else:
            return False

    return True
