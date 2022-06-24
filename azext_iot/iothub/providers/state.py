# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from multiprocessing.sharedctypes import Value
from time import sleep
from datetime import datetime, timedelta
from knack.log import get_logger
from azext_iot.sdk.iothub import device
from azure.cli.core.azclierror import (
    CLIInternalError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azext_iot.common.shared import SdkType, JobStatusType, JobType, JobVersionType
from azext_iot.common.utility import handle_service_exception, process_json_arg
from azext_iot.operations.generic import _execute_query, _process_top
from azext_iot.iothub.providers.base import IoTHubProvider, CloudError, SerializationError
from azext_iot.operations.hub import iot_device_list, iot_device_show, iot_device_create, iot_device_update, iot_device_delete, \
    iot_device_twin_show, iot_device_twin_replace

import json
import time

# logger = get_logger(__name__)


class StateProvider(IoTHubProvider):
    def __init__(self, cmd, hub, rg):
        super().__init__(cmd, hub, rg)

    def save_devices(self, filename):
        '''
        Writes all device identities and twins from the origin hub to a json file
        '''

        identities = iot_device_list(self.cmd, self.hub_name)

        with open(filename, 'w') as f:
            for id in identities: 

                # primary and secondary keys show up in the "show" output but not in the "list" output
                if id["authenticationType"] == "sas":
                    id2 = iot_device_show(self.cmd, id["deviceId"], self.hub_name)
                    id["symmetricKey"] = id2["authentication"]["symmetricKey"]

                twin = iot_device_twin_show(self.cmd, id["deviceId"], self.hub_name)

                json.dump(id, f)
                f.write('\n')
                json.dump(twin, f)
                f.write('\n')

    def upload_device_identity(self, identity, overwrite):
        device_id = identity["deviceId"]
        auth_type = identity["authenticationType"]
        edge = identity["capabilities"]["iotEdge"]
        status = identity["status"]
        ptp = identity["x509Thumbprint"]["primaryThumbprint"]
        stp = identity["x509Thumbprint"]["secondaryThumbprint"]
        etag = identity["etag"]
        properties = identity["properties"]["desired"]

        if "status_reason" in identity.keys():
            status_reason = identity["statusReason"]
        else:
            status_reason = None

        if(auth_type == "sas"):
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            iot_device_create(self.cmd, device_id, self.hub_name, edge, primary_key=pk, secondary_key=sk, status=status, status_reason=status_reason)

        elif(auth_type == "selfSigned"):
            iot_device_create(self.cmd, device_id, self.hub_name, edge, auth_method='x509_thumbprint', \
                    primary_thumbprint=ptp, secondary_thumbprint=stp, status=status, status_reason=status_reason)

        elif(auth_type == "certificateAuthority"):
                iot_device_create(self.cmd, device_id, self.hub_name, edge, auth_method='x509_ca', status=status, status_reason=status_reason)

        else:
            print("Authorization type for device '{0}' not recognized.".format(device_id))

    def delete_all_devices(self):
        identities = iot_device_list(self.cmd, self.hub_name) 
        for id in identities:
            iot_device_delete(self.cmd, id["deviceId"], self.hub_name, self.rg)

    def upload_devices(self, filename, overwrite):
        '''
        Uses device info from file to recreate the devices
        '''

        if overwrite:
            self.delete_all_devices()

        device_info = []
        with open(filename, 'r') as f:
            for obj in f:
                device_info.append(json.loads(obj))

        for i in range(0,len(device_info),2):
            identity = device_info[i]
            twin = device_info[i+1]

            self.upload_device_identity(identity, overwrite)
            
            iot_device_twin_replace(self.cmd, identity["deviceId"], json.dumps(twin), self.hub_name)