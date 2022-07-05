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


class EventRoutesOperations(object):
    """EventRoutesOperations operations.

    :param client: Client for service requests.
    :param config: Configuration of service client.
    :param serializer: An object model serializer.
    :param deserializer: An object model deserializer.
    :ivar api_version: The requested API version. Constant value: "2022-05-31".
    """

    models = models

    def __init__(self, client, config, serializer, deserializer):

        self._client = client
        self._serialize = serializer
        self._deserialize = deserializer
        self.api_version = "2022-05-31"

        self.config = config

    def list(
            self, event_routes_list_options=None, custom_headers=None, raw=False, **operation_config):
        """Retrieves all event routes.
        Status codes:
        * 200 OK.

        :param event_routes_list_options: Additional parameters for the
         operation
        :type event_routes_list_options:
         ~dataplane.models.EventRoutesListOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: An iterator like instance of EventRoute
        :rtype:
         ~dataplane.models.EventRoutePaged[~dataplane.models.EventRoute]
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        max_items_per_page = None
        if event_routes_list_options is not None:
            max_items_per_page = event_routes_list_options.max_items_per_page
        traceparent = None
        if event_routes_list_options is not None:
            traceparent = event_routes_list_options.traceparent
        tracestate = None
        if event_routes_list_options is not None:
            tracestate = event_routes_list_options.tracestate

        def internal_paging(next_link=None, raw=False):

            if not next_link:
                # Construct URL
                url = self.list.metadata['url']

                # Construct parameters
                query_parameters = {}
                query_parameters['api-version'] = self._serialize.query("self.api_version", self.api_version, 'str')

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
        deserialized = models.EventRoutePaged(internal_paging, self._deserialize.dependencies)

        if raw:
            header_dict = {}
            client_raw_response = models.EventRoutePaged(internal_paging, self._deserialize.dependencies, header_dict)
            return client_raw_response

        return deserialized
    list.metadata = {'url': '/eventroutes'}

    def get_by_id(
            self, id, event_routes_get_by_id_options=None, custom_headers=None, raw=False, **operation_config):
        """Retrieves an event route.
        Status codes:
        * 200 OK
        * 404 Not Found
        * EventRouteNotFound - The event route was not found.

        :param id: The id for an event route. The id is unique within event
         routes and case sensitive.
        :type id: str
        :param event_routes_get_by_id_options: Additional parameters for the
         operation
        :type event_routes_get_by_id_options:
         ~dataplane.models.EventRoutesGetByIdOptions
        :param dict custom_headers: headers that will be added to the request
        :param bool raw: returns the direct response alongside the
         deserialized response
        :param operation_config: :ref:`Operation configuration
         overrides<msrest:optionsforoperations>`.
        :return: EventRoute or ClientRawResponse if raw=true
        :rtype: ~dataplane.models.EventRoute or
         ~msrest.pipeline.ClientRawResponse
        :raises:
         :class:`ErrorResponseException<dataplane.models.ErrorResponseException>`
        """
        traceparent = None
        if event_routes_get_by_id_options is not None:
            traceparent = event_routes_get_by_id_options.traceparent
        tracestate = None
        if event_routes_get_by_id_options is not None:
            tracestate = event_routes_get_by_id_options.tracestate

        # Construct URL
        url = self.get_by_id.metadata['url']
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
            deserialized = self._deserialize('EventRoute', response)

        if raw:
            client_raw_response = ClientRawResponse(deserialized, response)
            return client_raw_response

        return deserialized
    get_by_id.metadata = {'url': '/eventroutes/{id}'}

    def add(
            self, id, endpoint_name, filter, event_routes_add_options=None, custom_headers=None, raw=False, **operation_config):
        """Adds or replaces an event route.
        Status codes:
        * 204 No Content
        * 400 Bad Request
        * EventRouteEndpointInvalid - The endpoint provided does not exist or
        is not active.
        * EventRouteFilterInvalid - The event route filter is invalid.
        * EventRouteIdInvalid - The event route id is invalid.
        * LimitExceeded - The maximum number of event routes allowed has been
        reached.

        :param id: The id for an event route. The id is unique within event
         routes and case sensitive.
        :type id: str
        :param endpoint_name: The name of the endpoint this event route is
         bound to.
        :type endpoint_name: str
        :param filter: An expression which describes the events which are
         routed to the endpoint.
        :type filter: str
        :param event_routes_add_options: Additional parameters for the
         operation
        :type event_routes_add_options:
         ~dataplane.models.EventRoutesAddOptions
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
        if event_routes_add_options is not None:
            traceparent = event_routes_add_options.traceparent
        tracestate = None
        if event_routes_add_options is not None:
            tracestate = event_routes_add_options.tracestate
        event_route = None
        if endpoint_name is not None or filter is not None:
            event_route = models.EventRoute(endpoint_name=endpoint_name, filter=filter)

        # Construct URL
        url = self.add.metadata['url']
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
        if traceparent is not None:
            header_parameters['traceparent'] = self._serialize.header("traceparent", traceparent, 'str')
        if tracestate is not None:
            header_parameters['tracestate'] = self._serialize.header("tracestate", tracestate, 'str')

        # Construct body
        if event_route is not None:
            body_content = self._serialize.body(event_route, 'EventRoute')
        else:
            body_content = None

        # Construct and send request
        request = self._client.put(url, query_parameters)
        response = self._client.send(
            request, header_parameters, body_content, stream=False, **operation_config)

        if response.status_code not in [204]:
            raise models.ErrorResponseException(self._deserialize, response)

        if raw:
            client_raw_response = ClientRawResponse(None, response)
            return client_raw_response
    add.metadata = {'url': '/eventroutes/{id}'}

    def delete(
            self, id, event_routes_delete_options=None, custom_headers=None, raw=False, **operation_config):
        """Deletes an event route.
        Status codes:
        * 204 No Content
        * 404 Not Found
        * EventRouteNotFound - The event route was not found.

        :param id: The id for an event route. The id is unique within event
         routes and case sensitive.
        :type id: str
        :param event_routes_delete_options: Additional parameters for the
         operation
        :type event_routes_delete_options:
         ~dataplane.models.EventRoutesDeleteOptions
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
        if event_routes_delete_options is not None:
            traceparent = event_routes_delete_options.traceparent
        tracestate = None
        if event_routes_delete_options is not None:
            tracestate = event_routes_delete_options.tracestate

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
    delete.metadata = {'url': '/eventroutes/{id}'}
