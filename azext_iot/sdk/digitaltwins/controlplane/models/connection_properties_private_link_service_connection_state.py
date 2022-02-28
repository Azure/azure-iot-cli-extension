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

from .connection_state import ConnectionState


class ConnectionPropertiesPrivateLinkServiceConnectionState(ConnectionState):
    """The connection state.

    All required parameters must be populated in order to send to Azure.

    :param status: Required. The status of a private endpoint connection.
     Possible values include: 'Pending', 'Approved', 'Rejected', 'Disconnected'
    :type status: str or
     ~controlplane.models.PrivateLinkServiceConnectionStatus
    :param description: Required. The description for the current state of a
     private endpoint connection.
    :type description: str
    :param actions_required: Actions required for a private endpoint
     connection.
    :type actions_required: str
    """

    _validation = {
        'status': {'required': True},
        'description': {'required': True},
    }

    _attribute_map = {
        'status': {'key': 'status', 'type': 'str'},
        'description': {'key': 'description', 'type': 'str'},
        'actions_required': {'key': 'actionsRequired', 'type': 'str'},
    }

    def __init__(self, **kwargs):
        super(ConnectionPropertiesPrivateLinkServiceConnectionState, self).__init__(**kwargs)
