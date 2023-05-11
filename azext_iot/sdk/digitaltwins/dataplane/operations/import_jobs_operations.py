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


class ImportJobsOperations(object):
    """ImportJobsOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    :ivar api_version: The requested API version. Constant value: "2023-06-30".
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2023-06-30"

        self.config = config

    def list(
            self, import_jobs_list_options=None, custom_headers=None, raw=False, **operation_config):
        """Retrieves all import jobs.
        Status codes:
        * 200 OK.

        :param import_jobs_list_options: Additional parameters for the
         operation
        :type import_jobs_list_options:
         ~dataplane.models.ImportJobsListOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: An iterator like instance of ImportJob
        :rtype:
         ~dataplane.models.ImportJobPaged[~dataplane.models.ImportJob]
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        max_items_per_page = None
        if import_jobs_list_options is not None:
            max_items_per_page = import_jobs_list_options.max_items_per_page
        traceparent = None
        if import_jobs_list_options is not None:
            traceparent = import_jobs_list_options.traceparent
        tracestate = None
        if import_jobs_list_options is not None:
            tracestate = import_jobs_list_options.tracestate

        def internal_paging(next_link=None, raw=False):

            if not next_link:
                # Construct URL
                url = self.list.metadata['url']

                # Construct parameters
                query_parameters = {}
                query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str', min_length=1)

            else:
                url = next_link
                query_parameters = {}

            # Construct headers
            header_parameters = {}
            header_parameters['Content-Type'] = 'application/json; charset=utf-8'
            if self.config.generate_client_request_id:
                header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
            if custom_headers:
                header_parameters.update(custom_headers)
            if self.config.accept_language is not None:
                header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')
            if max_items_per_page is not None:
                header_parameters['max-items-per-page'] = self._serialize.header("max_items_per_page", max_items_per_page, 'int')
            if traceparent is not None:
                header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
            if tracestate is not None:
                header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

            # Construct and send request
            request = self._client.get(url, query_parameters)
            response = self._client.send(
                request, header_parameters, stream=False, **operation_config)

            if response.status_code not in [200]:
                raise models.ErrorResponseException(self._deserialize, response)

            return response

        # Deserialize response
        deserialized = models.ImportJobPaged(internal_paging, self._deserialize.dependencies)

        if raw:
            header_dict = {}
            client_raw_response = models.ImportJobPaged(internal_paging, self._deserialize.dependencies, header_dict)
            return client_raw_response

        return deserialized
    list.metadata = {'url': '/jobs/imports'}

    def add(
            self, id, import_job, import_jobs_add_options=None, custom_headers=None, raw=False, **operation_config):
        """Creates an import job.
        Status codes:
        * 201 Created
        * 400 Bad Request
        * JobLimitReached - The maximum number of import jobs allowed has been
        reached.
        * ValidationFailed - The import job request is not valid.

        :param id: The id for the import job. The id is unique within the
         service and case sensitive.
        :type id: str
        :param import_job: The import job being added.
        :type import_job: ~dataplane.models.ImportJob
        :param import_jobs_add_options: Additional parameters for the
         operation
        :type import_jobs_add_options:
         ~dataplane.models.ImportJobsAddOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: ImportJob or ClientRawResponse if raw=true
        :rtype: ~dataplane.models.ImportJob or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        traceparent = None
        if import_jobs_add_options is not None:
            traceparent = import_jobs_add_options.traceparent
        tracestate = None
        if import_jobs_add_options is not None:
            tracestate = import_jobs_add_options.tracestate

        # Construct URL
        url = self.add.metadata['url']
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str', min_length=1)

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')
        if traceparent is not None:
            header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
        if tracestate is not None:
            header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

        # Construct body
        body_content = self._serialize.body(import_job, 'ImportJob')

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [201]:
            raise models.ErrorResponseException(self._deserialize, response)

        deserialized = None

        if response.status_code == 201:
            deserialized = self._deserialize('ImportJob', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    add.metadata = {'url': '/jobs/imports/{id}'}

    def get_by_id(
            self, id, import_jobs_get_by_id_options=None, custom_headers=None, raw=False, **operation_config):
        """Retrieves an import job.
        Status codes:
        * 200 OK
        * 404 Not Found
        * ImportJobNotFound - The import job was not found.

        :param id: The id for the import job. The id is unique within the
         service and case sensitive.
        :type id: str
        :param import_jobs_get_by_id_options: Additional parameters for the
         operation
        :type import_jobs_get_by_id_options:
         ~dataplane.models.ImportJobsGetByIdOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: ImportJob or ClientRawResponse if raw=true
        :rtype: ~dataplane.models.ImportJob or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        traceparent = None
        if import_jobs_get_by_id_options is not None:
            traceparent = import_jobs_get_by_id_options.traceparent
        tracestate = None
        if import_jobs_get_by_id_options is not None:
            tracestate = import_jobs_get_by_id_options.tracestate

        # Construct URL
        url = self.get_by_id.metadata['url']
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str', min_length=1)

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')
        if traceparent is not None:
            header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
        if tracestate is not None:
            header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

        # Construct and send request
        request = self._client.get(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200]:
            raise models.ErrorResponseException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('ImportJob', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    get_by_id.metadata = {'url': '/jobs/imports/{id}'}

    def delete(
            self, id, import_jobs_delete_options=None, custom_headers=None, raw=False, **operation_config):
        """Deletes an import job.
        Status codes:
        * 204 No Content
        * 400 Bad Request
        * ValidationFailed - The import job request is not valid.

        :param id: The id for the import job. The id is unique within the
         service and case sensitive.
        :type id: str
        :param import_jobs_delete_options: Additional parameters for the
         operation
        :type import_jobs_delete_options:
         ~dataplane.models.ImportJobsDeleteOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: None or ClientRawResponse if raw=true
        :rtype: None or ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        traceparent = None
        if import_jobs_delete_options is not None:
            traceparent = import_jobs_delete_options.traceparent
        tracestate = None
        if import_jobs_delete_options is not None:
            tracestate = import_jobs_delete_options.tracestate

        # Construct URL
        url = self.delete.metadata['url']
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str', min_length=1)

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')
        if traceparent is not None:
            header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
        if tracestate is not None:
            header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

        # Construct and send request
        request = self._client.delete(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [204]:
            raise models.ErrorResponseException(self._deserialize, response)

        if raw:
            client_raw_response = ClientRawResponse(None, response)
            return client_raw_response
    delete.metadata = {'url': '/jobs/imports/{id}'}

    def cancel(
            self, id, import_jobs_cancel_options=None, custom_headers=None, raw=False, **operation_config):
        """Cancels an import job.
        Status codes:
        * 200 Request Accepted
        * 400 Bad Request
        * ValidationFailed - The import job request is not valid.

        :param id: The id for the import job. The id is unique within the
         service and case sensitive.
        :type id: str
        :param import_jobs_cancel_options: Additional parameters for the
         operation
        :type import_jobs_cancel_options:
         ~dataplane.models.ImportJobsCancelOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: ImportJob or ClientRawResponse if raw=true
        :rtype: ~dataplane.models.ImportJob or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        traceparent = None
        if import_jobs_cancel_options is not None:
            traceparent = import_jobs_cancel_options.traceparent
        tracestate = None
        if import_jobs_cancel_options is not None:
            tracestate = import_jobs_cancel_options.tracestate

        # Construct URL
        url = self.cancel.metadata['url']
        path_format_arguments = {
            'id': self._serialize.url("id", id, 'str')
        }
        url = self._client.format_url(url, **path_format_arguments)

        # Construct parameters
        query_parameters = {}
        query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str', min_length=1)

        # Construct headers
        header_parameters = {}
        header_parameters['Content-Type'] = 'application/json; charset=utf-8'
        if self.config.generate_client_request_id:
            header_parameters['x-ms-client-request-id'] = str(uuid.uuid1())
        if custom_headers:
            header_parameters.update(custom_headers)
        if self.config.accept_language is not None:
            header_parameters['accept-language'] = self._serialize.header("self.config.accept_language", self.config.accept_language, 'str')
        if traceparent is not None:
            header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
        if tracestate is not None:
            header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

        # Construct and send request
        request = self._client.post(url, query_parameters)
        response = self._client.send(request, header_parameters, stream=False, **operation_config)

        if response.status_code not in [200]:
            raise models.ErrorResponseException(self._deserialize, response)

        deserialized = None

        if response.status_code == 200:
            deserialized = self._deserialize('ImportJob', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    cancel.metadata = {'url': '/jobs/imports/{id}/cancel'}
