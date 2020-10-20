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


class ConfigurationContent(Model):
    """The configuration content for devices or modules on edge devices.

    :param device_content: The device configuration content.
    :type device_content: dict[str, object]
    :param modules_content: The modules configuration content.
    :type modules_content: dict[str, dict[str, object]]
    :param module_content: The module configuration content.
    :type module_content: dict[str, object]
    """

    _attribute_map = {
        'device_content': {'key': 'deviceContent', 'type': '{object}'},
        'modules_content': {'key': 'modulesContent', 'type': '{{object}}'},
        'module_content': {'key': 'moduleContent', 'type': '{object}'},
    }

    def __init__(self, **kwargs):
        super(ConfigurationContent, self).__init__(**kwargs)
        self.device_content = kwargs.get('device_content', None)
        self.modules_content = kwargs.get('modules_content', None)
        self.module_content = kwargs.get('module_content', None)
