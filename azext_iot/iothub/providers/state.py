# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger

from azext_iot.common.shared import DeviceAuthApiType, DeviceAuthType, ConfigType
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.operations.hub import _iot_device_show, _iot_device_module_twin_show, _iot_device_module_create, \
    _iot_device_module_show, _iot_device_create, _iot_device_delete, _iot_hub_configuration_delete, _iot_device_twin_replace, \
    _iot_device_module_list, _iot_device_module_twin_replace, _iot_device_list, _iot_hub_configuration_list, \
    _iot_hub_configuration_create, _iot_device_children_list, _iot_device_children_add

import json
from tqdm import tqdm
from typing import Optional

logger = get_logger(__name__)


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

        # the login argument doesn't work later if auth type = "login" and a connection string isn't given initially
        if login or auth_type_dataplane == "key":
            self.login = self.target["cs"]
        else:
            self.login = None

    def process_hub(self, hub_name: str, target: dict):
        '''
        Returns a dictionary containing the hub state
        '''

        hub_state = {}

        all_configs = _iot_hub_configuration_list(hub_name, target)

        adm_configs = [
            c for c in all_configs
            if (
                c["content"].get("deviceContent") is not None
                or c["content"].get("moduleContent") is not None
            )
        ]

        hub_state["configurations"] = adm_configs

        num_configs = len(hub_state["configurations"])
        pbar = tqdm(total=num_configs, desc="Saving configurations")
        pbar.update(num_configs)
        pbar.close()

        hub_state["edgeDeployments"] = [c for c in all_configs if c["content"].get("modulesContent") is not None]

        num_edge_deployments = len(hub_state["edgeDeployments"])
        pbar = tqdm(total=num_edge_deployments, desc="Saving edge deployments")
        pbar.update(num_edge_deployments)
        pbar.close()

        identities = _iot_device_list(hub_name, target, top=-1)

        hub_state["devices"] = {}
        hub_state["modules"] = {}
        hub_state["children"] = {}

        for i in tqdm(range(len(identities)), desc="Saving devices and modules"):

            id = identities[i]
            hub_state["modules"][id["deviceId"]] = []

            module_objs = _iot_device_module_list(target, id["deviceId"])

            # primary and secondary keys show up in the "show" output but not in the "list" output
            if id["authenticationType"] == DeviceAuthApiType.sas.value:
                id2 = _iot_device_show(target, id["deviceId"])
                identities[i]["symmetricKey"] = id2["authentication"]["symmetricKey"]

            if id["capabilities"]["iotEdge"]:
                children = _iot_device_children_list(target, id["deviceId"])
                hub_state["children"][id["deviceId"]] = [c["deviceId"] for c in children]

            hub_state["devices"][id["deviceId"]] = identities[i]

            for module in module_objs:
                module = vars(module)

                if module["module_id"] not in ["$edgeAgent", "$edgeHub"]:

                    # these can't be json serialized, and they can't be explicitly set anyways
                    module.pop('connection_state_updated_time')
                    module.pop('last_activity_time')

                    module_twin = _iot_device_module_twin_show(target, id["deviceId"], module["module_id"])

                    module2 = _iot_device_module_show(target, id["deviceId"], module["module_id"])
                    module["authentication"] = module2["authentication"]

                    hub_state["modules"][id["deviceId"]].append([module, module_twin])

        return hub_state

    def upload_hub_from_dict(self, hub_state: dict):

        # upload configurations

        configs = hub_state["configurations"]

        for i in tqdm(range(len(configs)), desc="Uploading hub configurations"):
            c = configs[i]
            _iot_hub_configuration_create(target=self.target, config_id=c["id"], content=json.dumps(c["content"]),
                                          target_condition=c["targetCondition"], priority=c["priority"],
                                          labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"]))

        edge_deployments = hub_state["edgeDeployments"]

        for i in tqdm(range(len(edge_deployments)), desc="Uploading edge deployments"):
            d = edge_deployments[i]
            # config_type = ConfigType.layered if layered or no_validation else ConfigType.edge
            config_type = ConfigType.edge

            _iot_hub_configuration_create(target=self.target, config_id=d["id"], content=json.dumps(d["content"]),
                                          target_condition=d["targetCondition"], priority=d["priority"],
                                          labels=json.dumps(d["labels"]), metrics=json.dumps(d["metrics"]),
                                          config_type=config_type)

        for i in tqdm(hub_state["devices"], desc="Uploading devices and modules"):

            # upload device identity and twin
            identity = hub_state["devices"][i]

            self.upload_device_identity(identity)

            # all necessary twin attributes are already included in the identity
            # symmetricKey isn't a valid twin attribute
            twin = identity
            if identity["authenticationType"] == DeviceAuthApiType.sas.value:
                twin.pop("symmetricKey")

            _iot_device_twin_replace(self.target, identity["deviceId"], json.dumps(twin))

            # upload module identities and twins for the given device

            modules = hub_state["modules"][identity["deviceId"]]

            for j in range(len(modules)):
                module_identity = modules[j][0]
                module_twin = modules[j][1]

                self.upload_module_identity(module_identity)

                _iot_device_module_twin_replace(self.target, identity["deviceId"], module_identity["module_id"],
                                                json.dumps(module_twin))

        # set parent-child relationships
        for parentId in hub_state["children"]:
            child_list = hub_state["children"][parentId]
            _iot_device_children_add(self.target, parentId, child_list) 

    def save_state(self, filename: str):
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

        hub_state = self.process_hub(self.hub_name, self.target)

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(hub_state, f)

        logger.info("Saved state of IoT Hub '{}' to {}".format(self.hub_name, filename))

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

            _iot_device_create(self.target, device_id, edge, primary_key=pk, secondary_key=sk, status=status,
                               status_reason=status_reason)

        elif auth_type == DeviceAuthApiType.selfSigned.value:
            _iot_device_create(self.target, device_id, edge, DeviceAuthType.x509_thumbprint.value, primary_thumbprint=ptp,
                               secondary_thumbprint=stp, status=status, status_reason=status_reason)

        elif auth_type == DeviceAuthApiType.certificateAuthority.value:
            _iot_device_create(self.target, device_id, edge, DeviceAuthType.x509_ca.value, primary_thumbprint=ptp,
                               secondary_thumbprint=stp, status=status, status_reason=status_reason)

        else:
            logger.error("Authorization type for device '{0}' not recognized.".format(device_id))

    def upload_module_identity(self, identity: dict):

        device_id = identity["device_id"]
        module_id = identity["module_id"]
        auth_type = identity["authentication"]["type"]

        if auth_type == DeviceAuthApiType.sas.value:
            pk = identity["authentication"]["symmetricKey"]["primaryKey"]
            sk = identity["authentication"]["symmetricKey"]["secondaryKey"]

            _iot_device_module_create(self.target, device_id, module_id, primary_key=pk, secondary_key=sk)

        elif auth_type == DeviceAuthApiType.selfSigned.value:
            ptp = identity["authentication"]["x509Thumbprint"]["primaryThumbprint"]
            stp = identity["authentication"]["x509Thumbprint"]["secondaryThumbprint"]

            _iot_device_module_create(self.target, device_id, module_id, DeviceAuthType.x509_thumbprint.value,
                                      primary_thumbprint=ptp, secondary_thumbprint=stp)

        elif auth_type == DeviceAuthApiType.certificateAuthority.value:
            _iot_device_module_create(self.target, device_id, module_id, DeviceAuthType.x509_ca.value)

        else:
            logger.error("Authorization type for module '{0}' in device '{1}' not recognized.".format(module_id, device_id))

    def delete_all_configs(self):
        configs = _iot_hub_configuration_list(self.hub_name, self.target)
        for i in tqdm(range(len(configs)), desc="Deleting configurations and edge deployments from destination hub"):
            c = configs[i]
            _iot_hub_configuration_delete(self.target, config_id=c["id"])

    def delete_all_devices(self):
        identities = _iot_device_list(self.hub_name, self.target, top=-1)
        for i in tqdm(range(len(identities)), desc="Deleting identities from destination hub"):
            id = identities[i]
            _iot_device_delete(self.target, id["deviceId"])

    def upload_state(self, filename: str, replace: Optional[bool] = None):
        '''
        Uses device info from file to recreate the devices
        '''

        if replace:
            self.delete_all_configs()
            self.delete_all_devices()

        with open(filename, 'r', encoding='utf-8') as f:
            hub_state = json.load(f)

        self.upload_hub_from_dict(hub_state)

        logger.info("Uploaded state from '{}' to IoT Hub '{}'".format(filename, self.hub_name))

    def migrate_devices(
        self,
        orig_hub: Optional[str] = None,
        orig_rg: Optional[str] = None,
        orig_hub_login: Optional[str] = None,
        replace: Optional[bool] = False,
    ):

        if replace:
            self.delete_all_configs()
            self.delete_all_devices()

        orig_hub_target = self.discovery.get_target(
            resource_name=orig_hub,
            resource_group_name=orig_rg,
            login=orig_hub_login,
            auth_type=self.auth_type
        )

        hub_state = self.process_hub(orig_hub, orig_hub_target)
        self.upload_hub_from_dict(hub_state)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(orig_hub, self.hub_name))
