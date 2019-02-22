# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os

VERSION = '0.6.2'
EXTENSION_NAME = 'azure-cli-iot-ext'
EXTENSION_ROOT = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CONFIG_ROOT_KEY = 'iotext'
BASE_API_VERSION = '2018-08-30-preview'
METHOD_INVOKE_MAX_TIMEOUT_SEC = 300
METHOD_INVOKE_MIN_TIMEOUT_SEC = 10
MIN_SIM_MSG_INTERVAL = 1
MIN_SIM_MSG_COUNT = 1
SIM_RECEIVE_SLEEP_SEC = 3
DEVICE_DEVICESCOPE_PREFIX = 'ms-azure-iot-edge://'

# (Lib name, minimum version (including), maximum version (excluding))
EVENT_LIB = ('uamqp', '1.0.3', '1.1')

# Config Key's
CONFIG_KEY_UAMQP_EXT_VERSION = 'uamqp_ext_version'
