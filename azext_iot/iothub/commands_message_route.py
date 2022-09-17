# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.iothub.providers.message_route import MessageRoute
from knack.log import get_logger

logger = get_logger(__name__)


def message_route_create(
    cmd,
    hub_name: str,
    route_name: str,
    source_type: str,
    endpoint_name: str,
    enabled: bool = True,
    condition: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.create(
        route_name=route_name,
        source_type=source_type,
        endpoint_name=endpoint_name,
        enabled=enabled,
        condition=condition
    )


def message_route_update(
    cmd,
    hub_name: str,
    route_name: str,
    source_type: Optional[str] = None,
    endpoint_name: Optional[str] = None,
    enabled: Optional[bool] = None,
    condition: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.update(
        route_name=route_name,
        source_type=source_type,
        endpoint_name=endpoint_name,
        enabled=enabled,
        condition=condition
    )


def message_route_show(
    cmd,
    hub_name: str,
    route_name: str,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.show(route_name=route_name)


def message_route_list(
    cmd,
    hub_name: str,
    source_type: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.list(source_type=source_type)


def message_route_delete(
    cmd,
    hub_name: str,
    route_name: Optional[str] = None,
    source_type: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.delete(route_name=route_name, source_type=source_type)


def message_route_test(
    cmd,
    hub_name: str,
    route_name: Optional[str] = None,
    source_type: Optional[str] = None,
    body: Optional[str] = None,
    app_properties: Optional[str] = None,
    system_properties: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.test(
        route_name=route_name, source_type=source_type, body=body, app_properties=app_properties, system_properties=system_properties
    )


def message_fallback_route_show(
    cmd,
    hub_name: str,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.show_fallback()


def message_fallback_route_set(
    cmd,
    hub_name: str,
    enabled: bool,
    resource_group_name: Optional[str] = None,
):
    messaging_provider = MessageRoute(
        cmd=cmd, hub_name=hub_name, rg=resource_group_name
    )
    return messaging_provider.set_fallback(enabled=enabled)
