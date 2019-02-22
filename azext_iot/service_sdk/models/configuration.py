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


class Configuration(Model):
    """Configuration for IotHub devices and modules.

    :param id: Gets Identifier for the configuration
    :type id: str
    :param schema_version: Gets Schema version for the configuration
    :type schema_version: str
    :param labels: Gets or sets labels for the configuration
    :type labels: dict[str, str]
    :param content: Gets or sets Content for the configuration
    :type content: ~service.models.ConfigurationContent
    :param target_condition: Gets or sets Target Condition for the
     configuration
    :type target_condition: str
    :param created_time_utc: Gets creation time for the configuration
    :type created_time_utc: datetime
    :param last_updated_time_utc: Gets last update time for the configuration
    :type last_updated_time_utc: datetime
    :param priority: Gets or sets Priority for the configuration
    :type priority: int
    :param system_metrics: System Configuration Metrics
    :type system_metrics: ~service.models.ConfigurationMetrics
    :param metrics: Custom Configuration Metrics
    :type metrics: ~service.models.ConfigurationMetrics
    :param etag: Gets or sets configuration's ETag
    :type etag: str
    """

    # @digimaun - added missing contentType property
    _attribute_map = {
        'id': {'key': 'id', 'type': 'str'},
        'schema_version': {'key': 'schemaVersion', 'type': 'str'},
        'labels': {'key': 'labels', 'type': '{str}'},
        'content': {'key': 'content', 'type': 'ConfigurationContent'},
        'target_condition': {'key': 'targetCondition', 'type': 'str'},
        'created_time_utc': {'key': 'createdTimeUtc', 'type': 'iso-8601'},
        'last_updated_time_utc': {'key': 'lastUpdatedTimeUtc', 'type': 'iso-8601'},
        'priority': {'key': 'priority', 'type': 'int'},
        'system_metrics': {'key': 'systemMetrics', 'type': 'ConfigurationMetrics'},
        'metrics': {'key': 'metrics', 'type': 'ConfigurationMetrics'},
        'etag': {'key': 'etag', 'type': 'str'},
        'content_type': {'key': 'contentType', 'type': 'str'},
    }

    def __init__(self, id=None, schema_version=None, labels=None, content=None, target_condition=None, created_time_utc=None, last_updated_time_utc=None, priority=None, system_metrics=None, metrics=None, etag=None, content_type=None):
        super(Configuration, self).__init__()
        self.id = id
        self.schema_version = schema_version
        self.labels = labels
        self.content = content
        self.target_condition = target_condition
        self.created_time_utc = created_time_utc
        self.last_updated_time_utc = last_updated_time_utc
        self.priority = priority
        self.system_metrics = system_metrics
        self.metrics = metrics
        self.etag = etag
        self.content_type = content_type
