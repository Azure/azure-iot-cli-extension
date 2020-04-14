# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
import json
import re
import sys
import six
import yaml
import uamqp

from uuid import uuid4
from knack.log import get_logger
from azext_iot.constants import VERSION, USER_AGENT
from azext_iot.common.utility import process_json_arg
from azext_iot.operations.events3._builders import AmqpBuilder
from azext_iot.operations.events3._parser import Event3Parser

# To provide amqp frame trace
DEBUG = False
logger = get_logger(__name__)


class executorData:
    def __init__(self,
                 target,
                 consumer_group):
        self.target = target
        self.consumer_group = consumer_group


def executor(
    target,
    consumer_group,
    enqueued_time,
    properties=None,
    timeout=0,
    device_id=None,
    output=None,
    content_type=None,
    devices=None,
    interface_name=None,
    pnp_context=None,
    validate_messages=False,
    simulate_errors=False,
):
    executor = executorData(target, consumer_group)

    return nExecutor([executor], enqueued_time,
                     properties,
                     timeout,
                     device_id,
                     output,
                     content_type,
                     devices,
                     interface_name,
                     pnp_context,
                     validate_messages,
                     simulate_errors)


def nExecutor(
    executorTargets,
    enqueued_time,
    properties=None,
    timeout=0,
    device_id=None,
    output=None,
    content_type=None,
    devices=None,
    interface_name=None,
    pnp_context=None,
    validate_messages=False,
    simulate_errors=False,
):
    coroutines = []
    for executor in executorTargets:
        coroutines.append(
            initiate_event_monitor(
                executor.target,
                executor.consumer_group,
                enqueued_time,
                device_id,
                properties,
                timeout,
                output,
                content_type,
                devices,
                interface_name,
                pnp_context,
                validate_messages,
                simulate_errors
            )
        )

    loop = asyncio.get_event_loop()
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    future = asyncio.gather(*coroutines, loop=loop, return_exceptions=True)
    result = None

    try:
        device_filter_txt = None
        if device_id:
            device_filter_txt = " filtering on device: {},".format(device_id)

        def stop_and_suppress_eloop():
            try:
                loop.stop()
            except Exception:
                pass

        six.print_(
            "Starting {}event monitor,{} use ctrl-c to stop...".format(
                "Digital Twin " if pnp_context else "",
                device_filter_txt if device_filter_txt else "",
            )
        )
        future.add_done_callback(lambda future: stop_and_suppress_eloop())
        result = loop.run_until_complete(future)
    except KeyboardInterrupt:
        six.print_("Stopping event monitor...")
        for t in asyncio.Task.all_tasks():
            t.cancel()
        loop.run_forever()
    finally:
        if result:
            errors = result[0]
            if errors and errors[0]:
                logger.debug(errors)
                raise RuntimeError(errors[0])


async def initiate_event_monitor(
    target,
    consumer_group,
    enqueued_time,
    device_id=None,
    properties=None,
    timeout=0,
    output=None,
    content_type=None,
    devices=None,
    interface_name=None,
    pnp_context=None,
    validate_messages=False,
    simulate_errors=False,
):
    def _get_conn_props():
        properties = {}
        properties["product"] = USER_AGENT
        properties["version"] = VERSION
        properties["framework"] = "Python {}.{}.{}".format(*sys.version_info[0:3])
        properties["platform"] = sys.platform
        return properties

    if not target["partitions"]:
        logger.debug("No Event Hub partitions found to listen on.")
        return

    coroutines = []

    async with uamqp.ConnectionAsync(
        target["endpoint"],
        sasl=target["auth"],
        debug=DEBUG,
        container_id=_get_container_id(),
        properties=_get_conn_props(),
    ) as conn:
        for p in target["partitions"]:
            coroutines.append(
                monitor_events(
                    endpoint=target["endpoint"],
                    connection=conn,
                    path=target["path"],
                    auth=target["auth"],
                    partition=p,
                    consumer_group=consumer_group,
                    enqueuedtimeutc=enqueued_time,
                    properties=properties,
                    device_id=device_id,
                    timeout=timeout,
                    output=output,
                    content_type=content_type,
                    devices=devices,
                    interface_name=interface_name,
                    pnp_context=pnp_context,
                    validate_messages=validate_messages,
                    simulate_errors=simulate_errors,
                )
            )
        return await asyncio.gather(*coroutines, return_exceptions=True)


async def monitor_events(
    endpoint,
    connection,
    path,
    auth,
    partition,
    consumer_group,
    enqueuedtimeutc,
    properties,
    device_id=None,
    timeout=0,
    output=None,
    content_type=None,
    devices=None,
    interface_name=None,
    pnp_context=None,
    validate_messages=False,
    simulate_errors=False,
):
    source = uamqp.address.Source(
        "amqps://{}/{}/ConsumerGroups/{}/Partitions/{}".format(
            endpoint, path, consumer_group, partition
        )
    )
    source.set_filter(
        bytes("amqp.annotation.x-opt-enqueuedtimeutc > " + str(enqueuedtimeutc), "utf8")
    )

    exp_cancelled = False
    receive_client = uamqp.ReceiveClientAsync(
        source,
        auth=auth,
        timeout=timeout,
        prefetch=0,
        client_name=_get_container_id(),
        debug=DEBUG,
    )

    try:
        if connection:
            await receive_client.open_async(connection=connection)

        async for msg in receive_client.receive_messages_iter_async():
            _output_msg_kpi(
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
            )

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


def send_c2d_message(
    target,
    device_id,
    data,
    message_id=None,
    correlation_id=None,
    ack=None,
    content_type=None,
    user_id=None,
    content_encoding="utf-8",
    expiry_time_utc=None,
    properties=None,
):
    app_props = {}
    if properties:
        app_props.update(properties)

    app_props["iothub-ack"] = ack if ack else "none"

    msg_props = uamqp.message.MessageProperties()
    msg_props.to = "/devices/{}/messages/devicebound".format(device_id)

    target_msg_id = message_id if message_id else str(uuid4())
    msg_props.message_id = target_msg_id

    if correlation_id:
        msg_props.correlation_id = correlation_id

    if user_id:
        msg_props.user_id = user_id

    if content_type:
        msg_props.content_type = content_type

        # Ensures valid json when content_type is application/json
        content_type = content_type.lower()
        if content_type == "application/json":
            data = json.dumps(process_json_arg(data, "data"))

    if content_encoding:
        msg_props.content_encoding = content_encoding

    if expiry_time_utc:
        msg_props.absolute_expiry_time = int(expiry_time_utc)

    msg_body = str.encode(data)

    message = uamqp.Message(
        body=msg_body, properties=msg_props, application_properties=app_props
    )

    operation = "/messages/devicebound"
    endpoint = AmqpBuilder.build_iothub_amqp_endpoint_from_target(target)
    endpoint_with_op = endpoint + operation
    client = uamqp.SendClient(
        target="amqps://" + endpoint_with_op,
        client_name=_get_container_id(),
        debug=DEBUG,
    )
    client.queue_message(message)
    result = client.send_all_messages()
    errors = [m for m in result if m == uamqp.constants.MessageState.SendFailed]
    return target_msg_id, errors


def monitor_feedback(target, device_id, wait_on_id=None, token_duration=3600):
    def handle_msg(msg):
        payload = next(msg.get_data())
        if isinstance(payload, bytes):
            payload = str(payload, "utf8")
        # assume json [] based on spec
        payload = json.loads(payload)
        for p in payload:
            if (
                device_id
                and p.get("deviceId")
                and p["deviceId"].lower() != device_id.lower()
            ):
                return None
            six.print_(yaml.dump({"feedback": p}, default_flow_style=False), flush=True)
            if wait_on_id:
                msg_id = p["originalMessageId"]
                if msg_id == wait_on_id:
                    return msg_id
        return None

    operation = "/messages/servicebound/feedback"
    endpoint = AmqpBuilder.build_iothub_amqp_endpoint_from_target(
        target, duration=token_duration
    )
    endpoint = endpoint + operation

    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    six.print_(
        "Starting C2D feedback monitor,{} use ctrl-c to stop...".format(
            device_filter_txt if device_filter_txt else ""
        )
    )

    try:
        client = uamqp.ReceiveClient(
            "amqps://" + endpoint, client_name=_get_container_id(), debug=DEBUG
        )
        message_generator = client.receive_messages_iter()
        for msg in message_generator:
            match = handle_msg(msg)
            if match:
                logger.info("Requested message Id has been matched...")
                msg.accept()
                return match
    except uamqp.errors.AMQPConnectionError:
        logger.debug("AMQPS connection has expired...")
    finally:
        client.close()


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))


def _output_msg_kpi(
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
):
    parser = Event3Parser()
    origin_device_id = parser.parse_device_id(msg)

    if not _should_process_device(origin_device_id, device_id, devices):
        return

    parsed_msg = parser.parse_message(
        msg, pnp_context, interface_name, properties, content_type, simulate_errors
    )

    if output.lower() == "json":
        dump = json.dumps(parsed_msg, indent=4)
    else:
        dump = yaml.safe_dump(parsed_msg, default_flow_style=False)

    if validate_messages:
        parser.write_logs()

    if not validate_messages:
        six.print_(dump, flush=True)


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
