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

from azext_iot.central.models.instance import Instance, InstanceProperty

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
    from azext_iot.common._azure import get_iot_central_tokens

    tokens = get_iot_central_tokens(cmd, app_id, central_dns_suffix)
    exception = None

    # The device could be in any hub associated with the given app.
    # We must search through each IoT Hub until device is found.
    for token_group in tokens.values():
        sas_token = token_group["iothubTenantSasToken"]["sasToken"]
        endpoint = find_between(sas_token, "SharedAccessSignature sr=", "&sig=")
        target = {"entity": endpoint}
        auth = BasicSasTokenAuthentication(sas_token=sas_token)
        service_sdk, errors = _bind_sdk(target, SdkType.service_sdk, auth=auth)
        values = {}
        polling_interval_seconds = 10
        try:
            while True:
                twin_data = service_sdk.get_twin(device_id)

                invalid = {"$metadata", "$version"}

                desired_properties = twin_data.get("properties").get("desired")
                desired_properties_metadata = desired_properties.get("$metadata")
                desired_properties = without_keys(desired_properties, invalid)

                reported_properties = twin_data.get("properties").get("reported")
                reported_properties_metadata = reported_properties.get("$metadata")
                reported_properties = without_keys(reported_properties, invalid)

                from datetime import datetime, timezone, timezone

                utc_time = datetime.utcnow()
                utc_timestamp = utc_time.timestamp()

                desiredInstance = InstanceProperty("desired properties")
                value = desiredInstance.extract_print(
                    polling_interval_seconds + 100,
                    desired_properties_metadata,
                    desired_properties,
                    utc_timestamp,
                )
                if desiredInstance.data_List:
                    print(desiredInstance.name)
                    print(desiredInstance.data_List, sep="\n")

                # if desiredInstance.dataset:
                #     print)
                #     print(desiredInstance.dataset)

                reportedInstance = InstanceProperty("reported properties")
                value = reportedInstance.extract_print(
                    polling_interval_seconds + 1000,
                    reported_properties_metadata,
                    reported_properties,
                    utc_timestamp,
                )
                if reportedInstance.data_List:
                    print(reportedInstance.name)
                    print(*reportedInstance.data_List, sep="\n")
                # if desiredInstance.dataset:
                #     print()

                # print(value)

                # for values in data.items():
                #     datetime = values.get
                #     print(values, "\n")
                # # reported_properties_list = []
                # desired_properties_list = []

                # for value in reported_properties.items():
                #     if "iotin:" in value[0]:
                #         metadata = reported_properties.get("$metadata")
                #         temp = Instance(value[1], value[0], metadata)
                #         reported_properties_list.append(temp)

                # for value in desired_properties.items():
                #     if "iotin:" in value[0]:
                #         metadata = desired_properties.get("$metadata")
                #         temp = Instance(value[1], value[0], metadata)
                #         desired_properties_list.append(temp)

                import time

                # print("desired properties")
                # for value in desired_properties_list:
                #     print("instanceName :", value.instanceName)
                #     print(*value.property_list, sep="\n")
                # print("")

                # print("reported properties")
                # for value in reported_properties_list:
                #     print("instanceName :", value.instanceName)
                #     print(*value.property_list, sep="\n")
                # print("")
                time.sleep(polling_interval_seconds)
            return twin_data
        except errors.CloudError as e:
            if exception is None:
                exception = CLIError(unpack_msrest_error(e))

    raise exception


def without_keys(d, keys):
    return {x: d[x] for x in d if x not in keys}
