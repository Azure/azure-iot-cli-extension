# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from multiprocessing.sharedctypes import Value
from knack.log import get_logger
from azext_iot.operations import hub
from azext_iot.sdk.iothub import device
from azure.cli.core.azclierror import (
    CLIInternalError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azext_iot.common.shared import SdkType, JobStatusType, JobType, JobVersionType, DeviceAuthApiType, DeviceAuthType
from azext_iot.common.utility import handle_service_exception, process_json_arg
from azext_iot.operations.generic import _execute_query, _process_top
from azext_iot.iothub.providers.base import IoTHubProvider, CloudError, SerializationError
from azext_iot.operations.hub import _iot_device_show, _iot_device_twin_show, _iot_device_module_twin_show, _iot_device_module_show
from azext_iot.operations.hub import iot_device_list, iot_device_create, iot_device_delete, iot_device_twin_replace, iot_hub_configuration_create, iot_hub_configuration_list, \
    iot_hub_configuration_delete, iot_device_module_list, iot_device_module_create, iot_device_module_twin_replace

import json

logger = get_logger(__name__)


class StateProvider(IoTHubProvider):
    def __init__(self, cmd, hub, rg, orig_hub=None, orig_rg=None, auth_type_dataplane=None):
        super().__init__(
            cmd=cmd, 
            hub_name=hub,
            rg=rg, 
            auth_type_dataplane=auth_type_dataplane
        )
        self.auth_type = auth_type_dataplane
        self.orig_hub = orig_hub
        self.orig_rg = orig_rg

        if(orig_hub):
            self.orig_hub_target = self.discovery.get_target(
                resource_name=self.orig_hub,
                resource_group_name=self.orig_rg,
                auth_type=auth_type_dataplane,
            )

    def save_state(self, filename):
        '''
        Writes all hub configurations, device identities and device twins from the origin hub to a json file
        '''

        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        identities = iot_device_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        with open(filename, 'w') as f:

            json.dump(configs, f)
            f.write('\n')

            for id in identities: 

                module_objs = iot_device_module_list(cmd=self.cmd, device_id=id["deviceId"], hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

                # number of modules in the device (not including the two modules automatically included in edge devices)
                if(id["capabilities"]["iotEdge"]):
                    id["numModules"] = len(module_objs) - 2
                else: 
                    id["numModules"] = len(module_objs)

                # primary and secondary keys show up in the "show" output but not in the "list" output
                if id["authenticationType"] == DeviceAuthApiType.sas.value:
                    id2 = _iot_device_show(self.target, id["deviceId"])
                    id["symmetricKey"] = id2["authentication"]["symmetricKey"]

                twin = _iot_device_twin_show(self.target, id["deviceId"])

                json.dump(id, f)
                f.write('\n')
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

    def upload_device_identity(self, identity):
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

            iot_device_create(self.cmd, device_id, self.hub_name, edge, primary_key=pk, secondary_key=sk, status=status, \
                status_reason=status_reason, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.selfSigned.value):
            iot_device_create(self.cmd, device_id, self.hub_name, edge, auth_method='x509_thumbprint', \
                    primary_thumbprint=ptp, secondary_thumbprint=stp, status=status, status_reason=status_reason, resource_group_name=self.rg, \
                    auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.certificateAuthority.value):
                iot_device_create(self.cmd, device_id, self.hub_name, edge, auth_method='x509_ca', status=status, status_reason=status_reason, \
                    resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        else: 
            logger.error("Authorization type for device '{0}' not recognized.".format(device_id))

    def upload_module_identity(self, identity):

        device_id = identity["device_id"]
        module_id = identity["module_id"]
        auth_type = identity["authenticationType"]

        if(auth_type == DeviceAuthApiType.sas.value):
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, primary_key=pk, secondary_key=sk, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.selfSigned.value):
            ptp = identity["x509Thumbprint"]["primaryThumbprint"]
            stp = identity["x509Thumbprint"]["secondaryThumbprint"]

            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, auth_method='x509_thumbprint', primary_thumbprint=ptp, secondary_thumbprint=stp, \
                resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        elif(auth_type == DeviceAuthApiType.certificateAuthority.value):
            iot_device_module_create(self.cmd, device_id, module_id, self.hub_name, auth_method='x509_ca', resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        else:
            logger.error("Authorization type for module '{0}' in device '{1}' not recognized.".format(module_id, device_id))


    def delete_all_configs(self):
        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)
        for c in configs:
            iot_hub_configuration_delete(cmd=self.cmd, config_id=c["id"], hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

    def delete_all_devices(self):
        identities = iot_device_list(cmd=self.cmd, hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type) 
        for id in identities:
            iot_device_delete(cmd=self.cmd, device_id=id["deviceId"], hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

    def upload_state(self, filename, overwrite):
        '''
        Uses device info from file to recreate the devices
        '''

        if overwrite:
            self.delete_all_configs()
            self.delete_all_devices()

        hub_info = []
        with open(filename, 'r') as f:
            for obj in f:
                hub_info.append(json.loads(obj))

        # upload configurations

        configs = hub_info[0]

        for c in configs:
            iot_hub_configuration_create(cmd=self.cmd, config_id=c["id"], content=json.dumps(c["content"]), hub_name=self.hub_name, target_condition=c["targetCondition"], \
                priority=c["priority"], labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"]), resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        i = 1
        while(i < len(hub_info)):

            # upload device identity and twin

            numModules = hub_info[i]["numModules"]
            identity = hub_info[i]
            twin = hub_info[i+1]

            self.upload_device_identity(identity)

            iot_device_twin_replace(cmd=self.cmd, device_id=identity["deviceId"], target_json=json.dumps(twin), hub_name=self.hub_name, resource_group_name=self.rg, \
                auth_type_dataplane=self.auth_type)

            # upload module identities and twins for the given device

            for j in range(numModules):
                i += 2
                module_identity = hub_info[i]
                module_twin = hub_info[i+1]

                self.upload_module_identity(module_identity)

                iot_device_module_twin_replace(cmd=self.cmd, device_id=identity["deviceId"], module_id=module_identity["module_id"], target_json=json.dumps(module_twin), \
                    hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)
            
            i += 2

        logger.info("Uploaded state from '{}' to IoT Hub '{}'".format(filename, self.hub_name))

    def migrate_devices(self, overwrite):
        if overwrite:
            self.delete_all_configs()
            self.delete_all_devices()

        configs = iot_hub_configuration_list(cmd=self.cmd, hub_name=self.orig_hub, resource_group_name=self.orig_rg, auth_type_dataplane=self.auth_type)
        for c in configs:
            iot_hub_configuration_create(cmd=self.cmd, config_id=c["id"], content=json.dumps(c["content"]), hub_name=self.hub_name, target_condition=c["targetCondition"], \
                priority=c["priority"], labels=json.dumps(c["labels"]), metrics=json.dumps(c["metrics"]), resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        
        identities = iot_device_list(cmd=self.cmd, hub_name=self.orig_hub, resource_group_name=self.orig_rg, auth_type_dataplane=self.auth_type)

        for id in identities: 

            # upload device identity and twin

            # primary and secondary keys show up in the "show" output but not in the "list" output
            if id["authenticationType"] == DeviceAuthApiType.sas.value:
                id2 = _iot_device_show(self.orig_hub_target, id["deviceId"])
                id["symmetricKey"] = id2["authentication"]["symmetricKey"]

            twin = _iot_device_twin_show(self.orig_hub_target, id["deviceId"])

            self.upload_device_identity(id)
            iot_device_twin_replace(self.cmd, id["deviceId"], json.dumps(twin), self.hub_name, self.rg, auth_type_dataplane=self.auth_type)

            # upload modules for the given device

            module_objs = iot_device_module_list(cmd=self.cmd, device_id=id["deviceId"], hub_name=self.orig_hub, resource_group_name=self.orig_rg, auth_type_dataplane=self.auth_type)

            for module in module_objs:
                module = vars(module)

                if(module["module_id"] not in ["$edgeAgent", "$edgeHub"]):
                    module_twin = _iot_device_module_twin_show(self.orig_hub_target, id["deviceId"], module["module_id"])

                    module["authenticationType"] = module_twin["authenticationType"]
                    if (module["authenticationType"] == DeviceAuthApiType.sas.value):
                        module2 = _iot_device_module_show(self.orig_hub_target, id["deviceId"], module["module_id"])
                        module["symmetricKey"] = module2["authentication"]["symmetricKey"]

                    if (module["authenticationType"] == DeviceAuthApiType.selfSigned.value):
                        module2 = _iot_device_module_show(self.orig_hub_target, id["deviceId"], module["module_id"])
                        module["x509Thumbprint"] = module2["authentication"]["x509Thumbprint"]
 
                    self.upload_module_identity(module)
                    
                    iot_device_module_twin_replace(cmd=self.cmd, device_id=id["deviceId"], module_id=module["module_id"], target_json=json.dumps(module_twin), \
                        hub_name=self.hub_name, resource_group_name=self.rg, auth_type_dataplane=self.auth_type)

        logger.info("Migrated state from IoT Hub '{}' to {}".format(self.orig_hub, self.hub_name))