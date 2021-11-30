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

from .. import models


class EnrollmentGroupOperations(object):
    """EnrollmentGroupOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    :ivar api_version: The API version to use for the request. Supported versions include: 2021-10-01. Constant value: "2021-10-01".
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2021-10-01"

        self.config = config

    def get(
            self, id, custom_headers=None, raw=False, **operation_config):
        """Get a device enrollment group.

        :param id: Enrollment group ID.
        :type id: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: EnrollmentGroup or ClientRawResponse if raw=true
        :rtype: ~service.models.EnrollmentGroup or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
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

        if response.status_code not in [200]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('EnrollmentGroup', response)
            header_dict = {
                'x-ms-error-code': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response

        return deserialized
    get.metadata = {'url': '/enrollmentGroups/{id}'}

    def create_or_update(
            self, id, enrollment_group, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Create or update a device enrollment group.

        :param id: Enrollment group ID.
        :type id: str
        :param enrollment_group: The device enrollment group.
        :type enrollment_group: ~service.models.EnrollmentGroup
        :param if_match: The ETag of the enrollment record.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: EnrollmentGroup or ClientRawResponse if raw=true
        :rtype: ~service.models.EnrollmentGroup or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
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
        body_content = self._serialize.body(enrollment_group, 'EnrollmentGroup')

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('EnrollmentGroup', response)
            header_dict = {
                'x-ms-error-code': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response

        return deserialized
    create_or_update.metadata = {'url': '/enrollmentGroups/{id}'}

    def delete(
            self, id, if_match=None, custom_headers=None, raw=False, **operation_config):
        """Delete a device enrollment group.

        :param id: Enrollment group ID.
        :type id: str
        :param if_match: The ETag of the enrollment group record.
        :type if_match: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: None or ClientRawResponse if raw=true
        :rtype: None or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
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

        if response.status_code not in [204]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        if raw:
            client_raw_response = ClientRawResponse(None, response)
            client_raw_response.add_headers({
                'x-ms-error-code': 'str',
            })
            return client_raw_response
    delete.metadata = {'url': '/enrollmentGroups/{id}'}

    def query(
            self, query, x_ms_max_item_count=None, x_ms_continuation=None, custom_headers=None, raw=False, **operation_config):
        """Query the device enrollment groups.

        :param query:
        :type query: str
        :param x_ms_max_item_count: Page size
        :type x_ms_max_item_count: int
        :param x_ms_continuation: Continuation token
        :type x_ms_continuation: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: list or ClientRawResponse if raw=true
        :rtype: list[~service.models.EnrollmentGroup] or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
        """
        query_specification = models.QuerySpecification(query=query)

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
        if x_ms_max_item_count is not None:
            header_parameters['x-ms-max-item-count'] = self._serialize.header("x_ms_max_item_count", x_ms_max_item_count, 'int')
        if x_ms_continuation is not None:
            header_parameters['x-ms-continuation'] = self._serialize.header("x_ms_continuation", x_ms_continuation, 'str')
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')

        # Construct body
        body_content = self._serialize.body(query_specification, 'QuerySpecification')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('[EnrollmentGroup]', response)
            header_dict = {
                'x-ms-continuation': 'str',
                'x-ms-max-item-count': 'int',
                'x-ms-item-type': 'str',
                'x-ms-error-code': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response

        return deserialized
    query.metadata = {'url': '/enrollmentGroups/query'}

    def get_attestation_mechanism(
            self, id, custom_headers=None, raw=False, **operation_config):
        """Get the attestation mechanism in the device enrollment group record.

        :param id: Enrollment group ID
        :type id: str
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: AttestationMechanism or ClientRawResponse if raw=true
        :rtype: ~service.models.AttestationMechanism or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
        """
        # Construct URL
        url = self.get_attestation_mechanism.metadata['url']
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

        if response.status_code not in [200]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('AttestationMechanism', response)
            header_dict = {
                'x-ms-error-code': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response

        return deserialized
    get_attestation_mechanism.metadata = {'url': '/enrollmentGroups/{id}/attestationmechanism'}

    def run_bulk_operation(
            self, enrollment_groups, mode, custom_headers=None, raw=False, **operation_config):
        """Bulk device enrollment group operation with maximum of 10 groups.

        :param enrollment_groups: Enrollment items
        :type enrollment_groups: list[~service.models.EnrollmentGroup]
        :param mode: Operation mode. Possible values include: 'create',
         'update', 'updateIfMatchETag', 'delete'
        :type mode: str or ~service.models.enum
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: BulkEnrollmentGroupOperationResult or ClientRawResponse if
         raw=true
        :rtype: ~service.models.BulkEnrollmentGroupOperationResult or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ProvisioningServiceErrorDetailsException<service.models.ProvisioningServiceErrorDetailsException>`
        """
        bulk_operation = models.BulkEnrollmentGroupOperation(enrollment_groups=enrollment_groups, mode=mode)

        # Construct URL
        url = self.run_bulk_operation.metadata['url']

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
        body_content = self._serialize.body(bulk_operation, 'BulkEnrollmentGroupOperation')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [200]:
            raise models.ProvisioningServiceErrorDetailsException(self._deserialize, response)

        deserialized = None
        header_dict = {}

        if response.status_code == 200:
            deserialized = self._deserialize('BulkEnrollmentGroupOperationResult', response)
            header_dict = {
                'x-ms-error-code': 'str',
            }

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            client_raw_response.add_headers(header_dict)
            return client_raw_response

        return deserialized
    run_bulk_operation.metadata = {'url': '/enrollmentGroups'}