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


class DeleteJobsListOptions(Model):
    """Additional parameters for list operation.

    :param max_items_per_page: The maximum number of items to retrieve per
     request. The server may choose to return less than the requested number.
    :type max_items_per_page: int
    :param traceparent: Identifies the request in a distributed tracing
     system.
    :type traceparent: str
    :param tracestate: Provides vendor-specific trace identification
     information and is a companion to traceparent.
    :type tracestate: str
    """

    _attribute_map = {
        'max_items_per_page': {'key': '', 'type': 'int'},
        'traceparent': {'key': '', 'type': 'str'},
        'tracestate': {'key': '', 'type': 'str'},
    }

    def __init__(self, *, max_items_per_page: int=None, traceparent: str=None, tracestate: str=None, **kwargs) -> None:
        super(DeleteJobsListOptions, self).__init__(**kwargs)
        self.max_items_per_page = max_items_per_page
        self.traceparent = traceparent
        self.tracestate = tracestate
