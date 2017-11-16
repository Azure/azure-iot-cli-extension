# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from azure.cli.command_modules.iot.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import SdkType


def iot_hub_service_factory(_):
    from azure.cli.core.commands.client_factory import get_mgmt_service_client
    from azure.mgmt.iothub.iot_hub_client import IotHubClient
    return get_mgmt_service_client(IotHubClient).iot_hub_resource


def _bind_sdk(target, sdk_type):
    from azext_iot.device_query_sdk.device_identities_api import DeviceIdentitiesAPI
    from azext_iot.device_twin_sdk.device_twin_api import DeviceTwinAPI
    from azext_iot.modules_sdk.iot_hub_client import IotHubClient
    endpoint = "https://{}".format(target['hub'])
    if sdk_type is SdkType.device_query_sdk:
        return DeviceIdentitiesAPI(SasTokenAuthentication(target['hub'], target['policy'], target['primarykey']), endpoint)
    elif sdk_type is SdkType.device_twin_sdk:
        return DeviceTwinAPI(SasTokenAuthentication(target['hub'], target['policy'], target['primarykey']), endpoint)
    elif sdk_type is SdkType.modules_sdk:
        return IotHubClient(SasTokenAuthentication(target['hub'], target['policy'], target['primarykey']), None, endpoint)

    return None
