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


class ManagedIdentityReference(Model):
    """The properties of the Managed Identity.

    :param type: The type of managed identity used. Possible values include:
     'SystemAssigned', 'UserAssigned'
    :type type: str or ~controlplane.models.IdentityType
    :param user_assigned_identity: The user identity ARM resource id if the
     managed identity type is 'UserAssigned'.
    :type user_assigned_identity: str
    """

    _attribute_map = {
        'type': {'key': 'type', 'type': 'str'},
        'user_assigned_identity': {'key': 'userAssignedIdentity', 'type': 'str'},
    }

    def __init__(self, *, type=None, user_assigned_identity: str=None, **kwargs) -> None:
        super(ManagedIdentityReference, self).__init__(**kwargs)
        self.type = type
        self.user_assigned_identity = user_assigned_identity
