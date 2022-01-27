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

from .external_resource import ExternalResource


class DigitalTwinsEndpointResource(ExternalResource):
    """DigitalTwinsInstance endpoint resource.

    Variables are only populated by the server, and will be ignored when
    sending a request.

    All required parameters must be populated in order to send to Azure.

    :ivar id: The resource identifier.
    :vartype id: str
    :ivar name: Extension resource name.
    :vartype name: str
    :ivar type: The resource type.
    :vartype type: str
    :ivar system_data: Metadata pertaining to creation and last modification
     of the resource.
    :vartype system_data: ~azure.mgmt.digitaltwins.models.SystemData
    :param properties: Required. DigitalTwinsInstance endpoint resource
     properties.
    :type properties:
     ~azure.mgmt.digitaltwins.models.DigitalTwinsEndpointResourceProperties
    """

    _validation = {
        'id': {'readonly': True},
        'name': {'readonly': True, 'pattern': r'^(?![0-9]+$)(?!-)[a-zA-Z0-9-]{2,49}[a-zA-Z0-9]$'},
        'type': {'readonly': True},
        'system_data': {'readonly': True},
        'properties': {'required': True},
    }

    _attribute_map = {
        'id': {'key': 'id', 'type': 'str'},
        'name': {'key': 'name', 'type': 'str'},
        'type': {'key': 'type', 'type': 'str'},
        'system_data': {'key': 'systemData', 'type': 'SystemData'},
        'properties': {'key': 'properties', 'type': 'DigitalTwinsEndpointResourceProperties'},
    }

    def __init__(self, **kwargs):
        super(DigitalTwinsEndpointResource, self).__init__(**kwargs)
        self.properties = kwargs.get('properties', None)
