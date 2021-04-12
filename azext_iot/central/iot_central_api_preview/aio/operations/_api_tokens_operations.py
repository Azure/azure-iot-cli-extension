# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is regenerated.
# --------------------------------------------------------------------------
from typing import Any, AsyncIterable, Callable, Dict, Generic, Optional, TypeVar
import warnings

from azure.core.async_paging import AsyncItemPaged, AsyncList
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceExistsError, ResourceNotFoundError, map_error
from azure.core.pipeline import PipelineResponse
from azure.core.pipeline.transport import AsyncHttpResponse, HttpRequest
from azure.mgmt.core.exceptions import ARMErrorFormat

from ... import models as _models

T = TypeVar('T')
ClsType = Optional[Callable[[PipelineResponse[HttpRequest, AsyncHttpResponse], T, Dict[str, Any]], Any]]

class ApiTokensOperations:
    """ApiTokensOperations async operations.

    You should not instantiate this class directly. Instead, you should create a Client instance that
    instantiates it for you and attaches it as an attribute.

    :ivar models: Alias to model classes used in this operation group.
    :type models: ~iot_central_api_preview.models
    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    """

    models = _models

    def __init__(self, client, config, serializer, deserializer) -> None:
        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self._config = config

    def list(
        self,
        **kwargs
    ) -> AsyncIterable["_models.ApiTokenCollection"]:
        """Get the list of API tokens in an application. The token value will never be returned for security reasons.

        Get the list of API tokens in an application. The token value will never be returned for
        security reasons.

        :keyword callable cls: A custom type or function that will be passed the direct response
        :return: An iterator like instance of either ApiTokenCollection or the result of cls(response)
        :rtype: ~azure.core.async_paging.AsyncItemPaged[~iot_central_api_preview.models.ApiTokenCollection]
        :raises: ~azure.core.exceptions.HttpResponseError
        """
        cls = kwargs.pop('cls', None)  # type: ClsType["_models.ApiTokenCollection"]
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        error_map.update(kwargs.pop('error_map', {}))
        accept = "application/json"

        def prepare_request(next_link=None):
            # Construct headers
            header_parameters = {}  # type: Dict[str, Any]
            header_parameters['Accept'] = self._serialize.header("accept", accept, 'str')

            if not next_link:
                # Construct URL
                url = self.list.metadata['url']  # type: ignore
                path_format_arguments = {
                    'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
                    'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
                }
                url = self._client.format_url(url, **path_format_arguments)
                # Construct parameters
                query_parameters = {}  # type: Dict[str, Any]

                request = self._client.get(url, query_parameters, header_parameters)
            else:
                url = next_link
                query_parameters = {}  # type: Dict[str, Any]
                path_format_arguments = {
                    'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
                    'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
                }
                url = self._client.format_url(url, **path_format_arguments)
                request = self._client.get(url, query_parameters, header_parameters)
            return request

        async def extract_data(pipeline_response):
            deserialized = self._deserialize('ApiTokenCollection', pipeline_response)
            list_of_elem = deserialized.value
            if cls:
                list_of_elem = cls(list_of_elem)
            return deserialized.next_link or None, AsyncList(list_of_elem)

        async def get_next(next_link=None):
            request = prepare_request(next_link)

            pipeline_response = await self._client._pipeline.run(request, stream=False, **kwargs)
            response = pipeline_response.http_response

            if response.status_code not in [200]:
                map_error(status_code=response.status_code, response=response, error_map=error_map)
                raise HttpResponseError(response=response, error_format=ARMErrorFormat)

            return pipeline_response

        return AsyncItemPaged(
            get_next, extract_data
        )
    list.metadata = {'url': '/apiTokens'}  # type: ignore

    async def get(
        self,
        token_id: str,
        **kwargs
    ) -> "_models.ApiToken":
        """Get an API token by ID.

        Get an API token by ID.

        :param token_id: Unique ID for the API token.
        :type token_id: str
        :keyword callable cls: A custom type or function that will be passed the direct response
        :return: ApiToken, or the result of cls(response)
        :rtype: ~iot_central_api_preview.models.ApiToken
        :raises: ~azure.core.exceptions.HttpResponseError
        """
        cls = kwargs.pop('cls', None)  # type: ClsType["_models.ApiToken"]
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        error_map.update(kwargs.pop('error_map', {}))
        accept = "application/json"

        # Construct URL
        url = self.get.metadata['url']  # type: ignore
        path_format_arguments = {
            'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
            'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
            'token_id': self._serialize.url("token_id", token_id, 'str'),
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}  # type: Dict[str, Any]

        # Construct headers
        header_parameters = {}  # type: Dict[str, Any]
        header_parameters['Accept'] = self._serialize.header("accept", accept, 'str')

        request = self._client.get(url, query_parameters, header_parameters)
        pipeline_response = await self._client._pipeline.run(request, stream=False, **kwargs)
        response = pipeline_response.http_response

        if response.status_code not in [200]:
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            raise HttpResponseError(response=response, error_format=ARMErrorFormat)

        deserialized = self._deserialize('ApiToken', pipeline_response)

        if cls:
            return cls(pipeline_response, deserialized, {})

        return deserialized
    get.metadata = {'url': '/apiTokens/{token_id}'}  # type: ignore

    async def set(
        self,
        token_id: str,
        body: "_models.ApiToken",
        **kwargs
    ) -> "_models.ApiToken":
        """Create a new API token in the application to use in the IoT Central public API. The token value will be returned in the response, and won't be returned again in subsequent requests.

        Create a new API token in the application to use in the IoT Central public API. The token value
        will be returned in the response, and won't be returned again in subsequent requests.

        :param token_id: Unique ID for the API token.
        :type token_id: str
        :param body: API token body.
        :type body: ~iot_central_api_preview.models.ApiToken
        :keyword callable cls: A custom type or function that will be passed the direct response
        :return: ApiToken, or the result of cls(response)
        :rtype: ~iot_central_api_preview.models.ApiToken
        :raises: ~azure.core.exceptions.HttpResponseError
        """
        cls = kwargs.pop('cls', None)  # type: ClsType["_models.ApiToken"]
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        error_map.update(kwargs.pop('error_map', {}))
        content_type = kwargs.pop("content_type", "application/json")
        accept = "application/json"

        # Construct URL
        url = self.set.metadata['url']  # type: ignore
        path_format_arguments = {
            'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
            'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
            'token_id': self._serialize.url("token_id", token_id, 'str'),
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}  # type: Dict[str, Any]

        # Construct headers
        header_parameters = {}  # type: Dict[str, Any]
        header_parameters['Content-Type'] = self._serialize.header("content_type", content_type, 'str')
        header_parameters['Accept'] = self._serialize.header("accept", accept, 'str')

        body_content_kwargs = {}  # type: Dict[str, Any]
        body_content = self._serialize.body(body, 'ApiToken')
        body_content_kwargs['content'] = body_content
        request = self._client.put(url, query_parameters, header_parameters, **body_content_kwargs)
        pipeline_response = await self._client._pipeline.run(request, stream=False, **kwargs)
        response = pipeline_response.http_response

        if response.status_code not in [200]:
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            raise HttpResponseError(response=response, error_format=ARMErrorFormat)

        deserialized = self._deserialize('ApiToken', pipeline_response)

        if cls:
            return cls(pipeline_response, deserialized, {})

        return deserialized
    set.metadata = {'url': '/apiTokens/{token_id}'}  # type: ignore

    async def remove(
        self,
        token_id: str,
        **kwargs
    ) -> None:
        """Delete an API token.

        Delete an API token.

        :param token_id: Unique ID for the API token.
        :type token_id: str
        :keyword callable cls: A custom type or function that will be passed the direct response
        :return: None, or the result of cls(response)
        :rtype: None
        :raises: ~azure.core.exceptions.HttpResponseError
        """
        cls = kwargs.pop('cls', None)  # type: ClsType[None]
        error_map = {
            401: ClientAuthenticationError, 404: ResourceNotFoundError, 409: ResourceExistsError
        }
        error_map.update(kwargs.pop('error_map', {}))

        # Construct URL
        url = self.remove.metadata['url']  # type: ignore
        path_format_arguments = {
            'centralDnsSuffixInPath': self._serialize.url("self._config.central_dns_suffix_in_path", self._config.central_dns_suffix_in_path, 'str', skip_quote=True),
            'subdomain': self._serialize.url("self._config.subdomain", self._config.subdomain, 'str'),
            'token_id': self._serialize.url("token_id", token_id, 'str'),
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}  # type: Dict[str, Any]

        # Construct headers
        header_parameters = {}  # type: Dict[str, Any]

        request = self._client.delete(url, query_parameters, header_parameters)
        pipeline_response = await self._client._pipeline.run(request, stream=False, **kwargs)
        response = pipeline_response.http_response

        if response.status_code not in [204]:
            map_error(status_code=response.status_code, response=response, error_map=error_map)
            raise HttpResponseError(response=response, error_format=ARMErrorFormat)

        if cls:
            return cls(pipeline_response, None, {})

    remove.metadata = {'url': '/apiTokens/{token_id}'}  # type: ignore
