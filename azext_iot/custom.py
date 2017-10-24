# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=no-self-use,no-member,line-too-long,too-few-public-methods,no-name-in-module

import json
import time
import uuid
from enum import Enum
from os.path import exists
import six.moves
from azure.cli.core.util import CLIError
from azure.cli.core.util import read_file_content
from azure.cli.command_modules.iot.custom import (iot_hub_show_connection_string, iot_hub_policy_get,
                                                  _get_single_device_connection_string)
from azure.cli.command_modules.iot.sas_token_auth import SasTokenAuthentication
from iothub_service_client import IoTHubDeviceTwin, IoTHubDeviceMethod, IoTHubError, IoTHubMessaging, IoTHubMessage
from iothub_client import IoTHubTransportProvider, IoTHubClientError
from azext_iot.iot_sdk.utility import block_stdout, Default_Msg_Callbacks
from azext_iot.iot_sdk.device_manager import DeviceManager


class ProtocolType(Enum):
    http = 'http'
    amqp = 'amqp'
    mqtt = 'mqtt'


class SettleType(Enum):
    complete = 'complete'
    abandon = 'abandon'
    reject = 'reject'


# IoT SDK Extensions #
# Twin Ops

def iot_twin_show(client, device_id, hub_name):
    c = iot_hub_show_connection_string(client, hub_name)
    try:
        return json.loads(IoTHubDeviceTwin(c['connectionString']).get_twin(device_id))
    except IoTHubError as e:
        raise CLIError(e)


def iot_twin_update(client, device_id, hub_name, update_json):
    c = iot_hub_show_connection_string(client, hub_name)
    try:
        # The SDK is looking for a raw json string
        if exists(update_json):
            update_json = str(read_file_content(update_json))
        json.loads(update_json)
        return json.loads(IoTHubDeviceTwin(c['connectionString']).update_twin(device_id, update_json))
    except ValueError:
        raise CLIError('Improperly formatted JSON!')
    except IoTHubError as e:
        raise CLIError(e)


# Device Method Invoke

def iot_device_method(client, device_id, hub_name, method_name, method_payload, timeout=60):
    try:
        c = iot_hub_show_connection_string(client, hub_name)
        iothub_device_method = IoTHubDeviceMethod(c['connectionString'])
        response = iothub_device_method.invoke(device_id, method_name, method_payload, timeout)
        return {
            'status': response.status,
            'payload': response.payload
        }
    except IoTHubError as e:
        raise CLIError(e)


# Utility

def iot_get_sas_token(client, device_id, hub_name, policy_name, duration=3600, resource_group_name=None):
    base_url = '{0}.azure-devices.net'.format(hub_name)
    uri = '{0}/devices/{1}'.format(base_url, device_id)
    access_policy = iot_hub_policy_get(client, hub_name, policy_name, resource_group_name)
    result = SasTokenAuthentication(uri, access_policy.key_name, access_policy.primary_key,
                                    duration).generate_sas_token().replace('SharedAccessSignature ', '')
    return {"SharedAccessSignature": result}


# Messaging

def iot_device_send_message_ext(client, device_id, hub_name, protocol='http', data='Ping from Azure CLI',
                                resource_group_name=None, message_id=None, correlation_id=None, user_id=None):
    try:
        c = _get_single_device_connection_string(client, hub_name, device_id, resource_group_name, None)
        protocol = _iot_sdk_device_process_protocol(protocol)
        with block_stdout():
            device = DeviceManager(c, protocol)
            device.send_event(data, {'UserId': user_id} if user_id else None, message_id, correlation_id)
    except IoTHubClientError as e:
        raise CLIError(e)
    except RuntimeError as f:
        raise CLIError(f)


def iot_hub_message_send(client, device_id, hub_name, message_id=str(uuid.uuid4()), correlation_id=None,
                         data="Ping from Azure CLI", wait_feedback=False):
    try:
        c = iot_hub_show_connection_string(client, hub_name)
        iothub_messaging = IoTHubMessaging(c['connectionString'])

        message = IoTHubMessage(data)

        # optional: assign ids
        if correlation_id is not None:
            message.correlation_id = correlation_id
        if message_id is not None:
            message.message_id = message_id

        default = Default_Msg_Callbacks()

        iothub_messaging.open(default.open_complete_callback, 0)

        if wait_feedback:
            iothub_messaging.set_feedback_message_callback(default.feedback_received_callback, 0)

        iothub_messaging.send_async(device_id, message, default.send_complete_callback, 0)
        time.sleep(2)

        if wait_feedback:
            wait_feedback_msg = "Waiting for message feedback, press any key to continue...\n\n"
            six.print_('', flush=True)
            six.moves.input(wait_feedback_msg)

        iothub_messaging.close()
    except IoTHubError as e:
        raise CLIError(e)


def iot_simulate_device(client, device_id, hub_name, settle='complete', protocol='amqp', data="Ping from Azure CLI",
                        message_count=5, message_interval=1, receive_count=None, file_path=None):
    if message_count < 0:
        raise CLIError("message-count must be at least 0!")
    if message_interval < 1:
        raise CLIError("message-interval must be > 0!")

    try:
        protocol = _iot_sdk_device_process_protocol(protocol)
        c = _get_single_device_connection_string(client, hub_name, device_id, None, None)
        with block_stdout():
            sim_client = DeviceManager(c, protocol)

        if file_path:
            sim_client.upload_file_to_blob(file_path)

        if receive_count:
            sim_client.configure_receive_settle(settle)

        for message_counter in range(0, message_count):
            print_context = "Sending message %s, via %s with %s sec delay" % (message_counter + 1,
                                                                              protocol, message_interval)
            sim_client.send_event(data, None, str(uuid.uuid4()),
                                  str(uuid.uuid4()), 0, print_context)
            time.sleep(message_interval)

        if receive_count:
            if receive_count == -1:
                while True:
                    time.sleep(1)
            else:
                while sim_client.received() < receive_count:
                    time.sleep(1)

    except IoTHubClientError as e:
        raise CLIError("Unexpected client error %s" % e)
    except RuntimeError as f:
        raise CLIError("Unexpected runtime error %s" % f)


def _iot_sdk_device_process_protocol(protocol_string):
    protocol = None
    if protocol_string == "http":
        if hasattr(IoTHubTransportProvider, "HTTP"):
            protocol = IoTHubTransportProvider.HTTP
    elif protocol_string == "amqp":
        if hasattr(IoTHubTransportProvider, "AMQP"):
            protocol = IoTHubTransportProvider.AMQP
    elif protocol_string == "mqtt":
        if hasattr(IoTHubTransportProvider, "MQTT"):
            protocol = IoTHubTransportProvider.MQTT
    else:
        raise CLIError("Error: {} protocol is not supported".format(protocol_string))

    return protocol
