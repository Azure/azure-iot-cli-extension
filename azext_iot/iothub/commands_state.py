# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.job import JobProvider
from azext_iot.iothub.providers.state import StateProvider

import time

logger = get_logger(__name__)


def state_export(cmd, hub, rg=None, filename='/project/files/deviceFile.json', auth_type_dataplane=None):
    sp = StateProvider(cmd, hub, rg, auth_type_dataplane)
    sp.save_state(filename)

def state_import(cmd, hub, rg=None, filename='/project/files/deviceFile.json', auth_type_dataplane=None, overwrite=False): 
    sp = StateProvider(cmd, hub, rg, auth_type_dataplane)
    sp.upload_state(filename, overwrite)

def state_migrate(cmd, orig_hub, dest_hub, orig_rg=None, dest_rg=None, auth_type_dataplane=None, overwrite=False): 
    sp = StateProvider(cmd, dest_hub, dest_rg, auth_type_dataplane, orig_hub, orig_rg)
    sp.migrate_devices(overwrite)