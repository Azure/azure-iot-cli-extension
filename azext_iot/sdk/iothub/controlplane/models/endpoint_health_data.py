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


class EndpointHealthData(Model):
    """The health data for an endpoint.

    :param endpoint_id: Id of the endpoint
    :type endpoint_id: str
    :param health_status: Health statuses have following meanings. The
     'healthy' status shows that the endpoint is accepting messages as
     expected. The 'unhealthy' status shows that the endpoint is not accepting
     messages as expected and IoT Hub is retrying to send data to this
     endpoint. The status of an unhealthy endpoint will be updated to healthy
     when IoT Hub has established an eventually consistent state of health. The
     'dead' status shows that the endpoint is not accepting messages, after IoT
     Hub retried sending messages for the retrial period. See IoT Hub metrics
     to identify errors and monitor issues with endpoints. The 'unknown' status
     shows that the IoT Hub has not established a connection with the endpoint.
     No messages have been delivered to or rejected from this endpoint.
     Possible values include: 'unknown', 'healthy', 'degraded', 'unhealthy',
     'dead'
    :type health_status: str or ~service.models.EndpointHealthStatus
    :param last_known_error: Last error obtained when a message failed to be
     delivered to iot hub
    :type last_known_error: str
    :param last_known_error_time: Time at which the last known error occurred
    :type last_known_error_time: datetime
    :param last_successful_send_attempt_time: Last time iot hub successfully
     sent a message to the endpoint
    :type last_successful_send_attempt_time: datetime
    :param last_send_attempt_time: Last time iot hub tried to send a message
     to the endpoint
    :type last_send_attempt_time: datetime
    """

    _attribute_map = {
        'endpoint_id': {'key': 'endpointId', 'type': 'str'},
        'health_status': {'key': 'healthStatus', 'type': 'str'},
        'last_known_error': {'key': 'lastKnownError', 'type': 'str'},
        'last_known_error_time': {'key': 'lastKnownErrorTime', 'type': 'rfc-1123'},
        'last_successful_send_attempt_time': {'key': 'lastSuccessfulSendAttemptTime', 'type': 'rfc-1123'},
        'last_send_attempt_time': {'key': 'lastSendAttemptTime', 'type': 'rfc-1123'},
    }

    def __init__(self, **kwargs):
        super(EndpointHealthData, self).__init__(**kwargs)
        self.endpoint_id = kwargs.get('endpoint_id', None)
        self.health_status = kwargs.get('health_status', None)
        self.last_known_error = kwargs.get('last_known_error', None)
        self.last_known_error_time = kwargs.get('last_known_error_time', None)
        self.last_successful_send_attempt_time = kwargs.get('last_successful_send_attempt_time', None)
        self.last_send_attempt_time = kwargs.get('last_send_attempt_time', None)
