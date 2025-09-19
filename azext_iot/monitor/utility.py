# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

import asyncio


def generate_on_start_string(device_id=None):
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    return "Starting event monitor,{} use ctrl-c to stop...".format(
        device_filter_txt if device_filter_txt else "",
    )


def stop_monitor():
    raise KeyboardInterrupt()


def get_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


def unicode_decode(data: bytes, default: str = None):
    for encoding in ["utf-8", "utf-16", "utf-32"]:
        try:
            data = data.decode(encoding)
            break
        except (UnicodeError, UnicodeDecodeError):
            continue
    else:
        data = default

    return data
