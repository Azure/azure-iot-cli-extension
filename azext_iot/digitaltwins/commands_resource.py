# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.resource import ResourceProvider
from azext_iot.digitaltwins.common import (
    ADTEndpointType,
    ADTEndpointAuthType,
    ADTPublicNetworkAccessType,
)
from knack.log import get_logger

logger = get_logger(__name__)


def create_instance(
    cmd,
    name,
    resource_group_name,
    location=None,
    tags=None,
    assign_identity=None,
    scopes=None,
    role_type="Contributor",
    public_network_access=ADTPublicNetworkAccessType.enabled.value,
):
    rp = ResourceProvider(cmd)
    return rp.create(
        name=name,
        resource_group_name=resource_group_name,
        location=location,
        tags=tags,
        assign_identity=assign_identity,
        scopes=scopes,
        role_type=role_type,
        public_network_access=public_network_access,
    )


def list_instances(cmd, resource_group_name=None):
    rp = ResourceProvider(cmd)

    if not resource_group_name:
        return rp.list()
    return rp.list_by_resouce_group(resource_group_name)


def show_instance(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.find_instance(name=name, resource_group_name=resource_group_name)


def delete_instance(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.delete(name=name, resource_group_name=resource_group_name)


def list_endpoints(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.list_endpoints(name=name, resource_group_name=resource_group_name)


def show_endpoint(cmd, name, endpoint_name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.get_endpoint(
        name=name, endpoint_name=endpoint_name, resource_group_name=resource_group_name
    )


def delete_endpoint(cmd, name, endpoint_name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.delete_endpoint(
        name=name, endpoint_name=endpoint_name, resource_group_name=resource_group_name
    )


def add_endpoint_eventgrid(
    cmd,
    name,
    endpoint_name,
    eventgrid_topic_name,
    eventgrid_resource_group,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_uri=None,
    dead_letter_secret=None,
    auth_type=ADTEndpointAuthType.keybased.value,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.eventgridtopic.value,
        endpoint_resource_name=eventgrid_topic_name,
        endpoint_resource_group=eventgrid_resource_group,
        endpoint_subscription=endpoint_subscription,
        dead_letter_uri=dead_letter_uri,
        dead_letter_secret=dead_letter_secret,
        auth_type=auth_type,
    )


def add_endpoint_servicebus(
    cmd,
    name,
    endpoint_name,
    servicebus_topic_name,
    servicebus_resource_group,
    servicebus_namespace,
    servicebus_policy=None,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_uri=None,
    dead_letter_secret=None,
    auth_type=ADTEndpointAuthType.keybased.value,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.servicebus.value,
        endpoint_resource_name=servicebus_topic_name,
        endpoint_resource_group=servicebus_resource_group,
        endpoint_resource_namespace=servicebus_namespace,
        endpoint_resource_policy=servicebus_policy,
        endpoint_subscription=endpoint_subscription,
        dead_letter_uri=dead_letter_uri,
        dead_letter_secret=dead_letter_secret,
        auth_type=auth_type,
    )


def add_endpoint_eventhub(
    cmd,
    name,
    endpoint_name,
    eventhub_name,
    eventhub_resource_group,
    eventhub_namespace,
    eventhub_policy=None,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_uri=None,
    dead_letter_secret=None,
    auth_type=ADTEndpointAuthType.keybased.value,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.eventhub.value,
        endpoint_resource_name=eventhub_name,
        endpoint_resource_group=eventhub_resource_group,
        endpoint_resource_namespace=eventhub_namespace,
        endpoint_resource_policy=eventhub_policy,
        endpoint_subscription=endpoint_subscription,
        dead_letter_uri=dead_letter_uri,
        dead_letter_secret=dead_letter_secret,
        auth_type=auth_type,
    )


def show_private_link(cmd, name, link_name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.get_private_link(
        name=name, resource_group_name=resource_group_name, link_name=link_name
    )


def list_private_links(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.list_private_links(name=name, resource_group_name=resource_group_name)


def set_private_endpoint_conn(
    cmd,
    name,
    conn_name,
    status,
    description=None,
    group_ids=None,
    actions_required=None,
    resource_group_name=None,
):
    rp = ResourceProvider(cmd)
    return rp.set_private_endpoint_conn(
        name=name,
        resource_group_name=resource_group_name,
        conn_name=conn_name,
        status=status,
        description=description,
        group_ids=group_ids,
        actions_required=actions_required,
    )


def show_private_endpoint_conn(cmd, name, conn_name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.get_private_endpoint_conn(
        name=name, resource_group_name=resource_group_name, conn_name=conn_name
    )


def list_private_endpoint_conns(cmd, name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.list_private_endpoint_conns(
        name=name, resource_group_name=resource_group_name
    )


def delete_private_endpoint_conn(cmd, name, conn_name, resource_group_name=None):
    rp = ResourceProvider(cmd)
    return rp.delete_private_endpoint_conn(
        name=name, resource_group_name=resource_group_name, conn_name=conn_name
    )
