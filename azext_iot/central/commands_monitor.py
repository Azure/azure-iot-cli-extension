# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import datetime
import isodate
import time

from azure.cli.core.commands import AzCliCommand
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.monitor_provider import MonitorProvider
from azext_iot.monitor.models.enum import Severity
from azext_iot.monitor.models.arguments import (
    CommonParserArguments,
    CommonHandlerArguments,
    CentralHandlerArguments,
    TelemetryArguments,
)
from azext_iot.central.models.devicetwin import DeviceTwin, Property
from azext_iot.central.providers.device_provider import get_device_twin


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


def monitor_properties(
    cmd,
    device_id,
    app_id,
    polling_interval_seconds=1,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    prev_twin = None

    while True:
        raw_twin = get_device_twin(
            cmd,
            device_id=device_id,
            app_id=app_id,
            central_dns_suffix=central_dns_suffix,
        )

        twin = DeviceTwin(raw_twin)
        if prev_twin:
            change_d = compare_properties(
                prev_twin.desired_property, twin.desired_property
            )
            change_r = compare_properties(
                prev_twin.reported_property, twin.reported_property
            )

            if change_d:
                print("Changes in desired properties:")
                print(change_d)

            if change_r:
                print("Changes in reported properties:")
                print(change_r)

        time.sleep(polling_interval_seconds)

        prev_twin = twin


def compare_properties(prev_prop: Property, prop: Property):
    if prev_prop.version == prop.version:
        return

    changes = {
        key: prop.props[key]
        for key, val in prop.metadata.items()
        if is_relevant(key, val)
    }

    return changes


def is_relevant(key, val):
    if key in {"$lastUpdated", "$lastUpdatedVersion"}:
        return False

    updated_within = datetime.datetime.now() - datetime.timedelta(seconds=10)
    last_updated = isodate.parse_datetime(val["$lastUpdated"])
    return last_updated.timestamp() >= updated_within.timestamp()
