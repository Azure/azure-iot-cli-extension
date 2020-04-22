# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot._factory import _bind_sdk
from azext_iot.common._azure import get_iot_hub_token_from_central_app_id
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error, init_monitoring
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication
from azext_iot.central.providers import CentralDeviceProvider


def find_between(s, start, end):
    return (s.split(start))[1].split(end)[0]


def iot_central_device_show(
    cmd, device_id, app_id, central_api_uri="api.azureiotcentral.com"
):
    sasToken = get_iot_hub_token_from_central_app_id(cmd, app_id, central_api_uri)
    endpoint = find_between(sasToken, "SharedAccessSignature sr=", "&sig=")
    target = {"entity": endpoint}
    auth = BasicSasTokenAuthentication(sas_token=sasToken)
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk, auth=auth)
    try:
        return service_sdk.get_twin(device_id)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


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
    central_api_uri="api.azureiotcentral.com",
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
    central_api_uri="api.azureiotcentral.com",
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

    from azext_iot.operations.events3 import _builders, _events

    eventHubTarget = _builders.EventTargetBuilder().build_central_event_hub_target(
        cmd, app_id, central_api_uri
    )

    _events.executor(
        eventHubTarget,
        consumer_group=consumer_group,
        enqueued_time=enqueued_time,
        properties=properties,
        timeout=timeout,
        device_id=device_id,
        output=output,
        validate_messages=validate_messages,
        simulate_errors=simulate_errors,
        central_device_provider=central_device_provider,
    )
