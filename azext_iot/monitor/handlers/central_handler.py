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

    Args:
        duration          (int)       Maximum duration to keep listening for events. Use 0 "forever". Defaults to 0.
        max_messages        (int)       Maximum number of messages to read. Use 0 "forever". Defaults to 0.
        progress_interval   (int)       number of messages to wait between printing progress. Defaults to 5.
        minimum_severity    (Severity)  minimum severity for reporting issues. Defaults to Severity.warning.
        device_id           (str)       only process messages sent by this device
        properties          (list)      list of properties to extract from message headers
        output              (str)       output format (json, yaml, etc)
    """

    def __init__(
        self,
        device_id: str,
        content_type: str,
        properties: list,
        style: str,
        central_device_provider: CentralDeviceProvider,
        duration: int,
        max_messages: int,
        minimum_severity: Severity,
    ):
        super(CentralHandler, self).__init__(
            device_id=device_id,
            content_type=content_type,
            properties=properties,
            output="json",
            devices=None,
            interface_name=None,
        )
        self._progress_interval = 5
        self._central_device_provider = central_device_provider

        self._time_range = duration
        self._max_messages = max_messages
        self._minimum_severity = minimum_severity
        self._style = style

        self.messages = []
        self.issues: List[Issue] = []

        if self._time_range:
            loop = get_loop()
            # the monitor takes a few seconds to start
            loop.call_later(self._time_range + 5, self._quit_on_time_range)

    def validate_message(self, message):
        parser = CentralParser(self._central_device_provider)
        device_id = parser.parse_device_id(message)

        if not self._should_process_device(device_id, self.device_id, self.devices):
            return

        parsed_message = parser.parse_message(
            message,
            properties=self.properties,
            interface_name=self.interface_name,
            content_type=self.content_type,
        )

        issues = parser.issues_handler.get_issues_with_minimum_severity(
            self._minimum_severity
        )

        self.issues.extend(issues)

        self.messages.append(parsed_message)
        processed_messages_count = len(self.messages)
        if (processed_messages_count % self._progress_interval) == 0:
            print(
                "Processed {} messages...".format(processed_messages_count), flush=True
            )

        if self._max_messages and processed_messages_count >= self._max_messages:
            message = "Successfully parsed {} message(s).".format(self._max_messages)
            print(message, flush=True)
            self.print_results()
            stop_monitor()

        if self._style == "scroll":
            [issue.log() for issue in issues]
            return

    def print_results(self):
        message_len = len(self.messages)

        if not self.issues:
            print("No errors detected after parsing {} message(s).".format(message_len))
            return

        if self._style.lower() == "scroll":
            return

        print("Processing and displaying results.")

        issues = [issue.json_repr() for issue in self.issues]

        if self._style.lower() == "json":
            import json

            output = json.dumps(issues, indent=4)
            print(output)
            return

        if self._style.lower() == "csv":
            import csv
            import sys

            fieldnames = ["severity", "details", "message", "device_id", "template_id"]
            writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
            writer.writeheader()
            for issue in issues:
                writer.writerow(issue)
            return

    def generate_startup_string(self, name: str):
        device_filter_text = ""
        if self.device_id:
            device_filter_text = ".\nFiltering on device: {}".format(self.device_id)

        exit_text = ""
        if self._time_range and self._max_messages:
            exit_text = ".\nExiting after {} second(s), or {} message(s) have been parsed (whichever happens first).".format(
                self._time_range, self._max_messages
            )
        elif self._time_range:
            exit_text = ".\nExiting after {} second(s).".format(self._time_range)
        elif self._max_messages:
            exit_text = ".\nExiting after parsing {} message(s).".format(
                self._max_messages
            )

        result = "{} telemetry{}{}".format(name, device_filter_text, exit_text)

        return result

    def _quit_on_time_range(self):
        message = "{} second(s) have elapsed. Processing and displaying results.".format(
            self._time_range
        )
        print(message, flush=True)
        self.print_results()
        stop_monitor()
