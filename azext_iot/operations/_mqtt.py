# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from time import sleep
from azext_iot.constants import USER_AGENT, BASE_MQTT_API_VERSION
from azext_iot.common.utility import url_encode_str
from azure.iot.device import IoTHubDeviceClient as mqtt_device_client, Message, MethodResponse
import pprint


class mqtt_client(object):
    def __init__(self, target, device_conn_string, device_id, method_response_code=None, method_response_payload=None):
        self.device_id = device_id
        self.target = target
        self.device_client = mqtt_device_client.create_from_connection_string(device_conn_string)
        self.device_client.connect()
        self.device_client.on_message_received = self.message_handler
        self.device_client.on_method_request_received = self.method_request_handler
        self.method_response_code = method_response_code
        self.method_response_payload = method_response_payload
        self.device_client.on_twin_desired_properties_patch_received = self.twin_patch_handler
        self.printer = pprint.PrettyPrinter(indent=2)
        self.default_data_encoding = 'utf-8'

    def send_d2c_message(self, message_text, properties=None):
        message = Message(message_text)
        message.custom_properties = properties
        self.device_client.send_message(message)

    def message_handler(self, message):
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
        self.printer.pprint(output)

    def method_request_handler(self, method_request):

        output = {
            "Device Id": self.device_id,
            "Method Request Id": method_request.request_id,
            "Method Request Name": method_request.name,
            "Method Request Payload": method_request.payload
        }

        print("\nMethod Request Handler [Received direct method invocation request]:")
        self.printer.pprint(output)

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

    def twin_patch_handler(self, patch):
        modified_properties = {}
        for prop in patch:
            if not prop.startswith("$"):
                modified_properties[prop] = patch[prop]

        if modified_properties:
            print("\nTwin patch handler [Updating device twin reported properties]:")
            self.printer.pprint(modified_properties)
            self.device_client.patch_twin_reported_properties(modified_properties)

    def execute(self, data, properties={}, publish_delay=2, msg_count=100):
        from tqdm import tqdm
        try:
            for _ in tqdm(range(msg_count), desc='Device simulation in progress'):
                self.send_d2c_message(message_text=data.generate(True), properties=properties)
                sleep(publish_delay)

        except Exception as x:
            raise x


def build_mqtt_device_username(entity, device_id):
    return "{}/{}/?api-version={}&DeviceClientType={}".format(
        entity, device_id, BASE_MQTT_API_VERSION, url_encode_str(USER_AGENT)
    )
