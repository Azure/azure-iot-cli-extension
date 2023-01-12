# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""This module defines common values and functions for processing edge device configurations"""

from pathlib import PurePath
from os import getcwd
from typing import Optional, List, Dict, Any
from azext_iot.common.fileops import write_content_to_file
from azext_iot.common.certops import create_self_signed_certificate, load_ca_cert_info
from azext_iot.common.shared import (
    ConfigType,
    DeviceAuthType,
)
from azext_iot.iothub.common import (
    EdgeDevicesConfig,
    EdgeDeviceConfig,
    EdgeContainerAuth,
)
from azext_iot.common.utility import process_json_arg, process_toml_arg, assemble_nargs_to_dict

from azure.cli.core.azclierror import (
    CLIInternalError,
    FileOperationError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)

from azext_iot.operations.hub import _process_config_content
from azext_iot.sdk.iothub.service.models import ConfigurationContent
from knack.log import get_logger

logger = get_logger(__name__)

MAX_DEVICE_SCOPE_RETRIES = 5

DEVICE_CONFIG_SCHEMA_VALID_VERSIONS: Dict[str, Any] = {}

DEVICE_CONFIG_SCHEMA_VALID_VERSIONS["1.0"] = {
    "type": "object",
    "required": ["configVersion", "iotHub", "edgeConfiguration", "edgeDevices"],
    "properties": {
        "configVersion": {"type": "string"},
        "iotHub": {
            "type": "object",
            "required": ["authenticationMethod"],
            "properties": {
                "authenticationMethod": {
                    "type": "string",
                    "enum": ["symmetricKey", "x509Certificate"]
                },
            }
        },
        "certificates": {
            "type": "object",
            "required": ["rootCACertPath", "rootCACertKeyPath"],
            "properties": {
                "rootCACertPath": {"type": "string"},
                "rootCACertKeyPath": {"type": "string"}
            }
        },
        "edgeConfiguration": {
            "type": "object",
            "properties": {
                "templateConfigPath": {"type": "string"},
                "defaultEdgeAgent": {"type": "string"}
            },
            "required": ["defaultEdgeAgent"]
        },
        "edgeDevices": {
            "type": "array",
            "items": {"$ref": "#/$defs/edgeDevice"}
        },
    },
    "$defs": {
        "edgeDevice": {
            "type": "object",
            "properties": {
                "deviceId": {"type": "string"},
                "hostname": {"type": "string"},
                "edgeAgent": {"type": "string"},
                "deployment": {"type": "string"},
                "containerAuth": {
                    "type": "object",
                    "properties": {
                        "serverAddress": {"type": "string"},
                        "username": {"type": "string"},
                        "password": {"type": "string"}
                    }
                },
                "children": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/edgeDevice"},
                    "minItems": 1,
                }
            },
            "required": ["deviceId"]
        }
    }
}

# Edge device TOML default values
DEVICE_CONFIG_TOML = {
    "auto_reprovisioning_mode": "Dynamic",
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

EDGE_SUPPORTED_OS_LINK = "https://aka.ms/iotedge-supported-systems"
EDGE_LINUX_TUTORIAL_LINK = "https://aka.ms/iotedge-provision-linux-device"
EDGE_WINDOWS_TUTORIAL_LINK = "https://aka.ms/iotedge-provision-windows"

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


EDGE_ROOT_CERTIFICATE_SUBJECT = "Azure_IoT_CLI_Extension_Cert"


def create_edge_device_config(
    hub_hostname: str,
    device_id: str,
    auth_method: DeviceAuthType,
    device_config: EdgeDeviceConfig,
    default_edge_agent: str,
    device_config_path: Optional[str] = None,
    device_pk: Optional[str] = None,
    output_path: Optional[str] = None,
):
    # load default device TOML object or custom path
    device_toml = (
        process_toml_arg(device_config_path)
        if device_config_path
        else DEVICE_CONFIG_TOML
    )

    device_toml[
        "trust_bundle_cert"
    ] = f"file:///etc/aziot/certificates/{EDGE_ROOT_CERTIFICATE_FILENAME}"
    # Dynamic is the default auto reprovisioning mode, but respect config settings
    device_toml["auto_reprovisioning_mode"] = getattr(device_toml, "auto_reprovisioning_mode", "Dynamic")

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
        "image": device_config.edge_agent or default_edge_agent or '',
        "auth": {
            "serveraddress": device_config.container_auth.serveraddress,
            "username": device_config.container_auth.username,
            "password": device_config.container_auth.password,
        }
        if device_config.container_auth
        else {},
    }
    if output_path:
        import tomli_w
        write_content_to_file(
            tomli_w.dumps(device_toml),
            output_path,
            "config.toml",
            overwrite=True,
        )
    return device_toml


def process_edge_devices_config_file_content(
    content: dict,
    config_path: Optional[str] = None,
    override_auth_type: Optional[str] = None,
    override_root_cert_path: Optional[str] = None,
    override_root_key_path: Optional[str] = None,
    override_root_password: Optional[str] = None,
    override_default_edge_agent: Optional[str] = None,
    override_device_config_template: Optional[str] = None,
) -> EdgeDevicesConfig:
    """
    Process edge config file schema dictionary
    """

    # Use current directory if no config file path
    config_path = config_path or getcwd()

    # Warn about override values
    for value, name in [
        (override_auth_type, "Authentication Type"),
        (override_root_cert_path, "Root certificate"),
        (override_root_key_path, "Root certificate key"),
        (override_default_edge_agent, "Default edge agent"),
        (override_device_config_template, "Device config template"),
    ]:
        if value:
            logger.info(
                f"Overriding configuration file property `{name}` "
                f"with command argument value: `{value}`"
            )

    version = content.get("configVersion", None)
    if not version:
        raise InvalidArgumentValueError("'configVersion' property missing from device configuration file.")
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    try:
        validate(content, DEVICE_CONFIG_SCHEMA_VALID_VERSIONS[version])
    except ValidationError as err:
        raise InvalidArgumentValueError(f"Invalid devices config file schema:\n{err.message}")

    hub_config = content.get("iotHub", {})
    devices_config = content.get("edgeDevices", [])

    # edge root CA
    root_cert = None
    certificates = content.get("certificates", None)
    if certificates or any(
        [override_root_cert_path, override_root_key_path, override_root_password]
    ):
        root_ca_cert = override_root_cert_path or certificates.get(
            "rootCACertPath", None
        )
        root_ca_key = override_root_key_path or certificates.get(
            "rootCACertKeyPath", None
        )
        if not all([root_ca_cert, root_ca_key]):
            raise InvalidArgumentValueError(
                "Please check your config file to ensure values are provided "
                "for both `rootCACertPath` and `rootCACertKeyPath`."
            )
        root_cert = load_ca_cert_info(
            root_ca_cert, root_ca_key, password=override_root_password
        )
    else:
        root_cert = create_self_signed_certificate(
            subject=EDGE_ROOT_CERTIFICATE_SUBJECT,
            key_size=4096,
            sha_version=256,
            v3_extensions=True
        )

    # device auth
    # default to symmetric key
    device_authentication_method = DeviceAuthType.shared_private_key.value
    auth_value = hub_config.get("authenticationMethod", None)
    if override_auth_type:
        device_authentication_method = override_auth_type
    else:
        device_authentication_method = (
            DeviceAuthType.x509_thumbprint.value
            if auth_value == "x509Certificate"
            else DeviceAuthType.shared_private_key.value
        )

    # edge config
    edge_config = content.get("edgeConfiguration", None)
    if edge_config or any(
        [override_default_edge_agent, override_device_config_template]
    ):
        # do not use path relative to config file if overridden from CLI context
        if override_device_config_template:
            template_config_path = override_device_config_template
        else:
            template_config_path = edge_config.get("templateConfigPath", None)
            if template_config_path:  # relative path to config file to device.toml
                template_config_path = PurePath(config_path, template_config_path).as_posix()

        default_edge_agent = override_default_edge_agent or edge_config.get(
            "defaultEdgeAgent", None
        )
    all_devices = []

    def _process_edge_config_device(device: dict, parent_id=None, parent_hostname=None):
        device_id = device.get("deviceId", None)
        if not device_id:
            raise InvalidArgumentValueError(
                "A device parameter is missing required attribute 'device_id'"
            )
        deployment = device.get("deployment", None)
        if deployment:
            # relative path from config file to deployment.json
            deployment = PurePath(config_path, deployment).as_posix()
            deployment = try_parse_valid_deployment_config(deployment)

        child_devices = device.get("children", [])
        container_auth = device.get("containerAuth", {})
        hostname = device.get("hostname", None)
        edge_agent = device.get("edgeAgent", None)
        device_config = EdgeDeviceConfig(
            device_id=device_id,
            deployment=deployment,
            parent_id=parent_id,
            parent_hostname=parent_hostname,
            container_auth=EdgeContainerAuth(
                serveraddress=container_auth.get("serverAddress", None),
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
    return EdgeDevicesConfig(
        version=version,
        auth_method=device_authentication_method,
        root_cert=root_cert,
        devices=all_devices,
        template_config_path=template_config_path,
        default_edge_agent=default_edge_agent,
    )


def create_edge_device_config_script(
    device_id: str,
    hub_auth: bool = False,
    hostname: Optional[str] = None,
    has_parent: bool = False,
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


def try_parse_valid_deployment_config(deployment_path: str):
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


def process_edge_devices_config_args(
    device_args: List[List[str]],
    auth_type: str,
    default_edge_agent: Optional[str] = None,
    device_config_template: Optional[str] = None,
    root_cert_path: Optional[str] = None,
    root_key_path: Optional[str] = None,
    root_cert_password: Optional[str] = None,
) -> EdgeDevicesConfig:
    # raise error if only key or cert provided
    if (root_cert_path is not None) ^ (root_key_path is not None):
        raise RequiredArgumentMissingError(
            "You must provide a path to both the root cert public and private keys."
        )
    # create cert if one isn't provided
    root_cert = (
        load_ca_cert_info(root_cert_path, root_key_path, root_cert_password)
        if all([root_cert_path, root_key_path])
        else create_self_signed_certificate(
            subject=EDGE_ROOT_CERTIFICATE_SUBJECT,
            key_size=4096,
            sha_version=256,
            v3_extensions=True
        )
    )

    config = EdgeDevicesConfig(
        version="1.0",
        auth_method=(auth_type or DeviceAuthType.shared_private_key.value),
        default_edge_agent=default_edge_agent,
        template_config_path=device_config_template,
        devices=[],
        root_cert=root_cert,
    )
    # Process --device arguments
    all_devices: Dict[str, Dict[str, str]] = {}
    for device_input in device_args:
        # assemble device params from nArgs strings
        device_dict = assemble_nargs_to_dict(device_input)
        device_id = device_dict.get("id", None)
        if not device_id:
            raise InvalidArgumentValueError(
                "A device argument is missing required parameter 'id'"
            )
        if all_devices.get(device_id, None):
            raise InvalidArgumentValueError(
                f"Duplicate deviceId '{device_id}' detected"
            )
        all_devices[device_id] = device_dict

    for device_id in all_devices:
        device_dict = all_devices[device_id]
        deployment = device_dict.get("deployment", None)
        if deployment:
            deployment = try_parse_valid_deployment_config(deployment)
        parent_id = device_dict.get("parent", None)
        parent_hostname = None
        if parent_id:
            parent = all_devices.get(parent_id, {})
            parent_hostname = parent.get("hostname", None)
        hostname = device_dict.get("hostname", None)
        edge_agent = device_dict.get("edge_agent", None)
        container_auth_arg = device_dict.get("container_auth", "{}")
        container_auth_obj = process_json_arg(container_auth_arg)
        container_auth = (
            EdgeContainerAuth(
                serveraddress=container_auth_obj.get("serverAddress", None),
                username=container_auth_obj.get("username", None),
                password=container_auth_obj.get("password", None),
            )
            if container_auth_obj
            else None
        )
        device_config = EdgeDeviceConfig(
            device_id=device_id,
            deployment=deployment,
            parent_id=parent_id,
            hostname=hostname,
            parent_hostname=parent_hostname,
            edge_agent=edge_agent,
            container_auth=container_auth,
        )
        config.devices.append(device_config)
    return config
