# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import csv
import sys

from typing import List
from knack.log import get_logger

from azext_iot.monitor.utility import stop_monitor, get_loop
from azext_iot.central.providers.v1 import (
    CentralDeviceProviderV1,
    CentralDeviceTemplateProviderV1,
)
from azext_iot.monitor.handlers import CommonHandler
from azext_iot.monitor.models.arguments import CentralHandlerArguments
from azext_iot.monitor.parsers.central_parser import CentralParser
from azext_iot.monitor.parsers.issue import Issue

logger = get_logger(__name__)


class CentralHandler(CommonHandler):
    def __init__(
        self,
        central_device_provider: CentralDeviceProviderV1,
        central_template_provider: CentralDeviceTemplateProviderV1,
        central_handler_args: CentralHandlerArguments,
    ):
        super(CentralHandler, self).__init__(
            common_handler_args=central_handler_args.common_handler_args
        )

        self._central_device_provider = central_device_provider
        self._central_template_provider = central_template_provider

        self._central_handler_args = central_handler_args

        self._messages = []
        self._issues: List[Issue] = []

        if self._central_handler_args.duration:
            loop = get_loop()
            # the monitor takes a few seconds to start
            loop.call_later(
                self._central_handler_args.duration + 5, self._quit_duration_exceeded
            )

    def validate_message(self, message):
        parser = CentralParser(
            message=message,
            common_parser_args=self._common_handler_args.common_parser_args,
            central_device_provider=self._central_device_provider,
            central_template_provider=self._central_template_provider,
        )

        if not self._should_process_device(parser.device_id):
            return

        if not self._should_process_module(parser.module_id):
            return

        parsed_message = parser.parse_message()

        self._messages.append(parsed_message)
        n_messages = len(self._messages)

        issues = parser.issues_handler.get_issues_with_minimum_severity(
            self._central_handler_args.minimum_severity
        )

        self._issues.extend(issues)

        self._print_progress_update(n_messages)

        if self._central_handler_args.style == "scroll" and issues:
            [issue.log() for issue in issues]

        if (
            self._central_handler_args.max_messages
            and n_messages >= self._central_handler_args.max_messages
        ):
            self._quit_messages_exceeded()

    def generate_startup_string(self, name: str):
        device_id = self._central_handler_args.common_handler_args.device_id
        duration = self._central_handler_args.duration
        max_messages = self._central_handler_args.max_messages
        module_id = self._central_handler_args.common_handler_args.module_id

        filter_text = ""
        if device_id:
            filter_text = ".\nFiltering on device: {}".format(device_id)

        if module_id:
            logger.warning("Module filtering is applicable only for edge devices.")
            filter_text += ".\nFiltering on module: {}".format(module_id)

        exit_text = ""
        if duration and max_messages:
            exit_text = ".\nExiting after {} second(s), or {} message(s) have been parsed (whichever happens first).".format(
                duration, max_messages,
            )
        elif duration:
            exit_text = ".\nExiting after {} second(s).".format(duration)
        elif max_messages:
            exit_text = ".\nExiting after parsing {} message(s).".format(max_messages)

        result = "{} telemetry{}{}".format(name, filter_text, exit_text)

        return result

    def _print_progress_update(self, n_messages: int):
        if (n_messages % self._central_handler_args.progress_interval) == 0:
            print("Processed {} messages...".format(n_messages), flush=True)

    def _print_results(self):
        n_messages = len(self._messages)

        if not self._issues:
            print("No errors detected after parsing {} message(s).".format(n_messages))
            return

        if self._central_handler_args.style.lower() == "scroll":
            return

        print("Processing and displaying results.")

        issues = [issue.json_repr() for issue in self._issues]

        if self._central_handler_args.style.lower() == "json":
            self._handle_json_summary(issues)
            return

        if self._central_handler_args.style.lower() == "csv":
            self._handle_csv_summary(issues)
            return

    def _handle_json_summary(self, issues: List[Issue]):
        import json

        output = json.dumps(issues, indent=4)
        print(output)

    def _handle_csv_summary(self, issues: List[Issue]):
        fieldnames = ["severity", "details", "message", "device_id", "template_id"]
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue)

    def _quit_messages_exceeded(self):
        message = "Successfully parsed {} message(s).".format(
            self._central_handler_args.max_messages
        )
        print(message, flush=True)
        self._print_results()
        stop_monitor()

    def _quit_duration_exceeded(self):
        message = "{} second(s) have elapsed.".format(
            self._central_handler_args.duration
        )
        print(message, flush=True)
        self._print_results()
        stop_monitor()
