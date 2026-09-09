# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Factory functions for IoT Hub and Device Provisioning Service.
"""

import ssl

from knack.log import get_logger
from msrestazure.azure_exceptions import CloudError
import requests
from requests.adapters import HTTPAdapter

from azext_iot.common.auth import IoTOAuth
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azext_iot.common.shared import AuthenticationTypeDataplane, SdkType
from azext_iot.common.utility import ensure_azure_namespace_path
from azext_iot.constants import (
    IOTDPS_PROVISIONING_HOST,
    IOTDPS_RESOURCE_ID,
    IOTHUB_RESOURCE_ID,
    USER_AGENT,
)
from azext_iot.dps.common import (
    CERTIFICATE_FILE_ERROR,
    MISSING_DPS_CREDENTIALS_ERROR,
)
from azext_iot.dps.services.auth import get_dps_sas_auth_header

ensure_azure_namespace_path()

from azure.core.pipeline.policies import HttpLoggingPolicy, UserAgentPolicy
from azure.identity import AzureCliCredential

AZURE_CLI_CREDENTIAL = AzureCliCredential()
_ADR_CANARY_ARM_ENDPOINT = "https://centraluseuap.management.azure.com"
_IOT_HUB_API_VERSION = "2026-06-01-preview"
_ADR_IOT_HUB_API_VERSION = _IOT_HUB_API_VERSION

logger = get_logger(__name__)

__all__ = [
    "SdkResolver",
    "CloudError",
    "iot_hub_service_factory",
    "iot_service_provisioning_factory",
    "dps_device_service_factory",
    "adr_iot_hub_service_factory",
    "adr_iot_service_provisioning_factory",
    "adr_service_factory",
    "adr_update_instance_service_factory",
    "adr_software_update_data_service_factory",
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


def _as_https_endpoint(hostname):
    hostname = hostname.rstrip("/")
    if hostname.casefold().startswith("https://"):
        return hostname
    return f"https://{hostname}"


def _iot_hub_management_client(
    cli_ctx, subscription_id, base_url, api_version
):
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.iothub.mgmt import IotHubClient

    return IotHubClient(
        credential=AZURE_CLI_CREDENTIAL,
        subscription_id=subscription_id or get_subscription_id(cli_ctx),
        base_url=base_url,
        api_version=api_version,
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


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
    return _iot_hub_management_client(
        cli_ctx,
        subscription_id,
        _get_arm_endpoint(cli_ctx),
        _IOT_HUB_API_VERSION,
    )


def adr_iot_hub_service_factory(cli_ctx, *_, subscription_id=None):
    """Create an IoT Hub client for ADR preview link operations."""
    return _iot_hub_management_client(
        cli_ctx,
        subscription_id,
        _ADR_CANARY_ARM_ENDPOINT,
        _ADR_IOT_HUB_API_VERSION,
    )


def _iot_dps_management_client(cli_ctx, subscription_id, base_url):
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.dps.mgmt import IotDpsClient

    return IotDpsClient(
        credential=AZURE_CLI_CREDENTIAL,
        subscription_id=subscription_id or get_subscription_id(cli_ctx),
        base_url=base_url,
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
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
    return _iot_dps_management_client(
        cli_ctx,
        subscription_id,
        _get_arm_endpoint(cli_ctx),
    )


def adr_iot_service_provisioning_factory(
    cli_ctx, *_, subscription_id=None
):
    """Create a DPS management client for ADR preview link operations."""
    return _iot_dps_management_client(
        cli_ctx,
        subscription_id,
        _ADR_CANARY_ARM_ENDPOINT,
    )


def adr_service_factory(cli_ctx, *_, subscription_id=None):
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

    subscription_id = subscription_id or get_subscription_id(cli_ctx)

    return DeviceRegistryMgmtClient(
        credential=AZURE_CLI_CREDENTIAL,
        subscription_id=subscription_id,
        base_url=_ADR_CANARY_ARM_ENDPOINT,
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


def adr_update_instance_service_factory(cli_ctx, *_, subscription_id=None):
    """Create the Software Updates Update Instance management client."""
    from azure.cli.core.commands.client_factory import get_subscription_id

    from azext_iot.sdk.deviceupdate.duregistry import DeviceUpdateClient

    return DeviceUpdateClient(
        credential=AZURE_CLI_CREDENTIAL,
        subscription_id=subscription_id or get_subscription_id(cli_ctx),
        base_url=_ADR_CANARY_ARM_ENDPOINT,
        credential_scopes=_get_credential_scopes(cli_ctx),
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


def adr_software_update_data_service_factory(cli_ctx, *_, endpoint=None):
    """Create the Software Updates data-plane client."""
    from azure.cli.core.azclierror import RequiredArgumentMissingError
    from azext_iot.sdk.deviceupdate.duregistrydata import DeviceRegistrySoftwareUpdateClient

    if not endpoint:
        raise RequiredArgumentMissingError(
            "A service-derived Software Updates endpoint is required."
        )

    return DeviceRegistrySoftwareUpdateClient(
        endpoint=endpoint,
        credential=AZURE_CLI_CREDENTIAL,
        user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
        http_logging_policy=_get_default_logging_policy(),
    )


class _MutualTlsAdapter(HTTPAdapter):
    """Attach an SSL context containing an optionally encrypted client key."""

    def __init__(self, ssl_context, *args, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(*args, **kwargs)

    def init_poolmanager(
        self, connections, maxsize, block=False, **pool_kwargs
    ):
        pool_kwargs["ssl_context"] = self._ssl_context
        return super().init_poolmanager(
            connections, maxsize, block=block, **pool_kwargs
        )

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)

    def build_connection_pool_key_attributes(
        self, request, verify, cert=None
    ):
        """Keep the client-certificate context on requests 2.32 and later."""
        builder = getattr(
            super(), "build_connection_pool_key_attributes", None
        )
        if builder is None:
            return {}, {"ssl_context": self._ssl_context}
        host_params, pool_kwargs = builder(request, verify, cert)
        pool_kwargs["ssl_context"] = self._ssl_context
        pool_kwargs.pop("cert_file", None)
        pool_kwargs.pop("key_file", None)
        return host_params, pool_kwargs


def _dps_x509_transport(certificate_file, key_file, passphrase):
    from azure.cli.core.azclierror import InvalidArgumentValueError
    from azure.core.pipeline.transport import RequestsTransport

    context = ssl.create_default_context()
    try:
        context.load_cert_chain(
            certfile=certificate_file,
            keyfile=key_file,
            password=passphrase or None,
        )
    except (OSError, ssl.SSLError) as error:
        reason = getattr(error, "reason", str(error))
        raise InvalidArgumentValueError(
            f"Could not open certificate files: {reason}."
        ) from error

    session = requests.Session()
    session.mount("https://", _MutualTlsAdapter(context))
    return RequestsTransport(session=session)


def dps_device_service_factory(
    cli_ctx,
    *_,
    endpoint=None,
    registration_id=None,
    id_scope=None,
    device_symmetric_key=None,
    certificate_file=None,
    key_file=None,
    passphrase=None,
):
    """Create an authenticated modeless DPS device client."""
    from azure.cli.core.azclierror import RequiredArgumentMissingError
    from azure.core.credentials import AzureKeyCredential
    from azure.core.pipeline.policies import (
        AzureKeyCredentialPolicy,
        SansIOHTTPPolicy,
    )
    from azext_iot.sdk.dps.device import ProvisioningDeviceClient

    client_kwargs = {
        "endpoint": _as_https_endpoint(
            endpoint or IOTDPS_PROVISIONING_HOST
        ),
        "user_agent_policy": UserAgentPolicy(user_agent=USER_AGENT),
        "logging_policy": SansIOHTTPPolicy(),
        "http_logging_policy": _get_default_logging_policy(),
    }
    if device_symmetric_key:
        if not id_scope or not registration_id:
            raise RequiredArgumentMissingError(
                "--id-scope and --registration-id are required for "
                "symmetric-key authentication."
            )
        sas_token = get_dps_sas_auth_header(
            id_scope, registration_id, device_symmetric_key
        )
        client_kwargs["authentication_policy"] = AzureKeyCredentialPolicy(
            AzureKeyCredential(sas_token), "Authorization"
        )
    elif certificate_file or key_file or passphrase:
        if not certificate_file or not key_file:
            raise RequiredArgumentMissingError(CERTIFICATE_FILE_ERROR)
        client_kwargs["transport"] = _dps_x509_transport(
            certificate_file, key_file, passphrase
        )
    else:
        raise RequiredArgumentMissingError(MISSING_DPS_CREDENTIALS_ERROR)

    return ProvisioningDeviceClient(
        **client_kwargs
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
        # The legacy Hub data SDK exposes ``config``. The newly generated
        # modeless DPS SDK is azure-core based and receives policies in its
        # constructor instead.
        if hasattr(sdk_client, "config"):
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
        from azure.core.credentials import AzureKeyCredential
        from azext_iot.sdk.dps.service import ProvisioningServiceClient

        hostname = self.target.get("serviceHostName") or self.target["entity"]
        dps_name = hostname.split(".", 1)[0]

        if self.auth_override:
            if isinstance(self.auth_override, AzureKeyCredential):
                credential = self.auth_override
            else:
                authorization = self.auth_override.signed_session().headers.get(
                    "Authorization"
                )
                credential = AzureKeyCredential(authorization)
        elif self.target["policy"] == AuthenticationTypeDataplane.login.value:
            authorization = IoTOAuth(
                cli_ctx=self.target["cmd"].cli_ctx,
                resource_id=IOTDPS_RESOURCE_ID,
            ).signed_session().headers["Authorization"]
            credential = AzureKeyCredential(authorization)
        else:
            authorization = SasTokenAuthentication(
                uri=hostname,
                shared_access_policy_name=self.target["policy"],
                shared_access_key=self.target["primarykey"],
            ).generate_sas_token()
            credential = AzureKeyCredential(authorization)

        client = ProvisioningServiceClient(
            dps_name=dps_name,
            credential=credential,
            user_agent_policy=UserAgentPolicy(user_agent=USER_AGENT),
            http_logging_policy=_get_default_logging_policy(),
        )
        # The generated client currently templates every DPS service endpoint
        # onto the public-cloud suffix. Keep construction generated-standard,
        # then replace the PipelineClient base URL with the exact hostname
        # returned by discovery (including sovereign and custom hostnames).
        client._client._base_url = _as_https_endpoint(hostname)  # pylint: disable=protected-access
        return client
