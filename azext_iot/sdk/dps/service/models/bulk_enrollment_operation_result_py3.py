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


class BulkEnrollmentOperationResult(Model):
    """Results of a bulk enrollment operation.

    All required parameters must be populated in order to send to Azure.

    :param errors: Registration errors
    :type errors: list[~service.models.BulkEnrollmentOperationError]
    :param is_successful: Required. Indicates if the operation was successful
     in its entirety.
    :type is_successful: bool
    """

    _validation = {
        'is_successful': {'required': True},
    }

    _attribute_map = {
        'errors': {'key': 'errors', 'type': '[BulkEnrollmentOperationError]'},
        'is_successful': {'key': 'isSuccessful', 'type': 'bool'},
    }

    def __init__(self, *, is_successful: bool, errors=None, **kwargs) -> None:
        super(BulkEnrollmentOperationResult, self).__init__(**kwargs)
        self.errors = errors
        self.is_successful = is_successful
