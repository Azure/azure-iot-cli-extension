# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers.preview import CentralDeviceGroupProviderPreview
from azext_iot.central.models.enum import ApiVersion


def list_device_groups(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.preview.value,
):
    provider = CentralDeviceGroupProviderPreview(cmd=cmd, app_id=app_id, token=token)

    return provider.list_device_groups(central_dns_suffix=central_dns_suffix)
