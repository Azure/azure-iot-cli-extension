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


class DeviceRegistration(Model):
    """Device registration.

    :param registration_id: The registration ID is a case-insensitive string
     (up to 128 characters long) of alphanumeric characters plus certain
     special characters : . _ -. No special characters allowed at start or end.
    :type registration_id: str
    :param tpm: Tpm.
    :type tpm: ~dps.models.TpmAttestation
    :param payload: Custom allocation payload.
    :type payload: object
    """

    _attribute_map = {
        'registration_id': {'key': 'registrationId', 'type': 'str'},
        'tpm': {'key': 'tpm', 'type': 'TpmAttestation'},
        'payload': {'key': 'payload', 'type': 'object'},
    }

    def __init__(self, **kwargs):
        super(DeviceRegistration, self).__init__(**kwargs)
        self.registration_id = kwargs.get('registration_id', None)
        self.tpm = kwargs.get('tpm', None)
        self.payload = kwargs.get('payload', None)
