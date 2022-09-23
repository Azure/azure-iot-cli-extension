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
import base64

logger = get_logger(__name__)
cli = EmbeddedCLI()

class EndpointType(Enum):
    """
    Type of the routing endpoint.
    """
    EventHub = 'eventhub'
    ServiceBusQueue = 'servicebusqueue'
    ServiceBusTopic = 'servicebustopic'
    AzureStorageContainer = 'azurestoragecontainer'


class HubAspects(Enum):
    """
    Hub aspects to import or export.
    """
    Configurations = "configurations"
    EdgeDeployments = "edgedeployments"
    Devices = "devices"
    Routes = "routes"
    Certificates = "certificates"
    Endpoints = "endpoints"
    Identities = "identities"


ALL_HUB_ASPECTS = [
    HubAspects.Configurations.value,
    HubAspects.EdgeDeployments.value,
    HubAspects.Devices.value,
    HubAspects.Routes.value,
    HubAspects.Certificates.value,
    HubAspects.Endpoints.value,
    HubAspects.Identities.value,
]


# TODO: is file storage needed? built in endpoint? -> group under endpoints

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

    def save_state(self, filename: str, overwrite_file=False, hub_aspects = None):
        '''
        Writes hub state to file
        '''
        if os.path.exists(filename) and os.stat(filename).st_size and not overwrite_file:
            raise FileOperationError(f'File {filename} is not empty. Include the --overwrite-file flag to overwrite file.')

        if not hub_aspects:
            hub_aspects = ALL_HUB_ASPECTS

        hub_state = self.process_hub_to_dict(self.target, hub_aspects)

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(hub_state, f, indent=4, sort_keys=True)

            logger.info("Saved state of IoT Hub '{}' to {}".format(self.hub_name, filename))

        except FileNotFoundError:
            raise FileOperationError(f'File {filename} does not exist.')

    def upload_state(self, filename: str, replace: Optional[bool] = None, hub_aspects = None):
        '''Uses device info from file to recreate the hub state'''
        if not hub_aspects:
            hub_aspects = ALL_HUB_ASPECTS

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
        hub_aspects = None
    ):
        '''Migrates state from original hub to destination hub.'''
        orig_hub_target = self.discovery.get_target(
            resource_name=orig_hub,
            resource_group_name=orig_rg,
            login=orig_hub_login,
            auth_type=self.auth_type
        )

        if not hub_aspects:
            hub_aspects = ALL_HUB_ASPECTS

        # Command modifies hub_aspect - make copy so we can reuse for upload
        hub_state = self.process_hub_to_dict(orig_hub_target, hub_aspects[:])
        self.delete_aspects(replace, hub_aspects)
        self.upload_hub_from_dict(hub_state, hub_aspects)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(orig_hub, self.hub_name))

    def delete_aspects(self, replace, hub_aspects=[]):
        """
        Delete all necessary hub aspects.

        If hub aspects is empty, delete all aspects. Otherwise, delete if it is present in given
        hub aspects.
        """
        if replace:
            if HubAspects.Configurations.value in hub_aspects or HubAspects.EdgeDeployments.value in hub_aspects:
                self.delete_all_configs(
                    delete_configs=HubAspects.Configurations.value in hub_aspects,
                    delete_deployments=HubAspects.EdgeDeployments.value in hub_aspects
                )
            if HubAspects.Devices.value in hub_aspects:
                self.delete_all_devices()
            with capture_stderr():
                if HubAspects.Routes.value in hub_aspects:
                    self.delete_all_routes()
                if HubAspects.Certificates.value in hub_aspects:
                    self.delete_all_certificates()
                if HubAspects.Endpoints.value in hub_aspects:
                    self.delete_all_endpoints()
                if HubAspects.Identities.value in hub_aspects:
                    self.remove_identities()

    def process_hub_to_dict(self, target: dict, hub_aspects: list = []) -> dict:
        '''Returns a dictionary containing the hub state'''
        hub_state = {}

        if HubAspects.Configurations.value in hub_aspects:
            hub_aspects.remove(HubAspects.Configurations.value)
            all_configs = _iot_hub_configuration_list(target=target)
            adm_configs = []
            for c in all_configs:
                if c["content"].get("deviceContent") or c["content"].get("moduleContent"):
                    for key in ["createdTimeUtc", "etag", "lastUpdatedTimeUtc", "schemaVersion"]:
                        c.pop(key, None)
                    adm_configs.append(c)

            hub_state["configurations"] = adm_configs
            num_configs = len(hub_state["configurations"])
            pbar = tqdm(total=num_configs, desc="Saving configurations")
            pbar.update(num_configs)
            pbar.close()

        if HubAspects.EdgeDeployments.value in hub_aspects:
            hub_aspects.remove(HubAspects.EdgeDeployments.value)
            hub_state["edgeDeployments"] = [c for c in all_configs if c["content"].get("modulesContent")]

            num_edge_deployments = len(hub_state["edgeDeployments"])
            pbar = tqdm(total=num_edge_deployments, desc="Saving edge deployments")
            pbar.update(num_edge_deployments)
            pbar.close()

        if HubAspects.Devices.value in hub_aspects:
            hub_aspects.remove(HubAspects.Devices.value)
            hub_state["devices"] = {
                "identities": [],
                "children": {}
            }
            # TODO: figure out if modules should be a subgroup of devices or not
            hub_state["modules"] = []
            identities = _iot_device_list(target=target, top=-1)

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

        control_plane = None
        hub_name = target.get("entity").split(".")[0]
        hub_rg = target.get("resourcegroup")
        if not hub_rg and hub_aspects:
            control_plane = cli.invoke(f"iot hub show -n {hub_name}").as_json()
            hub_rg = control_plane["resourcegroup"]

        if HubAspects.Certificates.value in hub_aspects:
            hub_aspects.remove(HubAspects.Certificates.value)
            hub_state["certificates"] = cli.invoke(
                "iot hub certificate list --hub-name {} -g {}".format(hub_name, hub_rg)
            ).as_json()["value"]

            pbar = tqdm(total=len(hub_state["certificates"]), desc="Saving certificates", file=sys.stdout)
            pbar.update(len(hub_state["certificates"]))
            pbar.close()

        if HubAspects.Identities.value in hub_aspects:
            hub_aspects.remove(HubAspects.Identities.value)
            control_plane = control_plane or cli.invoke("iot hub show -n {} -g {}".format(hub_name, hub_rg)).as_json()
            if control_plane["identity"]["userAssignedIdentities"]:
                hub_state["identities"] = control_plane["identity"]["userAssignedIdentities"]
            else:
                hub_state["identities"] = []
            num_identities = len(hub_state["identities"])

            pbar = tqdm(total=num_identities, desc="Saving user-assigned identities", file=sys.stdout)
            pbar.update(num_identities)
            pbar.close()

        if HubAspects.Endpoints.value in hub_aspects:
            hub_aspects.remove(HubAspects.Endpoints.value)
            control_plane = control_plane or cli.invoke("iot hub show -n {} -g {}".format(hub_name, hub_rg)).as_json()
            hub_state["endpoints"] = control_plane["properties"]["routing"]["endpoints"]

            # Retrieve the connection strings if needed
            eventHubs = hub_state["endpoints"]["eventHubs"]
            for endpoint in eventHubs:
                if endpoint["authenticationType"] != "identityBased":
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(endpoint["connectionString"])
                    namespace = endpoint_props ["Endpoint"].trim("sb://").split(".")[0]
                    endpoint["connectionString"] = cli.invoke(
                        "eventhubs eventhub authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--eventhub-name {} --name {}".format(
                            namespace,
                            endpoint["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            serviceBusQueues = hub_state["endpoints"]["serviceBusQueues"]
            for endpoint in serviceBusQueues:
                if endpoint["authenticationType"] != "identityBased":
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(endpoint["connectionString"])
                    namespace = endpoint_props ["Endpoint"].trim("sb://").split(".")[0]
                    endpoint["connectionString"] = cli.invoke(
                        "servicebus queue authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--queue-name {} --name {}".format(
                            namespace,
                            endpoint["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            serviceBusTopics = hub_state["endpoints"]["serviceBusTopics"]
            for endpoint in serviceBusTopics:
                if endpoint["authenticationType"] != "identityBased":
                    endpoint_props = parse_iot_hub_message_endpoint_connection_string(endpoint["connectionString"])
                    namespace = endpoint_props ["Endpoint"].trim("sb://").split(".")[0]
                    endpoint["connectionString"] = cli.invoke(
                        "servicebus topic authorization-rule keys list --namespace-name {} --resource-group {} "
                        "--topic-name {} --name {}".format(
                            namespace,
                            endpoint["resourceGroup"],
                            endpoint_props["EntityPath"],
                            endpoint_props["SharedAccessKeyName"]
                        )
                    ).as_json()["primaryConnectionString"]
            storageContainers = hub_state["endpoints"]["storageContainers"]
            for endpoint in storageContainers:
                if endpoint["authenticationType"] != "identityBased":
                    endpoint_props = parse_storage_container_connection_string(endpoint["connectionString"])
                    endpoint["connectionString"] = cli.invoke(
                        "storage account show-connection-string -n {} -g {}".format(
                            endpoint_props["AccountName"],
                            endpoint["resourceGroup"],
                        )
                    ).as_json()["connectionString"]
            num_endpoints = len(eventHubs) + len(serviceBusQueues) + len(serviceBusTopics) + len(storageContainers)

            pbar = tqdm(total=num_endpoints, desc="Saving endpoints", file=sys.stdout)
            pbar.update(num_endpoints)
            pbar.close()

        if HubAspects.Routes.value in hub_aspects:
            hub_aspects.remove(HubAspects.Routes.value)
            control_plane = control_plane or cli.invoke("iot hub show -n {} -g {}".format(hub_name, hub_rg)).as_json()
            hub_state["routes"] = control_plane["properties"]["routing"]["routes"]

            pbar = tqdm(total=len(hub_state["routes"]), desc="Saving routes", file=sys.stdout)
            pbar.update(len(hub_state["routes"]))
            pbar.close()

        return hub_state

    def upload_hub_from_dict(self, hub_state: dict, hub_aspects: list = []):
        # upload configurations
        if HubAspects.Configurations.value in hub_aspects and hub_state.get("configurations"):
            hub_aspects.remove(HubAspects.Configurations.value)
            configs = hub_state["configurations"]
            for i in tqdm(range(len(configs)), desc="Uploading hub configurations", file=sys.stdout):
                c = configs[i]
                _iot_hub_configuration_create(
                    target=self.target, config_id=c["id"], content=json.dumps(c["content"]),
                    target_condition=c["targetCondition"], priority=c["priority"],
                    labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"])
                )

        if HubAspects.EdgeDeployments.value in hub_aspects and hub_state.get("edgeDeployments"):
            hub_aspects.remove(HubAspects.EdgeDeployments.value)
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

        if HubAspects.Devices.value in hub_aspects and hub_state.get("devices"):
            hub_aspects.remove(HubAspects.Devices.value)
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

        if not hub_aspects:
            return

        with capture_stderr():
            if not self.rg:
                control_plane = cli.invoke(f"iot hub show -n {self.hub_name}").as_json()
                self.rg = control_plane["resourcegroup"]

            if HubAspects.Certificates.value in hub_aspects and hub_state.get("certificates"):
                hub_aspects.remove(HubAspects.Certificates.value)
                temp_cert_file = f"cert{random.randrange(100000000)}.cer"

                for cert in tqdm(hub_state["certificates"], desc="Uploading certificates", file=sys.stdout):
                    with open(temp_cert_file, 'w', encoding='utf-8') as f:
                        cert_body = base64.b64decode(cert["properties"]["certificate"]).decode("utf-8")
                        cert_body = "".join(cert_body.split("\r"))
                        f.write(cert_body)
                    cli.invoke(
                        f"iot hub certificate create --name {cert['name']} -g {self.rg} --hub-name {self.hub_name} --path "
                        f"{temp_cert_file} -v {cert['properties']['isVerified']}"
                    )

                if os.path.isfile(temp_cert_file):
                    os.remove(temp_cert_file)

            if HubAspects.Identities.value in hub_aspects and hub_state.get("identities"):
                hub_aspects.remove(HubAspects.Identities.value)
                self.assign_identities_to_hub(hub_state["identities"])

            if HubAspects.Endpoints.value in hub_aspects and hub_state.get("endpoints"):
                hub_aspects.remove(HubAspects.Endpoints.value)
                self.upload_endpoints(hub_state["endpoints"])

            if HubAspects.Routes.value in hub_aspects and hub_state.get("routes"):
                hub_aspects.remove(HubAspects.Routes.value)
                for route in tqdm(hub_state["routes"], desc="Uploading routes", file=sys.stdout):
                    cli.invoke(
                        f"iot hub route create --endpoint {route['endpointNames'][0]} --hub-name {self.hub_name} "
                        f"-g {self.rg} --name {route['name']} --source {route['source']} "
                        f"--condition {route['condition']} --enabled {route['isEnabled']}"
                    )

    def assign_identities_to_hub(self, identities):
        pbar = tqdm(total=len(identities), desc="Assigning identities", file=sys.stdout)

        if identities:
            userIds = ""
            for userId in identities:
                userIds += userId + " "
            cli.invoke("iot hub identity assign --name {} -g {} --user-assigned {}".format(self.hub_name, self.rg, userIds))
            pbar.update(len(identities))

        pbar.close()

    def upload_endpoint(self, ep, ep_type):
        if ep["connectionString"]:
            if ep_type == EndpointType.AzureStorageContainer.value:
                cs = parse_storage_container_connection_string(ep["connectionString"])
                ep["connectionString"] = cli.invoke("storage account show-connection-string --name {} -g {}".format(
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

                keys = cli.invoke("{} authorization-rule keys list {} {} --namespace-name {} -g {} -n {}".format(type_str,
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

        cli.invoke(f"iot hub routing-endpoint create --hub-name {self.hub_name} -g {self.rg} --endpoint-name {ep['name']} "
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

    # Delete Commands
    def delete_all_configs(self, delete_configs: bool = False, delete_deployments: bool = False):
        all_configs = _iot_hub_configuration_list(target=self.target)
        if delete_configs:
            configurations = [
                c for c in all_configs if (c["content"].get("deviceContent") or c["content"].get("moduleContent"))
            ]
            for i in tqdm(range(len(configurations)), desc="Deleting configurations from destination hub"):
                c = configurations[i]
                try:
                    _iot_hub_configuration_delete(target=self.target, config_id=c["id"])
                except ResourceNotFoundError:
                    logger.warning("Configuration '{0}' not found during hub clean-up.".format(c["id"]))
        if delete_deployments:
            deployments = [c for c in all_configs if c["content"].get("modulesContent")]
            for i in tqdm(range(len(deployments)), desc="Deleting edge deployments from destination hub"):
                c = deployments[i]
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
        certificates = cli.invoke("iot hub certificate list --hub-name {} -g {}".format(self.hub_name, self.rg)).as_json()
        for i in tqdm(range(len(certificates["value"])), desc="Deleting certificates from destination hub", file=sys.stdout):
            c = certificates["value"][i]
            cli.invoke("iot hub certificate delete --name {} --etag {} --hub-name {} -g {}".format(c["name"], c["etag"],
                                                                                                        self.hub_name, self.rg))

    def delete_all_endpoints(self):
        endpoints = cli.invoke(f"iot hub routing-endpoint list --hub-name {self.hub_name} -g {self.rg}").as_json()
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]

        num_endpoints = len(eventHubs) + len(serviceBusQueues) + len(serviceBusTopics) + len(storageContainers)
        pbar = tqdm(total=num_endpoints, desc="Deleting endpoints from destination hub", file=sys.stdout)

        for ep in eventHubs:
            cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type eventhub")
            pbar.update(1)
        for ep in serviceBusQueues:
            cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebusqueue")
            pbar.update(1)
        for ep in serviceBusTopics:
            cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type servicebustopic")
            pbar.update(1)
        for ep in storageContainers:
            cli.invoke(f"iot hub routing-endpoint delete --hub-name {self.hub_name} -g {self.rg} --endpoint-name "
                            f"{ep['name']} --endpoint-type azurestoragecontainer")
            pbar.update(1)

        pbar.close()

    def delete_all_routes(self):
        routes = cli.invoke(f"iot hub route list --hub-name {self.hub_name} -g {self.rg}").as_json()
        for i in tqdm(range(len(routes)), desc="Deleting routes from destination hub", file=sys.stdout):
            route = routes[i]
            cli.invoke(f"iot hub route delete --hub-name {self.hub_name} -g {self.rg} --name {route['name']}")

    def remove_identities(self):
        userAssignedIds = cli.invoke(
            f"iot hub identity show -n {self.hub_name} -g {self.rg}"
        ).as_json()["userAssignedIdentities"]
        if userAssignedIds:
            userAssignedIds = " ".join(userAssignedIds.keys())
            cli.invoke(f"iot hub identity remove -n {self.hub_name} -g {self.rg} --user-assigned {userAssignedIds}")