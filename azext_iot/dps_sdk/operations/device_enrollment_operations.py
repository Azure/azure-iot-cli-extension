# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator 2.3.33.0
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

import uuid
from msrest.pipeline import ClientRawResponse

from .. import models


class DeviceEnrollmentOperations(object):
    """DeviceEnrollmentOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    :ivar api_version: The API version to use for the request. Supported versions include: 2018-09-01-preview. Constant value: "2018-09-01-preview".
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2018-09-01-preview"

        self.config = config

    def get(
            self, id, custom_headers=None, raw=False, **operation_config):
        """Get a device enrollment record.

        :param id: Registration ID.
        :type id: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: IndividualEnrollment or ClientRawResponse if raw=true
        :rtype:
         ~microsoft.azure.management.provisioningservices.models.IndividualEnrollment
         or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.get.metadata['url']
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
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200, 400, 401, 404, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('IndividualEnrollment', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response
        
        return deserialized
    get.metadata = {'url': '/enrollments/{id}'}

    def create_or_update(
            self, id, enrollment, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Create or update a device enrollment record.

        :param id: The registration ID is alphanumeric, lowercase, and may
         contain hyphens.
        :type id: str
        :param enrollment: The device enrollment record.
        :type enrollment:
         ~microsoft.azure.management.provisioningservices.models.IndividualEnrollment
        :param if_match: The ETag of the enrollment record.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: IndividualEnrollment or ClientRawResponse if raw=true
        :rtype:
         ~microsoft.azure.management.provisioningservices.models.IndividualEnrollment
         or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.create_or_update.metadata['url']
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
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if if_match is not None:
            header_parameters['If-Match'] = self._serialize.header("if_match", if_match, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(enrollment, 'IndividualEnrollment')

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200, 400, 401, 404, 409, 412, 415, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('IndividualEnrollment', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response
        
        return deserialized
    create_or_update.metadata = {'url': '/enrollments/{id}'}

    def delete(
            self, id, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Delete a device enrollment record.

        :param id: Registration ID.
        :type id: str
        :param if_match: The ETag of the enrollment record.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: None or ClientRawResponse if raw=true
        :rtype: None or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.delete.metadata['url']
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

        if response.status_code not in [204, 400, 401, 404, 409, 412, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        if raw:
            client_raw_response = ClientRawResponse(None, response)
            return client_raw_response
    delete.metadata = {'url': '/enrollments/{id}'}

    def bulk_operation(
            self, bulk_operation, custom_headers=None, raw=False, **operation_config):
        """Bulk device enrollment operation.

        :param bulk_operation: Bulk operation.
        :type bulk_operation:
         ~microsoft.azure.management.provisioningservices.models.BulkEnrollmentOperation
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: BulkEnrollmentOperationResult or ClientRawResponse if
         raw=true
        :rtype:
         ~microsoft.azure.management.provisioningservices.models.BulkEnrollmentOperationResult
         or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.bulk_operation.metadata['url']

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
        body_content = self._serialize.body(bulk_operation, 'BulkEnrollmentOperation')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200, 400, 401, 404, 409, 412, 415, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('BulkEnrollmentOperationResult', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    bulk_operation.metadata = {'url': '/enrollments'}

    def query(
            self, query_specification, custom_headers=None, raw=False, **operation_config):
        """Query the device enrollment records.

        :param query_specification: The query specification.
        :type query_specification:
         ~microsoft.azure.management.provisioningservices.models.QuerySpecification
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: list or ClientRawResponse if raw=true
        :rtype:
         list[~microsoft.azure.management.provisioningservices.models.IndividualEnrollment]
         or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.query.metadata['url']

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
        body_content = self._serialize.body(query_specification, 'QuerySpecification')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200, 400, 401, 404, 415, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('[IndividualEnrollment]', response)
            header_dict = {
                'x-ms-continuation': 'str',
                'x-ms-max-item-count': 'int',
                'x-ms-item-type': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response
        
        # Added Custom
        continuation = response.headers.get('x-ms-continuation')

        return deserialized, continuation
    query.metadata = {'url': '/enrollments/query'}

    def attestation_mechanism_method(
            self, id, custom_headers=None, raw=False, **operation_config):
        """Get the attestation mechanism in the device enrollment record.

        :param id: Registration ID.
        :type id: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: AttestationMechanism or ClientRawResponse if raw=true
        :rtype:
         ~microsoft.azure.management.provisioningservices.models.AttestationMechanism
         or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<microsoft.azure.management.provisioningservices.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.attestation_mechanism_method.metadata['url']
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
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200, 400, 401, 404, 429, 500]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('AttestationMechanism', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response
        
        return deserialized
    attestation_mechanism_method.metadata = {'url': '/enrollments/{id}/attestationmechanism'}
