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


class DigitalTwinsPatchProperties(Model):
    """The properties of a DigitalTwinsInstance.

    :param public_network_access: Public network access for the
     DigitalTwinsInstance. Possible values include: 'Enabled', 'Disabled'
    :type public_network_access: str or
     ~azure.mgmt.digitaltwins.models.PublicNetworkAccess
    """

    _attribute_map = {
        'public_network_access': {'key': 'publicNetworkAccess', 'type': 'str'},
    }

    def __init__(self, *, public_network_access=None, **kwargs) -> None:
        super(DigitalTwinsPatchProperties, self).__init__(**kwargs)
        self.public_network_access = public_network_access
