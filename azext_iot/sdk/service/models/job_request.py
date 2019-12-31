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


class JobRequest(Model):
    """JobRequest.

    :param job_id: Job identifier
    :type job_id: str
    :param type: Required.
     The type of job to execute. Possible values include: 'unknown', 'export',
     'import', 'backup', 'readDeviceProperties', 'writeDeviceProperties',
     'updateDeviceConfiguration', 'rebootDevice', 'factoryResetDevice',
     'firmwareUpdate', 'scheduleDeviceMethod', 'scheduleUpdateTwin',
     'restoreFromBackup', 'failoverDataCopy'
    :type type: str or ~service.models.enum
    :param cloud_to_device_method: Required if jobType is cloudToDeviceMethod.
     The method type and parameters.
    :type cloud_to_device_method: ~service.models.CloudToDeviceMethod
    :param update_twin:
    :type update_twin: ~service.models.Twin
    :param query_condition: Required if jobType is updateTwin or
     cloudToDeviceMethod.
     Condition for device query to get devices to execute the job on
    :type query_condition: str
    :param start_time: ISO 8601 date time to start the job
    :type start_time: datetime
    :param max_execution_time_in_seconds: Max execution time in secounds (ttl
     duration)
    :type max_execution_time_in_seconds: long
    """

    # @digimaun - altered update_twin type from Twin to {object}
    _attribute_map = {
        'job_id': {'key': 'jobId', 'type': 'str'},
        'type': {'key': 'type', 'type': 'str'},
        'cloud_to_device_method': {'key': 'cloudToDeviceMethod', 'type': 'CloudToDeviceMethod'},
        'update_twin': {'key': 'updateTwin', 'type': '{object}'},
        'query_condition': {'key': 'queryCondition', 'type': 'str'},
        'start_time': {'key': 'startTime', 'type': 'iso-8601'},
        'max_execution_time_in_seconds': {'key': 'maxExecutionTimeInSeconds', 'type': 'long'},
    }

    def __init__(self, job_id=None, type=None, cloud_to_device_method=None, update_twin=None, query_condition=None, start_time=None, max_execution_time_in_seconds=None):
        super(JobRequest, self).__init__()
        self.job_id = job_id
        self.type = type
        self.cloud_to_device_method = cloud_to_device_method
        self.update_twin = update_twin
        self.query_condition = query_condition
        self.start_time = start_time
        self.max_execution_time_in_seconds = max_execution_time_in_seconds
