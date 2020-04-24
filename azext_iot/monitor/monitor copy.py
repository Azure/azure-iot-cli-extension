# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import json
import re
import sys

from knack.log import get_logger
from uuid import uuid4

from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.monitor.parser import MessageParser
from azext_iot.monitor.target import Target

DEBUG = False
logger = get_logger(__name__)


def initiate_monitor_sync(
    target: Target,
    enqueued_time: int,
    consumer_group="$Default",
    timeout=0,
    device_id="",
    properties=[],
):
    loop = _get_loop()
    coroutine = initiate_monitor(
        target=target,
        enqueued_time=enqueued_time,
        consumer_group=consumer_group,
        timeout=timeout,
        device_id=device_id,
        properties=properties,
    )

    result = None
    try:
        device_filter_txt = None
        if device_id:
            device_filter_txt = " filtering on device: {},".format(device_id)

        print(
            "Starting event monitor,{} use ctrl-c to stop...".format(
                device_filter_txt if device_filter_txt else "",
            )
        )
        result = loop.run_until_complete(coroutine)
    except KeyboardInterrupt:
        print("Stopping event monitor...")
        _shutdown()
    finally:
        _process_result(result)


async def initiate_monitor(
    target: Target,
    enqueued_time: int,
    consumer_group="$Default",
    timeout=0,
    device_id="",
    properties=[],
):
    import uamqp

    if not target.partitions:
        logger.debug("No Event Hub partitions found to listen on.")
        return

    async with uamqp.ConnectionAsync(
        target.hostname,
        sasl=target.auth,
        debug=DEBUG,
        container_id=_get_container_id(),
        properties=_get_conn_props(),
    ) as connection:
        for partition in target.partitions:
            async_gen = process_single_partition(
                target=target,
                enqueued_time=enqueued_time,
                partition=partition,
                connection=connection,
                consumer_group=consumer_group,
                timeout=timeout,
                device_id=device_id,
                properties=properties,
            )
            async for parsed_msg in async_gen:
                print(parsed_msg)


async def process_single_partition(
    target: Target,
    enqueued_time: int,
    partition: str,
    connection,  # uamqp.ConnectionAsync
    consumer_group="$Default",
    timeout=0,
    device_id="",
    properties=[],
):
    import uamqp

    url = "amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
        target.hostname, target.path, consumer_group, partition
    )
    source = uamqp.address.Source(url)
    source.set_filter(
        bytes("amqp.annotation.x-opt-enqueuedtimeutc > " + str(enqueued_time), "utf8")
    )

    receive_client = uamqp.ReceiveClientAsync(
        source,
        auth=target.auth,
        timeout=timeout,
        prefetch=0,
        client_name=_get_container_id(),
        debug=DEBUG,
    )

    try:
        await receive_client.open_async(connection=connection)

        async for msg in receive_client.receive_messages_iter_async():
            result = _output_msg_kpi(msg, device_id, properties)
            if result:
                yield result
    finally:
        await receive_client.close_async()
        logger.info("Closed monitor on partition %s", partition)


def _output_msg_kpi(msg, device_id, properties):
    parser = MessageParser()
    origin_device_id = parser.parse_device_id(msg)

    if not _should_process_device(origin_device_id, device_id):
        return

    parsed_msg = parser.parse_message(msg, properties)

    return json.dumps(parsed_msg, indent=4)


def _should_process_device(origin_device_id, device_id):
    if device_id and device_id != origin_device_id:
        if "*" in device_id or "?" in device_id:
            regex = re.escape(device_id).replace("\\*", ".*").replace("\\?", ".") + "$"
            if not re.match(regex, origin_device_id):
                return False
        else:
            return False

    return True


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))


def _get_conn_props():
    return {
        "product": USER_AGENT,
        "version": VERSION,
        "framework": "Python {}.{}.{}".format(*sys.version_info[0:3]),
        "platform": sys.platform,
    }


def _stop_and_suppress_eloop(loop):
    try:
        loop.stop()
    except Exception:
        pass


def _get_loop():
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _process_result(result):
    if result:
        errors = result[0]
        if errors and errors[0]:
            logger.debug(errors)
            raise RuntimeError(errors[0])


def _shutdown():
    for task in asyncio.Task.all_tasks():
        task.cancel()
