# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.state import StateProvider
logger = get_logger(__name__)


def state_export(cmd, filename, hub_name=None, resource_group_name=None, login=None, auth_type_dataplane=None):
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=resource_group_name, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.save_state(filename)

def state_import(cmd, filename, hub_name=None, resource_group_name=None, login=None, auth_type_dataplane=None, overwrite=False): 
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=resource_group_name, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.upload_state(filename, overwrite)

def state_migrate(cmd, hub_name=None, rg=None, login=None, orig_hub=None, orig_rg=None, orig_hub_login=None, overwrite=False, auth_type_dataplane=None):
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=rg, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.migrate_devices(orig_hub, orig_rg, orig_hub_login, overwrite)



