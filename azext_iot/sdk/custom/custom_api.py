# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
custom_api: API configuration and API client classes.

"""

import uuid
import requests

from msrest.service_client import ServiceClient
from msrest import Serializer, Deserializer
from msrest.pipeline import ClientRawResponse
from msrestazure import AzureConfiguration
from . import models
from .version import VERSION
from azext_iot.constants import USER_AGENT


class CustomAPIConfiguration(AzureConfiguration):
    """
    Configuration for CustomClient.

    Note: all parameters used to create this instance are saved as instance
    attributes.

    Args:
        credentials (msrestazure.azure_active_directory): Credentials needed for
            the client to connect to Azure. `A msrestazure Credentials
            object<msrestazure.azure_active_directory>`
        base_url (str): Service URL
    """

    def __init__(
            self, credentials=None, base_url=None):

        if not base_url:
            base_url = 'https://<fully-qualified IoT hub domain name>'

        super(CustomAPIConfiguration, self).__init__(base_url)

        self.add_user_agent('customclient/{}'.format(VERSION))
        self.add_user_agent(USER_AGENT)

        self.credentials = credentials


class CustomClient(object):
    """
    Custom Client used for uploading of device files.

    Args:
        credentials (msrestazure.azure_active_directory): Credentials needed for
            the client to connect to Azure. `A msrestazure Credentials
            object<msrestazure.azure_active_directory>`
        base_url (str): Service URL

    Attributes:
        config (CustomAPIConfiguration): configuration object for this client.
        api_version (str): api version this client adhears to.

    """
    def __init__(
            self, credentials, base_url=None):

        self.config = CustomAPIConfiguration(credentials, base_url)
        self._client = ServiceClient(self.config.credentials, self.config)

        self.api_version = "2017-11-08-preview"

        self._serialize = Serializer()
        self._deserialize = Deserializer()

    def build_device_file_container(
            self, deviceid, blob_name, custom_headers=None, raw=False, **operation_config):
        """
        Create a device file container in Azure Blob Storage.

        Args:
            deviceid (): ID of device to associate to blob storage.
            blob_name (): name of blob to create
            custom_headers (): any custom headers to add to the request.
            raw (bool): should function return the 'raw' service client response.
            operation_config (service_client.configuration): See details here:
                https://github.com/Azure/msrest-for-python/blob/master/msrest/configuration.py

        Returns:
            deserialized (object): deserialized generic response object.
            or
            client_raw_response (ClientRawResponse): wrapper of raw response object.

        Raises:
            ErrorDetailsException: when http response is not 200 or 201.

        """

        # Construct URL
        url = '/devices/{id}/files'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = (
            self._serialize.query("self.api_version", self.api_version, 'str')
        )

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = (
                self._serialize.header(
                    "self.config.accept_language",
                    self.config.accept_language, 'str')
            )

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
        """
        Posts notification to device file notifications collection.

        Args:
            deviceid (str): ID of the device to post the notification to.
            correlation_id (str): the coorelation id from a build_device_file_container response.
            custom_headers (dict): dict of custom header values.
            raw (bool): return the result as a ClientRawResponse.
            operation_config (): any msrest.service_client configuration overrides.

        Returns:
            deserialized (): deserialized generic response object.
            or
            client_raw_response (ClientRawResponse): wrapper of raw response object.

        Raises:
            ErrorDetailsException: when http response is not 200, 201 or 204.

        """

        # Construct URL
        url = '/devices/{id}/files/notifications'
        path_format_arguments = {
            'id': self._serialize.url("id", deviceid, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = (
            self._serialize.query("self.api_version", self.api_version, 'str')
        )

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = (
                self._serialize.header(
                    "self.config.accept_language",
                    self.config.accept_language, 'str')
            )

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
            self, storage_endpoint, content, content_type):
        """
        Uploads a file to the specified Azure storage endpoint.

        Args:
            storage_endpoint (str): target url of container to post file to.
            content (object): the content to post to the storage endpoint
            content_type (dict): the IANA Media Type of the content.
            raw (bool): return the result as a ClientRawResponse.
            operation_config (): any msrest.service_client configuration overrides.

        Raises:
            ErrorDetailsException: when http response is not 200 or 201.

        """
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
