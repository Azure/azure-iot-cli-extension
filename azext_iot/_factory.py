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


def _bind_sdk(target, sdk_type, device_id=None, auth=None):
    from azext_iot.sdk.device.iot_hub_gateway_device_apis import IotHubGatewayDeviceAPIs
    from azext_iot.sdk.service.iot_hub_gateway_service_apis import IotHubGatewayServiceAPIs

    from azext_iot.sdk.custom.custom_api import CustomClient
    from azext_iot.sdk.dps import ProvisioningServiceClient
    from azext_iot.sdk.pnp.digital_twin_repository_service import DigitalTwinRepositoryService

    sas_uri = target['entity']
    endpoint = "https://{}".format(sas_uri)
    if device_id:
        sas_uri = '{}/devices/{}'.format(sas_uri, device_id)

    if sdk_type is SdkType.pnp_sdk:
        return (
            DigitalTwinRepositoryService(endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if not auth:
        auth = SasTokenAuthentication(sas_uri, target['policy'], target['primarykey'])

    if sdk_type is SdkType.device_sdk:
        return (
            IotHubGatewayDeviceAPIs(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.service_sdk:
        return (
            IotHubGatewayServiceAPIs(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.custom_sdk:
        return (
            CustomClient(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.dps_sdk:
        return (
            ProvisioningServiceClient(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    return None


def _get_sdk_exception_type(sdk_type):
    from importlib import import_module

    exception_library = {
        SdkType.custom_sdk: import_module('azext_iot.sdk.custom.models.error_details'),
        SdkType.service_sdk: import_module('msrestazure.azure_exceptions'),
        SdkType.device_sdk: import_module('msrestazure.azure_exceptions'),
        SdkType.dps_sdk: import_module('azext_iot.sdk.dps.models.provisioning_service_error_details'),
        SdkType.pnp_sdk: import_module('msrest.exceptions')
    }
    return exception_library.get(sdk_type, None)
