# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is regenerated.
# --------------------------------------------------------------------------

from typing import Any, TYPE_CHECKING

from azure.core.pipeline.transport import AsyncHttpResponse, HttpRequest
from azure.mgmt.core import AsyncARMPipelineClient
from msrest import Deserializer, Serializer

if TYPE_CHECKING:
    # pylint: disable=unused-import,ungrouped-imports
    from azure.core.credentials_async import AsyncTokenCredential

from ._configuration import IotCentralApiV1Configuration
from .operations import ApiTokensOperations
from .operations import DevicesOperations
from .operations import DeviceTemplatesOperations
from .operations import RolesOperations
from .operations import UsersOperations
from .. import models


class IotCentralApiV1(object):
    """Azure IoT Central is a service that makes it easy to connect, monitor, and manage your IoT devices at scale.

    :ivar api_tokens: ApiTokensOperations operations
    :vartype api_tokens: iot_central_api_v1.aio.operations.ApiTokensOperations
    :ivar devices: DevicesOperations operations
    :vartype devices: iot_central_api_v1.aio.operations.DevicesOperations
    :ivar device_templates: DeviceTemplatesOperations operations
    :vartype device_templates: iot_central_api_v1.aio.operations.DeviceTemplatesOperations
    :ivar roles: RolesOperations operations
    :vartype roles: iot_central_api_v1.aio.operations.RolesOperations
    :ivar users: UsersOperations operations
    :vartype users: iot_central_api_v1.aio.operations.UsersOperations
    :param credential: Credential needed for the client to connect to Azure.
    :type credential: ~azure.core.credentials_async.AsyncTokenCredential
    :param subdomain: The application subdomain.
    :type subdomain: str
    :param central_dns_suffix_in_path: The DNS suffix used as the base for all Azure IoT Central service requests.
    :type central_dns_suffix_in_path: str
    """

    def __init__(
        self,
        credential: "AsyncTokenCredential",
        subdomain: str,
        central_dns_suffix_in_path: str = "azureiotcentral.com",
        **kwargs: Any
    ) -> None:
        base_url = 'https://{subdomain}.{centralDnsSuffixInPath}/api/v1'
        self._config = IotCentralApiV1Configuration(credential, subdomain, central_dns_suffix_in_path, **kwargs)
        self._client = AsyncARMPipelineClient(base_url=base_url, config=self._config, **kwargs)

        client_models = {k: v for k, v in models.__dict__.items() if isinstance(v, type)}
        self._serialize = Serializer(client_models)
        self._serialize.client_side_validation = False
        self._deserialize = Deserializer(client_models)

        self.api_tokens = ApiTokensOperations(
            self._client, self._config, self._serialize, self._deserialize)
        self.devices = DevicesOperations(
            self._client, self._config, self._serialize, self._deserialize)
        self.device_templates = DeviceTemplatesOperations(
            self._client, self._config, self._serialize, self._deserialize)
        self.roles = RolesOperations(
            self._client, self._config, self._serialize, self._deserialize)
        self.users = UsersOperations(
            self._client, self._config, self._serialize, self._deserialize)

    async def _send_request(self, http_request: HttpRequest, **kwargs: Any) -> AsyncHttpResponse:
        """Runs the network request through the client's chained policies.

        :param http_request: The network request you want to make. Required.
        :type http_request: ~azure.core.pipeline.transport.HttpRequest
        :keyword bool stream: Whether the response payload will be streamed. Defaults to True.
        :return: The response of your network call. Does not do error handling on your response.
        :rtype: ~azure.core.pipeline.transport.AsyncHttpResponse
        """
        path_format_arguments = {
            'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
            'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
        }
        http_request.url = self._client.format_url(http_request.url, **path_format_arguments)
        stream = kwargs.pop("stream", True)
        pipeline_response = await self._client._pipeline.run(http_request, stream=stream, **kwargs)
        return pipeline_response.http_response

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> "IotCentralApiV1":
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc_details) -> None:
        await self._client.__aexit__(*exc_details)
