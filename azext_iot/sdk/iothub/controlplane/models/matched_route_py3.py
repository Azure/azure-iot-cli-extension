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


class MatchedRoute(Model):
    """Routes that matched.

    :param properties: Properties of routes that matched
    :type properties: ~service.models.RouteProperties
    """

    _attribute_map = {
        'properties': {'key': 'properties', 'type': 'RouteProperties'},
    }

    def __init__(self, *, properties=None, **kwargs) -> None:
        super(MatchedRoute, self).__init__(**kwargs)
        self.properties = properties
