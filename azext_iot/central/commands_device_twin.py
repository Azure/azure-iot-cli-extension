# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication
from azext_iot.central.providers.device_provider import get_device_twin


def device_twin_show(cmd, device_id, app_id, central_dns_suffix=CENTRAL_ENDPOINT):
    get_device_twin(cmd, device_id, app_id, central_dns_suffix=central_dns_suffix)
