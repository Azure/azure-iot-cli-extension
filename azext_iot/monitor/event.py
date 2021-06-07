# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import uamqp
import yaml

from uuid import uuid4
from knack.log import get_logger
from azext_iot.constants import USER_AGENT
from azext_iot.common.utility import process_json_arg
from azext_iot.monitor.builders.hub_target_builder import AmqpBuilder

# To provide amqp frame trace
DEBUG = False
logger = get_logger(__name__)


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

    msg_body = data.encode(encoding=content_encoding)

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
            print(yaml.dump({"feedback": p}, default_flow_style=False), flush=True)
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

    print(
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
