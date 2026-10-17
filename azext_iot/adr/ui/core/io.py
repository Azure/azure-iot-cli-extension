# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Await blocking Azure calls without tying terminal shutdown to executor joins."""

import asyncio
from contextvars import copy_context
from threading import Thread


async def run_io(operation, slots):
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    context = copy_context()
    await slots.acquire()

    def finish(value, error):
        slots.release()
        if result.done():
            return
        if error is not None:
            result.set_exception(error)
        else:
            result.set_result(value)

    def run():
        try:
            value, error = context.run(operation), None
        except BaseException as failure:  # Transport failures to the awaiting worker, like an executor.
            value, error = None, failure
        try:
            loop.call_soon_threadsafe(finish, value, error)
        except RuntimeError:
            if not loop.is_closed():
                raise

    try:
        Thread(target=run, name="radar-azure-io", daemon=True).start()
    except RuntimeError:
        slots.release()
        raise
    return await result
