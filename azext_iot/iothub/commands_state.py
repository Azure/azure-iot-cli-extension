# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.job import JobProvider
from azext_iot.iothub.providers.state import StateProvider


logger = get_logger(__name__)


def state_export(cmd, hub, rg=None, filename='/project/files/deviceFile.json'):
    sp = StateProvider(cmd, hub, rg)
    sp.save_devices(filename)

def state_import(cmd, hub, rg=None, filename='/project/files/deviceFile.json', overwrite=False): 
    sp = StateProvider(cmd, hub, rg)
    sp.upload_devices(filename, overwrite)