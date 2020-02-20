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
from msrestazure.azure_exceptions import CloudError

__all__ = [
    "CloudError",
    "iot_hub_service_factory",
    "iot_service_provisioning_factory",
    "SdkResolver",
    "_bind_sdk",
    "_get_sdk_exception_type"
]


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

    # To support newer and older IotHubClient. 0.9.0+ has breaking changes.
    try:
        from azure.mgmt.iothub import IotHubClient
    except:
        # For <0.9.0
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


class SdkResolver(object):
    def __init__(self, target, device_id=None):
        self.target = target
        self.device_id = device_id

        # This initialization will likely need to change to support more variation of SDK
        self.sas_uri = self.target["entity"]
        self.endpoint = "https://{}".format(self.sas_uri)
        if self.device_id:  # IoT Hub base endpoint stays the same
            self.sas_uri = "{}/devices/{}".format(self.sas_uri, self.device_id)

    def get_sdk(self, sdk_type):
        sdk_map = self._construct_sdk_map()
        return sdk_map[sdk_type]()

    def _construct_sdk_map(self):
        return {
            SdkType.service_sdk: self._get_iothub_service_sdk,  # Don't need to call here
            SdkType.device_sdk: self._get_iothub_device_sdk
        }

    def _get_iothub_device_sdk(self):
        from azext_iot.sdk.iothub.device import IotHubGatewayDeviceAPIs
        credentials = SasTokenAuthentication(
            uri=self.sas_uri,
            shared_access_policy_name=self.target['policy'],
            shared_access_key=self.target['primarykey'])

        return IotHubGatewayDeviceAPIs(credentials=credentials, base_url=self.endpoint)

    def _get_iothub_service_sdk(self):
        from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
        credentials = SasTokenAuthentication(
            uri=self.sas_uri,
            shared_access_policy_name=self.target['policy'],
            shared_access_key=self.target['primarykey'])

        return IotHubGatewayServiceAPIs(credentials=credentials, base_url=self.endpoint)


# TODO: Deprecated. To be removed asap.
def _bind_sdk(target, sdk_type, device_id=None, auth=None):
    from azext_iot.sdk.service.iot_hub_gateway_service_apis import IotHubGatewayServiceAPIs
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

    if sdk_type is SdkType.service_sdk:
        return (
            IotHubGatewayServiceAPIs(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    if sdk_type is SdkType.dps_sdk:
        return (
            ProvisioningServiceClient(auth, endpoint),
            _get_sdk_exception_type(sdk_type)
        )

    return None


# TODO: Dependency for _bind_sdk. Will be removed asap.
def _get_sdk_exception_type(sdk_type):
    from importlib import import_module

    exception_library = {
        SdkType.service_sdk: import_module('msrestazure.azure_exceptions'),
        SdkType.dps_sdk: import_module('azext_iot.sdk.dps.models.provisioning_service_error_details'),
        SdkType.pnp_sdk: import_module('msrest.exceptions')
    }
    return exception_library.get(sdk_type, None)
