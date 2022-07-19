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


class SharedAccessSignatureAuthorizationRule(Model):
    """The properties of an IoT hub shared access policy.

    All required parameters must be populated in order to send to Azure.

    :param key_name: Required. The name of the shared access policy.
    :type key_name: str
    :param primary_key: The primary key.
    :type primary_key: str
    :param secondary_key: The secondary key.
    :type secondary_key: str
    :param rights: Required. The permissions assigned to the shared access
     policy. Possible values include: 'RegistryRead', 'RegistryWrite',
     'ServiceConnect', 'DeviceConnect', 'RegistryRead, RegistryWrite',
     'RegistryRead, ServiceConnect', 'RegistryRead, DeviceConnect',
     'RegistryWrite, ServiceConnect', 'RegistryWrite, DeviceConnect',
     'ServiceConnect, DeviceConnect', 'RegistryRead, RegistryWrite,
     ServiceConnect', 'RegistryRead, RegistryWrite, DeviceConnect',
     'RegistryRead, ServiceConnect, DeviceConnect', 'RegistryWrite,
     ServiceConnect, DeviceConnect', 'RegistryRead, RegistryWrite,
     ServiceConnect, DeviceConnect'
    :type rights: str or ~service.models.AccessRights
    """

    _validation = {
        'key_name': {'required': True},
        'rights': {'required': True},
    }

    _attribute_map = {
        'key_name': {'key': 'keyName', 'type': 'str'},
        'primary_key': {'key': 'primaryKey', 'type': 'str'},
        'secondary_key': {'key': 'secondaryKey', 'type': 'str'},
        'rights': {'key': 'rights', 'type': 'AccessRights'},
    }

    def __init__(self, *, key_name: str, rights, primary_key: str=None, secondary_key: str=None, **kwargs) -> None:
        super(SharedAccessSignatureAuthorizationRule, self).__init__(**kwargs)
        self.key_name = key_name
        self.primary_key = primary_key
        self.secondary_key = secondary_key
        self.rights = rights
