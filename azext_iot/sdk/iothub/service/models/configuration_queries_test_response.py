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


class ConfigurationQueriesTestResponse(Model):
    """ConfigurationQueriesTestResponse.

    :param target_condition_error:
    :type target_condition_error: str
    :param custom_metric_query_errors:
    :type custom_metric_query_errors: dict[str, str]
    """

    _attribute_map = {
        'target_condition_error': {'key': 'targetConditionError', 'type': 'str'},
        'custom_metric_query_errors': {'key': 'customMetricQueryErrors', 'type': '{str}'},
    }

    def __init__(self, **kwargs):
        super(ConfigurationQueriesTestResponse, self).__init__(**kwargs)
        self.target_condition_error = kwargs.get('target_condition_error', None)
        self.custom_metric_query_errors = kwargs.get('custom_metric_query_errors', None)
