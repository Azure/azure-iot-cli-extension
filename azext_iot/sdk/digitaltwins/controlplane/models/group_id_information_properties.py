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


class GroupIdInformationProperties(Model):
    """The properties for a group information object.

    :param group_id: The group id.
    :type group_id: str
    :param required_members: The required members for a specific group id.
    :type required_members: list[str]
    :param required_zone_names: The required DNS zones for a specific group
     id.
    :type required_zone_names: list[str]
    """

    _attribute_map = {
        'group_id': {'key': 'groupId', 'type': 'str'},
        'required_members': {'key': 'requiredMembers', 'type': '[str]'},
        'required_zone_names': {'key': 'requiredZoneNames', 'type': '[str]'},
    }

    def __init__(self, **kwargs):
        super(GroupIdInformationProperties, self).__init__(**kwargs)
        self.group_id = kwargs.get('group_id', None)
        self.required_members = kwargs.get('required_members', None)
        self.required_zone_names = kwargs.get('required_zone_names', None)
