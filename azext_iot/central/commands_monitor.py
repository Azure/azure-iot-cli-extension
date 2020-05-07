# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.central.providers.monitor_provider import MonitorProvider
from azext_iot.monitor.parsers.issue import Severity


def validate_messages(
    cmd,
    app_id,
    device_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    max_messages=0,
    minimum_severity=Severity.warning.name,
    central_dns_suffix="azureiotcentral.com",
):
    kwargs = {
        "device_id": device_id,
        "consumer_group": consumer_group,
        "timeout": timeout,
        "enqueued_time": enqueued_time,
        "repair": repair,
        "properties": properties,
        "yes": yes,
        "max_messages": max_messages,
        "minimum_severity": Severity[minimum_severity],
        "central_dns_suffix": central_dns_suffix,
    }
    provider = MonitorProvider(cmd, app_id, **kwargs)
    provider.start_validate_messages()


def monitor_events(
    cmd,
    app_id,
    device_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    central_dns_suffix="azureiotcentral.com",
):
    kwargs = {
        "device_id": device_id,
        "consumer_group": consumer_group,
        "timeout": timeout,
        "enqueued_time": enqueued_time,
        "repair": repair,
        "properties": properties,
        "yes": yes,
        "central_dns_suffix": central_dns_suffix,
    }
    provider = MonitorProvider(cmd, app_id, **kwargs)
    provider.start_monitor_events()
