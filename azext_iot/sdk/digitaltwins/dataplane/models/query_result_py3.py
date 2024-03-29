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


class QueryResult(Model):
    """The results of a query operation and an optional continuation token.

    All required parameters must be populated in order to send to Azure.

    :param value: Required. The query results.
    :type value: list[object]
    :param continuation_token: A token which can be used to construct a new
     QuerySpecification to retrieve the next set of results.
    :type continuation_token: str
    """

    _validation = {
        'value': {'required': True},
    }

    _attribute_map = {
        'value': {'key': 'value', 'type': '[object]'},
        'continuation_token': {'key': 'continuationToken', 'type': 'str'},
    }

    def __init__(self, *, value, continuation_token: str=None, **kwargs) -> None:
        super(QueryResult, self).__init__(**kwargs)
        self.value = value
        self.continuation_token = continuation_token
