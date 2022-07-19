# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger

from azext_iot.common.shared import DeviceAuthApiType, DeviceAuthType
from azext_iot.iothub.providers.base import IoTHubProvider
from azext_iot.operations.hub import _iot_device_show, _iot_device_twin_show, _iot_device_module_twin_show, \
    _iot_device_module_show
from azext_iot.operations.hub import iot_device_list, iot_device_create, iot_device_delete, iot_device_twin_replace, \
    iot_hub_configuration_create, iot_hub_configuration_list, iot_hub_configuration_delete, iot_device_module_list, \
    iot_device_module_create, iot_device_module_twin_replace

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

    def save_state(self, filename: str):
        '''
        Writes all hub configurations, device identities and device twins from the origin hub to a json file
        '''

        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg,
                                             login=self.login, auth_type_dataplane=self.auth_type)

        identities = iot_device_list(cmd=self.cmd, hub_name=self.hub_name, top=-1, resource_group_name=self.rg,
                                     login=self.login, auth_type_dataplane=self.auth_type)

        with open(filename, 'w', encoding='utf-8') as f:

            json.dump(configs, f)
            f.write('\n')

            for i in tqdm(range(len(identities)), desc="Exporting devices"):
                id = identities[i]

                module_objs = iot_device_module_list(cmd=self.cmd, device_id=id["deviceId"], hub_name=self.hub_name,
                                                     resource_group_name=self.rg, login=self.login,
                                                     auth_type_dataplane=self.auth_type)

                # number of modules in the device (not including the two modules automatically included in edge devices)
                if(id["capabilities"]["iotEdge"]):
                    id["numModules"] = len(module_objs) - 2
                else:
                    id["numModules"] = len(module_objs)

                # primary and secondary keys show up in the "show" output but not in the "list" output
                if id["authenticationType"] == DeviceAuthApiType.sas.value:
                    id2 = _iot_device_show(self.target, id["deviceId"])
                    id["symmetricKey"] = id2["authentication"]["symmetricKey"]

                json.dump(id, f)
                f.write('\n')

                # this may be redundant, since it seems like the same fields are included in the identity
                twin = _iot_device_twin_show(self.target, id["deviceId"])
                json.dump(twin, f)
                f.write('\n')

                for module in module_objs:
                    module = vars(module)

                    if(module["module_id"] not in ["$edgeAgent", "$edgeHub"]):

                        module.pop('connection_state_updated_time')
                        module.pop('last_activity_time')
                        module.pop('authentication')

                        module_twin = _iot_device_module_twin_show(self.target, id["deviceId"], module["module_id"])

                        module["authenticationType"] = module_twin["authenticationType"]
                        if (module["authenticationType"] == DeviceAuthApiType.sas.value):
                            module2 = _iot_device_module_show(self.target, id["deviceId"], module["module_id"])
                            module["symmetricKey"] = module2["authentication"]["symmetricKey"]

                        if (module["authenticationType"] == DeviceAuthApiType.selfSigned.value):
                            module2 = _iot_device_module_show(self.target, id["deviceId"], module["module_id"])
                            module["x509Thumbprint"] = module2["authentication"]["x509Thumbprint"]

                        json.dump(module, f)
                        f.write('\n')
                        json.dump(module_twin, f)
                        f.write('\n')

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

        if(auth_type == DeviceAuthApiType.sas.value):
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            iot_device_create(self.cmd, device_id, self.hub_name, edge, primary_key=pk, secondary_key=sk, status=status,
                              status_reason=status_reason, resource_group_name=self.rg, login=self.login,
                              auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.selfSigned.value):
            iot_device_create(self.cmd, device_id, self.hub_name, edge, DeviceAuthType.x509_thumbprint.value,
                              primary_thumbprint=ptp, secondary_thumbprint=stp, status=status, status_reason=status_reason,
                              resource_group_name=self.rg, login=self.login, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.certificateAuthority.value):
            iot_device_create(self.cmd, device_id, self.hub_name, edge, DeviceAuthType.x509_ca.value, status=status,
                              status_reason=status_reason, resource_group_name=self.rg, login=self.login,
                              auth_type_dataplane=self.auth_type)

        else:
            logger.error("Authorization type for device '{0}' not recognized.".format(device_id))

    def upload_module_identity(self, identity: dict):

        device_id = identity["device_id"]
        module_id = identity["module_id"]
        auth_type = identity["authenticationType"]

        if(auth_type == DeviceAuthApiType.sas.value):
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, primary_key=pk, secondary_key=sk,
                                     resource_group_name=self.rg, login=self.login, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.selfSigned.value):
            ptp = identity["x509Thumbprint"]["primaryThumbprint"]
            stp = identity["x509Thumbprint"]["secondaryThumbprint"]

            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, primary_thumbprint=ptp,
                                     secondary_thumbprint=stp, auth_method=DeviceAuthType.x509_thumbprint.value,
                                     resource_group_name=self.rg, login=self.login, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.certificateAuthority.value):
            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, auth_method=DeviceAuthType.x509_ca.value,
                                     resource_group_name=self.rg, login=self.login, auth_type_dataplane=self.auth_type)

        else:
            logger.error("Authorization type for module '{0}' in device '{1}' not recognized.".format(module_id, device_id))

    def delete_all_configs(self):
        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg, login=self.login,
                                             auth_type_dataplane=self.auth_type)
        for i in tqdm(range(len(configs)), desc="Deleting configurations from destination hub"):
            c = configs[i]
            iot_hub_configuration_delete(cmd=self.cmd, config_id=c["id"], hub_name=self.hub_name, resource_group_name=self.rg,
                                         login=self.login, auth_type_dataplane=self.auth_type)

    def delete_all_devices(self):
        identities = iot_device_list(cmd=self.cmd, hub_name=self.hub_name, top=-1, resource_group_name=self.rg, login=self.login,
                                     auth_type_dataplane=self.auth_type)
        for i in tqdm(range(len(identities)), desc="Deleting identities from destination hub"):
            id = identities[i]
            iot_device_delete(cmd=self.cmd, device_id=id["deviceId"], hub_name=self.hub_name, resource_group_name=self.rg,
                              login=self.login, auth_type_dataplane=self.auth_type)

    def upload_state(self, filename: str, replace: Optional[bool] = None):
        '''
        Uses device info from file to recreate the devices
        '''

        if replace:
            self.delete_all_configs()
            self.delete_all_devices()

        hub_info = []
        with open(filename, 'r', encoding='utf-8') as f:
            for obj in f:
                hub_info.append(json.loads(obj))

        # upload configurations

        configs = hub_info[0]

        for i in tqdm(range(len(configs)), desc="Uploading hub configurations"):
            c = configs[i]
            iot_hub_configuration_create(cmd=self.cmd, config_id=c["id"], content=json.dumps(c["content"]), login=self.login,
                                         target_condition=c["targetCondition"], priority=c["priority"], hub_name=self.hub_name,
                                         metrics=json.dumps(c["metrics"]), resource_group_name=self.rg,
                                         labels=json.dumps(c["labels"]), auth_type_dataplane=self.auth_type)

        pbar = tqdm(total=len(hub_info), desc="Uploading devices and modules")
        i = 1
        pbar.update(1)

        while(i < len(hub_info)):

            # upload device identity and twin

            numModules = hub_info[i]["numModules"]
            identity = hub_info[i]
            twin = hub_info[i + 1]

            self.upload_device_identity(identity)

            # all necessary twin attributes are already included in the identity. maybe don't save the twin and just do this:
            # twin = identity
            # if identity["authenticationType"] == DeviceAuthApiType.sas.value:
            #     twin.pop("symmetricKey")

            iot_device_twin_replace(cmd=self.cmd, device_id=identity["deviceId"], target_json=json.dumps(twin), login=self.login,
                                    hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

            i += 2
            pbar.update(2)

            # upload module identities and twins for the given device

            for _ in range(numModules):
                module_identity = hub_info[i]
                module_twin = hub_info[i + 1]

                self.upload_module_identity(module_identity)

                iot_device_module_twin_replace(cmd=self.cmd, device_id=identity["deviceId"], resource_group_name=self.rg,
                                               module_id=module_identity["module_id"], target_json=json.dumps(module_twin),
                                               hub_name=self.hub_name, login=self.login, auth_type_dataplane=self.auth_type)

                i += 2
                pbar.update(2)

        pbar.close()

        logger.info("Uploaded state from '{}' to IoT Hub '{}'".format(filename, self.hub_name))

    def migrate_devices(
        self,
        orig_hub: Optional[str] = None,
        orig_rg: Optional[str] = None,
        orig_hub_login: Optional[str] = None,
        replace: Optional[bool] = None,
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

        self.orig_hub_login = orig_hub_target["cs"]

        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=orig_hub, resource_group_name=orig_rg, login=orig_hub_login,
                                             auth_type_dataplane=self.auth_type)

        for i in tqdm(range(len(configs)), desc="Migrating hub configurations"):
            c = configs[i]
            iot_hub_configuration_create(cmd=self.cmd, config_id=c["id"], content=json.dumps(c["content"]),
                                         hub_name=self.hub_name, target_condition=c["targetCondition"], priority=c["priority"],
                                         labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"]),
                                         resource_group_name=self.rg, login=self.login, auth_type_dataplane=self.auth_type)

        identities = iot_device_list(cmd=self.cmd, hub_name=orig_hub, top=-1, resource_group_name=orig_rg, login=orig_hub_login,
                                     auth_type_dataplane=self.auth_type)

        for i in tqdm(range(len(identities)), desc="Migrating devices"):
            id = identities[i]

            # upload device identity and twin

            # primary and secondary keys show up in the "show" output but not in the "list" output
            if id["authenticationType"] == DeviceAuthApiType.sas.value:
                id2 = _iot_device_show(orig_hub_target, id["deviceId"])
                id["symmetricKey"] = id2["authentication"]["symmetricKey"]

            twin = _iot_device_twin_show(orig_hub_target, id["deviceId"])

            self.upload_device_identity(id)
            iot_device_twin_replace(self.cmd, id["deviceId"], json.dumps(twin), self.hub_name, self.rg, login=self.login,
                                    auth_type_dataplane=self.auth_type)

            # upload modules for the given device

            module_objs = iot_device_module_list(cmd=self.cmd, device_id=id["deviceId"], hub_name=orig_hub,
                                                 resource_group_name=orig_rg, login=orig_hub_login,
                                                 auth_type_dataplane=self.auth_type)

            for module in module_objs:
                module = vars(module)

                if(module["module_id"] not in ["$edgeAgent", "$edgeHub"]):
                    module_twin = _iot_device_module_twin_show(orig_hub_target, id["deviceId"], module["module_id"])

                    module["authenticationType"] = module_twin["authenticationType"]
                    if (module["authenticationType"] == DeviceAuthApiType.sas.value):
                        module2 = _iot_device_module_show(orig_hub_target, id["deviceId"], module["module_id"])
                        module["symmetricKey"] = module2["authentication"]["symmetricKey"]

                    if (module["authenticationType"] == DeviceAuthApiType.selfSigned.value):
                        module2 = _iot_device_module_show(orig_hub_target, id["deviceId"], module["module_id"])
                        module["x509Thumbprint"] = module2["authentication"]["x509Thumbprint"]

                    self.upload_module_identity(module)

                    iot_device_module_twin_replace(cmd=self.cmd, device_id=id["deviceId"], module_id=module["module_id"],
                                                   target_json=json.dumps(module_twin), hub_name=self.hub_name,
                                                   resource_group_name=self.rg, login=self.login,
                                                   auth_type_dataplane=self.auth_type)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(orig_hub, self.hub_name))
