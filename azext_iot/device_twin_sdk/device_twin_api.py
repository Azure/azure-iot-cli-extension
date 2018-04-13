# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# These operations and models have been modified from generated behavior

import uuid
from msrest.service_client import ServiceClient
from msrest import Serializer, Deserializer
from msrest.pipeline import ClientRawResponse
from msrestazure import AzureConfiguration
from msrestazure.azure_exceptions import CloudError
from . import models
from .version import VERSION
from azext_iot._constants import VERSION as extver


class DeviceTwinAPIConfiguration(AzureConfiguration):
    """Configuration for DeviceTwinAPI
    Note that all parameters used to create this instance are saved as instance
    attributes.

    :param credentials: Credentials needed for the client to connect to Azure.
    :type credentials: :mod:`A msrestazure Credentials
     object<msrestazure.azure_active_directory>`
    :param str base_url: Service URL
    """

    def __init__(
            self, credentials, base_url=None):

        if credentials is None:
            raise ValueError("Parameter 'credentials' must not be None.")
        if not base_url:
            base_url = 'https://<fully-qualified IoT hub domain name>'

        super(DeviceTwinAPIConfiguration, self).__init__(base_url)

        self.add_user_agent('devicetwinapi/{}'.format(VERSION))
        self.add_user_agent('MicrosoftAzure/IoTPlatformCliExtension/{}'.format(extver))

        self.credentials = credentials


class DeviceTwinAPI(object):
    """Use this REST API to manage device twins in the identity registry of an IoT hub.
    This API enables you to create and update device twins and invoke direct methods on devices.
    Each API call must include the api-version query parameter as well the authorization header
     containing a Shared Access Signature token with the appropriate permissions.

    :ivar config: Configuration for client.
    :vartype config: DeviceTwinAPIConfiguration

    :param credentials: Credentials needed for the client to connect to Azure.
    :type credentials: :mod:`A msrestazure Credentials
     object<msrestazure.azure_active_directory>`
    :param str base_url: Service URL
    """

    def __init__(
            self, credentials, base_url=None):

        self.config = DeviceTwinAPIConfiguration(credentials, base_url)
        self._client = ServiceClient(self.config.credentials, self.config)

        self.api_version = "2017-11-08-preview"

        client_models = {k: v for k, v in models.__dict__.items() if isinstance(v, type)}
        self._serialize = Serializer(client_models)
        self._deserialize = Deserializer(client_models)

    def get_device_twin(
            self, deviceid, custom_headers=None, raw=False, **operation_config):
        """Get a device twin.

        Get a device twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param deviceid:
        :type deviceid: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>` or
         :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = '/twins/{id}'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
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
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def update_device_twin(
            self, deviceid, device_twin_info, custom_headers=None, raw=False, **operation_config):
        """Updates tags and desired properties of a device twin.

        Update a device twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param deviceid:
        :type deviceid: str
        :param device_twin_info:
        :type device_twin_info: :class:`DeviceTwinInfo
         <device_twin.models.DeviceTwinInfo>`
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>` or
         :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = '/twins/{id}'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
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

        # Construct body
        body_content = self._serialize.body(device_twin_info, 'object')

        # Construct and send request
        request = self._client.patch(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200]:
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def replace_device_twin(
            self, deviceid, device_twin_info, custom_headers=None, raw=False, **operation_config):
        """Updates tags and desired properties of a device twin.

        Update a device twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param deviceid:
        :type deviceid: str
        :param device_twin_info:
        :type device_twin_info: :class:`DeviceTwinInfo
         <device_twin.models.DeviceTwinInfo>`
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>`
         or :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`DeviceTwinInfo <device_twin.models.DeviceTwinInfo>` or
         :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = '/twins/{id}'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
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

        # Construct body
        body_content = self._serialize.body(device_twin_info, 'object')

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200]:
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def invoke_device_method(
            self, deviceid, direct_method_request, custom_headers=None, raw=False, **operation_config):
        """Invoke a direct method on a device.

        Invoke a direct method on a device. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-direct-methods
        for more information.

        :param deviceid:
        :type deviceid: str
        :param direct_method_request:
        :type direct_method_request: :class:`CloudToDeviceMethod
         <device_twin.models.CloudToDeviceMethod>`
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: :class:`CloudToDeviceMethodResult
         <device_twin.models.CloudToDeviceMethodResult>` or
         :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>` if
         raw=true
        :rtype: :class:`CloudToDeviceMethodResult
         <device_twin.models.CloudToDeviceMethodResult>` or
         :class:`ClientRawResponse<msrest.pipeline.ClientRawResponse>`
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = '/twins/{id}/methods'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = '2016-11-14'

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(direct_method_request, 'CloudToDeviceMethod')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200]:
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('CloudToDeviceMethodResult', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
