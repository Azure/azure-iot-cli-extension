# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Blocking Azure work preserves context, bounds concurrency, and permits terminal exit."""

import asyncio
from contextvars import ContextVar
from threading import Event, current_thread
from types import SimpleNamespace

import pytest

from azext_iot.adr.ui.core import io


def test_io_preserves_context_and_returns_on_a_daemon_thread():
    context = ContextVar("test-radar-context", default="missing")
    context.set("radar")

    async def runner():
        slots = asyncio.Semaphore(1)
        assert await io.run_io(lambda: (context.get(), current_thread().daemon), slots) == ("radar", True)
        assert not slots.locked()
    asyncio.run(runner())


def test_io_transports_failures_and_releases_capacity():
    def fail():
        raise ValueError("Azure rejected the call")

    async def runner():
        slots = asyncio.Semaphore(1)
        with pytest.raises(ValueError, match="Azure rejected"):
            await io.run_io(fail, slots)
        assert not slots.locked()
    asyncio.run(runner())


def test_cancelled_awaiter_does_not_release_a_still_running_request_slot():
    started, release, second_started = (Event() for _ in range(3))

    def first():
        started.set()
        release.wait(10)

    async def runner():
        slots = asyncio.Semaphore(1)
        task = asyncio.create_task(io.run_io(first, slots))
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        second = asyncio.create_task(io.run_io(second_started.set, slots))
        await asyncio.sleep(0)
        assert slots.locked()
        assert not second_started.is_set()
        release.set()
        await asyncio.wait_for(second, 3)
        assert second_started.is_set()
        assert not slots.locked()

    try:
        asyncio.run(runner())
    finally:
        release.set()


def test_failure_to_start_a_thread_releases_capacity(mocker):
    mocker.patch.object(io, "Thread").return_value.start.side_effect = RuntimeError("cannot start thread")

    async def runner():
        slots = asyncio.Semaphore(1)
        with pytest.raises(RuntimeError, match="cannot start"):
            await io.run_io(lambda: None, slots)
        assert not slots.locked()
    asyncio.run(runner())


@pytest.mark.parametrize("closed", [True, False])
def test_late_delivery_ignores_only_a_closed_loop(closed, mocker):
    async def runner():
        real_loop = asyncio.get_running_loop()
        future = real_loop.create_future()
        if closed:
            future.cancel()
        loop = mocker.Mock()
        loop.create_future.return_value = future
        loop.call_soon_threadsafe.side_effect = RuntimeError("loop delivery failed")
        loop.is_closed.return_value = closed
        mocker.patch.object(io.asyncio, "get_running_loop", return_value=loop)
        mocker.patch.object(io, "Thread", side_effect=lambda **kwargs: SimpleNamespace(start=kwargs["target"]))
        with pytest.raises(asyncio.CancelledError if closed else RuntimeError):
            await io.run_io(lambda: "late result", asyncio.Semaphore(1))
    asyncio.run(runner())
