# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azure.cli.core.commands import AzCliCommand
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.preview import MonitorProviderPreview
from azext_iot.central.providers.v1 import MonitorProviderV1
from azext_iot.monitor.models.enum import Severity
from azext_iot.monitor.models.arguments import (
    CommonParserArguments,
    CommonHandlerArguments,
    CentralHandlerArguments,
    TelemetryArguments,
)
from azext_iot.monitor.property import PropertyMonitor
from azext_iot.central.utils import process_version
from azext_iot.central.utils import throw_unsupported_version
from azext_iot.constants import PREVIEW
from azext_iot.constants import V1

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
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
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

    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = MonitorProviderPreview(
            cmd=cmd,
            app_id=app_id,
            token=token,
            consumer_group=consumer_group,
            central_dns_suffix=central_dns_suffix,
            central_handler_args=central_handler_args,
        )
    elif(version == V1):
        provider = MonitorProviderV1(
            cmd=cmd,
            app_id=app_id,
            token=token,
            consumer_group=consumer_group,
            central_dns_suffix=central_dns_suffix,
            central_handler_args=central_handler_args,
        )
    else:
        throw_unsupported_version(supported_versions)

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
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    version=None
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

    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)
    if(version == PREVIEW):
        provider = MonitorProviderPreview(
            cmd=cmd,
            app_id=app_id,
            token=token,
            consumer_group=consumer_group,
            central_dns_suffix=central_dns_suffix,
            central_handler_args=central_handler_args,
        )
    elif(version == V1):
        provider = MonitorProviderV1(
            cmd=cmd,
            app_id=app_id,
            token=token,
            consumer_group=consumer_group,
            central_dns_suffix=central_dns_suffix,
            central_handler_args=central_handler_args,
        )
    else:
        throw_unsupported_version(supported_versions)

    provider.start_monitor_events(telemetry_args)


def monitor_properties(
    cmd, device_id: str, app_id: str, token=None, central_dns_suffix=CENTRAL_ENDPOINT, version=None
):
    supported_versions = [PREVIEW, V1]
    version = process_version(supported_versions, version)

    if(version not in supported_versions):
        throw_unsupported_version(supported_versions)

    monitor = PropertyMonitor(
        cmd=cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
        version=version
    )
    monitor.start_property_monitor()


def validate_properties(
    cmd,
    device_id: str,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    minimum_severity=Severity.warning.name,
    version=None
):
    monitor = PropertyMonitor(
        cmd=cmd,
        app_id=app_id,
        device_id=device_id,
        token=token,
        central_dns_suffix=central_dns_suffix,
        version=version
    )
    monitor.start_validate_property_monitor(Severity[minimum_severity])
