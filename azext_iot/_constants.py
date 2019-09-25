# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os

VERSION = "0.8.3"
EXTENSION_NAME = "azure-iot"
EXTENSION_ROOT = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CONFIG_ROOT_KEY = "iotext"
EDGE_DEPLOYMENT_SCHEMA_2_PATH = os.path.join(EXTENSION_ROOT, 'assets', 'edge-deploy-2.0.schema.json')
BASE_API_VERSION = "2018-08-30-preview"
METHOD_INVOKE_MAX_TIMEOUT_SEC = 300
METHOD_INVOKE_MIN_TIMEOUT_SEC = 10
MIN_SIM_MSG_INTERVAL = 1
MIN_SIM_MSG_COUNT = 1
SIM_RECEIVE_SLEEP_SEC = 3
PNP_API_VERSION = "2019-07-01-preview"
PNP_ENDPOINT = "https://provider.azureiotrepository.com"
PNP_REPO_ENDPOINT = "https://repo.azureiotrepository.com"
DEVICE_DEVICESCOPE_PREFIX = "ms-azure-iot-edge://"
TRACING_PROPERTY = "azureiot*com^dtracing^1"
TRACING_ALLOWED_FOR_LOCATION = ("northeurope", "westus2", "west us 2", "southeastasia")
TRACING_ALLOWED_FOR_SKU = "standard"

# (Lib name, minimum version (including), maximum version (excluding))
EVENT_LIB = ("uamqp", "1.0.3", "1.1")

# Config Key's
CONFIG_KEY_UAMQP_EXT_VERSION = "uamqp_ext_version"
