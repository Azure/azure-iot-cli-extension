# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""This module defines constants for use across the CLI extension package"""

import os

VERSION = "0.16.1"
EXTENSION_NAME = "azure-iot"
EXTENSION_ROOT = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CONFIG_ROOT_KEY = "iotext"
EDGE_DEPLOYMENT_ROOT_SCHEMAS_PATH = os.path.join(EXTENSION_ROOT, "assets")
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
DEVICE_DEVICESCOPE_PREFIX = "ms-azure-iot-edge://"
TRACING_PROPERTY = "azureiot*com^dtracing^1"
TRACING_ALLOWED_FOR_LOCATION = ("northeurope", "westus2", "southeastasia")
TRACING_ALLOWED_FOR_SKU = "standard"
USER_AGENT = "IoTPlatformCliExtension/{}".format(VERSION)
IOTHUB_RESOURCE_ID = "https://iothubs.azure.net"
IOTDPS_RESOURCE_ID = "https://azure-devices-provisioning.net"
DIGITALTWINS_RESOURCE_ID = "https://digitaltwins.azure.net"
IOTDPS_PROVISIONING_HOST = "global.azure-devices-provisioning.net"
DEVICETWIN_POLLING_INTERVAL_SEC = 10
DEVICETWIN_MONITOR_TIME_SEC = 15
# (Lib name, minimum version (including), maximum version (excluding))
EVENT_LIB = ("uamqp", "1.2", "1.3")
PNP_DTDLV2_COMPONENT_MARKER = "__t"

# Initial Track 2 SDK version for IoT Hub
IOTHUB_MGMT_SDK_PACKAGE_NAME = "azure-mgmt-iothub"
IOTHUB_TRACK_2_SDK_MIN_VERSION = "2.0.0"

# Initial Track 2 SDK version for DPS
IOTDPS_MGMT_SDK_PACKAGE_NAME = "azure-mgmt-iothubprovisioningservice"
IOTDPS_TRACK_2_SDK_MIN_VERSION = "1.0.0"

IMMUTABLE_DEVICE_IDENTITY_FIELDS = ["cloudToDeviceMessageCount", "configurations", "deviceEtag", "deviceScope",
                                    "lastActivityTime", "modelId", "parentScopes", "statusUpdateTime", "etag", "version"]
IMMUTABLE_MODULE_IDENTITY_FIELDS = ["connection_state_updated_time", "last_activity_time", "cloud_to_device_message_count",
                                    "etag"]
IMMUTABLE_MODULE_TWIN_FIELDS = ["deviceEtag", "lastActivityTime", "etag", "version", "cloudToDeviceMessageCount",
                                "statusUpdateTime"]
