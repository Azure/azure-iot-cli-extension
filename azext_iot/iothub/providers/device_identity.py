# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
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
from azext_iot.common.utility import process_json_arg, process_yaml_arg
from azext_iot.operations.generic import _execute_query
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
)
from azext_iot.operations.hub import _assemble_device, _process_config_content
from azext_iot.sdk.iothub.service.models.configuration_content_py3 import (
    ConfigurationContent,
)
from azext_iot.sdk.iothub.service.models import Device

logger = get_logger(__name__)


# Utility classes for edge config file values and device arguments
class NestedEdgeDeviceConfig(NamedTuple):
    device_params: Dict[str, str]
    deployment: str
    parent: Optional[str] = None


class NestedEdgeConfig(NamedTuple):
    version: str
    auth_method: DeviceAuthType
    devices: List[NestedEdgeDeviceConfig]


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
            config = NestedEdgeConfig(
                version="1.0",
                auth_method=DeviceAuthType.shared_private_key.value,  # TODO - add input param for auth-type
                devices=[],
            )
            # Parse each device and add to the tree
            for device_input in devices:
                # assemble device params from nArgs strings
                device_params = self.assemble_nargs_to_dict(device_input)
                device_id = device_params.get("device_id", None)
                if not device_id:
                    raise InvalidArgumentValueError(
                        "A device parameter is missing required parameter 'device_id'"
                    )
                deployment = device_params.get("deployment", None)
                parent_id = device_params.get("parent", None)

                config.devices.append(
                    NestedEdgeDeviceConfig(
                        device_params=device_params,
                        deployment=deployment,
                        parent=parent_id,
                    )
                )

        if not config or not len(config.devices):
            raise InvalidArgumentValueError(
                "No devices found in input. "
                "Please check your input arguments or config file and try the command again"
            )

        tree = Tree()
        tree_root_node_id = "|root|"
        tree.create_node("Devices", tree_root_node_id)

        # dict of assembled Device objects by ID
        assembled_device_dict: Dict[str, Device] = {}
        # dict of device parents by ID
        device_to_parent_dict: Dict[str, str] = {}

        # first pass to create flat tree
        for device_config in config.devices:
            device_params = device_config.device_params
            device_id = device_params["device_id"]
            auth_method = config.auth_method

            # create device object
            assembled_device = _assemble_device(
                is_update=False,
                device_id=device_id,
                auth_method=auth_method,
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
            device_params = device_config.device_params
            device_id = device_params.get("device_id", None)

            # Move nodes to their correct parents, track device->parent in dict
            device_parent = device_config.parent or tree_root_node_id
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
            device_params = device_config.device_params
            device_id = device_params["device_id"]
            deployment_content = device_params.get("deployment", None)
            if deployment_content:
                # TODO - replace with iot_edge_set_modules once it's moved into provider
                # TODO - check module validity *before* deleting devices
                content = process_json_arg(deployment_content, argument_name="content")
                processed_content = _process_config_content(
                    content, config_type=ConfigType.edge
                )
                content = ConfigurationContent(**processed_content)
                self.service_sdk.configuration.apply_on_edge_device(
                    id=device_id, content=content
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
        auth_value = hub_config["authentication_method"]
        if auth_value not in ["symmetric_key", "x509_certificate"]:
            raise InvalidArgumentValueError(
                "Invalid authentication_method in edge config file, must be either symmetric_key or x509_certificate"
            )
        device_authentication_method = (
            DeviceAuthType.shared_private_key.value
            if auth_value == "symmetric_key"
            else DeviceAuthType.x509_thumbprint.value
        )
        all_devices = []

        def _process_edge_config_device(device: dict, parent_id=None):
            device_id = device.get("device_id", None)
            if not device_id:
                raise InvalidArgumentValueError(
                    "A device parameter is missing required attribute 'device_id'"
                )
            deployment = device.get("deployment", None)
            child_devices = device.get("child", [])
            device_obj = NestedEdgeDeviceConfig(
                device_params=device, deployment=deployment, parent=parent_id
            )
            all_devices.append(device_obj)
            for child_device in child_devices:
                _process_edge_config_device(child_device, parent_id=device_id)

        for device in devices_config:
            _process_edge_config_device(device)
        return NestedEdgeConfig(
            version=version,
            auth_method=device_authentication_method,
            devices=all_devices,
        )

    def assemble_nargs_to_dict(self, hash_list: List[str]) -> Dict[str, str]:
        result = {}
        if not hash_list or not hash_list[0]:
            return result
        for hash in hash_list:
            # filter for malformed nArg input (no = value assigned)
            if "=" not in hash:
                return result
            split_hash = hash.split("=", 1)
            result[split_hash[0]] = split_hash[1]
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
