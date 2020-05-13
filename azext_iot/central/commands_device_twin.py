# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.util import CLIError
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType
from azext_iot.common.utility import unpack_msrest_error
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication


def find_between(s, start, end):
    return (s.split(start))[1].split(end)[0]


def device_twin_show(cmd, device_id, app_id, central_dns_suffix="azureiotcentral.com"):
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
        try:
            return service_sdk.get_twin(device_id)
        except errors.CloudError as e:
            if exception is None:
                exception = CLIError(unpack_msrest_error(e))

    raise exception
