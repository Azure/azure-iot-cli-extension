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

from msrest.serialization import Model


class RoutingServiceBusQueueEndpointProperties(Model):
    """The properties related to service bus queue endpoint types.

    All required parameters must be populated in order to send to Azure.

    :param id: Id of the service bus queue endpoint
    :type id: str
    :param connection_string: The connection string of the service bus queue
     endpoint.
    :type connection_string: str
    :param endpoint_uri: The url of the service bus queue endpoint. It must
     include the protocol sb://
    :type endpoint_uri: str
    :param entity_path: Queue name on the service bus namespace
    :type entity_path: str
    :param authentication_type: Method used to authenticate against the
     service bus queue endpoint. Possible values include: 'keyBased',
     'identityBased'
    :type authentication_type: str or ~service.models.AuthenticationType
    :param identity: Managed identity properties of routing service bus queue
     endpoint.
    :type identity: ~service.models.ManagedIdentity
    :param name: Required. The name that identifies this endpoint. The name
     can only include alphanumeric characters, periods, underscores, hyphens
     and has a maximum length of 64 characters. The following names are
     reserved:  events, fileNotifications, $default. Endpoint names must be
     unique across endpoint types. The name need not be the same as the actual
     queue name.
    :type name: str
    :param subscription_id: The subscription identifier of the service bus
     queue endpoint.
    :type subscription_id: str
    :param resource_group: The name of the resource group of the service bus
     queue endpoint.
    :type resource_group: str
    """

    _validation = {
        'name': {'required': True, 'pattern': r'^[A-Za-z0-9-._]{1,64}$'},
    }

    _attribute_map = {
        'id': {'key': 'id', 'type': 'str'},
        'connection_string': {'key': 'connectionString', 'type': 'str'},
        'endpoint_uri': {'key': 'endpointUri', 'type': 'str'},
        'entity_path': {'key': 'entityPath', 'type': 'str'},
        'authentication_type': {'key': 'authenticationType', 'type': 'str'},
        'identity': {'key': 'identity', 'type': 'ManagedIdentity'},
        'name': {'key': 'name', 'type': 'str'},
        'subscription_id': {'key': 'subscriptionId', 'type': 'str'},
        'resource_group': {'key': 'resourceGroup', 'type': 'str'},
    }

    def __init__(self, **kwargs):
        super(RoutingServiceBusQueueEndpointProperties, self).__init__(**kwargs)
        self.id = kwargs.get('id', None)
        self.connection_string = kwargs.get('connection_string', None)
        self.endpoint_uri = kwargs.get('endpoint_uri', None)
        self.entity_path = kwargs.get('entity_path', None)
        self.authentication_type = kwargs.get('authentication_type', None)
        self.identity = kwargs.get('identity', None)
        self.name = kwargs.get('name', None)
        self.subscription_id = kwargs.get('subscription_id', None)
        self.resource_group = kwargs.get('resource_group', None)
