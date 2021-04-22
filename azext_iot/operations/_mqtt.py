# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import six

from time import sleep
from azext_iot.constants import USER_AGENT, BASE_MQTT_API_VERSION
from azext_iot.common.utility import url_encode_str
from azure.iot.device import IoTHubDeviceClient as mqtt_device_client, Message, MethodResponse
from azure.iot.hub import IoTHubRegistryManager, DigitalTwinClient

class mqtt_client(object):
    def __init__(self, target, device_connection_string, device_id):
        self.device_id = device_id
        self.registry_manager = IoTHubRegistryManager(target["cs"]) 
        self.device_client = mqtt_device_client.create_from_connection_string(device_connection_string)
        self.digital_twin_client =  DigitalTwinClient(target["cs"])
        self.device_client.connect()
        self.device_client.on_message_received = self.message_handler
        self.device_client.on_method_request_received = self.method_request_handler

    def send_c2d_message(self, message_text="", properties={}):
        result = {
            "status": None,
            "error": None
        }
        try:
            self.registry_manager.send_c2d_message(self.device_id, message_text, properties)
            result.status = "C2D Message sent succesfully"
        except Exception as ex:
            result.status = "Failed to send C2D Message"
            result.error = "Unexpected error {0}".format(ex)
        return result
    
    def send_d2c_message(self, message_text="", properties={}):
        message = Message(message_text)
        message.custom_properties = properties
        self.device_client.send_message(message)
    
    def invoke_direct_method(self, command_name, payload="", connect_timeout_in_seconds=100, response_timeout_in_seconds=100):
        self.digital_twin_client.invoke_command(self.device_id, command_name, payload, connect_timeout_in_seconds, response_timeout_in_seconds)

    def message_handler(self, message):
        six.print_()
        six.print_("_Received C2D message with topic_: /devices/{}/messages/devicebound".format(self.device_id))
        six.print_("_Payload_: {}".format(message.data))
        if message.custom_properties:
            six.print_("_Custom Properties_: {}".format(message.custom_properties))
    
    def method_request_handler(self, method_request):
        six.print_()
        six.print_("Received method request with id: '{}' and method name: '{}' for device with id: '{}'".format(method_request.request_id, method_request.name, self.device_id))
        six.print_("_Payload_: {}".format(method_request.payload))
        payload = {"result": True, "data": "Method succeeded"}  # set response payload
        status = 200  # set return status code
        method_response = MethodResponse.create_from_method_request(method_request, status, payload)
        self.device_client.send_method_response(method_response)
    
    def execute(self, data, properties={}, publish_delay=2, msg_count=100):
        try:
            msgs = 0
            while True:
                if msgs < msg_count:
                    msgs += 1
                    self.send_d2c_message(message_text=data.generate(True), properties=properties)
                    six.print_(".", end="", flush=True)
                else:
                    break
                sleep(publish_delay)
        except Exception as x:
            raise x

def build_mqtt_device_username(entity, device_id):
    return "{}/{}/?api-version={}&DeviceClientType={}".format(
        entity, device_id, BASE_MQTT_API_VERSION, url_encode_str(USER_AGENT)
    )