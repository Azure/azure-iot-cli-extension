# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""This module defines constants for use across the CLI extension package"""

import os

VERSION = "0.10.0"
EXTENSION_NAME = "azure-iot"
EXTENSION_ROOT = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CONFIG_ROOT_KEY = "iotext"
EDGE_DEPLOYMENT_SCHEMA_2_PATH = os.path.join(
    EXTENSION_ROOT, "assets", "edge-deploy-2.0.schema.json"
)
BASE_API_VERSION = "2018-08-30-preview"
BASE_MQTT_API_VERSION = "2018-06-30"
MESSAGING_HTTP_C2D_SYSTEM_PROPERTIES = [
    "iothub-messageid",
    "iothub-correlationid",
    "iothub-sequencenumber",
    "iothub-to",
    "iothub-userid",
    "iothub-ack",
    "iothub-expiry",
    "iothub-deliverycount",
    "iothub-enqueuedtime",
    "ContentType",
    "ContentEncoding",
]
METHOD_INVOKE_MAX_TIMEOUT_SEC = 300
METHOD_INVOKE_MIN_TIMEOUT_SEC = 10
MIN_SIM_MSG_INTERVAL = 1
MIN_SIM_MSG_COUNT = 1
SIM_RECEIVE_SLEEP_SEC = 3
CENTRAL_ENDPOINT = "azureiotcentral.com"
PNP_API_VERSION = "2020-05-01-preview"
PNP_ENDPOINT = "azureiotrepository.com"
PNP_TENANT_RESOURCE_ID = "822c8694-ad95-4735-9c55-256f7db2f9b4"
DEVICE_DEVICESCOPE_PREFIX = "ms-azure-iot-edge://"
TRACING_PROPERTY = "azureiot*com^dtracing^1"
TRACING_ALLOWED_FOR_LOCATION = ("northeurope", "westus2", "west us 2", "southeastasia")
TRACING_ALLOWED_FOR_SKU = "standard"
USER_AGENT = "IoTPlatformCliExtension/{}".format(VERSION)
DIGITALTWINS_RESOURCE_ID = "https://digitaltwins.azure.net"
DEVICETWIN_POLLING_INTERVAL_SEC = 10
DEVICETWIN_MONITOR_TIME_SEC = 15
# (Lib name, minimum version (including), maximum version (excluding))
EVENT_LIB = ("uamqp", "1.2", "1.3")
CENTRAL_PNP_INTERFACE_PREFIX = "$iotin:"

# Config Key's
CONFIG_KEY_UAMQP_EXT_VERSION = "uamqp_ext_version"
