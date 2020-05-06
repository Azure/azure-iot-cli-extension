# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


def generate_on_start_string(device_id, pnp_context):
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    return "Starting {}event monitor,{} use ctrl-c to stop...".format(
        "Digital Twin " if pnp_context else "",
        device_filter_txt if device_filter_txt else "",
    )


def stop_monitor():
    raise KeyboardInterrupt()
