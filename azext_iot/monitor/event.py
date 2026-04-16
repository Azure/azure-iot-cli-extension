# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import yaml

from typing import Optional, Tuple, Union
from uuid import uuid4
from knack.log import get_logger
from azext_iot.constants import USER_AGENT
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.common.utility import shell_safe_json_parse

# Use pyamqp for C2D send and feedback monitoring
from azure.eventhub._pyamqp import ReceiveClient as PyAMQPReceiveClient, SendClient as PyAMQPSendClient
from azure.eventhub._pyamqp.authentication import JWTTokenAuth as PyAMQPJWTTokenAuth
from azure.eventhub._pyamqp.authentication import _CBSAuth as PyAMQPCBSAuth
from azure.eventhub._pyamqp.message import Message as PyAMQPMessage
from azure.eventhub._pyamqp.error import AMQPLinkError, AMQPConnectionError

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

    # Build PyAMQP message properties (Properties is immutable, set all at creation)
    from azure.eventhub._pyamqp.message import Properties

    target_msg_id = message_id if message_id else str(uuid4())

    # Only include non-None properties
    props_kwargs = {
        "to": "/devices/{}/messages/devicebound".format(device_id),
        "message_id": target_msg_id,
    }

    if correlation_id:
        props_kwargs["correlation_id"] = correlation_id
    if user_id:
        props_kwargs["user_id"] = user_id
    if content_type:
        props_kwargs["content_type"] = content_type
    if content_encoding:
        props_kwargs["content_encoding"] = content_encoding
    if expiry_time_utc:
        props_kwargs["absolute_expiry_time"] = int(expiry_time_utc)

    msg_props = Properties(**props_kwargs)

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

    # Create PyAMQP message - use 'data' parameter (list of byte arrays)
    message = PyAMQPMessage(
        data=[msg_body] if isinstance(msg_body, bytes) else [msg_body.encode('utf-8')],
        properties=msg_props,
        application_properties=app_props
    )

    operation = "/messages/devicebound"
    endpoint_target, token_auth = _get_endpoint_and_token_auth_pyamqp(
        target=target, operation=operation
    )

    client = PyAMQPSendClient(
        hostname=target['entity'],
        target=endpoint_target,
        auth=token_auth,
        network_trace=DEBUG,
        container_id=_get_container_id(),
    )

    try:
        client.open()
        client.send_message(message, timeout=10)
        errors = []
    except Exception as e:
        logger.error(f"Failed to send C2D message: {e}")
        errors = [str(e)]
    finally:
        client.close()

    return target_msg_id, errors


def monitor_feedback(target, device_id, wait_on_id=None, token_duration=3600):
    def handle_msg(msg):
        # PyAMQP message has 'data' property
        # The data can be a list of data sections, so we get the first one
        payload = msg.data[0] if isinstance(msg.data, list) and msg.data else msg.data
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
    endpoint_target, token_auth = _get_endpoint_and_token_auth_pyamqp(
        target=target, operation=operation, token_duration=token_duration
    )
    device_filter_txt = None
    if device_id:
        device_filter_txt = " filtering on device: {},".format(device_id)

    print(
        f"Starting C2D feedback monitor,{device_filter_txt if device_filter_txt else ''} use ctrl-c to stop..."
    )

    try:
        client = PyAMQPReceiveClient(
            hostname=target['entity'],
            source=endpoint_target,
            auth=token_auth,
            client_name=_get_container_id(),
            network_trace=DEBUG,
        )
        client.open()
        message_generator = client.receive_messages_iter()
        for msg_tuple in message_generator:
            # PyAMQP returns (frame, message) tuples from _received_messages queue
            # frame is a TransferFrame NamedTuple with delivery_id and delivery_tag
            if isinstance(msg_tuple, tuple) and len(msg_tuple) == 2:
                frame, msg = msg_tuple
            else:
                # Fallback for when only message is returned
                frame, msg = None, msg_tuple

            match = handle_msg(msg)
            if match:
                logger.info("Requested message Id has been matched...")
                if frame and hasattr(frame, 'delivery_id') and hasattr(frame, 'delivery_tag'):
                    client.settle_messages(frame.delivery_id, frame.delivery_tag, 'accepted')
                else:
                    # If no frame info, message is auto-settled by PyAMQP
                    logger.debug("No frame delivery info available for settlement")
                return match
    except KeyboardInterrupt:
        logger.info("Stopping C2D feedback monitor...")
    except AMQPLinkError as e:
        # Link detachment is expected when device disconnects or service closes the connection
        error_condition = getattr(e, 'condition', None)
        if error_condition and 'detach' in str(error_condition).lower():
            logger.info("Feedback monitoring ended - link detached by service")
        else:
            logger.warning(f"AMQP link error during feedback monitoring: {e}")
    except AMQPConnectionError as e:
        # Connection errors can occur due to transient network issues or server-side disconnects
        logger.warning(f"AMQP connection error during feedback monitoring: {e}")
        # Don't re-raise - this is often a transient issue that shouldn't fail the operation
    except Exception as e:
        logger.error(f"Error in feedback monitoring: {e}", exc_info=True)
        raise
    finally:
        try:
            client.close()
        except Exception as e:
            logger.debug("Failed to close feedback client during cleanup: %s", e)


def _get_container_id():
    return "{}/{}".format(USER_AGENT, str(uuid4()))


def _get_endpoint_and_token_auth_pyamqp(
    target: dict, operation: str, token_duration: int = 3600
) -> Tuple[str, Union[PyAMQPJWTTokenAuth, PyAMQPCBSAuth, None]]:
    """
    Get endpoint and authentication for pyamqp.

    Note: IoT Hub requires SAS tokens with base64-decoded keys for HMAC signature,
    but PyAMQP's SASTokenAuth uses raw UTF-8 encoded keys (Event Hub/Service Bus style).
    We generate IoT Hub-compatible SAS tokens using SasTokenAuthentication and pass via CBS auth.
    """
    from azext_iot.constants import IOTHUB_RESOURCE_ID
    from azext_iot.common.sas_token_auth import SasTokenAuthentication
    from time import time
    from collections import namedtuple

    AccessToken = namedtuple("AccessToken", ["token", "expires_on"])
    endpoint_with_op = operation  # pyamqp uses relative path
    auth = None

    if target["policy"] == AuthenticationTypeDataplane.login.value:
        # Use JWT token auth for AAD login
        def token_provider():
            from azure.cli.core._profile import Profile
            profile = Profile(cli_ctx=target["cmd"].cli_ctx)
            creds, _, _ = profile.get_raw_token(resource=IOTHUB_RESOURCE_ID)
            access_token = AccessToken(f"{creds[0]} {creds[1]}", time() + 3599)
            return access_token

        auth = PyAMQPJWTTokenAuth(
            audience=IOTHUB_RESOURCE_ID,
            uri=f"amqps://{target['entity']}{operation}",
            get_token=token_provider,
            token_type=b"Bearer"
        )
    else:
        # Generate IoT Hub-compatible SAS token using our SasTokenAuthentication
        # which correctly uses base64-decoded keys for HMAC (unlike PyAMQP's generate_sas_token)
        sas_generator = SasTokenAuthentication(
            uri=target['entity'],
            shared_access_policy_name=target['policy'],
            shared_access_key=target['primarykey'],
            expiry=token_duration
        )

        def sas_token_provider():
            # Generate SAS token and return as AccessToken
            token = sas_generator.generate_sas_token()
            return AccessToken(token, time() + token_duration)

        # Use CBS authentication with our pre-generated SAS token
        auth = PyAMQPCBSAuth(
            uri=f"amqps://{target['entity']}{operation}",
            audience=target['entity'],
            token_type=b"servicebus.windows.net:sastoken",
            get_token=sas_token_provider,
            expires_in=token_duration
        )

    return endpoint_with_op, auth
