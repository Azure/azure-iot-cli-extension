# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from tqdm import tqdm
from time import sleep
from typing import Any, List
from knack.log import get_logger
from typing import Optional
from azext_iot._factory import SdkResolver
from azext_iot.common.shared import ConfigType, DeviceAuthType, EntityStatusType, SdkType, BulkDeviceImportMode
from azext_iot.iothub.providers.base import IoTHubProvider, CloudError
from azext_iot.common.utility import process_json_arg, process_yaml_arg
from azext_iot.operations.generic import _execute_query
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError
)
from azext_iot.operations.hub import _assemble_device, _process_config_content
from azext_iot.sdk.iothub.service.models.configuration_content_py3 import ConfigurationContent
from azext_iot.sdk.iothub.service.models.device_capabilities import DeviceCapabilities
from azext_iot.sdk.iothub.service.models.device_py3 import Device
from azext_iot.sdk.iothub.service.models.export_import_device import ExportImportDevice

logger = get_logger(__name__)


class DeviceIdentityProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub_name: Optional[str] = None,
        rg: Optional[str] = None,
        login: Optional[str] = None,
        auth_type_dataplane: Optional[str] = None
    ):
        super(DeviceIdentityProvider, self).__init__(
            cmd=cmd, hub_name=hub_name, rg=rg, login=login, auth_type_dataplane=auth_type_dataplane
        )

        self.hub_resolver = SdkResolver(target=self.target)
        self.service_sdk = self.hub_resolver.get_sdk(SdkType.service_sdk)
    
    
    def create_edge_hierarchy(
        self,
        devices: Optional[List[List[str]]]=None,
        config_file: Optional[str]=None,
        visualize: Optional[bool]=False,
        clean: Optional[bool]=False,
    ):
        """
        Creates a nested edge hierarchy based on user nargs input.
        Clean - parameter to determine if all devices are deleted first.
        Visualize - parameter to show a visualization of the devices before creating.

        If user does not select 'clean' - we try our best to validate that no duplicate deviceIds are created

        STEPS
        1 - process input hierarchy and validate
        2 - show visualization
        3 - flatten list but track parent-child hierarchy
        4 - clean existing devices (maybe)
        5 - create all devices
        6 - get all device scopes
        7 - set parent-child relationships
        8 - set modules
        """
        from treelib import Tree
        from treelib.exceptions import NodeIDAbsentError, LoopError, DuplicatedNodeIdError
        config = None
        if config_file:
            # Cannot process config file and --devices nargs*
            if devices:
                raise MutuallyExclusiveArgumentError('Please either use a config file (-c) or in-line device arguments, both were provided')
            
            config_content = None
            # Process Edge Config YAML
            if config_file.endswith('.yml'):
                # Process YAML file into config object dictionary
                config_content = process_yaml_arg(config_file)
            elif config_file.endsWith('.json'):
                # Process JSON file into config object dictionary
                config_content = process_json_arg(config_file)
            else:
                raise InvalidArgumentValueError('Config file must be JSON or YAML')
            
            config = self._process_nested_edge_config_file_content(config_content)
        elif devices:
            # parse inputs
            # Parse each device and add to the tree
            config = {
                'auth_method': DeviceAuthType.shared_private_key.value, # TODO - add input param for auth-type
                'devices': []
            }
            for device_input in devices:
                if not device_input or device_input[0]:
                    pass
                
                # assemble device with params
                device_params = self._assemble_nargs_to_dict(device_input)
                device = self._parse_edge_config_device_param_dict(device_params)
                config['devices'].append(device)

        tree = Tree()
        tree_root_node = "|root|"
        tree.create_node("Devices", tree_root_node)

        # dict of assembled devices
        assembled_device_dict = {}
        # dict of parents
        device_to_parent_dict = {}
        
        # first pass to create flat tree
        for device_obj in config['devices']:
            device = device_obj['device']
            device_id = device['device_id']
            auth_method = config['auth_method']

            # create device object
            assembled_device = _assemble_device(is_update=False, device_id=device_id, auth_method=auth_method,edge_enabled=True)

            # store in assembled device lookup
            assembled_device_dict[device_id] = assembled_device

            # add to flat tree
            try:
                tree.create_node(device_id, device_id, parent=tree_root_node)
            except DuplicatedNodeIdError:
                raise InvalidArgumentValueError(f"Duplicate deviceId '{device_id}' detected")

        # second pass to move nodes and check hierarchy
        for device_obj in config['devices']:
            device = device_obj['device']
            device_id = device['device_id']

            # Move nodes to their correct parents, track device->parent in dict
            device_parent = device_obj.get("parent", tree_root_node)
            if device_parent != tree_root_node:
                device_to_parent_dict[device_id] = device_parent
            try:
                tree.update_node(device_id, data=device_parent)
                tree.move_node(device_id, device_parent)
            except NodeIDAbsentError:
                raise InvalidArgumentValueError(
                    f'Error building hierarchy, missing parent "{device_parent}"'
                )
            except LoopError:
                raise InvalidArgumentValueError(
                    f'Error building hierarchy, found a loop - device "{device_id}" and "{device_parent}" cannot both be children of each other'
                )
        
        # Show the tree, break if user provides input
        if visualize:
            tree.show()
            i = input("Press enter to continue. Entering any value will cancel the operation.")
            if i != '':
                raise KeyboardInterrupt

        #Delete or verify existing device IDs
        query_args = ["SELECT deviceId FROM devices"]
        query_method = self.service_sdk.query.get_twins
        existing_devices = _execute_query(query_args, query_method)
        existing_device_ids = list(map(lambda x: x['deviceId'], existing_devices))
        
        # Clear devices if necessary
        if clean and len(existing_device_ids):
           self.delete_device_identities(existing_device_ids)
        else:
            # If not cleaning the hub, ensure no duplicate device ids
            duplicates = list(filter(lambda id: id in assembled_device_dict, existing_device_ids))
            if any(duplicates):
                raise InvalidArgumentValueError(f'Duplicate deviceIds detected: {duplicates}. '
                'To clear all devices before creating the hierarchy, please utilize the `--clean` switch.')
        
        # Bulk add devices
        self.create_device_identities(list(assembled_device_dict.values()))

        # Get all device ids and scopes (inconsistent timing, using basic retry)
        all_devices = []
        retries = 0
        progress = tqdm([range(0, 5)], desc="Querying device scopes:")
        progress.update(1)
        while len(all_devices) < len(config['devices']) and retries < 5:
            if retries > 0:
                progress.update(1)
            sleep(2)
            query_args = ["SELECT deviceId, deviceScope FROM devices"]
            query_method = self.service_sdk.query.get_twins
            all_devices = _execute_query(query_args, query_method)
            retries += 1
        progress.close()

        if len(all_devices) < len(config['devices']):
            raise AzureResponseError(
                "An error occurred - Failed to fetch device scopes for all devices"
            )

        # set all device scopes
        for device in all_devices:
            id = device['deviceId']
            assembled_device_dict[id].device_scope = device['deviceScope']

        # Set parent / child relationships
        # TODO - this is not currently working with bulk update.
        for device_id in tqdm(device_to_parent_dict, desc="Setting device parents"):
            device = assembled_device_dict[device_id]
            parent_id = device_to_parent_dict[device_id]
            parent_scope = assembled_device_dict[parent_id].device_scope
            device.parent_scopes = [parent_scope]
            try:
                self._handle_rate_limiting(self.service_sdk.devices.create_or_update_identity)(
                    id=device_id,
                    device=device,
                    if_match="*")
            except Exception as err:
                ## TODO - handle timeouts / rate limiting
                import pdb; pdb.set_trace()
                print(dir(err))

        # # update config / set-modules
        for device_obj in tqdm(config['devices'], desc="Setting edge module content"):
            device = device_obj['device']
            device_id = device['device_id']
            deployment_content = device.get('deployment', None)
            if deployment_content:
                content = process_json_arg(deployment_content, argument_name="content")
                processed_content = _process_config_content(
                    content, config_type=ConfigType.edge
                )

                content = ConfigurationContent(**processed_content)
                self._handle_rate_limiting(self.service_sdk.configuration.apply_on_edge_device)(id=device_id, content=content)


    def _process_nested_edge_config_file_content(self, content: dict) -> dict[str, Any]:
        # TODO version number is important here for schema validation
        version = content['config_version']
        hub_config = content['iothub']
        agent_config = content['configuration']
        devices_config = content['edgedevices']
        auth_value = hub_config['authentication_method']
        if auth_value not in ['symmetric_key', 'x509_certificate']:
            raise InvalidArgumentValueError('Invalid authentication_method in edge config file, must be either symmetric_key or x509_certificate')
        device_authentication_method = DeviceAuthType.shared_private_key.value if auth_value == 'symmetric_key' else DeviceAuthType.x509_thumbprint.value
        all_devices= []

        def _process_edge_device(device: dict, parent_id=None):
            device_id = device.get('device_id', None)
            if not device_id:
                raise InvalidArgumentValueError('A device parameter is missing a device ID')
            edge_agent = device.get('edge_agent', None)
            deployment = device.get('deployment', None)
            child_devices = device.get('child', [])
            device_obj = {
                'device': device,
                'edge_agent': edge_agent,
                'deployment': deployment
            }
            if parent_id:
                device_obj['parent'] = parent_id
            all_devices.append(device_obj)
            for child_device in child_devices:
                _process_edge_device(child_device, parent_id=device_id)
        
        for device in devices_config:
            _process_edge_device(device)
        return {
            'version': version,
            'auth_method': device_authentication_method,
            "devices": all_devices
        }


    def _parse_edge_config_device_param_dict(self, device) -> dict[str, Any]:
        device_id = device.get('device_id', None)
        if not device_id:
            raise InvalidArgumentValueError('A device parameter is missing a device ID')
        edge_agent = device.get('edge_agent', None)
        deployment = device.get('deployment', None)
        parent_id = device.get('parent', None)

        device_obj = {
            'device': device,
            'edge_agent': edge_agent,
            'deployment': deployment
        }
        if parent_id:
            device_obj['parent'] = parent_id
        return device_obj


    def _assemble_nargs_to_dict(self, hash_list: List[str]) -> dict[str, str]:
        result = {}
        if not hash_list:
            return result
        for hash in hash_list:
            split_hash = hash.split("=", 1)
            result[split_hash[0]] = split_hash[1]
        return result


    def delete_device_identities(self, device_ids, confirm=True):
        for id in tqdm(device_ids, "Deleting existing device identities"):
            try:
                self._handle_rate_limiting(self.service_sdk.devices.delete_identity)(id=id, if_match="*")
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
            for device in tqdm(devices, desc="Creating device identities"):
                self._handle_rate_limiting(self.service_sdk.devices.create_or_update_identity)(
                    id=device.device_id,
                    device=device
                )
        except Exception as err:
            raise AzureResponseError(err)


    def _handle_rate_limiting(self, operation):
        '''Decorator that handles individual service calls that are subject to rate limiting'''
        def wrap(*args, **kwargs):
            # print(f'wrapping {operation.__name__}')
            try:
                return operation(*args, **kwargs)
            except CloudError as e:
                if e.status_code == 409:
                    logger.log(e)
                    logger.log(args)
                    logger.log(kwargs)
                if e.status_code == 429:
                    logger.log(f'{operation.__name__} was rate limited...waiting to retry')
                    sleep(5)
                    return wrap(*args, **kwargs)
            except Exception as e:
                raise e
        return wrap


    def _bulk_create_devices(self, device_ids, chunk_size=100, edge=False):
        # Creates chunked arrays of device ops of size "chunk_size"
        bulk_device_chunks = [
            device_ids[i : i + chunk_size] for i in range(0, len(device_ids), chunk_size)
        ]

        edge_enabled = DeviceCapabilities(iot_edge=edge)
        for chunk in bulk_device_chunks:
            create_ops = list(
                map(
                    lambda device_id: ExportImportDevice(
                        id=device_id,
                        import_mode=BulkDeviceImportMode.Create.value,
                        capabilities=edge_enabled,

                    ),
                    chunk,
                )
            )
            try:
                self.service_sdk.bulk_registry.update_registry(create_ops)
            except Exception as err:
                raise AzureResponseError(err)


    def _bulk_delete_devices(self, device_ids, chunk_size=100, confirm=True):
        # Creates chunked arrays of device ops of size "chunk_size"
        bulk_delete_chunks = [
            device_ids[i : i + chunk_size] for i in range(0, len(device_ids), chunk_size)
        ]
        for chunk in bulk_delete_chunks:
            delete_ops = list(
                map(
                    lambda id: ExportImportDevice(
                        id=id, import_mode=BulkDeviceImportMode.Delete.value
                    ),
                    chunk,
                )
            )
            try:
                self.service_sdk.bulk_registry.update_registry(delete_ops)
            except Exception as err:
                import pdb; pdb.set_trace()
                raise AzureResponseError(err)
        if confirm:
            existing_devices = self.service_sdk.devices.get_devices()
            if len(existing_devices):
                raise AzureResponseError(
                    "An error has occurred - Not all devices were deleted."
                )