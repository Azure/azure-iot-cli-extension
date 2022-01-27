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


class Operation(Model):
    """DigitalTwins service REST API operation.

    Variables are only populated by the server, and will be ignored when
    sending a request.

    :ivar name: Operation name: {provider}/{resource}/{read | write | action |
     delete}
    :vartype name: str
    :param display: Operation properties display
    :type display: ~azure.mgmt.digitaltwins.models.OperationDisplay
    :ivar origin: The intended executor of the operation.
    :vartype origin: str
    :ivar is_data_action: If the operation is a data action (for data plane
     rbac).
    :vartype is_data_action: bool
    :ivar properties: Operation properties.
    :vartype properties: dict[str, object]
    """

    _validation = {
        'name': {'readonly': True},
        'origin': {'readonly': True},
        'is_data_action': {'readonly': True},
        'properties': {'readonly': True},
    }

    _attribute_map = {
        'name': {'key': 'name', 'type': 'str'},
        'display': {'key': 'display', 'type': 'OperationDisplay'},
        'origin': {'key': 'origin', 'type': 'str'},
        'is_data_action': {'key': 'isDataAction', 'type': 'bool'},
        'properties': {'key': 'properties', 'type': '{object}'},
    }

    def __init__(self, *, display=None, **kwargs) -> None:
        super(Operation, self).__init__(**kwargs)
        self.name = None
        self.display = display
        self.origin = None
        self.is_data_action = None
        self.properties = None
