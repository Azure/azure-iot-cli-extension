# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.job import JobProvider
from azext_iot.iothub.providers.state import StateProvider


logger = get_logger(__name__)


def state_export(cmd, orig_hub, filename='/project/files/deviceFile.json'):
    sp = StateProvider(cmd, filename, orig_hub)
    sp.save_devices()

def state_import(cmd, dest_hub, filename='/project/files/deviceFile.json'): 
    sp = StateProvider(cmd, filename, dest_hub)
    sp.load_devices()