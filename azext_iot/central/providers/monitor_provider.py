# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azure.cli.core.commands import AzCliCommand
from azext_iot.central.providers.v1 import (
    CentralDeviceProviderV1,
    CentralDeviceTemplateProviderV1,
)

from azext_iot.monitor.models.arguments import (
    CentralHandlerArguments,
    TelemetryArguments,
)


class MonitorProvider:
    """
    Provider for monitor events and validating messages
    """

    def __init__(
        self,
        cmd: AzCliCommand,
        app_id: str,
        token: str,
        consumer_group: str,
        central_handler_args: CentralHandlerArguments,
        central_dns_suffix: str,
    ):
        central_device_provider = CentralDeviceProviderV1(
            cmd=cmd, app_id=app_id, token=token
        )
        central_template_provider = CentralDeviceTemplateProviderV1(
            cmd=cmd, app_id=app_id, token=token
        )
        self._targets = self._build_targets(
            cmd=cmd,
            app_id=app_id,
            token=token,
            consumer_group=consumer_group,
            central_dns_suffix=central_dns_suffix,
        )
        self._handler = self._build_handler(
            central_device_provider=central_device_provider,
            central_template_provider=central_template_provider,
            central_handler_args=central_handler_args,
        )

    def start_monitor_events(self, telemetry_args: TelemetryArguments):
        from azext_iot.monitor import telemetry

        telemetry.start_multiple_monitors(
            targets=self._targets,
            enqueued_time_utc=telemetry_args.enqueued_time,
            on_start_string=self._handler.generate_startup_string("Monitoring"),
            on_message_received=self._handler.parse_message,
            timeout=telemetry_args.timeout,
        )

    def start_validate_messages(self, telemetry_args: TelemetryArguments):
        from azext_iot.monitor import telemetry

        telemetry.start_multiple_monitors(
            targets=self._targets,
            enqueued_time_utc=telemetry_args.enqueued_time,
            on_start_string=self._handler.generate_startup_string("Validating"),
            on_message_received=self._handler.validate_message,
            timeout=telemetry_args.timeout,
        )

    def _build_targets(
        self,
        cmd: AzCliCommand,
        app_id: str,
        token: str,
        consumer_group: str,
        central_dns_suffix: str,
    ):
        from azext_iot.monitor.builders import central_target_builder

        targets = central_target_builder.build_central_event_hub_targets(
            cmd, app_id, token, central_dns_suffix
        )
        [target.add_consumer_group(consumer_group) for target in targets]

        return targets

    def _build_handler(
        self,
        central_device_provider: CentralDeviceProviderV1,
        central_template_provider: CentralDeviceTemplateProviderV1,
        central_handler_args: CentralHandlerArguments,
    ):
        from azext_iot.monitor.handlers import CentralHandler

        return CentralHandler(
            central_device_provider=central_device_provider,
            central_template_provider=central_template_provider,
            central_handler_args=central_handler_args,
        )
