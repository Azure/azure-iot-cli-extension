# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# These operations and models have been modified from generated behavior

import uuid
from msrest.pipeline import ClientRawResponse
from .. import models


class DeviceTwinApiOperations(object):
    """DeviceTwinApiOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An objec model deserializer.
    :ivar api_version: Version of the Api. Constant value: "2017-11-08-preview".
    """

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2017-11-08-preview"
        self.config = config

    def get_module_twin(
            self, id, mid, custom_headers=None, raw=False, **operation_config):
        """

        :param id:
        :type id: str
        :param mid:
        :type mid: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises:
         :class:`ErrorDetailsException<iothubclient.models.ErrorDetailsException>`
        """
        # Construct URL
        url = '/twins/{id}/modules/{mid}'
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str'),
            'mid': self._serialize.url("mid", mid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, **operation_config)

        if response.status_code not in [200]:
            raise models.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def replace_module_twin(
            self, id, mid, device_twin_info, custom_headers=None, raw=False, **operation_config):
        """

        :param id:
        :type id: str
        :param mid:
        :type mid: str
        :param device_twin_info:
        :type device_twin_info: :class:`DeviceTwinInfo
         <iothubclient.models.DeviceTwinInfo>`
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises:
         :class:`ErrorDetailsException<iothubclient.models.ErrorDetailsException>`
        """
        # Construct URL
        url = '/twins/{id}/modules/{mid}'
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str'),
            'mid': self._serialize.url("mid", mid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body 'DeviceTwinInfo'
        body_content = self._serialize.body(device_twin_info, 'object')

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200]:
            raise models.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        'DeviceTwinInfo'
        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def update_module_twin(
            self, id, mid, device_twin_info, custom_headers=None, raw=False, **operation_config):
        """

        :param id:
        :type id: str
        :param mid:
        :type mid: str
        :param device_twin_info:
        :type device_twin_info: :class:`DeviceTwinInfo
         <iothubclient.models.DeviceTwinInfo>`
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <iothubclient.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises:
         :class:`ErrorDetailsException<iothubclient.models.ErrorDetailsException>`
        """
        # Construct URL
        url = '/twins/{id}/modules/{mid}'
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str'),
            'mid': self._serialize.url("mid", mid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body 'DeviceTwinInfo'
        body_content = self._serialize.body(device_twin_info, 'object')

        # Construct and send request
        request = self._client.patch(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200]:
            raise models.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        # 'DeviceTwinInfo'
        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
