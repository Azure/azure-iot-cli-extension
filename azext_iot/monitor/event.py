# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import uamqp
import yaml

from typing import Optional, Tuple, Union
from uuid import uuid4
from knack.log import get_logger
from azext_iot.constants import USER_AGENT
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.common.utility import shell_safe_json_parse
from azext_iot.monitor.builders.hub_target_builder import AmqpBuilder
from uamqp.authentication import JWTTokenAuth

# To provide amqp frame trace
DEBUG = False
logger = get_logger(__name__)


def send_c2d_message(
    target,
    device_id,
    data,
    data_file_path: Optional[str] = None,
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

    if content_encoding:
        msg_props.content_encoding = content_encoding

    if expiry_time_utc:
        msg_props.absolute_expiry_time = int(expiry_time_utc)

    content_type = content_type.lower() if content_type else ""

    if data_file_path:
        if not os.path.exists(data_file_path):
            raise FileNotFoundError("File path {} does not exist.".format(data_file_path))

        binary_content = 'application/octet-stream' in content_type

        # send bytes as message when content type is defined as binary
        if binary_content:
            with open(data_file_path, "rb") as f:
                data = f.read()
        else:
            with open(data_file_path, "r", encoding="utf-8") as f:
                data = f.read()
    else:
        # Ensures valid json when content_type is application/json
        if "application/json" in content_type:
            data = json.dumps(shell_safe_json_parse(data))

    if isinstance(data, str) and content_encoding in ["utf-8", "utf8", "utf-16", "utf16", "utf-32", "utf32"]:
        msg_body = data.encode(encoding=content_encoding)
    else:
        msg_body = data

    message = uamqp.Message(
        body=msg_body, properties=msg_props, application_properties=app_props
    )

    operation = "/messages/devicebound"
    endpoint_target, token_auth = _get_endpoint_and_token_auth(
        target=target, operation=operation
    )

    client = uamqp.SendClient(
        target=endpoint_target,
        auth=token_auth,
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
            print(yaml.safe_dump({"feedback": p}, default_flow_style=False), flush=True)
            if wait_on_id:
                msg_id = p["originalMessageId"]
                if msg_id == wait_on_id:
                    return msg_id
        return None

    operation = "/messages/servicebound/feedback"
    endpoint_target, token_auth = _get_endpoint_and_token_auth(
        target=target, operation=operation
    )
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    print(
        f"Starting C2D feedback monitor,{device_filter_txt if device_filter_txt else ''} use ctrl-c to stop..."
    )

    try:
        client = uamqp.ReceiveClient(
            source=endpoint_target,
            auth=token_auth,
            client_name=_get_container_id(),
            debug=DEBUG,
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


def _get_endpoint_and_token_auth(
    target: dict, operation: str
) -> Tuple[str, Union[JWTTokenAuth, None]]:
    from azext_iot.constants import IOTHUB_RESOURCE_ID
    from time import time
    from collections import namedtuple

    AccessToken = namedtuple("AccessToken", ["token", "expires_on"])

    def token_provider():
        from azure.cli.core._profile import Profile
        profile = Profile(cli_ctx=target["cmd"].cli_ctx)
        creds, _, _ = profile.get_raw_token(resource=IOTHUB_RESOURCE_ID)
        access_token = AccessToken(f"{creds[0]} {creds[1]}", time() + 3599)
        return access_token

    endpoint_with_op = None
    jwt_token_auth = None
    if target["policy"] == AuthenticationTypeDataplane.login.value:
        endpoint_with_op = f"amqps://{target['entity']}{operation}"
        jwt_token_auth = JWTTokenAuth(
            audience=IOTHUB_RESOURCE_ID,
            uri=endpoint_with_op,
            get_token=token_provider,
            token_type=b"Bearer",
        )
        jwt_token_auth.update_token()  # Work-around for uamqp error.
    else:
        endpoint_with_op = f"amqps://{AmqpBuilder.build_iothub_amqp_endpoint_from_target(target)}{operation}"

    return endpoint_with_op, jwt_token_auth
