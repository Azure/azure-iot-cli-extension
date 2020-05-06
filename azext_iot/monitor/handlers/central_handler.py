# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import time

from typing import List

from azext_iot.central.providers.device_provider import CentralDeviceProvider
from azext_iot.monitor.utility import kill_monitor
from azext_iot.monitor.handlers.handler import CommonHandler
from azext_iot.monitor.parsers.central_parser import CentralParser
from azext_iot.monitor.parsers.issue import Severity, Issue


class CentralHandler(CommonHandler):
    """
    Handles messages as they are read from egress event hub.
    Use this handler if you aren't sure which handler is right for you.
    Check CommonHandler (parent) for more kwargs.

    Keyword Args:
        abs_timeout         (int)       max run time for monitor in seconds. Use 0 for infinite. Defaults to 0.
        max_messages        (int)       max number of messages to validate. Use 0 for infinite. Defaults to 0.
        progress_interval   (int)       number of messages to wait between printing progress. Defaults to 5.
        minimum_severity    (Severity)  minimum severity for reporting issues. Defaults to Severity.warning.
    """

    def __init__(self, central_device_provider: CentralDeviceProvider, **kwargs):
        super(CentralHandler, self).__init__(**kwargs)
        self.central_device_provider = central_device_provider

        self.abs_timeout = kwargs.get("abs_timeout")
        self.max_messages = kwargs.get("max_messages")
        self.progress_interval = kwargs.get("progress_interval")
        self.minimum_severity = kwargs.get("minimum_severity")

        if not self.abs_timeout:
            self.abs_timeout = 0

        if not self.max_messages:
            self.max_messages = 10

        if not self.progress_interval or self.progress_interval < 1:
            self.progress_interval = 5

        if not self.minimum_severity:
            self.minimum_severity = Severity.warning

        print("Validation settings: {}".format(vars(self)))

        self.messages = []
        self.issues: List[Issue] = []
        self.start = time.time()

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

        end = time.time()
        if self.abs_timeout and (end - self.start) >= self.abs_timeout:
            print("Exiting due to timeout.", flush=True)
            self.print_results()
            kill_monitor()

        if self.max_messages and processed_messages_count >= self.max_messages:
            print("Exiting due to message count reached.", flush=True)
            self.print_results()
            kill_monitor()

    def print_results(self):
        message_len = len(self.messages)

        if not self.issues:
            print("No errors detected after parsing {} messages!".format(message_len))
            return

        for issue in self.issues:
            issue.log()
