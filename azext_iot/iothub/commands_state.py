# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.state import StateProvider


def state_export(cmd, filename, hub_name=None, resource_group_name=None, login=None, auth_type_dataplane=None):
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=resource_group_name, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.save_state(filename)


def state_import(cmd, filename, hub_name=None, resource_group_name=None, login=None, auth_type_dataplane=None, replace=False):
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=resource_group_name, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.upload_state(filename, replace)


def state_migrate(cmd, hub_name=None, resource_group_name=None, login=None, orig_hub=None, orig_resource_group_name=None,
    orig_hub_login=None, replace=False, auth_type_dataplane=None
):
    sp = StateProvider(cmd=cmd, hub=hub_name, rg=resource_group_name, login=login, auth_type_dataplane=auth_type_dataplane)
    sp.migrate_devices(orig_hub, orig_resource_group_name, orig_hub_login, replace)