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


class RouteErrorRange(Model):
    """Range of route errors.

    :param start: Start where the route error happened
    :type start: ~service.models.RouteErrorPosition
    :param end: End where the route error happened
    :type end: ~service.models.RouteErrorPosition
    """

    _attribute_map = {
        'start': {'key': 'start', 'type': 'RouteErrorPosition'},
        'end': {'key': 'end', 'type': 'RouteErrorPosition'},
    }

    def __init__(self, **kwargs):
        super(RouteErrorRange, self).__init__(**kwargs)
        self.start = kwargs.get('start', None)
        self.end = kwargs.get('end', None)
