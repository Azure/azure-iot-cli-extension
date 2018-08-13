# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator 2.3.33.0
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

from msrest.serialization import Model


class BulkEnrollmentOperationError(Model):
    """Bulk enrollment operation error.

    :param registration_id: Device registration id.
    :type registration_id: str
    :param error_code: Error code
    :type error_code: int
    :param error_status: Error status
    :type error_status: str
    """

    _validation = {
        'registration_id': {'required': True},
        'error_code': {'required': True},
        'error_status': {'required': True},
    }

    _attribute_map = {
        'registration_id': {'key': 'registrationId', 'type': 'str'},
        'error_code': {'key': 'errorCode', 'type': 'int'},
        'error_status': {'key': 'errorStatus', 'type': 'str'},
    }

    def __init__(self, registration_id, error_code, error_status):
        super(BulkEnrollmentOperationError, self).__init__()
        self.registration_id = registration_id
        self.error_code = error_code
        self.error_status = error_status
