# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError

from azext_iot.central.providers import CentralDeviceProvider
from azext_iot.common.utility import init_monitoring


class MonitorProvider:
    """
    Provider for monitor events and validating messages

    Keyword Args:
        device_id           (str)   Only process messages sent by this device.
                                    Will monitor all messages from all devices if omitted.
        consumer_group      (str)   Specify the consumer group to use when connecting to event hub endpoint.
                                    See more: https://docs.microsoft.com/en-us/azure/event-hubs/event-hubs-features
        timeout             (int)   Max time to listen for events.
                                    Unit: seconds.
        max_messages        (int)   Max number of messages to validate. Use 0 for infinite. Defaults to 0.
        properties          (list)  Key message properties to output.
                                    sys = system properties, app = application properties, anno = annotations
                                    Default: None.
        enqueued_time       (float) Time that should be used as a starting point to read messages.
                                    Unit: milliseconds since Epoch (Jan 1, 1970).
                                    Default: "Now".
        repair              (bool)  Reinstall uamqp dependency compatible with extension version.
                                    Default: False.
        yes                 (bool)  Skip user prompts. Indicates acceptance of dependency installation (if required).
                                    Default: False.
        minimum_severity    (Sev)   minimum severity for reporting issues.
                                    Default: Severity.warning.
        central_dns_suffix  (str)   This enables running cli commands against non public/prod environments.
    """

    def __init__(
        self,
        cmd,
        app_id,
        device_id,
        consumer_group,
        timeout,
        max_messages,
        properties,
        enqueued_time,
        repair,
        yes,
        minimum_severity,
        central_dns_suffix,
        content_type,
        time_range,
    ):
        self._importing_allowed = False
        self._provider = CentralDeviceProvider(cmd, app_id)
        self._init_monitoring(cmd, timeout, properties, enqueued_time, repair, yes)
        self._targets = self._build_targets(
            cmd, app_id, central_dns_suffix, consumer_group
        )
        self._handler = self._build_handler(
            device_id,
            content_type,
            properties,
            self._provider,
            time_range,
            max_messages,
            minimum_severity,
        )

    def start_monitor_events(self):
        self._ensure_uamqp_import_succeeded()
        from azext_iot.monitor import telemetry

        telemetry.start_multiple_monitors(
            targets=self._targets,
            enqueued_time_utc=self._enqueued_time,
            on_start_string=self._handler.generate_startup_string("Monitoring"),
            on_message_received=self._handler.parse_message,
            timeout=self._timeout,
        )

    def start_validate_messages(self):
        self._ensure_uamqp_import_succeeded()
        from azext_iot.monitor import telemetry

        telemetry.start_multiple_monitors(
            targets=self._targets,
            enqueued_time_utc=self._enqueued_time,
            on_start_string=self._handler.generate_startup_string("Validating"),
            on_message_received=self._handler.validate_message,
            timeout=self._timeout,
        )

    def _init_monitoring(
        self,
        cmd,
        timeout: int,
        properties: list,
        enqueued_time: float,
        repair: bool,
        yes: bool,
    ):
        (enqueued_time, unique_properties, timeout_ms, output) = init_monitoring(
            cmd, timeout, properties, enqueued_time, repair, yes
        )

        self._enqueued_time = enqueued_time
        self._properties = unique_properties
        self._timeout = timeout_ms
        self._output = output

        self._importing_allowed = True

    def _ensure_uamqp_import_succeeded(self):
        if not self._importing_allowed:
            raise CLIError("Cannot proceed until monitor is initialized")

    def _build_targets(self, cmd, app_id, central_dns_suffix: str, consumer_group: str):
        self._ensure_uamqp_import_succeeded()

        from azext_iot.monitor.builders import central_target_builder

        targets = central_target_builder.build_central_event_hub_targets(
            cmd, app_id, central_dns_suffix
        )
        [target.add_consumer_group(consumer_group) for target in targets]

        return targets

    def _build_handler(
        self,
        device_id,
        content_type,
        properties,
        provider,
        time_range,
        max_messages,
        minimum_severity,
    ):
        self._ensure_uamqp_import_succeeded()
        from azext_iot.monitor.handlers import CentralHandler

        return CentralHandler(
            device_id,
            content_type,
            properties,
            self._output,
            provider,
            time_range,
            max_messages,
            minimum_severity,
        )
