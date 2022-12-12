# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
from pathlib import PurePath
from knack.prompting import prompt_y_n
from os import makedirs
from os.path import exists, abspath
from shutil import rmtree
from azext_iot.common.certops import (
    create_v3_self_signed_root_certificate,
    create_ca_signed_certificate,
    make_cert_chain,
)

from azext_iot.common.fileops import tar_directory, write_content_to_file
from azext_iot.iothub.providers.helpers.edge_device_config import (
    DEVICE_README,
    EDGE_ROOT_CERTIFICATE_FILENAME,
    create_edge_device_config,
    process_edge_devices_config_args,
    process_edge_devices_config_file_content,
    create_edge_device_config_script,
)
from tqdm import tqdm
from time import sleep
from typing import Dict, List
from knack.log import get_logger
from typing import Optional
from azext_iot.common.shared import (
    DeviceAuthType,
    SdkType,
)
from azext_iot.iothub.common import (
    EdgeDevicesConfig,
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common.utility import (
    process_json_arg,
    process_yaml_arg,
)
from azext_iot.operations.generic import _execute_query
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ManualInterrupt,
    MutuallyExclusiveArgumentError,
)
from azext_iot.operations.hub import _assemble_device
from azext_iot.sdk.iothub.service.models import Device

logger = get_logger(__name__)


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
        self.service_sdk = self.get_sdk(sdk_type=SdkType.service_sdk)

    def create_edge_devices(
        self,
        devices: Optional[List[List[str]]] = None,
        config_file: Optional[str] = None,
        visualize: bool = False,
        clean: bool = False,
        yes: bool = False,
        auth_type: Optional[str] = None,
        default_edge_agent: Optional[str] = None,
        device_config_template: Optional[str] = None,
        root_cert_path: Optional[str] = None,
        root_key_path: Optional[str] = None,
        root_cert_password: Optional[str] = None,
        output_path: Optional[str] = None,
    ):
        from treelib import Tree
        from treelib.exceptions import (
            NodeIDAbsentError,
            LoopError,
            DuplicatedNodeIdError,
        )

        config: EdgeDevicesConfig = None

        # configuration for root cert and output directories
        root_cert_name = EDGE_ROOT_CERTIFICATE_FILENAME
        bundle_output_directory = None
        if output_path:
            if not exists(output_path):
                makedirs(output_path, exist_ok=True)
            bundle_output_directory = PurePath(output_path)

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

            config = process_edge_devices_config_file_content(
                content=config_content,
                override_auth_type=auth_type,
                override_root_cert_path=root_cert_path,
                override_root_key_path=root_key_path,
                override_default_edge_agent=default_edge_agent,
                override_device_config_template=device_config_template,
            )
        elif devices:
            config = process_edge_devices_config_args(
                device_args=devices,
                auth_type=auth_type,
                default_edge_agent=default_edge_agent,
                device_config_template=device_config_template,
                root_cert_path=root_cert_path,
                root_key_path=root_key_path,
                root_cert_password=root_cert_password,
            )

        if not config or not len(config.devices):
            raise InvalidArgumentValueError(
                "No devices found in input. "
                "Please check your input arguments or config file and try the command again"
            )
        tree = Tree()
        tree_root_node_id = "|root|"
        tree.create_node("Devices", tree_root_node_id)
        hub_cert_auth = config.auth_method == DeviceAuthType.x509_thumbprint.value

        # dict of device parents by ID
        device_to_parent_dict: Dict[str, str] = {}
        # device configs by id
        device_config_dict: Dict[str, EdgeDevicesConfig] = {}
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

        # Show the device tree
        if visualize:
            tree.show()

        # Query existing devices
        query_args = ["SELECT deviceId FROM devices"]
        query_method = self.service_sdk.query.get_twins
        existing_devices = _execute_query(query_args, query_method)
        existing_device_ids = [x["deviceId"] for x in existing_devices]

        # Clear devices if necessary
        if clean and len(existing_device_ids):
            if not yes and not prompt_y_n(msg=f"Confirm you want to delete all devices in '{self.hub_name}'", default='Y'):
                raise ManualInterrupt("Operation was aborted, existing device deletion was not confirmed.")
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
            device_cert_output_directory = None
            if bundle_output_directory:
                device_cert_output_directory = bundle_output_directory.joinpath(device_id)
                # if the device's folder already exists, remove it
                if exists(device_cert_output_directory):
                    rmtree(device_cert_output_directory)
                # create fresh device folder
                makedirs(device_cert_output_directory)

            # signed device cert
            signed_device_cert = create_ca_signed_certificate(
                subject=f"{device_id}.deviceca",
                ca_public=config.root_cert["certificate"],
                ca_private=config.root_cert["privateKey"],
                cert_output_dir=device_cert_output_directory,
                cert_file=device_id,
            )

            device_pk = None
            device_sk = None
            # if using x509 device auth
            if hub_cert_auth:
                # hub auth cert for device
                device_hub_cert = create_v3_self_signed_root_certificate(
                    subject=device_id,
                    valid_days=365,
                )
                device_pk = signed_device_cert["thumbprint"]
                device_sk = device_hub_cert["thumbprint"]

            # create device object for service
            assembled_device = _assemble_device(
                is_update=False,
                device_id=device_id,
                auth_method=config.auth_method,
                pk=device_pk,
                sk=device_sk,
                edge_enabled=True,
            )
            # create device identity
            device_result: Device = self.service_sdk.devices.create_or_update_identity(
                id=device_id, device=assembled_device
            )

            # write all device bundle content
            if device_cert_output_directory:
                if hub_cert_auth:
                    # hub auth cert
                    write_content_to_file(
                        content=device_hub_cert["certificate"],
                        destination=device_cert_output_directory,
                        file_name=f"{device_id}.hub-auth-cert.pem",
                        overwrite=True
                    )
                    # hub auth key
                    write_content_to_file(
                        content=device_hub_cert["privateKey"],
                        destination=device_cert_output_directory,
                        file_name=f"{device_id}.hub-auth-key.pem",
                        overwrite=True
                    )
                else:
                    device_keys = device_result.authentication.symmetric_key
                    device_pk = device_keys.primary_key if device_keys else None

                # edge device config
                create_edge_device_config(
                    device_id=device_id,
                    hub_hostname=self.target["entity"],
                    auth_method=config.auth_method,
                    default_edge_agent=config.default_edge_agent,
                    device_config=device_config_dict[device_id],
                    device_config_path=config.template_config_path,
                    device_pk=device_pk,
                    output_path=device_cert_output_directory,
                )
                # root cert
                write_content_to_file(
                    content=config.root_cert["certificate"],
                    destination=device_cert_output_directory,
                    file_name=root_cert_name,
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
                # write install script
                write_content_to_file(
                    content=create_edge_device_config_script(
                        device_id=device_id,
                        hub_auth=hub_cert_auth,
                        hostname=device.hostname,
                        has_parent=(device.parent_id is not None),
                        parent_hostname=device.parent_hostname,
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
                # create archive
                tar_directory(
                    target_directory=device_cert_output_directory,
                    tarfile_path=bundle_output_directory,
                    tarfile_name=device_id,
                    overwrite=True,
                )
                # delete uncompressed files
                rmtree(device_cert_output_directory)

        # Give device registry a chance to catch up
        sleep(1)

        # Get all device ids and scopes (inconsistent timing, hence sleep)
        query_args = ["SELECT deviceId, deviceScope FROM devices"]
        query_method = self.service_sdk.query.get_twins
        all_hub_devices = _execute_query(query_args, query_method)

        # Sanity check we got all device scopes
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

        # Print device bundle details after other visuals
        if bundle_output_directory:
            num_bundles = len(config.devices)
            bundle_plural = '' if num_bundles == 1 else 's'
            print(f"{num_bundles} device bundle{bundle_plural} created in folder: {abspath(bundle_output_directory)}")

    # TODO - Unit test
    def delete_device_identities(self, device_ids: List[str], confirm: bool = False):
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
