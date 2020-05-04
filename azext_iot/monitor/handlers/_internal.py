# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re
import yaml

from azext_iot.monitor.handlers._parser import Event3Parser


def parse_message(
    msg,
    device_id,
    devices,
    pnp_context,
    interface_name,
    content_type,
    properties,
    output,
    validate_messages,
    simulate_errors,
    central_device_provider,
):
    parser = Event3Parser()
    origin_device_id = parser.parse_device_id(msg)

    if not _should_process_device(origin_device_id, device_id, devices):
        return

    parsed_msg = parser.parse_message(
        msg,
        pnp_context,
        interface_name,
        properties,
        content_type,
        simulate_errors,
        central_device_provider,
    )

    if output.lower() == "json":
        dump = json.dumps(parsed_msg, indent=4)
    else:
        dump = yaml.safe_dump(parsed_msg, default_flow_style=False)

    if validate_messages:
        parser.write_logs()

    if not validate_messages:
        print(dump, flush=True)


def _should_process_device(origin_device_id, device_id, devices):
    if device_id and device_id != origin_device_id:
        if "*" in device_id or "?" in device_id:
            regex = re.escape(device_id).replace("\\*", ".*").replace("\\?", ".") + "$"
            if not re.match(regex, origin_device_id):
                return False
        else:
            return False
    if devices and origin_device_id not in devices:
        return False

    return True
