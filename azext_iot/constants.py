# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""This module defines constants for use across the CLI extension package"""

import os

VERSION = "0.17.3"
EXTENSION_NAME = "azure-iot"
EXTENSION_ROOT = os.path.dirname(os.path.abspath(__file__))
EXTENSION_CONFIG_ROOT_KEY = "iotext"
INTERNAL_AZURE_CORE_NAMESPACE: str = "azext_iot_internal.azure.core"
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

# Edge device TOML default values
DEVICE_CONFIG_TOML = {
    "hostname": "",
    "provisioning": {
        "device_id": "",
        "iothub_hostname": "",
        "source": "manual",
        "authentication": {
            "device_id_pk": "",
            "method": "sas",
            "trust_bundle_cert": "",
        },
    },
    "edge_ca": {"cert": "file:///", "pk": "file:///"},
    "agent": {"config": {"image": ""}, "name": "edgeAgent", "type": "docker"},
    "connect": {
        "management_uri": "unix:///var/run/iotedge/mgmt.sock",
        "workload_uri": "unix:///var/run/iotedge/workload.sock",
    },
    "listen": {
        "management_uri": "fd://aziot-edged.mgmt.socket",
        "workload_uri": "fd://aziot-edged.workload.socket",
    },
    "moby_runtime": {"network": "azure-iot-edge", "uri": "unix:///var/run/docker.sock"},
}

EDGE_ROOT_CERTIFICATE_FILENAME = "iotedge_config_cli_root.pem"

EDGE_DEVICE_BUNDLE_DEFAULT_FOLDER_NAME = "device_bundles"

EDGE_CONFIG_SCRIPT_HEADERS = """
# This script will attempt to configure a pre-installed iotedge as a nested node.
# It must be run as sudo, and will modify the ca

device_id="{}"
cp config.toml /etc/aziot/config.toml
"""
EDGE_CONFIG_SCRIPT_HOSTNAME = """
# ======================= Set Hostname =======================================

read -p "Enter the hostname to use: " hostname
if [ -z "$hostname" ]
then
    echo "Invalid hostname $hostname"
    exit 1
fi

sed -i "s/{{HOSTNAME}}/$hostname/" /etc/aziot/config.toml
"""
EDGE_CONFIG_SCRIPT_PARENT_HOSTNAME = """
# ======================= Set Parent Hostname =======================================

read -p "Enter the parent hostname to use: " parent_hostname
if [ -z "$parent_hostname" ]
then
    echo "Invalid parent hostname $parent_hostname"
    exit 1
fi

sed -i "s/{{PARENT_HOSTNAME}}/$parent_hostname/" /etc/aziot/config.toml
"""
EDGE_CONFIG_SCRIPT_CA_CERTS = f"""
# ======================= Install nested root CA =======================================
if [ -f /etc/os-release ]
then
        . /etc/os-release
        if [[ "$NAME" == "Common Base Linux Mariner"* ]];
        then
                cp {EDGE_ROOT_CERTIFICATE_FILENAME} /etc/pki/ca-trust/source/anchors/{EDGE_ROOT_CERTIFICATE_FILENAME}.crt
                update-ca-trust
        else
                cp {EDGE_ROOT_CERTIFICATE_FILENAME} /usr/local/share/ca-certificates/{EDGE_ROOT_CERTIFICATE_FILENAME}.crt
                update-ca-certificates
        fi
else
        cp {EDGE_ROOT_CERTIFICATE_FILENAME} /usr/local/share/ca-certificates/{EDGE_ROOT_CERTIFICATE_FILENAME}.crt
        update-ca-certificates
fi

systemctl restart docker

# ======================= Copy device certs  =======================================
cert_dir="/etc/aziot/certificates"
mkdir -p $cert_dir
cp "{EDGE_ROOT_CERTIFICATE_FILENAME}" "$cert_dir/{EDGE_ROOT_CERTIFICATE_FILENAME}"
cp "$device_id.full-chain.cert.pem" "$cert_dir/$device_id.full-chain.cert.pem"
cp "$device_id.key.pem" "$cert_dir/$device_id.key.pem"
"""
EDGE_CONFIG_SCRIPT_HUB_AUTH_CERTS = """
# ======================= Copy hub auth certs  =======================================
cert_dir="/etc/aziot/certificates"
mkdir -p $cert_dir
cp "$device_id.hub-auth-cert.pem" "$cert_dir/$device_id.hub-auth-cert.pem"
cp "$device_id.hub-auth-key.pem" "$cert_dir/$device_id.hub-auth-key.pem"
"""
EDGE_CONFIG_SCRIPT_APPLY = """
# ======================= Read User Input =======================================
iotedge config apply -c /etc/aziot/config.toml

echo "To check the edge runtime status, run 'iotedge system status'. To validate the configuration, run 'sudo iotedge check'"
"""

DEVICE_README = """
# Prerequisites
Each device must have IoT Edge (must be v1.2 or later) installed. Pick the [supported OS](https://docs.microsoft.com/en-us/azure/iot-edge/support?view=iotedge-2020-11) and follow the [tutorial](https://docs.microsoft.com/en-us/azure/iot-edge/support?view=iotedge-2020-11) to install Azure IoT Edge.

# Steps

1. After install and configure IoT Edge to Azure IoT Hub or Azure IoT Central, copy the zip file for each device created, named [[device-id]].zip. 
2. Transfer each zip to its respective device. A good option for this is to use [scp](https://man7.org/linux/man-pages/man1/scp.1.html).
3. Unzip the zip file by running following commands

```Unzip
    sudo apt install zip
    unzip ~/<PATH_TO_CONFIGURATION_BUNDLE>/<CONFIGURATION_BUNDLE>.zip
```
4. Run the script
```Run
    sudo ./install.sh
```
5. If the hostname was not provided in the configuration file, it will prompt for hostname. Follow the prompt by entering the hostname (FQDN or IP address). On the parent device, it may prompt its own hostname and on the child deivce, it may prompt the hostname of both the child and parent device.

"""
