# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pprint
from time import sleep
from azext_iot.common.utility import ensure_azure_namespace_path
from knack.util import CLIError
from azext_iot.common.shared import DeviceAuthApiType

printer = pprint.PrettyPrinter(indent=2)


class mqtt_client(object):
    def __init__(
        self, target, device_conn_string, device_id, device_auth_api_type,
        method_response_code=None, method_response_payload=None, init_reported_properties=None
    ):
        ensure_azure_namespace_path()
        from azure.iot.device import IoTHubDeviceClient as mqtt_device_client

        if device_auth_api_type != DeviceAuthApiType.sas.value:
            raise CLIError('MQTT simulation is only supported for symmetric key auth (SAS) based devices')

        self.device_id = device_id
        self.target = target
        # The client automatically connects when we send/receive a message or method invocation
        self.device_client = mqtt_device_client.create_from_connection_string(device_conn_string, websockets=True)
        self.device_client.on_message_received = self.message_handler
        self.device_client.on_method_request_received = self.method_request_handler
        self.method_response_code = method_response_code
        self.method_response_payload = method_response_payload
        self.device_client.on_twin_desired_properties_patch_received = self.twin_patch_handler
        self.default_data_encoding = 'utf-8'
        self.init_reported_properties = init_reported_properties

    def send_d2c_message(
        self, message_text, properties=None
    ):
        from azure.iot.device import Message

        message = Message(message_text)
        message.custom_properties = properties
        self.device_client.send_message(message)

    def message_handler(
        self, message
    ):
        property_names = [
            "message_id", "expiry_time_utc", "correlation_id", "user_id",
            "content_encoding", "content_type", "_iothub_interface_id"
        ]

        message_properties = {}
        message_attributes = vars(message)

        for item in message_attributes:
            if item in property_names and message_attributes[item] is not None:
                message_properties[item] = message_attributes[item]

        message_properties.update(message.custom_properties)

        if message.data and "content_encoding" in message_properties:
            try:
                payload = message.data.decode(encoding=message_properties["content_encoding"])
            except Exception as x:
                raise x
        else:
            payload = message.data.decode(encoding=self.default_data_encoding)

        output = {
            "Topic": "/devices/{}/messages/devicebound".format(self.device_id),
            "Payload": payload,
            "Message Properties": message_properties
        }
        print("\nC2D Message Handler [Received C2D message]:")
        printer.pprint(output)

    def method_request_handler(
        self, method_request
    ):
        from azure.iot.device import MethodResponse

        output = {
            "Device Id": self.device_id,
            "Method Request Id": method_request.request_id,
            "Method Request Name": method_request.name,
            "Method Request Payload": method_request.payload
        }

        print("\nMethod Request Handler [Received direct method invocation request]:")
        printer.pprint(output)

        # set response payload
        if self.method_response_payload:
            payload = self.method_response_payload
        else:
            payload = {
                "methodName": method_request.name,
                "methodRequestId": method_request.request_id,
                "methodRequestPayload": method_request.payload
            }

        # set response status code
        if self.method_response_code:
            status = self.method_response_code
        else:
            status = 200

        method_response = MethodResponse.create_from_method_request(method_request, status, payload)
        self.device_client.send_method_response(method_response)

    def twin_patch_handler(
        self, patch
    ):
        modified_properties = {}
        for prop in patch:
            if not prop.startswith("$"):
                modified_properties[prop] = patch[prop]

        if modified_properties:
            print("\nTwin patch handler [Updating device twin reported properties]:")
            printer.pprint(modified_properties)
            self.device_client.patch_twin_reported_properties(modified_properties)

    def execute(
        self, data, properties={}, publish_delay=2, msg_count=100
    ):
        from tqdm import tqdm

        try:
            if self.init_reported_properties:
                self.device_client.patch_twin_reported_properties(self.init_reported_properties)

            for _ in tqdm(range(0, msg_count), desc='Device simulation in progress', ascii=' #'):
                self.send_d2c_message(message_text=data.generate(True), properties=properties)
                sleep(publish_delay)

        except Exception as x:
            raise x

    def shutdown(self):
        try:
            self.device_client.shutdown()
        except Exception:
            pass
