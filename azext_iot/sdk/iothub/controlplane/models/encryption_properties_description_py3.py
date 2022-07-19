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


class EncryptionPropertiesDescription(Model):
    """The encryption properties for the IoT hub.

    :param key_source: The source of the key.
    :type key_source: str
    :param key_vault_properties: The properties of the KeyVault key.
    :type key_vault_properties: list[~service.models.KeyVaultKeyProperties]
    """

    _attribute_map = {
        'key_source': {'key': 'keySource', 'type': 'str'},
        'key_vault_properties': {'key': 'keyVaultProperties', 'type': '[KeyVaultKeyProperties]'},
    }

    def __init__(self, *, key_source: str=None, key_vault_properties=None, **kwargs) -> None:
        super(EncryptionPropertiesDescription, self).__init__(**kwargs)
        self.key_source = key_source
        self.key_vault_properties = key_vault_properties
