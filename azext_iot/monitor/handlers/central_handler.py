# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List

from azext_iot.central.providers.device_provider import CentralDeviceProvider
from azext_iot.monitor.utility import stop_monitor, get_loop
from azext_iot.monitor.handlers.common_handler import CommonHandler
from azext_iot.monitor.parsers.central_parser import CentralParser
from azext_iot.monitor.parsers.issue import Severity, Issue


class CentralHandler(CommonHandler):
    """
    Handles messages as they are read from egress event hub.

    Keyword Args:
        timeout             (int)       Maximum duration to keep listening for events. Use 0 "forever". Defaults to 0.
        max_messages        (int)       Maximum number of messages to read. Use 0 "forever". Defaults to 0.
        progress_interval   (int)       number of messages to wait between printing progress. Defaults to 5.
        minimum_severity    (Severity)  minimum severity for reporting issues. Defaults to Severity.warning.
        device_id           (str)       only process messages sent by this device
        properties          (list)      list of properties to extract from message headers
        output              (str)       output format (json, yaml, etc)
    """

    def __init__(self, central_device_provider: CentralDeviceProvider, **kwargs):
        super(CentralHandler, self).__init__(**kwargs)
        self.central_device_provider = central_device_provider

        self.timeout = kwargs.get("timeout") or 0
        self.max_messages = kwargs.get("max_messages") or 0
        self.progress_interval = kwargs.get("progress_interval") or 5
        self.minimum_severity = kwargs.get("minimum_severity") or Severity.warning

        self.messages = []
        self.issues: List[Issue] = []

        if self.timeout:
            loop = get_loop()
            # the monitor takes a few seconds to start
            loop.call_later(self.timeout + 5, self._quit_on_timeout)

    def validate_message(self, msg):
        parser = CentralParser(self.central_device_provider)
        device_id = parser.parse_device_id(msg)

        if not self._should_process_device(device_id, self.device_id, self.devices):
            return

        parsed_msg = parser.parse_message(
            msg,
            properties=self.properties,
            interface_name=self.interface_name,
            pnp_context=self.pnp_context,
            content_type=self.content_type,
        )

        issues = parser.issues_handler.get_issues_with_minimum_severity(
            self.minimum_severity
        )

        self.issues.extend(issues)

        self.messages.append(parsed_msg)
        processed_messages_count = len(self.messages)
        if (processed_messages_count % self.progress_interval) == 0:
            print(
                "Processed {} messages...".format(processed_messages_count), flush=True
            )

        if self.max_messages and processed_messages_count >= self.max_messages:
            message = "Successfully parsed {} message(s). Processing and displaying results.".format(
                self.max_messages
            )
            print(message, flush=True)
            self.print_results()
            stop_monitor()

    def print_results(self):
        message_len = len(self.messages)

        if not self.issues:
            print("No errors detected after parsing {} message(s).".format(message_len))
            return

        for issue in self.issues:
            issue.log()

    def generate_startup_string(self, name: str):
        device_filter_text = ""
        if self.device_id:
            device_filter_text = ".\nFiltering on device: {}".format(self.device_id)

        exit_text = ""
        if self.timeout and self.max_messages:
            exit_text = ".\nExiting after {} second(s), or {} message(s) have been parsed (whichever happens first).".format(
                self.timeout, self.max_messages
            )
        elif self.timeout:
            exit_text = ".\nExiting after {} second(s).".format(self.timeout)
        elif self.max_messages:
            exit_text = ".\nExiting after parsing {} message(s).".format(
                self.max_messages
            )

        result = "{} telemetry{}{}".format(name, device_filter_text, exit_text)

        return result

    def _quit_on_timeout(self):
        message = "{} second(s) have elapsed. Processing and displaying results.".format(
            self.timeout
        )
        print(message, flush=True)
        self.print_results()
        stop_monitor()
