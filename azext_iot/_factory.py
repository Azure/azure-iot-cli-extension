# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Factory functions for IoT Hub and Device Provisioning Service.
"""

from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.auth import IoTOAuth, get_aad_token
from azext_iot.common.shared import SdkType, AuthenticationTypeDataplane
from azext_iot.constants import (
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
    # TODO - CMS Preview - ADR MGMT SDK
    "adr_service_factory",
]


# TODO - CMS Preview - figure out why we need a new implementation of SDK Auth
class CliTokenCredential:
    """TokenCredential implementation using Azure CLI authentication."""

    def __init__(self, cli_ctx):
        self.cli_ctx = cli_ctx

    def get_token(self, *scopes, **kwargs):
        """Get an access token for the given scopes."""
        from types import SimpleNamespace

        token_info = get_aad_token(self.cli_ctx)

        # TODO - CMS Preview - find out why this is needed too :(
        # Convert expiresOn to Unix timestamp if it's a string
        expires_on = token_info.get("expiresOn")
        if isinstance(expires_on, str):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(expires_on.replace("Z", "+00:00"))
                expires_on = dt.timestamp()
            except (ValueError, TypeError):
                raise ValueError("Invalid expiresOn format: {}".format(expires_on))

        return SimpleNamespace(token=token_info["accessToken"], expires_on=expires_on)


def iot_hub_service_factory(cli_ctx, *_):
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        service_client (IotHubClient): operational resource for
            working with IoT Hub Service.
    """
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.iothub.mgmt import IotHubClient

    # Get subscription ID and credentials from CLI context
    subscription_id = get_subscription_id(cli_ctx)

    # Use custom TokenCredential implementation
    credential = CliTokenCredential(cli_ctx)
    return IotHubClient(
        subscription_id=subscription_id, credential=credential, endpoint=cli_ctx.cloud.endpoints.resource_manager
    )

    # TODO - CMS Preview - Original implementation (uncomment when official SDK is released):
    # from azure.cli.core.commands.client_factory import get_mgmt_service_client
    # from azure.cli.core.profiles import ResourceType
    # return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_IOTHUB)


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
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.dps.mgmt import IotDpsClient

    # Get subscription ID and credentials from CLI context
    subscription_id = get_subscription_id(cli_ctx)

    # Use custom TokenCredential implementation
    credential = CliTokenCredential(cli_ctx)

    return IotDpsClient(
        subscription_id=subscription_id, credential=credential, endpoint=cli_ctx.cloud.endpoints.resource_manager
    )

    # TODO - CMS Preview - Original implementation (uncomment when official SDK is released):
    # from azure.cli.core.commands.client_factory import get_mgmt_service_client
    # from azure.cli.core.profiles import ResourceType

    # return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_IOTDPS)


# TODO - CMS Preview - ADR MGMT SDK
def adr_service_factory(cli_ctx, *_):
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        service_client (DeviceRegistryManagementService): operational resource for
            working with Azure Device Registry Service.
    """
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.deviceregistry.mgmt import DeviceRegistryManagementService

    # Get subscription ID and credentials from CLI context
    subscription_id = get_subscription_id(cli_ctx)

    # Use custom TokenCredential implementation
    credential = CliTokenCredential(cli_ctx)

    return DeviceRegistryManagementService(
        subscription_id=subscription_id, credential=credential, endpoint=cli_ctx.cloud.endpoints.resource_manager
    )


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
                cli_ctx=self.target["cmd"].cli_ctx,
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
                cli_ctx=self.target["cmd"].cli_ctx,
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
