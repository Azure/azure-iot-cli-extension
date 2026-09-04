# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from azext_iot.adr.providers.link import LinkProvider


def adr_link_hub_add(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    hub_resource_id: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    availability: Optional[str] = None,
    allocation_weight: Optional[int] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.hub_add(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        hub_resource_id=hub_resource_id,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        availability=availability,
        allocation_weight=allocation_weight,
        no_wait=no_wait,
    )


def adr_link_hub_update(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.hub_update(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_link_hub_delete(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return LinkProvider(cmd, client=client).hub_delete(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_link_hub_show(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.hub_show(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_link_hub_list(
    cmd,
    client,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.hub_list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


# ==================== link dps ====================


def adr_link_dps_add(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    dps_resource_id: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.dps_add(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        dps_resource_id=dps_resource_id,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_link_dps_update(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.dps_update(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_link_dps_delete(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return LinkProvider(cmd, client=client).dps_delete(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_link_dps_show(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.dps_show(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_link_dps_list(
    cmd,
    client,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.dps_list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


# ==================== link su ====================


def adr_link_su_add(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    su_resource_id: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.su_add(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        su_resource_id=su_resource_id,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_link_su_update(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    mi_system_assigned: bool = False,
    mi_user_assigned: Optional[str] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.su_update(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        mi_system_assigned=mi_system_assigned,
        mi_user_assigned=mi_user_assigned,
        no_wait=no_wait,
    )


def adr_link_su_delete(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    return LinkProvider(cmd, client=client).su_delete(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_link_su_show(
    cmd,
    client,
    endpoint_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.su_show(
        endpoint_name=endpoint_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_link_su_list(
    cmd,
    client,
    namespace_name: str,
    resource_group_name: str,
):
    provider = LinkProvider(cmd, client=client)
    return provider.su_list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


# ==================== link add (bundled) ====================


def adr_link_add(
    cmd,
    client,
    namespace_name: str,
    resource_group_name: str,
    hub_endpoint_name: str,
    hub_resource_id: str,
    dps_endpoint_name: str,
    dps_resource_id: str,
    hub_mi_system_assigned: bool = False,
    hub_mi_user_assigned: Optional[str] = None,
    dps_mi_system_assigned: bool = False,
    dps_mi_user_assigned: Optional[str] = None,
    hub_availability: Optional[str] = None,
    hub_allocation_weight: Optional[int] = None,
    no_wait: bool = False,
):
    provider = LinkProvider(cmd, client=client)
    return provider.link_add(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        hub_endpoint_name=hub_endpoint_name,
        hub_resource_id=hub_resource_id,
        dps_endpoint_name=dps_endpoint_name,
        dps_resource_id=dps_resource_id,
        hub_mi_system_assigned=hub_mi_system_assigned,
        hub_mi_user_assigned=hub_mi_user_assigned,
        dps_mi_system_assigned=dps_mi_system_assigned,
        dps_mi_user_assigned=dps_mi_user_assigned,
        hub_availability=hub_availability,
        hub_allocation_weight=hub_allocation_weight,
        no_wait=no_wait,
    )
