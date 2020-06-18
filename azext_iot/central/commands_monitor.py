# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.commands import AzCliCommand
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.monitor_provider import MonitorProvider
from azext_iot.monitor.models.enum import Severity
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error, find_between
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication
from azext_iot.central.models.instance import Property
from datetime import datetime, timezone, timezone
from azext_iot.central.providers.device_provider import get_device_twin
import time

from azext_iot.monitor.models.arguments import (
    CommonParserArguments,
    CommonHandlerArguments,
    CentralHandlerArguments,
    TelemetryArguments,
)


def validate_messages(
    cmd: AzCliCommand,
    app_id,
    device_id=None,
    module_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    max_messages=10,
    duration=300,
    style="scroll",
    minimum_severity=Severity.warning.name,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    telemetry_args = TelemetryArguments(
        cmd,
        timeout=timeout,
        properties=properties,
        enqueued_time=enqueued_time,
        repair=repair,
        yes=yes,
    )
    common_parser_args = CommonParserArguments(
        properties=telemetry_args.properties, content_type="application/json"
    )
    common_handler_args = CommonHandlerArguments(
        output=telemetry_args.output,
        common_parser_args=common_parser_args,
        device_id=device_id,
        module_id=module_id,
    )
    central_handler_args = CentralHandlerArguments(
        duration=duration,
        max_messages=max_messages,
        style=style,
        minimum_severity=Severity[minimum_severity],
        common_handler_args=common_handler_args,
    )
    provider = MonitorProvider(
        cmd=cmd,
        app_id=app_id,
        consumer_group=consumer_group,
        central_dns_suffix=central_dns_suffix,
        central_handler_args=central_handler_args,
    )
    provider.start_validate_messages(telemetry_args)


def monitor_events(
    cmd: AzCliCommand,
    app_id,
    device_id=None,
    module_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    telemetry_args = TelemetryArguments(
        cmd,
        timeout=timeout,
        properties=properties,
        enqueued_time=enqueued_time,
        repair=repair,
        yes=yes,
    )
    common_parser_args = CommonParserArguments(
        properties=telemetry_args.properties, content_type="application/json"
    )
    common_handler_args = CommonHandlerArguments(
        output=telemetry_args.output,
        common_parser_args=common_parser_args,
        device_id=device_id,
        module_id=module_id,
    )
    central_handler_args = CentralHandlerArguments(
        duration=0,
        max_messages=0,
        style="scroll",
        minimum_severity=Severity.warning,
        common_handler_args=common_handler_args,
    )
    provider = MonitorProvider(
        cmd=cmd,
        app_id=app_id,
        consumer_group=consumer_group,
        central_dns_suffix=central_dns_suffix,
        central_handler_args=central_handler_args,
    )
    provider.start_monitor_events(telemetry_args)


def monitor_properties(cmd, device_id, app_id, central_dns_suffix=CENTRAL_ENDPOINT):
    polling_interval_seconds = 10
    processed_desired_properties_version = None
    processed_reported_properties_version = None
    while True:

        twin_data = get_device_twin(
            cmd,
            device_id=device_id,
            app_id=app_id,
            central_dns_suffix=central_dns_suffix,
        )

        utc_time_stamp_now = datetime.utcnow().timestamp()

        desired_properties = Property(
            "desired property",
            twin_data.get("properties").get("desired"),
            utc_time_stamp_now,
        )

        reported_properties = Property(
            "reported property",
            twin_data.get("properties").get("reported"),
            utc_time_stamp_now,
        )

        # process desired properties
        if processed_desired_properties_version != desired_properties.version:
            desired_properties.process_property_updates()
            processed_desired_properties_version = desired_properties.version

        # process reported properties
        if processed_reported_properties_version != reported_properties.version:
            reported_properties.process_property_updates()
            processed_reported_properties_version = reported_properties.version
        time.sleep(polling_interval_seconds)

