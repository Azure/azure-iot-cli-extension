# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

import uuid
from msrest.pipeline import ClientRawResponse
from msrestazure.azure_exceptions import CloudError

from .. import models


class DeviceMethodOperations(object):
    """DeviceMethodOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    :ivar api_version: Version of the Api. Constant value: "2019-10-01".
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2019-10-01"

        self.config = config

    def invoke_device_method(
            self, device_id, direct_method_request, custom_headers=None, raw=False, **operation_config):
        """Invoke a direct method on a device.

        Invoke a direct method on a device. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-direct-methods
        for more information.

        :param device_id:
        :type device_id: str
        :param direct_method_request:
        :type direct_method_request: ~service.models.CloudToDeviceMethod
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: CloudToDeviceMethodResult or ClientRawResponse if raw=true
        :rtype: ~service.models.CloudToDeviceMethodResult or
         ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.invoke_device_method.metadata['url']
        path_format_arguments = {
            'deviceId': self._serialize.url("device_id", device_id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Accept'] = 'application/json'
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
        request = self._client.post(url, query_parameters, header_parameters, body_content)
        response = self._client.send(request, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('CloudToDeviceMethodResult', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    invoke_device_method.metadata = {'url': '/twins/{deviceId}/methods'}

    def invoke_module_method(
            self, device_id, module_id, direct_method_request, custom_headers=None, raw=False, **operation_config):
        """Invoke a direct method on a module of a device.

        Invoke a direct method on a module of a device. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-direct-methods
        for more information.

        :param device_id:
        :type device_id: str
        :param module_id:
        :type module_id: str
        :param direct_method_request:
        :type direct_method_request: ~service.models.CloudToDeviceMethod
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: CloudToDeviceMethodResult or ClientRawResponse if raw=true
        :rtype: ~service.models.CloudToDeviceMethodResult or
         ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.invoke_module_method.metadata['url']
        path_format_arguments = {
            'deviceId': self._serialize.url("device_id", device_id, 'str'),
            'moduleId': self._serialize.url("module_id", module_id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Accept'] = 'application/json'
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
        request = self._client.post(url, query_parameters, header_parameters, body_content)
        response = self._client.send(request, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('CloudToDeviceMethodResult', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    invoke_module_method.metadata = {'url': '/twins/{deviceId}/modules/{moduleId}/methods'}
