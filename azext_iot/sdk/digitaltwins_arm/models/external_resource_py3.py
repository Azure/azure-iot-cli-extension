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


class ExternalResource(Model):
    """Definition of a Resource.

    Variables are only populated by the server, and will be ignored when
    sending a request.

    :ivar id: The resource identifier.
    :vartype id: str
    :ivar name: Extension resource name.
    :vartype name: str
    :ivar type: The resource type.
    :vartype type: str
    """

    _validation = {
        'id': {'readonly': True},
        'name': {'readonly': True, 'pattern': r'^(?![0-9]+$)(?!-)[a-zA-Z0-9-]{2,49}[a-zA-Z0-9]$'},
        'type': {'readonly': True},
    }

    _attribute_map = {
        'id': {'key': 'id', 'type': 'str'},
        'name': {'key': 'name', 'type': 'str'},
        'type': {'key': 'type', 'type': 'str'},
    }

    def __init__(self, **kwargs) -> None:
        super(ExternalResource, self).__init__(**kwargs)
        self.id = None
        self.name = None
        self.type = None
