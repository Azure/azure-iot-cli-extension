# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
from asyncio import AbstractEventLoop


def generate_on_start_string(device_id=None):
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    return "Starting event monitor,{} use ctrl-c to stop...".format(
        device_filter_txt if device_filter_txt else "",
    )


def stop_monitor():
    raise KeyboardInterrupt()


def get_loop() -> AbstractEventLoop:
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop
