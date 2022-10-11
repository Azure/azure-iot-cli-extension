# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from pathlib import PurePath
from os import getcwd, makedirs
from azext_iot.common.certops import (
    CertInfo,
    create_edge_root_ca_certificate,
    create_self_signed_certificate,
    create_signed_device_cert,
    load_ca_cert_info,
    make_cert_chain,
)
from azext_iot.constants import DEVICE_CONFIG_TOML
from tqdm import tqdm
from time import sleep
from typing import Dict, List, NamedTuple
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
    deployment: ConfigurationContent
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

    # TODO - add input param for device auth type
    # TODO - add input param for root cert and key
    # TODO - add input param for cert output directory
    # TODO - create device TOML
    def create_edge_hierarchy(
        self,
        devices: Optional[List[List[str]]] = None,
        config_file: Optional[str] = None,
        visualize: Optional[bool] = False,
        clean: Optional[bool] = False,
    ):
        """
        Creates a nested edge hierarchy of devices

        Parameters
        ----------
            devices : List[List[str]]
                List of [List of device creation parameters]
            config_file : str
                Path to nested edge config file
            clean : bool
                Whether to delete all devices in hub before creating new devices.
            visualize: bool
                Whether to show a visualization of hierarchy and operation progress.
        """
        from treelib import Tree
        from treelib.exceptions import (
            NodeIDAbsentError,
            LoopError,
            DuplicatedNodeIdError,
        )

        config: NestedEdgeConfig = None
        cert_output_directory = PurePath.joinpath(
            PurePath(getcwd()), "device_certificates"
        )
        root_cert_name = "iotedge_config_cli_root"

        # If user has provided a path to a configuration file
        if config_file:
            # Cannot process both config file and --devices nargs*
            if devices:
                raise MutuallyExclusiveArgumentError(
                    "Please either use a --config-file argument or inline --device arguments, both were provided."
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
            # Process --device arguments
            # TODO - process root cert from --root-cert arg
            config = NestedEdgeConfig(
                version="1.0",
                auth_method=DeviceAuthType.shared_private_key.value,
                devices=[],
                root_cert=create_edge_root_ca_certificate(
                    cert_output_dir=cert_output_directory,
                    cert_name=root_cert_name,
                ),
            )
            # Parse each device and add to the tree
            for device_input in devices:
                # assemble device params from nArgs strings
                device_params = self.assemble_nargs_to_dict(device_input)
                device_id = device_params.get("id", None)
                if not device_id:
                    raise InvalidArgumentValueError(
                        "A device parameter is missing required parameter 'id'"
                    )
                deployment = device_params.get("deployment", None)
                if deployment:
                    deployment = self._try_parse_valid_deployment_config(deployment)
                parent_id = device_params.get("parent", None)

                device_config = NestedEdgeDeviceConfig(
                    device_id=device_id,
                    deployment=deployment,
                    parent_id=parent_id,
                )
                config.devices.append(device_config)
                device_config_obj = self.create_edge_device_config(
                    device_id=device_id, edgeConfig=config, deviceConfig=device_config
                )

        if not config or not len(config.devices):
            raise InvalidArgumentValueError(
                "No devices found in input. "
                "Please check your input arguments or config file and try the command again"
            )

        tree = Tree()
        tree_root_node_id = "|root|"
        tree.create_node("Devices", tree_root_node_id)

        # Certs needed in bundle

        # --- root cert ---
        # iotedge_config_cli_root.key.pem
        # iotedge_config_cli_root.pem

        # --- device cert ---
        # device-id.cert.pem
        # device-id.key.pem
        # device-id.full-chain.cert.pem

        # --- depends on auth type ---
        # device-id.hub-auth.cert.pem
        # device-id.hub-auth.key.pem

        # dict of assembled Device objects by ID
        assembled_device_dict: Dict[str, Device] = {}
        # dict of device parents by ID
        device_to_parent_dict: Dict[str, str] = {}

        # first pass to create devices in flat tree
        for device_config in config.devices:
            device_id = device_config.device_id
            pk = None
            sk = None
            device_cert_output_directory = cert_output_directory.joinpath(device_id)
            makedirs(device_cert_output_directory)
            # write root cert to device directory
            with open(
                PurePath(device_cert_output_directory).joinpath(
                    root_cert_name + ".pem"
                ),
                "wt",
                encoding="utf-8",
            ) as f:
                f.write(config.root_cert["certificate"])
            signed_device_cert = create_signed_device_cert(
                device_id,
                config.root_cert["certificate"],
                config.root_cert["privateKey"],
                device_cert_output_directory,
            )
            if config.auth_method == DeviceAuthType.x509_ca.value:

                device_hub_cert = create_self_signed_certificate(
                    subject=device_id,
                    valid_days=365,
                    cert_output_dir=device_cert_output_directory,
                    file_prefix=f"{device_id}.hub-auth",
                )
                pk = signed_device_cert["thumbprint"]
                sk = device_hub_cert["thumbprint"]
                make_cert_chain(
                    certs=[
                        signed_device_cert["certificate"],
                        config.root_cert["certificate"],
                    ],
                    output_dir=device_cert_output_directory,
                    output_file=f"{device_id}.full-chain.pem",
                )

            # create device object
            assembled_device = _assemble_device(
                is_update=False,
                device_id=device_id,
                auth_method=config.auth_method,
                pk=pk,
                sk=sk,
                edge_enabled=True,
            )

            # store in assembled device lookup
            assembled_device_dict[device_id] = assembled_device

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
                filter(lambda id: id in assembled_device_dict, existing_device_ids)
            )
            if any(duplicates):
                raise InvalidArgumentValueError(
                    f"The following devices already exist on hub '{self.hub_name}': {duplicates}. "
                    "To clear all devices before creating the hierarchy, please utilize the `--clean` switch."
                )

        # Bulk add devices
        device_list = list(assembled_device_dict.values())
        device_iterator = (
            tqdm(device_list, desc="Creating device identities")
            if visualize
            else device_list
        )
        self.create_device_identities(device_iterator)

        # Give device registry a chance to catch up
        sleep(1)

        # Get all device ids and scopes (inconsistent timing, hence sleep)
        query_args = ["SELECT deviceId, deviceScope FROM devices"]
        query_method = self.service_sdk.query.get_twins
        all_devices = _execute_query(query_args, query_method)

        # Throw an error if we don't get the same number of desired devices back
        if len(all_devices) < len(config.devices):
            raise AzureResponseError(
                "An error occurred - Failed to fetch device scopes for all devices"
            )

        # set all device scopes
        for device in all_devices:
            id = device["deviceId"]
            if assembled_device_dict.get(id, None):
                assembled_device_dict[id].device_scope = device["deviceScope"]

        # Set parent / child relationships
        device_to_parent_iterator = (
            tqdm(device_to_parent_dict, desc="Setting device parents")
            if visualize
            else device_to_parent_dict
        )
        for device_id in device_to_parent_iterator:
            device = assembled_device_dict[device_id]
            parent_id = device_to_parent_dict[device_id]
            parent_scope = assembled_device_dict[parent_id].device_scope
            device.parent_scopes = [parent_scope]
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
        # TODO version / schema validation
        version = content["config_version"]
        hub_config = content["iothub"]
        devices_config = content["edgedevices"]

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
            cert_output_directory = PurePath.joinpath(
                PurePath(getcwd()), "device_certificates"
            )
            root_cert = create_edge_root_ca_certificate(
                cert_output_dir=cert_output_directory,
                cert_name="iotedge_config_cli_root",
            )

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
                deployment = self._try_parse_valid_deployment_config(deployment)

            child_devices = device.get("child", [])
            container_auth = device.get("container_auth", {})
            hostname = device.get("hostname", None)
            device_obj = NestedEdgeDeviceConfig(
                device_id=device_id,
                deployment=deployment,
                parent_id=parent_id,
                parent_hostname=parent_hostname,
                container_auth=EdgeContainerAuth(
                    serveraddress=container_auth.get("serveraddress", None),
                    username=container_auth.get("username", None),
                    password=container_auth.get("password", None),
                ),
                hostname=hostname,
                edge_agent=device.get("edge_agent", None),
            )
            all_devices.append(device_obj)
            for child_device in child_devices:
                _process_edge_config_device(child_device, parent_id=device_id, parent_hostname=hostname)

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

    def create_device_identities(self, devices: List[Device]):
        try:
            for device in devices:
                self.service_sdk.devices.create_or_update_identity(
                    id=device.device_id, device=device
                )
        except Exception as err:
            raise AzureResponseError(err)

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
        edgeConfig: NestedEdgeConfig,
        deviceConfig: NestedEdgeDeviceConfig,
    ):
        device_config_toml_path = edgeConfig.template_config_path
        device_toml = (
            process_toml_content(device_config_toml_path)
            if device_config_toml_path
            else DEVICE_CONFIG_TOML
        )

        # trust bundle
        device_toml[
            "trust_bundle_cert"
        ] = f"file://etc/aziot/certificates/iotedge_config_cli_root.pem"
        device_toml["hostname"] = deviceConfig.hostname if deviceConfig.hostname else ""
        device_toml["parent_hostname"] = deviceConfig.parent_hostname if deviceConfig.parent_hostname else ""

        return device_toml
