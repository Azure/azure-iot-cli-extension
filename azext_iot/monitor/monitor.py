# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import re
import sys

from knack.log import get_logger
from uuid import uuid4

from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.monitor.parser import MessageParser
from azext_iot.monitor.runner import Runner
from azext_iot.monitor.target import Target

DEBUG = False
logger = get_logger(__name__)


def initiate_monitor(
    target: Target,
    continuous_output: bool,
    enqueued_time: int,
    consumer_group="$Default",
    device_id="",
    properties=[],
    timeout=0,
    max_messages=0,
):
    runner = Runner(timeout=timeout, max_messages=max_messages)
    print("Setting up event monitors...")
    coroutine = generate_monitor_coroutines(
        runner=runner,
        target=target,
        continuous_output=continuous_output,
        enqueued_time=enqueued_time,
        consumer_group=consumer_group,
        timeout=timeout,
        device_id=device_id,
        properties=properties,
    )
    runner.run_coroutine(coroutine)

    print(
        "Waiting for either {} seconds, or until {} messages are read (whichever happens first).".format(
            timeout, max_messages
        )
    )
    if continuous_output:
        print("Messages will be output as they are received.")
    else:
        print("Messages will be output at the end of execution.")
    runner.start()
    messages = runner.get_messages()
    return messages


async def generate_monitor_coroutines(
    runner: Runner,
    target: Target,
    continuous_output: bool,
    enqueued_time: int,
    consumer_group: str,
    timeout: int,
    device_id: str,
    properties: list,
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
                continuous_output=continuous_output,
                enqueued_time=enqueued_time,
                consumer_group=consumer_group,
                partition=partition,
                connection=connection,
                timeout=timeout,
                device_id=device_id,
                properties=properties,
                messages=messages,
            )
        )


async def process_single_partition(
    target: Target,
    continuous_output: bool,
    enqueued_time: int,
    consumer_group: str,
    partition: str,
    connection,  # uamqp.ConnectionAsync
    timeout: int,
    device_id: str,
    properties: list,
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
            message = _output_msg_kpi(msg, device_id, properties)
            if message:
                messages.append(message)
                if continuous_output:
                    dumps = json.dumps(message, indent=4)
                    print(dumps)
    finally:
        await receive_client.close_async()
        logger.info("Closed monitor on partition %s", partition)


def _output_msg_kpi(msg, device_id, properties):
    parser = MessageParser()
    origin_device_id = parser.parse_device_id(msg)

    if not _should_process_device(origin_device_id, device_id):
        return

    return parser.parse_message(msg, properties)


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
