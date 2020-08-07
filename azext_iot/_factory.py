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
    "SdkResolver",
    "CloudError",
    "iot_hub_service_factory",
    "iot_service_provisioning_factory",
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
    from azure.cli.core.profiles import ResourceType

    return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_IOTHUB).iot_hub_resource


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
    def __init__(self, target, device_id=None, auth_override=None):
        self.target = target
        self.device_id = device_id
        self.auth_override = auth_override

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
            SdkType.device_sdk: self._get_iothub_device_sdk,
            SdkType.pnp_sdk: self._get_pnp_runtime_sdk,
            SdkType.dps_sdk: self._get_dps_service_sdk,
        }

    def _get_iothub_device_sdk(self):
        from azext_iot.sdk.iothub.device import IotHubGatewayDeviceAPIs

        credentials = SasTokenAuthentication(
            uri=self.sas_uri,
            shared_access_policy_name=self.target["policy"],
            shared_access_key=self.target["primarykey"],
        )

        return IotHubGatewayDeviceAPIs(credentials=credentials, base_url=self.endpoint)

    def _get_iothub_service_sdk(self):
        from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs

        credentials = (
            self.auth_override
            if self.auth_override
            else SasTokenAuthentication(
                uri=self.sas_uri,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            )
        )

        return IotHubGatewayServiceAPIs(credentials=credentials, base_url=self.endpoint)

    def _get_pnp_runtime_sdk(self):
        from azext_iot.sdk.iothub.pnp_runtime import IotHubGatewayServiceAPIs

        credentials = SasTokenAuthentication(
            uri=self.sas_uri,
            shared_access_policy_name=self.target["policy"],
            shared_access_key=self.target["primarykey"],
        )

        return IotHubGatewayServiceAPIs(credentials=credentials, base_url=self.endpoint)

    def _get_dps_service_sdk(self):
        from azext_iot.sdk.dps import ProvisioningServiceClient

        credentials = SasTokenAuthentication(
            uri=self.sas_uri,
            shared_access_policy_name=self.target["policy"],
            shared_access_key=self.target["primarykey"],
        )

        return ProvisioningServiceClient(
            credentials=credentials, base_url=self.endpoint
        )
