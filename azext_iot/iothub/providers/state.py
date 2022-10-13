# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger

from azext_iot.common.shared import DeviceAuthApiType, DeviceAuthType, ConfigType
from azext_iot.iothub.common import (
    IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS,
    IMMUTABLE_DEVICE_IDENTITY_FIELDS,
    IMMUTABLE_MODULE_IDENTITY_FIELDS,
    HubAspects
)
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common._azure import (
    parse_iot_hub_message_endpoint_connection_string,
    parse_storage_container_connection_string,
    parse_cosmos_db_connection_string
)
from azure.cli.core.azclierror import FileOperationError, ResourceNotFoundError, BadRequestError, AzCLIError
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.operations.hub import (
    _iot_device_set_parent,
    _iot_device_show,
    _iot_device_module_twin_show,
    _iot_device_module_create,
    _iot_device_module_show,
    _iot_device_create,
    _iot_device_delete,
    _iot_edge_set_modules,
    _iot_hub_configuration_delete,
    _iot_device_module_list,
    _iot_device_twin_list,
    _iot_hub_configuration_list,
    _iot_hub_configuration_create,
    _iot_device_twin_update,
    _iot_device_module_twin_update,
)
from azext_iot._factory import iot_hub_full_service_factory
import json
from tqdm import tqdm
from typing import List, Optional
import os

logger = get_logger(__name__)
cli = EmbeddedCLI()


class StateProvider(IoTHubProvider):
    def __init__(
        self,
        cmd,
        hub: Optional[str] = None,
        rg: Optional[str] = None,
        login: Optional[str] = None,
        auth_type_dataplane: Optional[str] = None,
    ):
        super(StateProvider, self).__init__(
            cmd=cmd,
            hub_name=hub,
            rg=rg,
            login=login,
            auth_type_dataplane=auth_type_dataplane
        )
        self.auth_type = auth_type_dataplane

        if not self.hub_name:
            self.hub_name = self.target["entity"].split('.')[0]
        if not self.rg:
            self.rg = self.target.get("resourcegroup")

    def get_client(self):
        return iot_hub_full_service_factory(self.cmd.cli_ctx)

    def save_state(self, filename: str, overwrite_file: bool = False, hub_aspects: List[str] = None):
        '''
        Writes hub state to file
        '''
        if os.path.exists(filename) and os.stat(filename).st_size and not overwrite_file:
            raise FileOperationError(f'File {filename} is not empty. Include the --overwrite-file flag to overwrite file.')

        if not hub_aspects:
            hub_aspects = HubAspects.list()

        hub_state = self.process_hub_to_dict(self.target, hub_aspects)

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(hub_state, f, indent=4, sort_keys=True)

            logger.info("Saved state of IoT Hub '{}' to {}".format(self.hub_name, filename))

        except FileNotFoundError:
            raise FileOperationError(f'File {filename} does not exist.')

    def upload_state(self, filename: str, replace: Optional[bool] = None, hub_aspects: List[str] = None):
        '''Uses device info from file to recreate the hub state'''
        if not hub_aspects:
            hub_aspects = HubAspects.list()

        self.delete_aspects(replace, hub_aspects)

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                hub_state = json.load(f)

            self.upload_hub_from_dict(hub_state, hub_aspects)
            logger.info("Uploaded state from '{}' to IoT Hub '{}'".format(filename, self.hub_name))

        except FileNotFoundError:
            raise FileOperationError(f'File {filename} does not exist.')

    def migrate_state(
        self,
        orig_hub: Optional[str] = None,
        orig_rg: Optional[str] = None,
        orig_hub_login: Optional[str] = None,
        replace: Optional[bool] = False,
        hub_aspects: List[str] = None
    ):
        '''Migrates state from original hub to destination hub.'''
        orig_hub_target = self.discovery.get_target(
            resource_name=orig_hub,
            resource_group_name=orig_rg,
            login=orig_hub_login,
            auth_type=self.auth_type
        )

        if not hub_aspects:
            hub_aspects = HubAspects.list()

        # Command modifies hub_aspect - make copy so we can reuse for upload
        hub_state = self.process_hub_to_dict(orig_hub_target, hub_aspects[:])
        self.delete_aspects(replace, hub_aspects)
        self.upload_hub_from_dict(hub_state, hub_aspects)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(orig_hub, self.hub_name))

    def delete_aspects(self, replace, hub_aspects=[]):
        """
        Delete all necessary hub aspects if the hub exists.

        Delete dataplane aspects only present in hub_aspects.
        """
        if self.target and replace:
            if HubAspects.Configurations.value in hub_aspects:
                self.delete_all_configs()
            if HubAspects.Devices.value in hub_aspects:
                self.delete_all_devices()
            if HubAspects.Arm.value in hub_aspects:
                cert_client = self.get_client().certificates
                # serialize strips name and etag - use as_dict instead
                certificates = cert_client.list_by_iot_hub(self.rg, self.hub_name).as_dict()

                for cert in tqdm(certificates["value"], desc="Deleting certificates from destination hub"):
                    cert_client.delete(self.rg, self.hub_name, cert["name"], cert["etag"])

    def process_hub_to_dict(self, target: dict, hub_aspects: list = []) -> dict:
        '''Returns a dictionary containing the hub state'''
        hub_state = {}

        if HubAspects.Configurations.value in hub_aspects:
            hub_aspects.remove(HubAspects.Configurations.value)
            all_configs = _iot_hub_configuration_list(target=target)
            hub_state["configurations"] = {}
            # if HubAspects.Configurations.value in hub_aspects:
            adm_configs = {}
            for c in all_configs:
                if c["content"].get("deviceContent") or c["content"].get("moduleContent"):
                    for key in ["createdTimeUtc", "etag", "lastUpdatedTimeUtc", "schemaVersion"]:
                        c.pop(key, None)
                    adm_configs[c["id"]] = c

            hub_state["configurations"]["admConfigurations"] = adm_configs

            # if HubAspects.EdgeDeployments.value in hub_aspects:
            hub_state["configurations"]["edgeDeployments"] = {
                c["id"]: c for c in all_configs if c["content"].get("modulesContent")
            }

        if HubAspects.Devices.value in hub_aspects:
            hub_aspects.remove(HubAspects.Devices.value)
            hub_state["devices"] = {}
            twins = _iot_device_twin_list(target=target, top=-1)

            for i in tqdm(range(len(twins)), desc="Saving devices and modules"):
                device_twin = twins[i]
                device_id = device_twin["deviceId"]
                device_obj = {}

                if device_twin.get("parentScopes"):
                    device_parent = device_twin["parentScopes"][0].split("://")[1]
                    device_obj["parent"] = device_parent[:device_parent.rfind("-")]

                # put properties + tags into the saved twin
                device_twin["properties"].pop("reported")
                for key in ["$metadata", "$version"]:
                    device_twin["properties"]["desired"].pop(key)

                device_obj["twin"] = {
                    "properties": device_twin.pop("properties")
                }

                if device_twin.get("tags"):
                    device_obj["twin"]["tags"] = device_twin.pop("tags")

                # create the device identity from the device twin
                # primary and secondary keys show up in the "show" output but not in the "list" output
                authentication = {
                    "type": device_twin.pop("authenticationType"),
                    "x509Thumbprint": device_twin.pop("x509Thumbprint")
                }
                if authentication["type"] == DeviceAuthApiType.sas.value:
                    id2 = _iot_device_show(target=target, device_id=device_id)
                    authentication["symmetricKey"] = id2["authentication"]["symmetricKey"]
                device_twin["authentication"] = authentication

                for key in IMMUTABLE_DEVICE_IDENTITY_FIELDS:
                    device_twin.pop(key, None)
                device_obj["identity"] = device_twin

                module_objs = _iot_device_module_list(target=target, device_id=device_id)
                if module_objs:
                    device_obj["modules"] = {}

                for module in module_objs:
                    module = module.serialize()
                    module_id = module["moduleId"]
                    module_identity_show = _iot_device_module_show(
                        target=target, device_id=device_id, module_id=module_id
                    )
                    module["authentication"] = module_identity_show["authentication"]

                    for key in IMMUTABLE_MODULE_IDENTITY_FIELDS:
                        module.pop(key)

                    module_twin = _iot_device_module_twin_show(
                        target=target, device_id=device_id, module_id=module_id
                    )
                    for key in IMMUTABLE_AND_DUPLICATE_MODULE_TWIN_FIELDS:
                        module_twin.pop(key)
                    for key in ["$metadata", "$version"]:
                        module_twin["properties"]["desired"].pop(key)
                    module_twin["properties"].pop("reported")

                    device_obj["modules"][module_id] = {
                        "identity": module,
                        "twin": module_twin
                    }

                hub_state["devices"][device_id] = device_obj

        # Controlplane using ARM
        if HubAspects.Arm.value in hub_aspects:
            hub_name = target.get("entity").split(".")[0]
            hub_rg = target.get("resourcegroup")

            control_plane_obj = self.discovery.find_resource(hub_name, hub_rg)

            if not hub_rg:
                hub_rg = control_plane_obj.additional_properties["resourcegroup"]
            hub_resource_id = control_plane_obj.id
            hub_arm = cli.invoke(f"group export -n {hub_rg} --resource-ids '{hub_resource_id}' --skip-all-params").as_json()
            hub_state["arm"] = hub_arm
            hub_resource = hub_state["arm"]["resources"][0]
            # get connection strings if needed
            endpoints = hub_resource["properties"]["routing"]["endpoints"]
            for ep in endpoints["cosmosDBSqlCollections"]:
                pass
                # TODO: test when cosmos db endpoint feature is out
                # if ep.get("primaryKey") or ep.get("secondaryKey"):
                #     account_name = ep["endpointUri"].strip("https://").split(".")[0]
                #     cosmos_keys = cli.invoke(
                #         'cosmosdb keys list --resource-group {} --name {} --type connection-strings'.format(
                #             account_name,
                #             ep["resourceGroup"]
                #         )
                #     ).as_json()
                #     for cs_object in cosmos_keys["connectionStrings"]:
                #         if cs_object["description"] == "Primary SQL Connection String" and ep.get("primaryKey"):
                #             ep["primaryKey"] = parse_cosmos_db_connection_string(cs_object["connectionString"])["AccountKey"]
                #         if cs_object["description"] == "Secondary SQL Connection String" and ep.get("secondaryKey"):
                #             ep["secondaryKey"] = parse_cosmos_db_connection_string(cs_object["connectionString"])["AccountKey"]
            for ep in endpoints["eventHubs"]:
                if ep.get("connectionString"):
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(ep["connectionString"])
                    namespace = endpoint_props["Endpoint"].strip("sb://").split(".")[0]
                    ep["connectionString"] = cli.invoke(
                        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--eventhub-name {} --name {}".format(
                            namespace,
                            ep["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            for ep in endpoints["serviceBusQueues"]:
                if ep.get("connectionString"):
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(ep["connectionString"])
                    namespace = endpoint_props["Endpoint"].strip("sb://").split(".")[0]
                    ep["connectionString"] = cli.invoke(
                        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--queue-name {} --name {}".format(
                            namespace,
                            ep["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            for ep in endpoints["serviceBusTopics"]:
                if ep.get("connectionString"):
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(ep["connectionString"])
                    namespace = endpoint_props["Endpoint"].strip("sb://").split(".")[0]
                    ep["connectionString"] = cli.invoke(
                        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--topic-name {} --name {}".format(
                            namespace,
                            ep["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            for ep in endpoints["storageContainers"]:
                if ep.get("connectionString"):
                    endpoint_props = parse_storage_container_connection_string(ep["connectionString"])
                    ep["connectionString"] = cli.invoke(
                        "storage account show-connection-string -n {} -g {}".format(
                            endpoint_props["AccountName"],
                            ep["resourceGroup"],
                        )
                    ).as_json()["connectionString"]

            file_upload = hub_resource["properties"]["storageEndpoints"]["$default"]
            if file_upload["connectionString"]:
                endpoint_props = parse_storage_container_connection_string(file_upload["connectionString"])
                file_upload["connectionString"] = cli.invoke(
                    "storage account show-connection-string -n {}".format(
                        endpoint_props["AccountName"]
                    )
                ).as_json()["connectionString"]

        return hub_state

    def upload_hub_from_dict(self, hub_state: dict, hub_aspects: list = []):
        # Control plane
        if HubAspects.Arm.value in hub_aspects and hub_state.get("arm"):
            hub_aspects.remove(HubAspects.Arm.value)
            hub_resources = []
            hub_resource = hub_state["arm"]["resources"][0]
            hub_resource["name"] = self.hub_name
            if self.target:
                # remove/overwrite attributes that cannot be changed
                current_hub_resource = self.discovery.find_resource(self.hub_name, self.rg)
                if not self.rg:
                    self.rg = current_hub_resource.additional_properties["resourcegroup"]
                # location
                hub_resource["location"] = current_hub_resource.location
                # sku
                hub_resource["sku"] = current_hub_resource.sku.serialize()
                # event hub partitions
                partition_count = current_hub_resource.properties.event_hub_endpoints["events"].partition_count
                hub_resource["properties"]["eventHubEndpoints"]["events"]["partitionCount"] = partition_count
                # enable data residency
                hub_resource["properties"]["enableDataResidency"] = current_hub_resource.properties.enable_data_residency
                # features - hub takes care of this
                hub_resource["properties"]["features"] = current_hub_resource.properties.features
                # other props TODO!

            hub_resources.append(hub_resource)

            hub_certs = [res for res in hub_state["arm"]["resources"][1:] if res["type"].endswith("certificates")]
            if len(hub_certs) < len(hub_state["arm"]["resources"]) - 1:
                logger.warning("Private endpoints for IoT Hub will be ignored for state import.")

            for res in hub_certs:
                res["name"] = self.hub_name + "/" + res["name"].split("/")[1]
                depends_on = res["dependsOn"][0].split("'")
                depends_on[3] = self.hub_name
                res["dependsOn"][0] = "'".join(depends_on)
            hub_resources.extend(hub_certs)
            hub_state["arm"]["resources"] = hub_resources

            filename = f"arm_deployment{self.hub_name}.json"
            with open(filename, "w", encoding='utf-8') as f:
                json.dump(hub_state["arm"], f)

            arm_result = cli.invoke(
                f"deployment group create --template-file {filename} -g {self.rg}"
            )
            os.remove(filename)

            if not arm_result.success():
                raise BadRequestError(f"Arm deployment for IoT Hub {self.hub_name} failed.")

            if not self.target:
                self.target = self.discovery.get_target(
                    hub_resource["name"],
                    resource_group_name=arm_result.as_json()["resourceGroup"]
                )
                print(f"Created IoT Hub {self.hub_name}.")
            else:
                print(f"Updated IoT Hub {self.hub_name}.")

        # Data plane
        # upload configurations
        if HubAspects.Configurations.value in hub_aspects and hub_state.get("configurations"):
            hub_aspects.remove(HubAspects.Configurations.value)
            configs = hub_state["configurations"]["admConfigurations"]
            for config_id, config_obj in tqdm(configs.items(), desc="Uploading ADM Configurations"):
                try:
                    _iot_hub_configuration_create(
                        target=self.target,
                        config_id=config_id,
                        content=json.dumps(config_obj["content"]),
                        target_condition=config_obj["targetCondition"],
                        priority=config_obj["priority"],
                        labels=json.dumps(config_obj["labels"]),
                        metrics=json.dumps(config_obj["metrics"])
                    )
                except AzCLIError as e:
                    logger.error(f" Failed to upload ADM configuration {config_id}. Error Message: {e}")

            edge_deployments = hub_state["configurations"]["edgeDeployments"]
            for config_id, config_obj in tqdm(edge_deployments.items(), desc="Uploading Edge Deployments"):
                if "properties.desired" in config_obj["content"]["modulesContent"]["$edgeAgent"]:
                    config_type = ConfigType.edge
                else:
                    config_type = ConfigType.layered

                try:
                    _iot_hub_configuration_create(
                        target=self.target,
                        config_id=config_id,
                        content=json.dumps(config_obj["content"]),
                        target_condition=config_obj["targetCondition"],
                        priority=config_obj["priority"],
                        labels=json.dumps(config_obj["labels"]),
                        metrics=json.dumps(config_obj["metrics"]),
                        config_type=config_type
                    )
                except AzCLIError as e:
                    logger.error(f" Failed to upload Edge Deployment {config_id}. Error Message: {e}")

        if HubAspects.Devices.value in hub_aspects and hub_state.get("devices"):
            hub_aspects.remove(HubAspects.Devices.value)
            child_to_parent = {}
            for device_id, device_obj in tqdm(hub_state["devices"].items(), desc="Uploading devices and modules"):
                # upload device identity and twin
                try:
                    self.upload_device_identity(device_id, device_obj["identity"])
                except AzCLIError as e:
                    logger.error(
                        f" Failed to upload device identity for {device_id}. Proceeding to next device. Error Message: {e}"
                    )
                    continue

                try:
                    _iot_device_twin_update(
                        target=self.target, device_id=device_id, parameters=device_obj["twin"]
                    )
                except AzCLIError as e:
                    logger.error(
                        f" Failed to upload device twin for {device_id}. Proceeding to next device. Error Message: {e}"
                    )
                    continue

                edge_modules = {}

                for module_id, module_obj in device_obj.get("modules", {}).items():
                    # upload will fail for modules that start with $ or have no auth
                    if module_id.startswith("$") or module_obj["identity"]["authentication"]["type"] == "none":
                        edge_modules[module_id] = {
                            "properties.desired": module_obj["twin"]["properties"]["desired"]
                        }
                    else:
                        module_identity = module_obj["identity"]
                        module_twin = module_obj["twin"]

                        try:
                            self.upload_module_identity(device_id, module_id, module_identity)
                        except AzCLIError as e:
                            logger.error(
                                f" Failed to upload module identity for {module_id} for the device {device_id}. "
                                f"Proceeding to next module. Error Message: {e}"
                            )
                            continue
                        try:
                            _iot_device_module_twin_update(
                                target=self.target,
                                device_id=device_id,
                                module_id=module_id,
                                parameters=module_twin
                            )
                        except AzCLIError as e:
                            logger.error(
                                f" Failed to upload module identity for {module_id} for the device {device_id}. "
                                f"Proceeding to next module. Error Message: {e}"
                            )
                            continue

                if edge_modules:
                    try:
                        _iot_edge_set_modules(
                            target=self.target, device_id=device_id, content=json.dumps({"modulesContent": edge_modules})
                        )
                    except AzCLIError as e:
                        logger.error(
                            f" Failed to upload edge modules for the device {device_id}. Proceeding to next device. "
                            f"Error Message: {e}"
                        )
                        continue

                if device_obj.get("parent"):
                    child_to_parent[device_id] = device_obj["parent"]

            # set parent-child relationships after all devices are created
            for device_id in child_to_parent:
                try:
                    _iot_device_set_parent(target=self.target, parent_id=child_to_parent[device_id], device_id=device_id)
                except AzCLIError as e:
                    logger.error(
                        f" Failed to set parent-child relationship for the parent device {child_to_parent[device_id]} to "
                        f"the child device {device_id}. Error Message: {e}"
                    )
                    continue

        # Leftover aspects
        if hub_aspects:
            logger.warning(
                f"Some hub aspects ({', '.join(hub_aspects)}) were not uploaded because the necessary aspects were "
                "not found in the file."
            )

    # Upload commands
    def upload_device_identity(self, device_id: str, identity: dict):
        auth_type = identity["authentication"]["type"]
        edge = identity["capabilities"]["iotEdge"]
        status = identity["status"]
        ptp = identity["authentication"]["x509Thumbprint"]["primaryThumbprint"]
        stp = identity["authentication"]["x509Thumbprint"]["secondaryThumbprint"]

        if "status_reason" in identity.keys():
            status_reason = identity["statusReason"]
        else:
            status_reason = None

        if auth_type == DeviceAuthApiType.sas.value:
            pk = identity["authentication"]["symmetricKey"]["primaryKey"]
            sk = identity["authentication"]["symmetricKey"]["secondaryKey"]

            _iot_device_create(
                target=self.target,
                device_id=device_id,
                edge_enabled=edge,
                primary_key=pk,
                secondary_key=sk,
                status=status,
                status_reason=status_reason
            )

        elif auth_type == DeviceAuthApiType.selfSigned.value:
            _iot_device_create(
                target=self.target,
                device_id=device_id,
                edge_enabled=edge,
                auth_method=DeviceAuthType.x509_thumbprint.value,
                primary_thumbprint=ptp,
                secondary_thumbprint=stp,
                status=status,
                status_reason=status_reason
            )

        elif auth_type == DeviceAuthApiType.certificateAuthority.value:
            _iot_device_create(
                target=self.target,
                device_id=device_id,
                edge_enabled=edge,
                auth_method=DeviceAuthType.x509_ca.value,
                primary_thumbprint=ptp,
                secondary_thumbprint=stp,
                status=status,
                status_reason=status_reason
            )

        else:
            logger.error("Authorization type for device '{0}' not recognized.".format(device_id))

        _iot_device_show(target=self.target, device_id=device_id)

    def upload_module_identity(self, device_id: str, module_id: str, identity: dict):
        auth_type = identity["authentication"]["type"]

        if auth_type == DeviceAuthApiType.sas.value:
            pk = identity["authentication"]["symmetricKey"]["primaryKey"]
            sk = identity["authentication"]["symmetricKey"]["secondaryKey"]

            _iot_device_module_create(target=self.target, device_id=device_id, module_id=module_id, primary_key=pk,
                                      secondary_key=sk)

        elif auth_type == DeviceAuthApiType.selfSigned.value:
            ptp = identity["authentication"]["x509Thumbprint"]["primaryThumbprint"]
            stp = identity["authentication"]["x509Thumbprint"]["secondaryThumbprint"]

            _iot_device_module_create(target=self.target, device_id=device_id, module_id=module_id,
                                      auth_method=DeviceAuthType.x509_thumbprint.value, primary_thumbprint=ptp,
                                      secondary_thumbprint=stp)

        elif auth_type == DeviceAuthApiType.certificateAuthority.value:
            _iot_device_module_create(target=self.target, device_id=device_id, module_id=module_id,
                                      auth_method=DeviceAuthType.x509_ca.value)

        else:
            logger.error("Authorization type for module '{0}' in device '{1}' not recognized.".format(module_id, device_id))

    # Delete Commands
    def delete_all_configs(self):
        """Delete all configs if possible."""
        # Basic tier does not support list config
        try:
            all_configs = _iot_hub_configuration_list(target=self.target)
        except AzCLIError:
            logger.warning("Failed to retrieve configurations. Skipping configuration deletion.")
            return

        for config in tqdm(all_configs, desc="Deleting configurations from destination hub"):
            try:
                _iot_hub_configuration_delete(target=self.target, config_id=config["id"])
            except ResourceNotFoundError:
                logger.warning("Configuration '{0}' not found during hub clean-up.".format(config["id"]))

    def delete_all_devices(self):
        """Delete all devices if possible."""
        identities = _iot_device_twin_list(target=self.target, top=-1)
        for d in tqdm(identities, desc="Deleting device identities from destination hub"):
            try:
                _iot_device_delete(target=self.target, device_id=d["deviceId"])
            except ResourceNotFoundError:
                logger.warning("Device identity '{0}' not found during hub clean-up.".format(d["deviceId"]))
