# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Factory functions for IoT Hub and Device Provisioning Service.
"""

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.utility import ensure_iotdps_sdk_min_version
from azext_iot.common.auth import IoTOAuth
from azext_iot.common.shared import SdkType, AuthenticationTypeDataplane
from azext_iot.constants import (
    IOTDPS_TRACK_2_SDK_MIN_VERSION,
    USER_AGENT,
    IOTHUB_RESOURCE_ID,
    IOTDPS_RESOURCE_ID
)
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
        service_client (IotHubClient): operational resource for
            working with IoT Hub.
    """
    from azure.cli.core.commands.client_factory import get_mgmt_service_client
    from azure.cli.core.profiles import ResourceType

    return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_IOTHUB)


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
    if ensure_iotdps_sdk_min_version(IOTDPS_TRACK_2_SDK_MIN_VERSION):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.cli.core.profiles import ResourceType

        return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_IOTDPS)

    from azure.cli.command_modules.iot._client_factory import iot_service_provisioning_factory
    return iot_service_provisioning_factory(cli_ctx=cli_ctx)


class SdkResolver(object):
    def __init__(self, target, device_id=None, auth_override=None):
        self.target = target
        self.device_id = device_id
        self.auth_override = auth_override

        # This initialization will likely need to change to support more variation of SDK
        self.sas_uri = self.target["entity"]
        self.endpoint = "https://{}".format(self.sas_uri)

        # Base endpoints stay the same
        if self.device_id:
            self.sas_uri = "{}/devices/{}".format(self.sas_uri, self.device_id)

    def get_sdk(self, sdk_type):
        sdk_map = self._construct_sdk_map()
        sdk_client = sdk_map[sdk_type]()
        sdk_client.config.enable_http_logger = True
        sdk_client.config.add_user_agent(USER_AGENT)
        return sdk_client

    def _construct_sdk_map(self):
        return {
            SdkType.service_sdk: self._get_iothub_service_sdk,  # Don't need to call here
            SdkType.device_sdk: self._get_iothub_device_sdk,
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

        credentials = None

        if self.auth_override:
            credentials = self.auth_override
        elif self.target["policy"] == AuthenticationTypeDataplane.login.value:
            credentials = IoTOAuth(
                cmd=self.target["cmd"],
                resource_id=IOTHUB_RESOURCE_ID
            )
        else:
            credentials = SasTokenAuthentication(
                uri=self.sas_uri,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            )

        return IotHubGatewayServiceAPIs(credentials=credentials, base_url=self.endpoint)

    def _get_dps_service_sdk(self):
        from azext_iot.sdk.dps.service import ProvisioningServiceClient

        credentials = None

        if self.auth_override:
            credentials = self.auth_override
        elif self.target["policy"] == AuthenticationTypeDataplane.login.value:
            credentials = IoTOAuth(
                cmd=self.target["cmd"],
                resource_id=IOTDPS_RESOURCE_ID
            )
        else:
            credentials = SasTokenAuthentication(
                uri=self.sas_uri,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            )

        return ProvisioningServiceClient(
            credentials=credentials, base_url=self.endpoint
        )
