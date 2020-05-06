# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.utility import init_monitoring
from azext_iot.central.providers import CentralDeviceProvider


def validate_messages(
    cmd,
    app_id,
    device_id=None,
    simulate_errors=False,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    central_dns_suffix="azureiotcentral.com",
):
    _events3_runner(
        cmd=cmd,
        app_id=app_id,
        device_id=device_id,
        validate_messages=True,
        simulate_errors=simulate_errors,
        consumer_group=consumer_group,
        timeout=timeout,
        enqueued_time=enqueued_time,
        repair=repair,
        properties=properties,
        yes=yes,
        central_dns_suffix=central_dns_suffix,
    )


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
    _events3_runner(
        cmd=cmd,
        app_id=app_id,
        device_id=device_id,
        validate_messages=False,
        simulate_errors=False,
        consumer_group=consumer_group,
        timeout=timeout,
        enqueued_time=enqueued_time,
        repair=repair,
        properties=properties,
        yes=yes,
        central_dns_suffix=central_dns_suffix,
    )


def _events3_runner(
    cmd,
    app_id,
    device_id,
    validate_messages,
    simulate_errors,
    consumer_group,
    timeout,
    enqueued_time,
    repair,
    properties,
    yes,
    central_dns_suffix,
):
    provider = CentralDeviceProvider(cmd, app_id)
    (enqueued_time, properties, timeout, output) = init_monitoring(
        cmd, timeout, properties, enqueued_time, repair, yes
    )

    from azext_iot.monitor.builders import central_target_builder
    from azext_iot.monitor.handlers import CentralHandler
    from azext_iot.monitor.utility import generate_on_start_string
    from azext_iot.monitor import telemetry

    on_start_string = generate_on_start_string(device_id=device_id, pnp_context=None)

    targets = central_target_builder.build_central_event_hub_targets(
        cmd, app_id, central_dns_suffix
    )
    [target.add_consumer_group(consumer_group) for target in targets]

    handler = CentralHandler(
        provider, device_id=device_id, properties=properties, output=output
    )

    telemetry.start_multiple_monitors(
        targets=targets,
        enqueued_time_utc=enqueued_time,
        on_start_string=on_start_string,
        on_message_received=handler.validate_message,
        timeout=timeout,
    )
