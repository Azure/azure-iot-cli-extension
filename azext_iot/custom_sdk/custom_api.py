# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import uuid
from msrest.service_client import ServiceClient
from msrest import Serializer, Deserializer
from msrest.pipeline import ClientRawResponse
from msrestazure import AzureConfiguration
from . import models
from .version import VERSION


class CustomAPIConfiguration(AzureConfiguration):
    """Configuration for CustomClient
    Note that all parameters used to create this instance are saved as instance
    attributes.

    :param credentials: Credentials needed for the client to connect to Azure.
    :type credentials: :mod:`A msrestazure Credentials
     object<msrestazure.azure_active_directory>`
    :param str base_url: Service URL
    """

    def __init__(
            self, credentials=None, base_url=None):

        if not base_url:
            base_url = 'https://<fully-qualified IoT hub domain name>'

        super(CustomAPIConfiguration, self).__init__(base_url)
        
        self.add_user_agent('iotextension/{}'.format(VERSION))

        self.credentials = credentials


class CustomClient(object):
    def __init__(
            self, credentials, base_url=None):

        self.config = CustomAPIConfiguration(credentials, base_url)
        self._client = ServiceClient(self.config.credentials, self.config)

        self.api_version = "2017-11-08-preview"

        self._serialize = Serializer()
        self._deserialize = Deserializer()

    def build_device_file_container(
            self, deviceid, blob_name, custom_headers=None, raw=False, **operation_config):

        # Construct URL
        url = '/devices/{id}/files'
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

        blob_payload = {'blobName': blob_name}
        # Construct body
        body_content = self._serialize.body(blob_payload, 'object')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200, 201]:
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def post_file_notification(
            self, deviceid, correlation_id, custom_headers=None, raw=False, **operation_config):

        # Construct URL
        url = '/devices/{id}/files/notifications'
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

        notify_payload = {'correlationId': correlation_id}
        # Construct body
        body_content = self._serialize.body(notify_payload, 'object')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, **operation_config)

        if response.status_code not in [200, 201, 204]:
            raise models.error_details.ErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('object', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized

    def upload_file_to_container(
            self, storage_endpoint, content, content_type, raw=False, **operation_config):
        import requests

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = content_type
        header_parameters['Content-Length'] = str(len(content))
        header_parameters['x-ms-blob-type'] = 'BlockBlob'
        header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())

        blob_payload = content
        protocol = 'https://'
        response = requests.put('{}{}'.format(protocol, storage_endpoint),
                                headers=header_parameters,
                                data=blob_payload)

        if response.status_code in [200, 201]:
            return

        raise models.error_details.ErrorDetailsException(self._deserialize, response)
