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
    """Configuration Content for Devices or Modules on Edge Devices.

    :param device_content: Gets or sets device Configurations
    :type device_content: dict[str, object]
    :param modules_content: Gets or sets Module Configurations
    :type modules_content: dict[str, dict[str, object]]
    """

    _attribute_map = {
        'device_content': {'key': 'deviceContent', 'type': '{object}'},
        'modules_content': {'key': 'modulesContent', 'type': '{{object}}'},
    }

    def __init__(self, device_content=None, modules_content=None):
        super(ConfigurationContent, self).__init__()
        self.device_content = device_content
        self.modules_content = modules_content
