# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.pnp_runtime import PnPRuntimeProvider
from knack.log import get_logger

logger = get_logger(__name__)


def invoke_device_command(
    cmd,
    device_id,
    command_name,
    timeout=30,
    component_path=None,
    payload="{}",
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    runtime_provider = PnPRuntimeProvider(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return runtime_provider.invoke_device_command(
        device_id=device_id,
        command_name=command_name,
        payload=payload,
        component_path=component_path,
        timeout=timeout,
    )


def get_digital_twin(
    cmd,
    device_id,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    runtime_provider = PnPRuntimeProvider(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return runtime_provider.get_digital_twin(
        device_id=device_id,
    )


def patch_digital_twin(
    cmd,
    device_id,
    json_patch,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    runtime_provider = PnPRuntimeProvider(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login
    )
    return runtime_provider.patch_digital_twin(
        device_id=device_id, json_patch=json_patch
    )
