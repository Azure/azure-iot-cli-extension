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


class ModulesOperations(object):
    """ModulesOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2024-03-31"

        self.config = config

    def get_twin(
            self, id, mid, custom_headers=None, raw=False, **operation_config):
        """Gets the module twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param id: The unique identifier of the device.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: Twin or ClientRawResponse if raw=true
        :rtype: ~service.models.Twin or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.get_twin.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('Twin', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    get_twin.metadata = {'url': '/twins/{id}/modules/{mid}'}

    def replace_twin(
            self, id, mid, device_twin_info, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Replaces the tags and desired properties of a module twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param id: The unique identifier of the device.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param device_twin_info: The module twin info that will replace the
         existing info.
        :type device_twin_info: ~service.models.Twin
        :param if_match: The string representing a weak ETag for the device
         twin, as per RFC7232. It determines if the replace operation should be
         carried out.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: Twin or ClientRawResponse if raw=true
        :rtype: ~service.models.Twin or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.replace_twin.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if if_match is not None:
            header_parameters['If-Match'] = self._serialize.header("if_match", if_match, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(device_twin_info, 'Twin')

        # Construct and send request
        request = self._client.put(url, query_parameters, header_parameters, body_content)
        response = self._client.send(request, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('Twin', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    replace_twin.metadata = {'url': '/twins/{id}/modules/{mid}'}

    def update_twin(
            self, id, mid, device_twin_info, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Updates the tags and desired properties of a module twin. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-device-twins
        for more information.

        :param id: The unique identifier of the device.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param device_twin_info: The module twin info containing the tags and
         desired properties to be updated.
        :type device_twin_info: ~service.models.Twin
        :param if_match: The string representing a weak ETag for the device
         twin, as per RFC7232. It determines if the update operation should be
         carried out.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: Twin or ClientRawResponse if raw=true
        :rtype: ~service.models.Twin or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.update_twin.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if if_match is not None:
            header_parameters['If-Match'] = self._serialize.header("if_match", if_match, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(device_twin_info, 'Twin')

        # Construct and send request
        request = self._client.patch(url, query_parameters, header_parameters, body_content)
        response = self._client.send(request, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('Twin', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    update_twin.metadata = {'url': '/twins/{id}/modules/{mid}'}

    def get_modules_on_device(
            self, id, custom_headers=None, raw=False, **operation_config):
        """Gets all the module identities on the device.

        :param id: The unique identifier of the device.
        :type id: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: list or ClientRawResponse if raw=true
        :rtype: list[~service.models.Module] or
         ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.get_modules_on_device.metadata['url']
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('[Module]', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    get_modules_on_device.metadata = {'url': '/devices/{id}/modules'}

    def get_identity(
            self, id, mid, custom_headers=None, raw=False, **operation_config):
        """Gets a module identity on the device.

        :param id: The unique identifier of the device.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: Module or ClientRawResponse if raw=true
        :rtype: ~service.models.Module or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.get_identity.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('Module', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    get_identity.metadata = {'url': '/devices/{id}/modules/{mid}'}

    def create_or_update_identity(
            self, id, mid, module, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Creates or updates the module identity for a device in the IoT Hub. The
        moduleId and generationId cannot be updated by the user.

        :param id: The unique identifier of the device.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param module: The module identity.
        :type module: ~service.models.Module
        :param if_match: The string representing a weak ETag for the module,
         as per RFC7232. This should not be set when creating a module, but may
         be set when updating a module.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: Module or ClientRawResponse if raw=true
        :rtype: ~service.models.Module or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.create_or_update_identity.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if if_match is not None:
            header_parameters['If-Match'] = self._serialize.header("if_match", if_match, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(module, 'Module')

        # Construct and send request
        request = self._client.put(url, query_parameters, header_parameters, body_content)
        response = self._client.send(request, stream=False, **operation_config)

        if response.status_code not in [200, 201]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('Module', response)
        if response.status_code == 201:
            deserialized = self._deserialize('Module', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    create_or_update_identity.metadata = {'url': '/devices/{id}/modules/{mid}'}

    def delete_identity(
            self, id, mid, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Deletes the module identity for a device in the IoT Hub.

        :param id: The unique identifier of the deivce.
        :type id: str
        :param mid: The unique identifier of the module.
        :type mid: str
        :param if_match: The string representing a weak ETag for the module,
         as per RFC7232. The delete operation is performed only if this ETag
         matches the value maintained by the server, indicating that the module
         has not been modified since it was last retrieved. To force an
         unconditional delete, set If-Match to the wildcard character (*).
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: None or ClientRawResponse if raw=true
        :rtype: None or ~msrest.pipeline.ClientRawResponse
        :raises: :class:`CloudError<msrestazure.azure_exceptions.CloudError>`
        """
        # Construct URL
        url = self.delete_identity.metadata['url']
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
        if if_match is not None:
            header_parameters['If-Match'] = self._serialize.header("if_match", if_match, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.delete(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [204]:
            exp = CloudError(response)
            exp.request_id = response.headers.get('x-ms-request-id')
            raise exp

        if raw:
            client_raw_response = ClientRawResponse(None, response)
            return client_raw_response
    delete_identity.metadata = {'url': '/devices/{id}/modules/{mid}'}

    def invoke_method(
            self, device_id, module_id, direct_method_request, custom_headers=None, raw=False, **operation_config):
        """Invokes a direct method on a module of a device. See
        https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-direct-methods
        for more information.

        :param device_id: The unique identifier of the device.
        :type device_id: str
        :param module_id: The unique identifier of the module.
        :type module_id: str
        :param direct_method_request: The parameters to execute a direct
         method on the module.
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
        url = self.invoke_method.metadata['url']
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
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
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
    invoke_method.metadata = {'url': '/twins/{deviceId}/modules/{moduleId}/methods'}
