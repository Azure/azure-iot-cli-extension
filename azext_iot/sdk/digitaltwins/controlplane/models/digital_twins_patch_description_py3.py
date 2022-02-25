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


class DigitalTwinsPatchDescription(Model):
    """The description of the DigitalTwins service.

    :param tags: Instance patch properties
    :type tags: dict[str, str]
    :param identity: The managed identity for the DigitalTwinsInstance.
    :type identity: ~controlplane.models.DigitalTwinsIdentity
    :param properties: Properties for the DigitalTwinsInstance.
    :type properties:
     ~controlplane.models.DigitalTwinsPatchProperties
    """

    _attribute_map = {
        'tags': {'key': 'tags', 'type': '{str}'},
        'identity': {'key': 'identity', 'type': 'DigitalTwinsIdentity'},
        'properties': {'key': 'properties', 'type': 'DigitalTwinsPatchProperties'},
    }

    def __init__(self, *, tags=None, identity=None, properties=None, **kwargs) -> None:
        super(DigitalTwinsPatchDescription, self).__init__(**kwargs)
        self.tags = tags
        self.identity = identity
        self.properties = properties
