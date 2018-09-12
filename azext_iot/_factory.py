# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Factory functions for IoT Hub and Device Provisioning Service.
"""

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import SdkType


# pylint: disable=invalid-name
def iot_hub_service_factory(cli_ctx, *_):
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        iot_hub_resource (IotHubClient.iot_hub_resource): operational resource for
            working with IoT Hub.
    """
    from azure.cli.core.commands.client_factory import get_mgmt_service_client
    from azure.mgmt.iothub.iot_hub_client import IotHubClient
    return get_mgmt_service_client(cli_ctx, IotHubClient).iot_hub_resource


# pylint: disable=invalid-name,no-name-in-module
def iot_service_provisioning_factory(cli_ctx, *_):
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        service_client (IotDpsClient): operational resource for
            working with IoT Hub Device Provisioning Service.
    """
    from azure.cli.core.commands.client_factory import get_mgmt_service_client
    from azure.mgmt.iothubprovisioningservices.iot_dps_client import IotDpsClient
    return get_mgmt_service_client(cli_ctx, IotDpsClient)


# pylint: disable=too-many-return-statements
def _bind_sdk(target, sdk_type, device_id=None):
    from azext_iot.device_sdk.iot_hub_gateway_device_apis import IotHubGatewayDeviceAPIs
    from azext_iot.service_sdk.iot_hub_gateway_service_apis import IotHubGatewayServiceAPIs

    from azext_iot.custom_sdk.custom_api import CustomClient
    from azext_iot.dps_sdk import ProvisioningServiceClient

    sas_uri = target['entity']
    endpoint = "https://{}".format(sas_uri)
    if device_id:
        sas_uri = '{}/devices/{}'.format(sas_uri, device_id)

    if sdk_type is SdkType.device_sdk:
        return (
            IotHubGatewayDeviceAPIs(
                SasTokenAuthentication(
                    sas_uri, target['policy'], target['primarykey']),
                endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.service_sdk:
        return (
            IotHubGatewayServiceAPIs(
                SasTokenAuthentication(
                    sas_uri, target['policy'], target['primarykey']),
                endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.custom_sdk:
        return (
            CustomClient(
                SasTokenAuthentication(
                    sas_uri, target['policy'], target['primarykey']),
                endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.dps_sdk:
        return (
            ProvisioningServiceClient(
                SasTokenAuthentication(
                    sas_uri, target['policy'], target['primarykey']),
                endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    return None


def _get_sdk_exception_type(sdk_type):
    from importlib import import_module

    exception_library = {
        SdkType.custom_sdk: import_module('azext_iot.custom_sdk.models.error_details'),
        SdkType.service_sdk: import_module('msrestazure.azure_exceptions'),
        SdkType.device_sdk: import_module('msrestazure.azure_exceptions'),
        SdkType.dps_sdk: import_module('azext_iot.dps_sdk.models.provisioning_service_error_details')
    }
    return exception_library.get(sdk_type, None)
