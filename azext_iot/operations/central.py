# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error, init_monitoring
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication
from azext_iot.central.providers import CentralDeviceProvider


def find_between(s, start, end):
    return (s.split(start))[1].split(end)[0]


def iot_central_device_show(
    cmd, device_id, app_id, central_api_uri="azureiotcentral.com"
):
    from azext_iot.common._azure import get_iot_central_tokens

    tokens = get_iot_central_tokens(cmd, app_id, central_api_uri)
    exception = None

    # The device could be in any hub associated with the given app.
    # We must search through each IoT Hub until device is found.
    for token_group in tokens.values():
        sas_token = token_group["iothubTenantSasToken"]["sasToken"]
        endpoint = find_between(sas_token, "SharedAccessSignature sr=", "&sig=")
        target = {"entity": endpoint}
        auth = BasicSasTokenAuthentication(sas_token=sas_token)
        service_sdk, errors = _bind_sdk(target, SdkType.service_sdk, auth=auth)
        try:
            return service_sdk.get_twin(device_id)
        except errors.CloudError as e:
            if exception is None:
                exception = CLIError(unpack_msrest_error(e))

    raise exception


def iot_central_validate_messages(
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
    central_api_uri="azureiotcentral.com",
):
    provider = CentralDeviceProvider(cmd, app_id)
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
        central_api_uri=central_api_uri,
        central_device_provider=provider,
    )


def iot_central_monitor_events(
    cmd,
    app_id,
    device_id=None,
    consumer_group="$Default",
    timeout=300,
    enqueued_time=None,
    repair=False,
    properties=None,
    yes=False,
    central_api_uri="azureiotcentral.com",
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
        central_api_uri=central_api_uri,
        central_device_provider=None,
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
    central_api_uri,
    central_device_provider,
):
    (enqueued_time, properties, timeout, output) = init_monitoring(
        cmd, timeout, properties, enqueued_time, repair, yes
    )

    from azext_iot.monitor import runner
    from azext_iot.monitor.builders import central_target_builder
    from azext_iot.monitor.models.runner import ExecutorData
    from azext_iot.monitor.handlers.handler import CommonHandler

    event_hub_targets = central_target_builder.build_central_event_hub_targets(
        cmd, app_id, central_api_uri
    )
    executors = [ExecutorData(target, consumer_group) for target in event_hub_targets]

    handler = CommonHandler(device_id=device_id, properties=properties, output=output)

    on_start_string = runner.generate_on_start_string(
        device_id=device_id, pnp_context=None
    )

    runner.n_executor(
        executors=executors,
        enqueued_time_utc=enqueued_time,
        on_start_string=on_start_string,
        on_message_received=handler.parse_message,
        timeout=timeout,
    )
