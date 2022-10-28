# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""This module defines common values for IoT Hub modules"""

from typing import Optional
from azext_iot.common.fileops import write_content_to_file
from azext_iot.common.certops import create_root_certificate, load_ca_cert_info
from azext_iot.common.shared import (
    ConfigType,
    DeviceAuthType,
    NestedEdgeConfig,
    NestedEdgeDeviceConfig,
    EdgeContainerAuth,
)
from azext_iot.common.utility import process_json_arg, process_toml_content

from azure.cli.core.azclierror import (
    CLIInternalError,
    FileOperationError,
    InvalidArgumentValueError,
)

from azext_iot.operations.hub import _process_config_content
from azext_iot.sdk.iothub.service.models import ConfigurationContent
from knack.log import get_logger

logger = get_logger(__name__)

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

EDGE_SUPPORTED_OS_LINK = (
    "https://docs.microsoft.com/en-us/azure/iot-edge/support?view=iotedge-2020-11"
)

EDGE_LINUX_TUTORIAL_LINK = (
    "https://learn.microsoft.com/en-us/azure/iot-edge/how-to-provision-single-device-linux-symmetric"
)

EDGE_WINDOWS_TUTORIAL_LINK = (
    "https://learn.microsoft.com/en-us/azure/iot-edge/how-to-provision-single-device-linux-on-windows-symmetric"
)

DEVICE_README = f"""
# Prerequisites
Each device must have IoT Edge (must be v1.2 or later) installed.
Pick a [supported OS]({EDGE_SUPPORTED_OS_LINK}) and follow the corresponding tutorial to install Azure IoT Edge:
    - [Linux on Windows]({EDGE_WINDOWS_TUTORIAL_LINK})
    - [Linux]({EDGE_LINUX_TUTORIAL_LINK})

# Steps

1. Copy the bundle for each created device (device_id.tgz) onto the device.
2. Extract the bundle file by running following command:

```Extract
    tar zxvf ~/<PATH_TO_BUNDLE>/[[device-id]].tgz
```

3. Run the install script:

```Run
    sudo bash ./install.sh
```

4. If hostnames were not provided in the configuration file, the script will prompt for hostnames.
    - Follow the prompt by entering the device and/or parent hostname (FQDN or IP address).
    - On the parent device, it will prompt for its own hostname.
    - On a child device, it may prompt the hostname of both the child and parent devices.

"""


def create_edge_device_config(
    hub_hostname: str,
    device_id: str,
    auth_method: DeviceAuthType,
    device_config: NestedEdgeDeviceConfig,
    default_edge_agent: str,
    device_config_path: Optional[str] = None,
    device_pk: Optional[str] = None,
    output_path: Optional[str] = None,
):
    # load default device TOML object or custom path
    device_toml = (
        process_toml_content(device_config_path)
        if device_config_path
        else DEVICE_CONFIG_TOML
    )

    device_toml[
        "trust_bundle_cert"
    ] = f"file:///etc/aziot/certificates/{EDGE_ROOT_CERTIFICATE_FILENAME}"
    # Dynamic, AlwaysOnStartup, OnErrorOnly
    device_toml["auto_reprovisioning_mode"] = "Dynamic"
    device_toml["hostname"] = (
        device_config.hostname if device_config.hostname else "{{HOSTNAME}}"
    )
    if device_config.parent_id:
        device_toml["parent_hostname"] = (
            device_config.parent_hostname
            if device_config.parent_hostname
            else "{{PARENT_HOSTNAME}}"
        )
    device_toml["provisioning"] = {
        "device_id": device_id,
        "iothub_hostname": hub_hostname,
        "source": "manual",
        "authentication": {"device_id_pk": {"value": device_pk}, "method": "sas"}
        if auth_method == DeviceAuthType.shared_private_key.value
        else {
            "method": "x509",
            "identity_cert": f"file:///etc/aziot/certificates/{device_id}.hub-auth-cert.pem",
            "identity_pk": f"file:///etc/aziot/certificates/{device_id}.hub-auth-key.pem",
        },
    }
    device_toml["edge_ca"] = {
        "cert": f"file:///etc/aziot/certificates/{device_id}.full-chain.cert.pem",
        "pk": f"file:///etc/aziot/certificates/{device_id}.key.pem",
    }
    device_toml["agent"]["config"] = {
        "image": device_config.edge_agent or default_edge_agent,
        "auth": {
            "serveraddress": device_config.container_auth.serveraddress,
            "username": device_config.container_auth.username,
            "password": device_config.container_auth.password,
        }
        if device_config.container_auth
        else {},
    }
    if output_path:
        import toml

        write_content_to_file(
            toml.dumps(device_toml),
            output_path,
            "config.toml",
            overwrite=True,
        )
    return device_toml


def process_nested_edge_config_file_content(content: dict) -> NestedEdgeConfig:
    """
    Process edge config file schema dictionary
    """
    # TODO - version / schema validation
    version = content.get("config_version", None)
    hub_config = content.get("iothub", None)
    devices_config = content.get("edgedevices", [])
    for check, err in [
        (version, "No schema version specified in configuration file"),
        (hub_config, "No `iothub` properties specified in configuration file")
        # (len(devices_config), "No devices specified in configuration file")
    ]:
        if not check:
            raise InvalidArgumentValueError(err)

    # edge root CA
    root_cert = None
    certificates = content.get("certificates", None)
    if certificates:
        root_ca_cert = certificates.get("root_ca_cert_path", None)
        root_ca_key = certificates.get("root_ca_cert_key_path", None)
        if not all([root_ca_cert, root_ca_key]):
            raise InvalidArgumentValueError(
                "Please check your config file to ensure values are provided "
                "for both `root_ca_cert_path` and `root_ca_cert_key_path`."
            )
        root_cert = load_ca_cert_info(root_ca_cert, root_ca_key)
    else:
        root_cert = create_root_certificate()

    # device auth
    auth_value = hub_config["authentication_method"]
    if auth_value not in ["symmetric_key", "x509_certificate"]:
        raise InvalidArgumentValueError(
            "Invalid authentication_method in edge config file, must be either symmetric_key or x509_certificate"
        )
    device_authentication_method = (
        DeviceAuthType.shared_private_key.value
        if auth_value == "symmetric_key"
        else DeviceAuthType.x509_ca.value
    )

    # edge config
    edge_config = content.get("configuration", None)
    if edge_config:
        template_config_path = edge_config.get("template_config_path", None)
        default_edge_agent = edge_config.get("default_edge_agent", None)
    all_devices = []

    def _process_edge_config_device(device: dict, parent_id=None, parent_hostname=None):
        device_id = device.get("device_id", None)
        if not device_id:
            raise InvalidArgumentValueError(
                "A device parameter is missing required attribute 'device_id'"
            )
        deployment = device.get("deployment", None)
        if deployment:
            deployment = try_parse_valid_deployment_config(deployment)

        child_devices = device.get("child", [])
        container_auth = device.get("container_auth", {})
        hostname = device.get("hostname", None)
        edge_agent = device.get("edge_agent", None)
        device_config = NestedEdgeDeviceConfig(
            device_id=device_id,
            deployment=deployment,
            parent_id=parent_id,
            parent_hostname=parent_hostname,
            container_auth=EdgeContainerAuth(
                serveraddress=container_auth.get("serveraddress", None),
                username=container_auth.get("username", None),
                password=container_auth.get("password", None),
            )
            if container_auth
            else None,
            hostname=hostname,
            edge_agent=edge_agent,
        )
        all_devices.append(device_config)
        for child_device in child_devices:
            _process_edge_config_device(
                child_device, parent_id=device_id, parent_hostname=hostname
            )

    for device in devices_config:
        _process_edge_config_device(device)
    return NestedEdgeConfig(
        version=version,
        auth_method=device_authentication_method,
        root_cert=root_cert,
        devices=all_devices,
        template_config_path=template_config_path,
        default_edge_agent=default_edge_agent,
    )


def create_nested_edge_device_config_script(
    device_id: str,
    hub_auth: Optional[bool] = False,
    hostname: Optional[str] = None,
    has_parent: Optional[bool] = False,
    parent_hostname: Optional[str] = None,
):
    return "\n".join(
        [EDGE_CONFIG_SCRIPT_HEADERS.format(device_id)]
        + ([EDGE_CONFIG_SCRIPT_HOSTNAME] if not hostname else [])
        + (
            [EDGE_CONFIG_SCRIPT_PARENT_HOSTNAME]
            if (has_parent and not parent_hostname)
            else []
        )
        + [EDGE_CONFIG_SCRIPT_CA_CERTS]
        + ([EDGE_CONFIG_SCRIPT_HUB_AUTH_CERTS] if hub_auth else [])
        + [EDGE_CONFIG_SCRIPT_APPLY]
    )


def try_parse_valid_deployment_config(deployment_path):
    try:
        deployment_content = process_json_arg(
            deployment_path, argument_name="deployment"
        )
        processed_content = _process_config_content(
            deployment_content, config_type=ConfigType.edge
        )
        return ConfigurationContent(**processed_content)
    except CLIInternalError:
        raise FileOperationError(
            f"Please ensure a deployment file exists at path: '{deployment_path}'"
        )
    except Exception as ex:
        logger.warning(f"Error processing config file at '{deployment_path}'")
        raise InvalidArgumentValueError(ex)
