# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Factory functions for IoT Hub and Device Provisioning Service.
"""

from functools import wraps

from knack.log import get_logger
from msrestazure.azure_exceptions import CloudError

from azext_iot.common.auth import IoTOAuth, get_cli_credential
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import AuthenticationTypeDataplane, SdkType
from azext_iot.common.utility import ensure_azure_namespace_path
from azext_iot.constants import IOTDPS_RESOURCE_ID, IOTHUB_RESOURCE_ID, USER_AGENT

ensure_azure_namespace_path()

from azure.core.pipeline.policies import HttpLoggingPolicy, UserAgentPolicy
from azure.mgmt.core.polling.arm_polling import ARMPolling

logger = get_logger(__name__)

__all__ = [
    "SdkResolver",
    "CloudError",
    "iot_hub_service_factory",
    "iot_service_provisioning_factory",
    "adr_service_factory",
]


def _get_default_logging_policy():
    """
    Get default HTTP logging policy for Azure clients.
    Following the pattern from the new edge module.
    """

    http_logging_policy = HttpLoggingPolicy(logger=logger)
    http_logging_policy.allowed_query_params.add("api-version")
    http_logging_policy.allowed_query_params.add("$filter")
    http_logging_policy.allowed_query_params.add("$expand")
    http_logging_policy.allowed_header_names.add("x-ms-correlation-request-id")

    return http_logging_policy


def _get_credential_scopes(cli_ctx):
    """Get cloud-specific credential scopes for management plane authentication."""
    from azure.cli.core.auth.util import resource_to_scopes
    return resource_to_scopes(cli_ctx.cloud.endpoints.active_directory_resource_id)


def _get_arm_endpoint(cli_ctx):
    return cli_ctx.cloud.endpoints.resource_manager


# TODO: Remove after https://github.com/microsoft/typespec/issues/11966 is fixed
# and the IoT Hub SDK is regenerated.
class _ModelessJsonARMPolling(ARMPolling):
    """Deserialize modeless ARM LRO results without the generated callback."""

    def __init__(self, result_callback=None, **kwargs):
        self._result_callback = result_callback
        super().__init__(**kwargs)

    def initialize(self, client, initial_response, _):
        super().initialize(client, initial_response, self._deserialize_response)

    def _deserialize_response(self, pipeline_response):
        response = pipeline_response.http_response
        deserialized = response.json() if response.content else None
        if self._result_callback:
            return self._result_callback(pipeline_response, deserialized, {})
        return deserialized


def _wrap_modeless_lro_operation(operation_group, operation_name):
    operation = getattr(operation_group, operation_name)

    @wraps(operation)
    def wrapped(*args, **kwargs):
        if kwargs.get("polling", True) is True:
            kwargs["polling"] = _ModelessJsonARMPolling(
                timeout=kwargs.get("polling_interval", operation_group._config.polling_interval),
                path_format_arguments={"endpoint": operation_group._config.base_url},
                result_callback=kwargs.get("cls"),
            )
        return operation(*args, **kwargs)

    setattr(operation_group, operation_name, wrapped)


def _configure_iot_hub_modeless_lro_polling(client):
    _wrap_modeless_lro_operation(client.private_endpoint_connections, "begin_update")
    _wrap_modeless_lro_operation(client.private_endpoint_connections, "begin_delete")
    _wrap_modeless_lro_operation(client.iot_hub_resource, "begin_create_or_update")
    _wrap_modeless_lro_operation(client.iot_hub_resource, "begin_delete")
    return client


def iot_hub_service_factory(cli_ctx, *_, subscription_id=None):
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

    subscription_id = subscription_id or get_subscription_id(cli_ctx)

    return _configure_iot_hub_modeless_lro_polling(
        IotHubClient(
            credential=get_cli_credential(cli_ctx, subscription_id=subscription_id),
            subscription_id=subscription_id,
            base_url=_get_arm_endpoint(cli_ctx),
            credential_scopes=_get_credential_scopes(cli_ctx),
            user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
            http_logging_policy=_get_default_logging_policy(),
        )
    )


def iot_service_provisioning_factory(cli_ctx, *_, subscription_id=None):
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

    subscription_id = subscription_id or get_subscription_id(cli_ctx)

    return IotDpsClient(
        credential=get_cli_credential(cli_ctx, subscription_id=subscription_id),
        subscription_id=subscription_id,
        base_url=_get_arm_endpoint(cli_ctx),
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


def adr_service_factory(cli_ctx, *_):
    """
    Factory for importing deps and getting service client resources.

    Args:
        cli_ctx (knack.cli.CLI): CLI context.
        *_ : all other args ignored.

    Returns:
        service_client (DeviceRegistryMgmtClient): operational resource for
            working with Azure Device Registry Service.
    """
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient

    subscription_id = get_subscription_id(cli_ctx)

    return DeviceRegistryMgmtClient(
        credential=get_cli_credential(cli_ctx, subscription_id=subscription_id),
        subscription_id=subscription_id,
        base_url=_get_arm_endpoint(cli_ctx),
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


def resource_service_factory(cli_ctx, **_):
    from azure.cli.core.commands.client_factory import get_mgmt_service_client
    from azure.cli.core.profiles import ResourceType

    return get_mgmt_service_client(cli_ctx, ResourceType.MGMT_RESOURCE_RESOURCES)


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

        hostname = self.target.get("deviceHostName") or self.target["entity"]
        sas_uri = hostname
        if self.device_id:
            sas_uri = "{}/devices/{}".format(hostname, self.device_id)
        credentials = SasTokenAuthentication(
            uri=sas_uri,
            shared_access_policy_name=self.target["policy"],
            shared_access_key=self.target["primarykey"],
        )

        return IotHubGatewayDeviceAPIs(credentials=credentials, base_url="https://{}".format(hostname))

    def _get_iothub_service_sdk(self):
        from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs

        hostname = self.target.get("serviceHostName") or self.target["entity"]
        credentials = None

        if self.auth_override:
            credentials = self.auth_override
        elif self.target["policy"] == AuthenticationTypeDataplane.login.value:
            credentials = IoTOAuth(cli_ctx=self.target["cmd"].cli_ctx, resource_id=IOTHUB_RESOURCE_ID)
        else:
            credentials = SasTokenAuthentication(
                uri=hostname,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            )

        return IotHubGatewayServiceAPIs(credentials=credentials, base_url="https://{}".format(hostname))

    def _get_dps_service_sdk(self):
        from azext_iot.sdk.dps.service import ProvisioningServiceClient

        credentials = None

        if self.auth_override:
            credentials = self.auth_override
        elif self.target["policy"] == AuthenticationTypeDataplane.login.value:
            credentials = IoTOAuth(cli_ctx=self.target["cmd"].cli_ctx, resource_id=IOTDPS_RESOURCE_ID)
        else:
            credentials = SasTokenAuthentication(
                uri=self.sas_uri,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            )

        return ProvisioningServiceClient(credentials=credentials, base_url=self.endpoint)
