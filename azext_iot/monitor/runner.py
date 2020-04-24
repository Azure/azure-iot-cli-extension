# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio


class Runner:
    def __init__(self, polling_interval_seconds=1, timeout=0, max_messages=0):
        self.polling_interval_seconds = polling_interval_seconds
        self.messages = []
        self.coroutines = []
        self.tasks = []
        self.loop = self._get_loop()

        self._add_timeout(timeout)
        self._add_max_messages(max_messages)

    def run_coroutine(self, coroutine):
        task = self.loop.create_task(coroutine)
        self.loop.run_until_complete(task)

    def add_coroutine(self, coroutine_lambda):
        coroutine = coroutine_lambda(self.messages)
        self.coroutines.append(coroutine)

    def start(self):
        future = asyncio.gather(
            *self.coroutines, loop=self.loop, return_exceptions=True
        )
        result = None
        try:
            self.loop.run_until_complete(future)
        except BaseException:
            self.stop()
        finally:
            if result and result[0] and result[0][0]:
                print(result)

    def stop(self):
        for t in asyncio.Task.all_tasks():
            t.cancel()

    def get_messages(self):
        return self.messages

    def _get_loop(self):
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop

    def _add_timeout(self, timeout=0):
        if not timeout:
            return

        self.coroutines.append(self._timeout(timeout))

    def _add_max_messages(self, max_messages=0):
        if not max_messages:
            return

        self.coroutines.append(self._max_messages(max_messages))

    async def _timeout(self, timeout=0):
        await asyncio.sleep(timeout)
        print("Read messages timed out, no longer reading messages.")
        self.stop()

    async def _max_messages(self, max_messages=0):
        while True:
            await asyncio.sleep(self.polling_interval_seconds)
            if len(self.messages) >= max_messages:
                print("Max message count received, no longer reading messages.")
                self.stop()
