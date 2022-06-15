# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.device_messaging import DeviceMessagingProvider
from knack.log import get_logger

logger = get_logger(__name__)


def iot_device_send_message(
    cmd,
    device_id: str,
    data: str = "Ping from Az CLI IoT Extension",
    properties: str = None,
    msg_count: int = 1,
    device_symmetric_key: str = None,
    certificate_file: str = None,
    key_file: str = None,
    passphrase: str = "",
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.device_send_message(
        data=data,
        properties=properties,
        msg_count=msg_count,
        device_symmetric_key=device_symmetric_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase
    )


def iot_c2d_message_complete(
    cmd,
    device_id: str,
    etag: str = None,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.c2d_message_complete(
        etag=etag
    )


def iot_c2d_message_reject(
    cmd,
    device_id: str,
    etag: str = None,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.c2d_message_reject(
        etag=etag
    )


def iot_c2d_message_abandon(
    cmd,
    device_id: str,
    etag: str = None,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.c2d_message_abandon(
        etag=etag
    )


def iot_c2d_message_receive(
    cmd,
    device_id: str,
    lock_timeout: int = 60,
    abandon: bool = False,
    complete: bool = False,
    reject: bool = False,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.c2d_message_receive(
        lock_timeout=lock_timeout, abandon=abandon, complete=complete, reject=reject
    )


def iot_c2d_message_send(
    cmd,
    device_id: str,
    data: str = "Ping from Az CLI IoT Extension",
    message_id: str = None,
    correlation_id: str = None,
    user_id: str = None,
    content_encoding: str = "utf-8",
    content_type: str = None,
    expiry_time_utc=None,
    properties: str = None,
    ack=None,
    wait_on_feedback=False,
    yes: bool = False,
    repair: bool = False,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
    auth_type_dataplane: str = None
):
    from azext_iot.common.deps import ensure_uamqp
    ensure_uamqp(cmd.cli_ctx.config, yes, repair)

    simulator_provider = DeviceMessagingProvider(
        cmd=cmd,
        device_id=device_id,
        hub_name=hub_name,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    return simulator_provider.c2d_message_send(
        data=data,
        message_id=message_id,
        correlation_id=correlation_id,
        user_id=user_id,
        content_encoding=content_encoding,
        content_type=content_type,
        expiry_time_utc=expiry_time_utc,
        properties=properties,
        ack=ack,
        wait_on_feedback=wait_on_feedback
    )


def iot_c2d_message_purge(
    cmd,
    device_id: str,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.c2d_message_purge()


def iot_simulate_device(
    cmd,
    device_id: str,
    receive_settle: str = "complete",
    data: str = "Ping from Az CLI IoT Extension",
    msg_count: int = 100,
    msg_interval: int = 3,
    protocol_type: str = "mqtt",
    properties: str = None,
    device_symmetric_key: str = None,
    certificate_file: str = None,
    key_file: str = None,
    passphrase: str = "",
    method_response_code: str = None,
    method_response_payload: str = None,
    init_reported_properties: str = None,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.simulate_device(
        receive_settle=receive_settle,
        data=data,
        properties=properties,
        msg_count=msg_count,
        msg_interval=msg_interval,
        protocol_type=protocol_type,
        device_symmetric_key=device_symmetric_key,
        certificate_file=certificate_file,
        key_file=key_file,
        passphrase=passphrase,
        method_response_code=method_response_code,
        method_response_payload=method_response_payload,
        init_reported_properties=init_reported_properties
    )


def iot_device_upload_file(
    cmd,
    device_id: str,
    file_path: str,
    content_type: str,
    hub_name: str = None,
    resource_group_name: str = None,
    login: str = None,
):
    simulator_provider = DeviceMessagingProvider(
        cmd=cmd, device_id=device_id, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return simulator_provider.device_upload_file(
        file_path=file_path,
        content_type=content_type,
    )
