# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import sys

from knack.log import get_logger
from uuid import uuid4

from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.monitor.runner import Runner
from azext_iot.monitor.target import Target

DEBUG = False
logger = get_logger(__name__)


def initiate_monitor(
    target: Target,
    parse_message,
    enqueued_time: int,
    consumer_group="$Default",
    timeout=0,
    max_messages=0,
):
    runner = Runner(timeout=timeout, max_messages=max_messages)
    print("Setting up event monitors...")
    coroutine = generate_monitor_coroutines(
        runner=runner,
        target=target,
        parse_message=parse_message,
        enqueued_time=enqueued_time,
        consumer_group=consumer_group,
        timeout=timeout,
    )
    runner.run_coroutine(coroutine)

    print(
        "Waiting for either {} seconds, or until {} messages are read (whichever happens first).".format(
            timeout, max_messages
        )
    )

    runner.start()
    messages = runner.get_messages()
    return messages


async def generate_monitor_coroutines(
    runner: Runner,
    target: Target,
    parse_message,
    enqueued_time: int,
    consumer_group: str,
    timeout: int,
):
    import uamqp

    if not target.partitions:
        logger.debug("No Event Hub partitions found to listen on.")
        return

    connection = uamqp.ConnectionAsync(
        target.hostname,
        sasl=target.auth,
        debug=DEBUG,
        container_id=_get_container_id(),
        properties=_get_conn_props(),
    )

    for partition in target.partitions:
        runner.add_coroutine(
            lambda messages: process_single_partition(
                target=target,
                parse_message=parse_message,
                enqueued_time=enqueued_time,
                consumer_group=consumer_group,
                partition=partition,
                connection=connection,
                timeout=timeout,
                messages=messages,
            )
        )


async def process_single_partition_bkp(
    target: Target,
    parse_message,
    enqueued_time: int,
    consumer_group: str,
    partition: str,
    connection,  # uamqp.ConnectionAsync
    timeout: int,
    messages: list,
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
            message = parse_message(msg)
            if message:
                messages.append(message)
    finally:
        await receive_client.close_async()
        logger.info("Closed monitor on partition %s", partition)


async def process_single_partition(
    target: Target,
    parse_message,
    enqueued_time: int,
    consumer_group: str,
    partition: str,
    connection,  # uamqp.ConnectionAsync
    timeout: int,
    messages: list,
):
    import uamqp

    url = "amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
        target.hostname, target.path, consumer_group, partition
    )
    source = uamqp.address.Source(url)
    source.set_filter(
        bytes("amqp.annotation.x-opt-enqueuedtimeutc > " + str(enqueued_time), "utf8")
    )

    exp_cancelled = False
    receive_client = uamqp.ReceiveClientAsync(
        source,
        auth=target.auth,
        timeout=timeout,
        prefetch=0,
        client_name=_get_container_id(),
        debug=DEBUG,
    )

    try:
        if connection:
            await receive_client.open_async(connection=connection)

        async for msg in receive_client.receive_messages_iter_async():
            message = parse_message(msg)
            if message:
                messages.append(message)
    except asyncio.CancelledError:
        exp_cancelled = True
        await receive_client.close_async()
    except uamqp.errors.LinkDetach as ld:
        if isinstance(ld.description, bytes):
            ld.description = str(ld.description, "utf8")
        raise RuntimeError(ld.description)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, closing monitor on partition %s", partition)
        exp_cancelled = True
        await receive_client.close_async()
        raise
    finally:
        if not exp_cancelled:
            await receive_client.close_async()
        logger.info("Closed monitor on partition %s", partition)


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))


def _get_conn_props():
    return {
        "product": USER_AGENT,
        "version": VERSION,
        "framework": "Python {}.{}.{}".format(*sys.version_info[0:3]),
        "platform": sys.platform,
    }
