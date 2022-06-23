# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

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
from azext_iot.operations.hub import iot_device_list, iot_device_show, iot_device_create, iot_device_twin_show

import subprocess
import json

logger = get_logger(__name__)


class StateProvider(IoTHubProvider):
    def __init__(self, cmd, filename, orig_hub = None, dest_hub = None):
        self.cmd = cmd
        self.orig_hub = orig_hub
        self.dest_hub = orig_hub
        self.filename = filename

    def save_devices(self):
        '''
        Writes all device identities and twins from the origin hub to a json file
        example command: az iot hub state export --filename C:\project\files\deviceFile.json --orig-hub ms-hub
        '''

        identities = iot_device_list(self.cmd, self.orig_hub)

        print(type(identities), type(identities[0]))

        with open(self.filename, 'a+') as f:
            for id in identities: 

                # primary and secondary keys show up in the "show" output but not in the "list" output
                if id["authenticationType"] == "sas":
                    id2 = iot_device_show(self.cmd, id["deviceId"], self.orig_hub)
                    id["symmetricKey"] = id2["authentication"]["symmetricKey"]

                twin = iot_device_twin_show(self.cmd, id["deviceId"], self.orig_hub)

                json.dump(id, f)
                f.write('\n')
                json.dump(twin, f)
                f.write('\n')

    def load_device_identity(self, identity):
        device_id = identity["deviceId"]
        auth_type = identity["authenticationType"]
        edge = identity["capabilities"]["iotEdge"]
        status = identity["status"]
        ptp = identity["x509Thumbprint"]["primaryThumbprint"]
        stp = identity["x509Thumbprint"]["secondaryThumbprint"]
        properties = identity["properties"]["desired"]

        if(auth_type == "sas"):
            pk = identity["symmetricKey"]["primaryKey"]
            sk = identity["symmetricKey"]["secondaryKey"]

            iot_device_create(self.cmd, device_id, self.dest_hub, edge, primary_key=pk, secondary_key=sk, status=status)

        elif(auth_type == "selfSigned"):
            iot_device_create(self.cmd, device_id, self.dest_hub, edge, auth_method='x509_thumbprint', \
                    primary_thumbprint=ptp, secondary_thumbprint=stp, status=status)

        elif(auth_type == "certificateAuthority"):
            iot_device_create(self.cmd, device_id, self.dest_hub, edge, auth_method='x509_ca', status=status)

        else:
            print("Authorization type for device '{0}' not recognized.".format(device_id))

        # update properties in the device twin, which updates them in the identity as well
        for prop in properties.keys():
            if prop not in ["$metadata", "$version"]:
                subprocess.run("az iot hub device-twin update -n {0} -d {1} --set properties.desired.{2}={3}" \
                    .format(self.dest_hub, device_id, prop, properties[prop]), shell=True)

        # if "tags" in identity.keys():
        #     tags = identity["tags"]
        #     subprocess.run("az iot hub device-identity update -n {0} -d {1} --add tags={3}" \
        #             .format(self.dest_hub, device_id, tags), shell=True)

                    # az iot hub device-identity update -n ms-hub2 -d simDevice --set tags='{"deviceType": "Type1, Type2, Type3"}'
                    # az iot hub device-identity update -n ms-hub2 -d simDevice --set properties.desired.bean=green

    def load_devices(self):
        '''
        Uses device info from file to recreate the devices
        file has alternating device identity and twin
        example command: az iot hub state import --filename C:\project\files\deviceFile.json --dest-hub ms-hub2
        '''

        device_info = []
        with open(self.filename, 'r') as f:
            for obj in f:
                device_info.append(json.loads(obj))

        for i in range(0,len(device_info),2):
            identity = device_info[i]
            twin = device_info[i+1]

            self.load_device_identity(identity)