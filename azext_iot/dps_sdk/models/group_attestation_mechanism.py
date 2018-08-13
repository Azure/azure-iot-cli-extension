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


class GroupAttestationMechanism(Model):
    """Attestation mechanism for enrollment groups.

    :param type: Attestation Type. Possible values include: 'none', 'x509'
    :type type: str or
     ~microsoft.azure.management.provisioningservices.models.enum
    :param x509: X509 attestation method.
    :type x509:
     ~microsoft.azure.management.provisioningservices.models.X509Attestation
    """

    _validation = {
        'type': {'required': True},
    }

    _attribute_map = {
        'type': {'key': 'type', 'type': 'str'},
        'x509': {'key': 'x509', 'type': 'X509Attestation'},
    }

    def __init__(self, type, x509=None):
        super(GroupAttestationMechanism, self).__init__()
        self.type = type
        self.x509 = x509
