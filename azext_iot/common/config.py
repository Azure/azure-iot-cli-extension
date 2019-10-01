# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.constants import CONFIG_KEY_UAMQP_EXT_VERSION, EXTENSION_CONFIG_ROOT_KEY


def get_uamqp_ext_version(config):
    return config.get(EXTENSION_CONFIG_ROOT_KEY, CONFIG_KEY_UAMQP_EXT_VERSION, None)


def update_uamqp_ext_version(config, version):
    return config.set_value(EXTENSION_CONFIG_ROOT_KEY, CONFIG_KEY_UAMQP_EXT_VERSION, version)
