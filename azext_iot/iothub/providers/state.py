# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum
from time import sleep
from knack.log import get_logger

from azext_iot.common.shared import DeviceAuthApiType, DeviceAuthType, ConfigType
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.common._azure import parse_iot_hub_message_endpoint_connection_string, parse_storage_container_connection_string
from azure.cli.core.azclierror import FileOperationError, ResourceNotFoundError
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import capture_stderr
# from azext_iot.constants import IMMUTABLE_DEVICE_IDENTITY_FIELDS, IMMUTABLE_MODULE_IDENTITY_FIELDS, IMMUTABLE_MODULE_TWIN_FIELDS
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
from azext_iot._factory import iot_hub_full_service_factory

from azure.mgmt.iothub.models import (
    IotHubSku,
    AccessRights,
    ArmIdentity,
    CertificateDescription,
    CertificateProperties,
    CertificateVerificationDescription,
    CloudToDeviceProperties,
    IotHubDescription,
    IotHubSkuInfo,
    SharedAccessSignatureAuthorizationRule,
    IotHubProperties,
    EventHubProperties,
    EventHubConsumerGroupBodyDescription,
    EventHubConsumerGroupName,
    FailoverInput,
    FeedbackProperties,
    ManagedIdentity,
    MessagingEndpointProperties,
    OperationInputs,
    EnrichmentProperties,
    RoutingEventHubProperties,
    RoutingServiceBusQueueEndpointProperties,
    RoutingServiceBusTopicEndpointProperties,
    RoutingStorageContainerProperties,
    RouteProperties,
    RoutingMessage,
    StorageEndpointProperties,
    TestRouteInput,
    TestAllRoutesInput
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


IMMUTABLE_DEVICE_IDENTITY_FIELDS = [
    "cloudToDeviceMessageCount",
    "configurations",
    "deviceEtag",
    "deviceScope",
    "lastActivityTime",
    "modelId",
    "parentScopes",
    "statusUpdateTime",
    "etag",
    "version"
]
IMMUTABLE_MODULE_IDENTITY_FIELDS = [
    "connectionStateUpdatedTime",
    "lastActivityTime",
    "cloudToDeviceMessageCount",
    "etag"
]
IMMUTABLE_MODULE_TWIN_FIELDS = [
    "deviceEtag",
    "lastActivityTime",
    "etag",
    "version",
    "cloudToDeviceMessageCount",
    "statusUpdateTime"
]

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
    Network = "network"
    BuiltIn = "builtin"
    Policy = "policy"

    @classmethod
    def list(cls):
        return list(map(lambda c: c.value, cls))


class AuthenticationType(Enum):
    """
    Type of the Authentication for the routing endpoint.
    """
    KeyBased = 'keyBased'
    IdentityBased = 'identityBased'


# pylint: disable=too-few-public-methods
class IdentityType(Enum):
    """
    Type of managed identity for the IoT Hub.
    """
    SystemAssigned = "SystemAssigned"
    UserAssigned = "UserAssigned"
    SystemAndUserAssigned = "SystemAssigned, UserAssigned"
    NoneAssigned = "None"


ALL_HUB_ASPECTS = HubAspects.list()


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

    def get_client(self):
        return iot_hub_full_service_factory(self.cmd.cli_ctx)

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
            identities = _iot_device_list(target=target, top=-1)

            for i in tqdm(range(len(identities)), desc="Saving devices and modules"):
                id = identities[i]
                device_obj = {}

                # primary and secondary keys show up in the "show" output but not in the "list" output
                if id["authenticationType"] == DeviceAuthApiType.sas.value:
                    id2 = _iot_device_show(target=target, device_id=id["deviceId"])
                    id["symmetricKey"] = id2["authentication"]["symmetricKey"]

                id["properties"].pop("reported")
                for key in ["$metadata", "$version"]:
                    id["properties"]["desired"].pop(key)
                for key in IMMUTABLE_DEVICE_IDENTITY_FIELDS:
                    id.pop(key, None)

                device_obj["identity"] = id

                module_objs = _iot_device_module_list(target=target, device_id=id["deviceId"])
                if module_objs:
                    device_obj["modules"] = {}
                for module in module_objs:
                    module = module.serialize()

                    if module["moduleId"] not in ["$edgeAgent", "$edgeHub"]:
                        module_twin = _iot_device_module_twin_show(target=target, device_id=id["deviceId"],
                                                                module_id=module["moduleId"])

                        module2 = _iot_device_module_show(
                            target=target, device_id=id["deviceId"], module_id=module["moduleId"]
                        )
                        module["authentication"] = module2["authentication"]

                        for key in IMMUTABLE_MODULE_IDENTITY_FIELDS:
                            module.pop(key)
                        for key in IMMUTABLE_MODULE_TWIN_FIELDS:
                            module_twin.pop(key)
                        for key in ["$metadata", "$version"]:
                            module_twin["properties"]["desired"].pop(key)
                        module_twin["properties"].pop("reported")

                        device_obj["modules"][module["moduleId"]] = {
                            "identity": module,
                            "twin": module_twin
                        }
                hub_state["devices"][id["deviceId"]] = device_obj


        hub_name = target.get("entity").split(".")[0]
        hub_rg = target.get("resourcegroup")

        control_plane_obj = self.discovery.find_resource(hub_name, hub_rg)

        if not hub_rg:
            hub_rg = control_plane_obj.additional_properties["resourcegroup"]
        hub_resource_id = control_plane_obj.id

        if HubAspects.Routes.value in hub_aspects:
            hub_arm = cli.invoke(f"group export -n {hub_rg} --resource-ids {hub_resource_id}").as_json()
            import pdb; pdb.set_trace()
            hub_state["arm"] = hub_arm

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



    def assign_identities_to_hub(self, control_plane, identities):
        # pbar = tqdm(total=len(identities), desc="Assigning identities", file=sys.stdout)

        if identities:
            if control_plane.identity.type == IdentityType.SystemAssigned.value:
                control_plane.identity.type = IdentityType.SystemAndUserAssigned.value
            elif control_plane.identity.type == IdentityType.NoneAssigned.value:
                control_plane.identity.type == IdentityType.UserAssigned.value
            if not control_plane.identity.user_assigned_identities:
                control_plane.identity.user_assigned_identities = {}
            for userId in identities:
                control_plane.identity.user_assigned_identities[userId] = {}
                # pbar.update(1)

        # pbar.close()

    def upload_endpoints(self, control_plane, endpoints):
        eventHubs = endpoints["eventHubs"]
        serviceBusQueues = endpoints["serviceBusQueues"]
        serviceBusTopics = endpoints["serviceBusTopics"]
        storageContainers = endpoints["storageContainers"]

        num_endpoints = len(eventHubs) + len(serviceBusQueues) + len(serviceBusTopics) + len(storageContainers)
        # pbar = tqdm(total=num_endpoints, desc="Uploading endpoints", file=sys.stdout)
        cendpoints = control_plane.properties.routing.endpoints

        for ep in eventHubs:
            endpoint_identity = (
                ManagedIdentity(ep["identity"]["userAssignedIdentity"]) if ep.get("identity") else None
            )
            cendpoints.event_hubs.append({
                "connectionString": ep.get("connectionString"),
                "name": ep["name"],
                "subscriptionId": ep["subscriptionId"],
                "resourceGroup": ep["resourceGroup"],
                "authenticationType": ep.get("authenticationType"),
                "endpointUri": ep.get("endpointUri"),
                "entityPath": ep.get("entityPath"),
                "identity": endpoint_identity
            })
            # pbar.update(1)
        for ep in serviceBusQueues:
            endpoint_identity = (
                ManagedIdentity(ep["identity"]["userAssignedIdentity"]) if ep.get("identity") else None
            )
            cendpoints.service_bus_queues.append({
                "connectionString": ep.get("connectionString"),
                "name": ep["name"],
                "subscriptionId": ep["subscriptionId"],
                "resourceGroup": ep["resourceGroup"],
                "authenticationType": ep.get("authenticationType"),
                "endpointUri": ep.get("endpointUri"),
                "entityPath": ep.get("entityPath"),
                "identity": endpoint_identity
            })
            # pbar.update(1)
        for ep in serviceBusTopics:
            endpoint_identity = (
                ManagedIdentity(ep["identity"]["userAssignedIdentity"]) if ep.get("identity") else None
            )
            cendpoints.service_bus_topics.append({
                "connectionString": ep.get("connectionString"),
                "name": ep["name"],
                "subscriptionId": ep["subscriptionId"],
                "resourceGroup": ep["resourceGroup"],
                "authenticationType": ep.get("authenticationType"),
                "endpointUri": ep.get("endpointUri"),
                "entityPath": ep.get("entityPath"),
                "identity": endpoint_identity
            })
            # pbar.update(1)
        for ep in storageContainers:
            endpoint_identity = (
                ManagedIdentity(ep["identity"]["userAssignedIdentity"]) if ep.get("identity") else None
            )
            cendpoints.storage_containers.append({
                "connectionString": ep.get("connectionString"),
                "name": ep["name"],
                "subscriptionId": ep["subscriptionId"],
                "resourceGroup": ep["resourceGroup"],
                "containerName": ep['containerName'],
                "encoding": ep['encoding'],
                "fileNameFormat": ep['fileNameFormat'],
                "batchFrequencyInSeconds": ep['batchFrequencyInSeconds'],
                "maxChunkSizeInBytes": ep["maxChunkSizeInBytes"],
                "authenticationType": ep.get("authenticationType"),
                "endpointUri": ep.get("endpointUri"),
                "identity": endpoint_identity
            })
            # pbar.update(1)

        # pbar.close()

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
        for i in tqdm(range(len(identities)), desc="Deleting device identities from destination hub"):
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
