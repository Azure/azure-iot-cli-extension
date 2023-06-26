# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.iothub.providers.state import StateProvider
from typing import Optional, List


def state_export(
    cmd,
    state_file: str,
    hub_name_or_hostname: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    hub_aspects: Optional[List[str]] = None,
    login: Optional[str] = None,
    auth_type_dataplane: Optional[str] = None,
    replace: bool = False
):
    sp = StateProvider(
        cmd=cmd,
        hub=hub_name_or_hostname,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane,
        export=True
    )
    sp.save_state(state_file, replace, hub_aspects)


def state_import(
    cmd,
    state_file: str,
    hub_name_or_hostname: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    hub_aspects: Optional[List[str]] = None,
    login: Optional[str] = None,
    auth_type_dataplane: Optional[str] = None,
    replace: bool = False
):
    sp = StateProvider(
        cmd=cmd,
        hub=hub_name_or_hostname,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    sp.upload_state(state_file, replace, hub_aspects)


def state_migrate(
    cmd,
    hub_name_or_hostname: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    hub_aspects: Optional[List[str]] = None,
    login: Optional[str] = None,
    orig_hub: Optional[str] = None,
    orig_resource_group_name: Optional[str] = None,
    orig_hub_login: Optional[str] = None,
    auth_type_dataplane: Optional[str] = None,
    replace: bool = False
):
    sp = StateProvider(
        cmd=cmd,
        hub=hub_name_or_hostname,
        rg=resource_group_name,
        login=login,
        auth_type_dataplane=auth_type_dataplane
    )
    sp.migrate_state(orig_hub, orig_resource_group_name, orig_hub_login, replace, hub_aspects)
