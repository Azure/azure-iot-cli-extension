# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.route import RouteProvider
from knack.log import get_logger

logger = get_logger(__name__)


def create_route(cmd, name, route_name, endpoint_name, filter="true", resource_group_name=None):
    route_provider = RouteProvider(cmd=cmd, name=name, rg=resource_group_name)
    return route_provider.create(route_name=route_name, endpoint_name=endpoint_name, filter=filter)


def show_route(cmd, name, route_name, resource_group_name=None):
    route_provider = RouteProvider(cmd=cmd, name=name, rg=resource_group_name)
    return route_provider.get(route_name=route_name)


def list_routes(cmd, name, resource_group_name=None):
    route_provider = RouteProvider(cmd=cmd, name=name, rg=resource_group_name)
    return route_provider.list()


def delete_route(cmd, name, route_name, resource_group_name=None):
    route_provider = RouteProvider(cmd=cmd, name=name, rg=resource_group_name)
    return route_provider.delete(route_name=route_name)
