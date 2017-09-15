# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.
# pylint: disable=no-self-use,unused-argument,no-name-in-module,too-many-instance-attributes

import time
import os
import threading
import functools
import six
from iothub_client import (IoTHubMessage, IoTHubMessageDispositionResult, IoTHubClient,
                           IoTHubTransportProvider, IoTHubClientConfirmationResult,
                           IoTHubClientRetryPolicy)

six.print_ = functools.partial(six.print_, flush=True)


class DeviceManager(object):
    def __init__(self, connection_string, protocol=IoTHubTransportProvider.MQTT):
        self.receive_context = 0
        self.connection_status_context = 0
        self.file_upload_context = 0

        # messageTimeout - the maximum time in milliseconds until a message times out.
        # The timeout period starts at IoTHubClient.send_event_async.
        # By default, messages do not expire.
        self.default_msg_timeout = 10000

        self.protocol = protocol
        self.client = IoTHubClient(connection_string, self.protocol)
        self.client.set_option("messageTimeout", self.default_msg_timeout)
        self.default_receive_settle = IoTHubMessageDispositionResult.ACCEPTED
        self.client.set_retry_policy(IoTHubClientRetryPolicy.RETRY_INTERVAL, 100)

        # Due to current event handling mechanics
        self._keep_alive = True
        self._send_error = None
        self._receive_count = 0

        self.lock = threading.Lock()

        # HTTP options
        # Because it can poll "after 9 seconds" polls will happen effectively
        # at ~10 seconds.
        # Note that for scalabilty, the default value of minimumPollingTime
        # is 25 minutes. For more information, see:
        # https://azure.microsoft.com/documentation/articles/iot-hub-devguide/#messaging
        self.http_timeout = 241000
        self.http_min_poll_time = 9

        if self.protocol == IoTHubTransportProvider.HTTP:
            self.client.set_option("timeout", self.http_timeout)
            self.client.set_option("MinimumPollingTime", self.http_min_poll_time)
        if self.protocol == IoTHubTransportProvider.AMQP:
            self.client.set_connection_status_callback(self.connection_status_callback,
                                                       self.connection_status_context)

    def keep_alive(self):
        return self._keep_alive

    def received(self):
        return self._receive_count

    def get_errors(self):
        return self._send_error

    def configure_receive_settle(self, settle=None):
        if settle is not None:
            if settle == "reject":
                self.default_receive_settle = IoTHubMessageDispositionResult.REJECTED
            elif settle == "abandon":
                self.default_receive_settle = IoTHubMessageDispositionResult.ABANDONED
            else:
                self.default_receive_settle = IoTHubMessageDispositionResult.ACCEPTED
            # Callback
            self.client.set_message_callback(self.receive_message_callback, self.receive_context)
            return self.default_receive_settle

    def receive_message_callback(self, message, context):
        with self.lock:
            self._receive_count += 1

        message_buffer = message.get_bytearray()
        size = len(message_buffer)
        six.print_("\n")
        six.print_("_Received Message_")
        six.print_("Size: %d " % size)
        six.print_("Data: %s " % (message_buffer[:size].decode('utf-8')))
        map_properties = message.properties()
        key_value_pair = map_properties.get_internals()
        six.print_("Properties: %s" % key_value_pair)
        six.print_("Message settled with: %s" % self.default_receive_settle)

        return self.default_receive_settle

    def send_event(self, data, props, message_id=None, correlation_id=None, send_context=0, print_context=None):
        msg = IoTHubMessage(bytearray(data, 'utf8'))
        if message_id is not None:
            msg.message_id = message_id
        if correlation_id is not None:
            msg.correlation_id = correlation_id

        if props:
            for k in props.keys():
                properties = msg.properties()
                properties.add_or_update(str(k), props[k])

        if print_context:
            # flush buffer
            six.print_("\n")
            six.print_(print_context)

        self.client.send_event_async(msg, self.send_event_result_callback, send_context)

        # This section is due to current IoT SDK event mechanics
        time_accum = 0
        wait_time = 1
        while time_accum < self.default_msg_timeout and self.keep_alive():
            time.sleep(wait_time)
            time_accum += wait_time

        errors = self.get_errors()
        if errors:
            raise RuntimeError(errors)

    def send_event_result_callback(self, message, result, context):
        if result is not IoTHubClientConfirmationResult.OK:
            self._send_error = "Send message error. Result: {}".format(result)
        self._keep_alive = False

    def connection_status_callback(self, result, reason, user_context):
        # Leaving the callback helps prevents amqp destroy output
        pass

    def upload_file_to_blob(self, file_path):
        six.print_("Processing file upload...")
        _file = open(file_path, 'r')
        content = _file.read()
        filename = os.path.basename(file_path)
        self.client.upload_blob_async(filename, content, len(content),
                                      self.upload_file_to_blob_result_callback, self.file_upload_context)

    def upload_file_to_blob_result_callback(self, result, context):
        six.print_("File upload to blob completed. Result: {}".format(result))
