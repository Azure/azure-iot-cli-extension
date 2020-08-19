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


class FailToQueueTaskError(Model):
    """FailToQueueTaskError.

    :param message:
    :type message: str
    :param code:
    :type code: int
    :param details:
    :type details: list[object]
    """

    _attribute_map = {
        'message': {'key': 'message', 'type': 'str'},
        'code': {'key': 'code', 'type': 'int'},
        'details': {'key': 'details', 'type': '[object]'},
    }

    def __init__(self, **kwargs):
        super(FailToQueueTaskError, self).__init__(**kwargs)
        self.message = kwargs.get('message', None)
        self.code = kwargs.get('code', None)
        self.details = kwargs.get('details', None)
