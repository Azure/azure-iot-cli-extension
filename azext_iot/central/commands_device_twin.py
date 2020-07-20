# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.devicetwin_provider import CentralDeviceTwinProvider


def device_twin_show(
    cmd, device_id, app_id, token=None, central_dns_suffix=CENTRAL_ENDPOINT
):
    device_twin_provider = CentralDeviceTwinProvider(
        cmd=cmd, app_id=app_id, token=token, device_id=device_id
    )
    return device_twin_provider.get_device_twin(central_dns_suffix=central_dns_suffix)
