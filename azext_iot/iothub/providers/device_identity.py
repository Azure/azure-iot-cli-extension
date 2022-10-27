# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from pathlib import PurePath
from os import getcwd, makedirs
from os.path import exists
from shutil import rmtree
from azext_iot.common.certops import (
    CertInfo,
    create_root_certificate,
    create_self_signed_certificate,
    create_signed_cert,
    load_ca_cert_info,
    make_cert_chain,
)

from azext_iot.common.fileops import tar_directory, write_content_to_file
from azext_iot.constants import (
    DEVICE_CONFIG_TOML,
    DEVICE_README,
    EDGE_DEVICE_BUNDLE_DEFAULT_FOLDER_NAME,
    EDGE_ROOT_CERTIFICATE_FILENAME,
)
from tqdm import tqdm
from time import sleep
from typing import Any, Dict, List, NamedTuple
from knack.log import get_logger
from typing import Optional
from azext_iot._factory import SdkResolver
from azext_iot.common.shared import (
    ConfigType,
    DeviceAuthType,
    SdkType,
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common.utility import (
    create_nested_edge_device_config_script,
    process_json_arg,
    process_toml_content,
    process_yaml_arg,
)
from azext_iot.operations.generic import _execute_query
from azure.cli.core.azclierror import (
    AzureResponseError,
    CLIInternalError,
    FileOperationError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    MutuallyExclusiveArgumentError,
)
from azext_iot.operations.hub import (
    _assemble_device,
    _process_config_content,
)
from azext_iot.sdk.iothub.service.models.configuration_content_py3 import (
    ConfigurationContent,
)
from azext_iot.sdk.iothub.service.models import Device

logger = get_logger(__name__)


# Utility classes for edge config file values and device arguments


class EdgeContainerAuth(NamedTuple):
    serveraddress: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class NestedEdgeDeviceConfig(NamedTuple):
    device_id: str
    deployment: Optional[ConfigurationContent] = None
    config: Optional[Any] = None
    parent_id: Optional[str] = None
    hostname: Optional[str] = None
    parent_hostname: Optional[str] = None
    edge_agent: Optional[str] = None
    container_auth: Optional[EdgeContainerAuth] = None


class NestedEdgeConfig(NamedTuple):
    version: str
    auth_method: DeviceAuthType
    root_cert: CertInfo
    devices: List[NestedEdgeDeviceConfig]
    template_config_path: Optional[str] = None
    default_edge_agent: Optional[str] = None


class DeviceIdentityProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
        login: Optional[str] = None,
        auth_type_dataplane: Optional[str] = None,
    ):
        super(DeviceIdentityProvider, self).__init__(
            cmd=cmd,
            hub_name=hub_name,
            rg=rg,
            login=login,
            auth_type_dataplane=auth_type_dataplane,
        )

        self.hub_resolver = SdkResolver(target=self.target)
        self.service_sdk = self.hub_resolver.get_sdk(SdkType.service_sdk)

    def create_edge_hierarchy(
        self,
        devices: Optional[List[List[str]]] = None,
        config_file: Optional[str] = None,
        visualize: Optional[bool] = False,
        clean: Optional[bool] = False,
        auth_type: Optional[DeviceAuthType] = None,
        root_cert_path: Optional[str] = None,
        root_key_path: Optional[str] = None,
        output_path: Optional[str] = None,
    ):
        from treelib import Tree
        from treelib.exceptions import (
            NodeIDAbsentError,
            LoopError,
            DuplicatedNodeIdError,
        )

        config: NestedEdgeConfig = None

        # configuration for root cert and output directories
        root_cert_name = EDGE_ROOT_CERTIFICATE_FILENAME
        if output_path:
            if not exists(output_path):
                makedirs(output_path)
            cert_output_directory = PurePath(output_path)
        else:
            cert_output_directory = PurePath(getcwd()).joinpath(
                EDGE_DEVICE_BUNDLE_DEFAULT_FOLDER_NAME
            )
            makedirs(cert_output_directory, exist_ok=True)

        # If user has provided a path to a configuration file
        if config_file:
            # Cannot process both config file and --devices nargs*
            if devices:
                raise MutuallyExclusiveArgumentError(
                    "Please either use a --config-file argument or inline --device arguments, both were provided."
                )
            # if config file is specified, warn user that auth_type and cert info should be set in the file
            if any([auth_type, root_cert_path, root_key_path]):
                raise MutuallyExclusiveArgumentError(
                    "If using a --config-file argument, please set device auth and root certificate parameters in that file."
                )

            config_content = None
            # Process Edge Config file into object dictionary
            if config_file.endswith((".yaml", ".yml")):
                config_content = process_yaml_arg(config_file)
            elif config_file.endswith(".json"):
                config_content = process_json_arg(config_file)
            else:
                raise InvalidArgumentValueError("Config file must be JSON or YAML")

            config = self._process_nested_edge_config_file_content(config_content)
        elif devices:
            # raise error if only key or cert provided
            if (root_cert_path is not None) ^ (root_key_path is not None):
                raise RequiredArgumentMissingError(
                    "You must provide a path to both the root cert public and private keys."
                )
            # create cert if one isn't provided
            root_cert = (
                load_ca_cert_info(root_cert_path, root_key_path)
                if all([root_cert_path, root_key_path])
                else create_root_certificate()
            )

            config = NestedEdgeConfig(
                version="1.0",
                auth_method=auth_type or DeviceAuthType.shared_private_key.value,
                devices=[],
                root_cert=root_cert,
            )
            # Process --device arguments
            # Parse each device and add to the tree
            for device_input in devices:
                # assemble device params from nArgs strings
                device_params = self.assemble_nargs_to_dict(device_input)
                device_id = device_params.get("id", None)
                if not device_id:
                    raise InvalidArgumentValueError(
                        "A device argument is missing required parameter 'id'"
                    )
                deployment = device_params.get("deployment", None)
                if deployment:
                    deployment = self._try_parse_valid_deployment_config(deployment)
                parent_id = device_params.get("parent", None)
                hostname = device_params.get("hostname", None)
                edge_agent = device_params.get("edge_agent", None)
                container_auth_arg = device_params.get("container_auth", '{}')
                container_auth_obj = process_json_arg(container_auth_arg)
                container_auth = EdgeContainerAuth(
                    serveraddress=container_auth_obj.get("serveraddress", None),
                    username=container_auth_obj.get("username", None),
                    password=container_auth_obj.get("password", None),
                ) if container_auth_obj else None

                device_config = NestedEdgeDeviceConfig(
                    device_id=device_id,
                    deployment=deployment,
                    parent_id=parent_id,
                    hostname=hostname,
                    edge_agent=edge_agent,
                    container_auth=container_auth
                )
                config.devices.append(device_config)

        if not config or not len(config.devices):
            raise InvalidArgumentValueError(
                "No devices found in input. "
                "Please check your input arguments or config file and try the command again"
            )
        tree = Tree()
        tree_root_node_id = "|root|"
        tree.create_node("Devices", tree_root_node_id)
        hub_cert_auth = config.auth_method == DeviceAuthType.x509_ca.value

        # dict of device parents by ID
        device_to_parent_dict: Dict[str, str] = {}
        # device configs by id
        device_config_dict: Dict[str, NestedEdgeConfig] = {}
        for device_config in config.devices:
            device_config_dict[device_config.device_id] = device_config

        # first pass to create devices in flat tree
        config_devices_iterator = (
            tqdm(
                config.devices,
                desc="Creating device structure and certificates",
            )
            if visualize
            else config.devices
        )
        for device_config in config_devices_iterator:
            device_id = device_config.device_id
            # add to flat tree
            try:
                tree.create_node(device_id, device_id, parent=tree_root_node_id)
            except DuplicatedNodeIdError:
                raise InvalidArgumentValueError(
                    f"Duplicate deviceId '{device_id}' detected"
                )

        # second pass to move nodes and check hierarchy
        for device_config in config.devices:
            device_id = device_config.device_id

            # Move nodes to their correct parents, track device->parent in dict
            device_parent = device_config.parent_id or tree_root_node_id
            if device_parent != tree_root_node_id:
                device_to_parent_dict[device_id] = device_parent
            try:
                tree.update_node(device_id, data=device_parent)
                tree.move_node(device_id, device_parent)
            except NodeIDAbsentError:
                raise InvalidArgumentValueError(
                    f"Error building device hierarchy, missing parent '{device_parent}'"
                )
            except LoopError:
                raise InvalidArgumentValueError(
                    "Error building device hierarchy, found a loop between "
                    f"devices '{device_id}' and '{device_parent}'."
                )

        # Show the tree
        if visualize:
            tree.show()

        # Delete or verify existing device IDs
        query_args = ["SELECT deviceId FROM devices"]
        query_method = self.service_sdk.query.get_twins
        existing_devices = _execute_query(query_args, query_method)
        existing_device_ids = list(map(lambda x: x["deviceId"], existing_devices))

        # Clear devices if necessary
        if clean and len(existing_device_ids):
            delete_iterator = (
                tqdm(existing_device_ids, "Deleting existing device identities")
                if visualize
                else existing_device_ids
            )
            self.delete_device_identities(delete_iterator, confirm=True)
        else:
            # If not cleaning the hub, ensure no duplicate device ids
            duplicates = list(
                filter(lambda id: id in device_config_dict, existing_device_ids)
            )
            if any(duplicates):
                raise InvalidArgumentValueError(
                    f"The following devices already exist on hub '{self.hub_name}': {duplicates}. "
                    "To clear all devices before creating the hierarchy, please utilize the `--clean` switch."
                )

        # Create all devices and configs
        device_iterator = (
            tqdm(config.devices, desc="Creating device identities and configs")
            if visualize
            else config.devices
        )
        for device in device_iterator:
            device_id = device.device_id

            device_cert_output_directory = cert_output_directory.joinpath(device_id)
            # if the device folder already exists, remove it
            if exists(device_cert_output_directory):
                rmtree(device_cert_output_directory)
            # create fresh device folder
            makedirs(device_cert_output_directory)

            # write root cert to device directory
            write_content_to_file(
                content=config.root_cert["certificate"],
                destination=device_cert_output_directory,
                file_name=root_cert_name,
            )
            # signed device cert
            signed_device_cert = create_signed_cert(
                subject=f"{device_id}.deviceca",
                ca_public=config.root_cert["certificate"],
                ca_private=config.root_cert["privateKey"],
                cert_output_dir=device_cert_output_directory,
                cert_file=device_id,
            )
            # full-chain cert
            make_cert_chain(
                certs=[
                    signed_device_cert["certificate"],
                    config.root_cert["certificate"],
                ],
                output_dir=device_cert_output_directory,
                output_file=f"{device_id}.full-chain.cert.pem",
            )
            pk = None
            sk = None
            # if using x509 device auth
            if hub_cert_auth:
                # hub auth cert for device
                device_hub_cert = create_self_signed_certificate(
                    subject=device_id,
                    valid_days=365,
                    cert_output_dir=device_cert_output_directory,
                    file_prefix=f"{device_id}.hub-auth",
                )
                pk = signed_device_cert["thumbprint"]
                sk = device_hub_cert["thumbprint"]

            # create device object for service
            assembled_device = _assemble_device(
                is_update=False,
                device_id=device_id,
                auth_method=config.auth_method,
                pk=pk,
                sk=sk,
                edge_enabled=True,
            )
            # create device identity
            device_result: Device = self.service_sdk.devices.create_or_update_identity(
                id=device_id, device=assembled_device
            )
            # write install script
            write_content_to_file(
                content=create_nested_edge_device_config_script(
                    device_id=device_id,
                    hub_auth=hub_cert_auth,
                    hostname=device_config.hostname,
                    has_parent=(device_config.parent_id is not None),
                    parent_hostname=device_config.parent_hostname,
                ),
                destination=device_cert_output_directory,
                file_name="install.sh",
                overwrite=True,
            )
            # write device readme
            write_content_to_file(
                content=DEVICE_README,
                destination=device_cert_output_directory,
                file_name="README.md",
                overwrite=True,
            )
            device_pk = None
            if not hub_cert_auth:
                device_keys = device_result.authentication.symmetric_key
                device_pk = device_keys.primary_key if device_keys else None
            device_cert_output_directory = cert_output_directory.joinpath(device_id)
            self.create_edge_device_config(
                device_id=device_id,
                auth_method=config.auth_method,
                default_edge_agent=config.default_edge_agent,
                device_config=device_config_dict[device_id],
                device_config_path=config.template_config_path,
                device_pk=device_pk,
                output_path=device_cert_output_directory,
            )

            # zip up
            tar_directory(
                target_directory=device_cert_output_directory,
                tarfile_path=cert_output_directory,
                tarfile_name=device_id,
                overwrite=True,
            )

            # delete non-tarred folder
            rmtree(device_cert_output_directory)

        # Give device registry a chance to catch up
        sleep(1)

        # Get all device ids and scopes (inconsistent timing, hence sleep)
        query_args = ["SELECT deviceId, deviceScope FROM devices"]
        query_method = self.service_sdk.query.get_twins
        all_hub_devices = _execute_query(query_args, query_method)

        # Throw an error if we don't get the same number of desired devices back
        if len(all_hub_devices) < len(config.devices):
            raise AzureResponseError(
                "An error occurred - Failed to fetch device scopes for all devices"
            )

        # set all device scopes
        scope_dict: Dict[str, str] = {}
        for device in all_hub_devices:
            id = device["deviceId"]
            if device_config_dict.get(id, None):
                scope_dict[id] = device["deviceScope"]

        # Set parent / child relationships
        device_to_parent_iterator = (
            tqdm(device_to_parent_dict, desc="Setting device parents")
            if visualize
            else device_to_parent_dict
        )
        for device_id in device_to_parent_iterator:
            # get device properties
            device = self.service_sdk.devices.get_identity(id=device_id)
            parent_id = device_to_parent_dict[device_id]
            parent_scope = scope_dict[parent_id]
            # set new parent scope
            device.parent_scopes = [parent_scope]
            # update device
            self.service_sdk.devices.create_or_update_identity(
                id=device_id, device=device, if_match="*"
            )

        # update edge config / set-modules
        devices_config_iterator = (
            tqdm(config.devices, desc="Setting edge module content")
            if visualize
            else config.devices
        )
        for device_config in devices_config_iterator:
            device_id = device_config.device_id
            deployment_content = device_config.deployment
            if deployment_content:
                self.service_sdk.configuration.apply_on_edge_device(
                    id=device_id, content=deployment_content
                )

    def _process_nested_edge_config_file_content(
        self, content: dict
    ) -> NestedEdgeConfig:
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

        def _process_edge_config_device(
            device: dict, parent_id=None, parent_hostname=None
        ):
            device_id = device.get("device_id", None)
            if not device_id:
                raise InvalidArgumentValueError(
                    "A device parameter is missing required attribute 'device_id'"
                )
            deployment = device.get("deployment", None)
            if deployment:
                deployment = self._try_parse_valid_deployment_config(deployment)

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
                ) if container_auth else None,
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

    def assemble_nargs_to_dict(self, hash_list: List[str]) -> Dict[str, str]:
        result = {}
        if not hash_list:
            return result
        for hash in hash_list:
            if "=" not in hash:
                logger.warning("Skipping processing of '%s', input format is key=value | key='value value'.", hash)
                continue
            split_hash = hash.split("=", 1)
            result[split_hash[0]] = split_hash[1]
        for key in result:
            if not result.get(key):
                logger.warning("No value assigned to key '%s', input format is key=value | key='value value'.", key)
        return result

    # TODO - Unit test
    def delete_device_identities(
        self, device_ids: List[str], confirm: Optional[bool] = False
    ):
        for id in device_ids:
            try:
                self.service_sdk.devices.delete_identity(id=id, if_match="*")
            except Exception as err:
                raise AzureResponseError(err)
        if confirm:
            existing_devices = self.service_sdk.devices.get_devices()
            if len(existing_devices):
                raise AzureResponseError(
                    "An error has occurred - Not all devices were deleted."
                )

    def _try_parse_valid_deployment_config(self, deployment_path):
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

    def create_edge_device_config(
        self,
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
            "iothub_hostname": self.target["entity"],
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
