# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import AzCliCommand
from azext_iot.common.utility import init_monitoring
from azext_iot.monitor.models.enum import Severity


class TelemetryArguments:
    def __init__(
        self,
        cmd: AzCliCommand,
        timeout: int,
        properties: list,
        enqueued_time: int,
        repair: bool,
        yes: bool,
    ):
        (enqueued_time, unique_properties, timeout_ms, output) = init_monitoring(
            cmd=cmd,
            timeout=timeout,
            properties=properties,
            enqueued_time=enqueued_time,
            repair=repair,
            yes=yes,
        )
        self.output = output
        self.timeout = timeout_ms
        self.properties = unique_properties
        self.enqueued_time = enqueued_time


class CommonParserArguments:
    def __init__(
        self, properties: list = None, content_type="",
    ):
        self.properties = properties or []
        self.content_type = content_type or ""


class CommonHandlerArguments:
    def __init__(
        self,
        output: str,
        common_parser_args: CommonParserArguments,
        devices: list = None,
        device_id="",
        interface_name="",
    ):
        self.output = output
        self.devices = devices or []
        self.device_id = device_id or ""
        self.interface_name = interface_name or ""
        self.common_parser_args = common_parser_args


class CentralHandlerArguments:
    def __init__(
        self,
        duration: int,
        max_messages: int,
        common_handler_args: CommonHandlerArguments,
        style="json",
        minimum_severity=Severity.warning,
        progress_interval=5,
    ):
        self.duration = duration
        self.max_messages = max_messages
        self.minimum_severity = minimum_severity
        self.progress_interval = progress_interval
        self.style = style
        self.common_handler_args = common_handler_args
