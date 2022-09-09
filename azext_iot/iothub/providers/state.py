# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum
from knack.log import get_logger

from azext_iot.common.shared import DeviceAuthApiType, DeviceAuthType, ConfigType
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common._azure import parse_iot_hub_message_endpoint_connection_string, parse_storage_container_connection_string
from azure.cli.core.azclierror import FileOperationError, ResourceNotFoundError
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import capture_stderr
from azext_iot.constants import IMMUTABLE_DEVICE_IDENTITY_FIELDS, IMMUTABLE_MODULE_IDENTITY_FIELDS, IMMUTABLE_MODULE_TWIN_FIELDS
from azext_iot.operations.hub import (
    _iot_device_show,
    _iot_device_module_twin_show,
    _iot_device_module_create,
    _iot_device_module_show,
    _iot_device_create,
    _iot_device_delete,
    _iot_hub_configuration_delete,
    _iot_device_twin_replace,
    _iot_device_module_list,
    _iot_device_module_twin_replace,
    _iot_device_list,
    _iot_hub_configuration_list,
    _iot_hub_configuration_create,
    _iot_device_children_list,
    _iot_device_children_add
)

import json
from tqdm import tqdm
from typing import Optional
import os
import sys
import random

logger = get_logger(__name__)

class EndpointType(Enum):
    """
    Type of the routing endpoint.
    """
    EventHub = 'eventhub'
    ServiceBusQueue = 'servicebusqueue'
    ServiceBusTopic = 'servicebustopic'
    AzureStorageContainer = 'azurestoragecontainer'


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

    def save_state(self, filename: str, overwrite_file=False):
        '''
        Writes all hub configurations, device identities and device twins from the origin hub to a json file
        {
            "configurations": [{}, ...],
            "edgeDeployments": [{}, ...],
            "devices": {
                "deviceId": {},
                ...
            }
            "modules": {
                "deviceId": [ [{identity}, {twin}], ... ],
                ...
            }
        }
        '''
        if os.path.exists(filename) and os.stat(filename).st_size and not overwrite_file:
            raise FileOperationError(f'File {filename} is not empty. Include the --overwrite-file flag to overwrite file.')

        hub_state = self.process_hub(self.target)

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(hub_state, f)

            logger.info("Saved state of IoT Hub '{}' to {}".format(self.hub_name, filename))

        except FileNotFoundError:
            raise FileOperationError(f'File {filename} does not exist.')

    def upload_state(self, filename: str, replace: Optional[bool] = None):
        '''Uses device info from file to recreate the hub state'''

        if replace:
            self.delete_all_configs()
            self.delete_all_devices()

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                hub_state = json.load(f)

            self.upload_hub_from_dict(hub_state)
            logger.info("Uploaded state from '{}' to IoT Hub '{}'".format(filename, self.hub_name))

        except FileNotFoundError:
            raise FileOperationError(f'File {filename} does not exist.')

    def migrate_state(
        self,
        orig_hub: Optional[str] = None,
        orig_rg: Optional[str] = None,
        orig_hub_login: Optional[str] = None,
        replace: Optional[bool] = False,
    ):
        '''Migrates state from original hub to destination hub.'''
        orig_hub_target = self.discovery.get_target(
            resource_name=orig_hub,
            resource_group_name=orig_rg,
            login=orig_hub_login,
            auth_type=self.auth_type
        )

        if replace:
            self.delete_all_configs()
            self.delete_all_devices()

        hub_state = self.process_hub(orig_hub_target)
        self.upload_hub_from_dict(hub_state)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(orig_hub, self.hub_name))

    def process_hub(self, target: dict):
        '''Returns a dictionary containing the hub state'''

        hub_state = {}

        all_configs = _iot_hub_configuration_list(target=target)

        adm_configs = [
            c for c in all_configs if (c["content"].get("deviceContent") or c["content"].get("moduleContent"))
        ]
        for c in adm_configs:
            for key in ["createdTimeUtc", "etag", "lastUpdatedTimeUtc", "schemaVersion"]:
                c.pop(key, None)

        hub_state["configurations"] = adm_configs

        num_configs = len(hub_state["configurations"])
        pbar = tqdm(total=num_configs, desc="Saving configurations")
        pbar.update(num_configs)
        pbar.close()

        hub_state["edgeDeployments"] = [c for c in all_configs if c["content"].get("modulesContent")]

        num_edge_deployments = len(hub_state["edgeDeployments"])
        pbar = tqdm(total=num_edge_deployments, desc="Saving edge deployments")
        pbar.update(num_edge_deployments)
        pbar.close()

        identities = _iot_device_list(target=target, top=-1)

        hub_state["devices"] = {
            "identities": [],
            "children": {}
        }
        hub_state["modules"] = []

        for i in tqdm(range(len(identities)), desc="Saving devices and modules"):

            id = identities[i]

            module_objs = _iot_device_module_list(target=target, device_id=id["deviceId"])

            # primary and secondary keys show up in the "show" output but not in the "list" output
            if id["authenticationType"] == DeviceAuthApiType.sas.value:
                id2 = _iot_device_show(target=target, device_id=id["deviceId"])
                identities[i]["symmetricKey"] = id2["authentication"]["symmetricKey"]

            if id["capabilities"]["iotEdge"]:
                children = _iot_device_children_list(target=target, device_id=id["deviceId"])
                hub_state["devices"]["children"][id["deviceId"]] = [c["deviceId"] for c in children]

            identities[i]["properties"].pop("reported")
            for key in ["$metadata", "$version"]:
                identities[i]["properties"]["desired"].pop(key)
            for key in IMMUTABLE_DEVICE_IDENTITY_FIELDS:
                identities[i].pop(key, None)
            hub_state["devices"]["identities"].append(identities[i])

            for module in module_objs:
                module = vars(module)

                if module["module_id"] not in ["$edgeAgent", "$edgeHub"]:
                    module_twin = _iot_device_module_twin_show(target=target, device_id=id["deviceId"],
                                                               module_id=module["module_id"])

                    module2 = _iot_device_module_show(target=target, device_id=id["deviceId"], module_id=module["module_id"])
                    module["authentication"] = module2["authentication"]

                    for key in IMMUTABLE_MODULE_IDENTITY_FIELDS:
                        module.pop(key)
                    for key in IMMUTABLE_MODULE_TWIN_FIELDS:
                        module_twin.pop(key)
                    for key in ["$metadata", "$version"]:
                        module_twin["properties"]["desired"].pop(key)
                    module_twin["properties"].pop("reported")

                    hub_state["modules"].append([module, module_twin])

        return hub_state

    def upload_hub_from_dict(self, hub_state: dict):
        # upload configurations
        configs = hub_state["configurations"]
        for i in tqdm(range(len(configs)), desc="Uploading hub configurations", file=sys.stdout):
            c = configs[i]
            _iot_hub_configuration_create(
                target=self.target, config_id=c["id"], content=json.dumps(c["content"]),
                target_condition=c["targetCondition"], priority=c["priority"],
                labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"])
            )

        edge_deployments = hub_state["edgeDeployments"]

        for i in tqdm(range(len(edge_deployments)), desc="Uploading edge deployments", file=sys.stdout):
            d = edge_deployments[i]

            if "properties.desired" in d["content"]["modulesContent"]["$edgeAgent"]:
                config_type = ConfigType.edge
            else:
                config_type = ConfigType.layered

            _iot_hub_configuration_create(
                target=self.target, config_id=d["id"], content=json.dumps(d["content"]),
                target_condition=d["targetCondition"], priority=d["priority"],
                labels=json.dumps(d["labels"]), metrics=json.dumps(d["metrics"]),
                config_type=config_type
            )

        for identity in tqdm(hub_state["devices"]["identities"], desc="Uploading devices", file=sys.stdout):

            # upload device identity and twin
            self.upload_device_identity(identity)

            # all necessary twin attributes are already included in the identity
            # symmetricKey isn't a valid twin attribute
            twin = identity
            if identity["authenticationType"] == DeviceAuthApiType.sas.value:
                twin.pop("symmetricKey")

            _iot_device_twin_replace(target=self.target, device_id=identity["deviceId"], target_json=json.dumps(twin))

        for module_info in tqdm(hub_state["modules"], desc="Uploading modules", file=sys.stdout):
            module_identity = module_info[0]
            module_twin = module_info[1]

            self.upload_module_identity(module_identity)
            _iot_device_module_twin_replace(target=self.target, device_id=module_identity["device_id"],
                                            module_id=module_identity["module_id"], target_json=json.dumps(module_twin))

        # set parent-child relationships
        for parentId in hub_state["devices"]["children"]:
            child_list = hub_state["devices"]["children"][parentId]
            _iot_device_children_add(target=self.target, device_id=parentId, child_list=child_list)

    def assign_identities_to_hub(self, identities):

        pbar = tqdm(total=len(identities), desc="Assigning identities", file=sys.stdout)

        if identities:
            userIds = ""
            for userId in identities:
                userIds += userId + " "
            self.cli.invoke("iot hub identity assign --name {} -g {} --user-assigned {}".format(self.hub_name, self.rg, userIds))
            pbar.update(len(identities))

        pbar.close()

    def upload_endpoint(self, ep, ep_type):

        if ep["connectionString"]:

            if ep_type == EndpointType.AzureStorageContainer.value:
                cs = parse_storage_container_connection_string(ep["connectionString"])
                ep["connectionString"] = self.cli.invoke("storage account show-connection-string --name {} -g {}".format(
                    cs["AccountName"], ep["resourceGroup"])).as_json()["connectionString"]
            else:
                cs = parse_iot_hub_message_endpoint_connection_string(ep["connectionString"])
                namespace = cs["Endpoint"].split('.')[0][5:]

                if ep_type == EndpointType.EventHub.value:
                    type_str = "eventhubs eventhub"
                    entity_str = "--eventhub-name"
                elif ep_type == EndpointType.ServiceBusQueue.value:
                    type_str = "servicebus queue"
                    entity_str = "--queue-name"
                elif ep_type == EndpointType.ServiceBusTopic.value:
                    type_str = "servicebus topic"
                    entity_str = "--topic-name"

                keys = self.cli.invoke("{} authorization-rule keys list {} {} --namespace-name {} -g {} -n {}".format(type_str,
                                       entity_str, cs["EntityPath"], namespace, ep["resourceGroup"], cs["SharedAccessKeyName"])
                                       ).as_json()

                ep["connectionString"] = keys["primaryConnectionString"]

        if ep["authenticationType"] == "identityBased":

            parameters = "--endpoint-uri {} ".format(ep["endpointUri"])

            if ep_type != EndpointType.AzureStorageContainer.value:
                parameters += "--entity-path {} ".format(ep["entityPath"])

            if ep["identity"]:
                id = ep["identity"]["userAssignedIdentity"]
                parameters += "--identity {} ".format(id)

        else:
            parameters = "-c {} ".format(ep["connectionString"])

        if ep["authenticationType"]:
            parameters += "--auth-type {} ".format(ep["authenticationType"])

        if ep_type == EndpointType.AzureStorageContainer.value:
            max_chunk_size = int(ep["maxChunkSizeInBytes"] / 1048576)
            parameters += f"--container-name {ep['containerName']} --encoding {ep['encoding']} --batch-frequency " + \
                          f"{ep['batchFrequencyInSeconds']} --chunk-size {max_chunk_size} --file-name-format " + \
                          ep['fileNameFormat']

        self.cli.invoke(f"iot hub routing-endpoint create --hub-name {self.hub_name} -g {self.rg} --endpoint-name {ep['name']} "
                        f"--erg {ep['resourceGroup']} --endpoint-subscription-id {ep['subscriptionId']} --type {ep_type} "
                        f"{parameters}")

    def upload_endpoints(self, endpoints):
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]

        num_endpoints = len(eventHubs) + len(serviceBusQueues) + len(serviceBusTopics) + len(storageContainers)
        pbar = tqdm(total=num_endpoints, desc="Uploading endpoints", file=sys.stdout)

        for ep in eventHubs:
            self.upload_endpoint(ep, EndpointType.EventHub.value)
            pbar.update(1)
        for ep in serviceBusQueues:
            self.upload_endpoint(ep, EndpointType.ServiceBusQueue.value)
            pbar.update(1)
        for ep in serviceBusTopics:
            self.upload_endpoint(ep, EndpointType.ServiceBusTopic.value)
            pbar.update(1)
        for ep in storageContainers:
            self.upload_endpoint(ep, EndpointType.AzureStorageContainer.value)
            pbar.update(1)

        pbar.close()

    def upload_device_identity(self, identity: dict):
        device_id = identity["deviceId"]
        auth_type = identity["authenticationType"]
        edge = identity["capabilities"]["iotEdge"]
        status = identity["status"]
        ptp = identity["x509Thumbprint"]["primaryThumbprint"]
        stp = identity["x509Thumbprint"]["secondaryThumbprint"]

        if "status_reason" in identity.keys():
            status_reason = identity["statusReason"]
        else:
            status_reason = None

        if auth_type == DeviceAuthApiType.sas.value:
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            x = _iot_device_create(target=self.target, device_id=device_id, edge_enabled=edge, primary_key=pk, secondary_key=sk,
                               status=status, status_reason=status_reason)

        elif auth_type == DeviceAuthApiType.selfSigned.value:
            x = _iot_device_create(target=self.target, device_id=device_id, edge_enabled=edge,
                               auth_method=DeviceAuthType.x509_thumbprint.value, primary_thumbprint=ptp,
                               secondary_thumbprint=stp, status=status, status_reason=status_reason)

        elif auth_type == DeviceAuthApiType.certificateAuthority.value:
            x = _iot_device_create(target=self.target, device_id=device_id, edge_enabled=edge,
                               auth_method=DeviceAuthType.x509_ca.value, primary_thumbprint=ptp, secondary_thumbprint=stp,
                               status=status, status_reason=status_reason)

        else:
            logger.error("Authorization type for device '{0}' not recognized.".format(device_id))
        print(f"added {device_id}")
        try:
            _iot_device_show(target=self.target, device_id=device_id)
        except ResourceNotFoundError:
            import pdb; pdb.set_trace()

    def upload_module_identity(self, identity: dict):

        device_id = identity["device_id"]
        module_id = identity["module_id"]
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

    def delete_all_configs(self):
        configs = _iot_hub_configuration_list(target=self.target)
        for i in tqdm(range(len(configs)), desc="Deleting configurations and edge deployments from destination hub"):
            c = configs[i]
            try:
                _iot_hub_configuration_delete(target=self.target, config_id=c["id"])
            except ResourceNotFoundError:
                logger.warning("Configuration '{0}' not found during hub clean-up.".format(c["id"]))


    def delete_all_devices(self):
        identities = _iot_device_list(target=self.target, top=-1)
        for i in tqdm(range(len(identities)), desc="Deleting identities from destination hub"):
            id = identities[i]
            try:
                _iot_device_delete(target=self.target, device_id=id["deviceId"])
            except ResourceNotFoundError:
                logger.warning("Device identity '{0}' not found during hub clean-up.".format(id["deviceId"]))

    def delete_all_certificates(self):
        certificates = self.cli.invoke("iot hub certificate list --hub-name {} -g {}".format(self.hub_name, self.rg)).as_json()
        for i in tqdm(range(len(certificates["value"])), desc="Deleting certificates from destination hub", file=sys.stdout):
            c = certificates["value"][i]
            self.cli.invoke("iot hub certificate delete --name {} --etag {} --hub-name {} -g {}".format(c["name"], c["etag"],
                                                                                                        self.hub_name, self.rg))

    def delete_all_endpoints(self):
        endpoints = self.cli.invoke(f"iot hub routing-endpoint list --hub-name {self.hub_name} -g {self.rg}").as_json()
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]

        num_endpoints = len(eventHubs) + len(serviceBusQueues) + len(serviceBusTopics) + len(storageContainers)
        pbar = tqdm(total=num_endpoints, desc="Deleting endpoints from destination hub", file=sys.stdout)

        for ep in eventHubs:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type eventhub")
            pbar.update(1)
        for ep in serviceBusQueues:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebusqueue")
            pbar.update(1)
        for ep in serviceBusTopics:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebustopic")
            pbar.update(1)
        for ep in storageContainers:
            self.cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type azurestoragecontainer")
            pbar.update(1)

        pbar.close()

    def delete_all_routes(self):
        routes = self.cli.invoke(f"iot hub route list --hub-name {self.hub_name} -g {self.rg}").as_json()
        for i in tqdm(range(len(routes)), desc="Deleting routes from destination hub", file=sys.stdout):
            route = routes[i]
            self.cli.invoke(f"iot hub route delete --hub-name {self.hub_name} -g {self.rg} --name {route['name']}")

    def remove_identities(self):
        userAssignedIds = self.cli.invoke(
            f"iot hub identity show -n {self.hub_name} -g {self.rg}"
        ).as_json()["userAssignedIdentities"]
        if userAssignedIds:
            userAssignedIds = " ".join(userAssignedIds.keys())
            self.cli.invoke(f"iot hub identity remove -n {self.hub_name} -g {self.rg} --user-assigned {userAssignedIds}")