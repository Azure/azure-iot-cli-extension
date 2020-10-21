# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.resource import ResourceProvider
from azext_iot.digitaltwins.common import ADTEndpointType
from knack.log import get_logger

logger = get_logger(__name__)


def create_instance(cmd, name, resource_group_name, location=None, tags=None):
    rp = ResourceProvider(cmd)
    return rp.create(
        name=name, resource_group_name=resource_group_name, location=location, tags=tags
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
    dead_letter_endpoint=None,
    tags=None,
):
    return _add_endpoint_eventgrid(
        cmd=cmd,
        name=name,
        endpoint_name=endpoint_name,
        eventgrid_resource_group=eventgrid_resource_group,
        eventgrid_topic_name=eventgrid_topic_name,
        resource_group_name=resource_group_name,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )


def _add_endpoint_eventgrid(
    cmd,
    name,
    endpoint_name,
    eventgrid_topic_name,
    eventgrid_resource_group,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_endpoint=None,
    tags=None,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.eventgridtopic,
        endpoint_resource_name=eventgrid_topic_name,
        endpoint_resource_group=eventgrid_resource_group,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )


def add_endpoint_servicebus(
    cmd,
    name,
    endpoint_name,
    servicebus_topic_name,
    servicebus_resource_group,
    servicebus_policy,
    servicebus_namespace,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_endpoint=None,
    tags=None,
):
    return _add_endpoint_servicebus(
        cmd=cmd,
        name=name,
        endpoint_name=endpoint_name,
        servicebus_topic_name=servicebus_topic_name,
        servicebus_resource_group=servicebus_resource_group,
        servicebus_policy=servicebus_policy,
        servicebus_namespace=servicebus_namespace,
        resource_group_name=resource_group_name,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )


def _add_endpoint_servicebus(
    cmd,
    name,
    endpoint_name,
    servicebus_topic_name,
    servicebus_resource_group,
    servicebus_policy,
    servicebus_namespace,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_endpoint=None,
    tags=None,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.servicebus,
        endpoint_resource_name=servicebus_topic_name,
        endpoint_resource_group=servicebus_resource_group,
        endpoint_resource_namespace=servicebus_namespace,
        endpoint_resource_policy=servicebus_policy,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )


def add_endpoint_eventhub(
    cmd,
    name,
    endpoint_name,
    eventhub_name,
    eventhub_resource_group,
    eventhub_policy,
    eventhub_namespace,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_endpoint=None,
    tags=None,
):
    return _add_endpoint_eventhub(
        cmd=cmd,
        name=name,
        endpoint_name=endpoint_name,
        eventhub_name=eventhub_name,
        eventhub_resource_group=eventhub_resource_group,
        eventhub_policy=eventhub_policy,
        eventhub_namespace=eventhub_namespace,
        resource_group_name=resource_group_name,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )


def _add_endpoint_eventhub(
    cmd,
    name,
    endpoint_name,
    eventhub_name,
    eventhub_resource_group,
    eventhub_policy,
    eventhub_namespace,
    resource_group_name=None,
    endpoint_subscription=None,
    dead_letter_endpoint=None,
    tags=None,
):
    rp = ResourceProvider(cmd)
    return rp.add_endpoint(
        name=name,
        resource_group_name=resource_group_name,
        endpoint_name=endpoint_name,
        endpoint_resource_type=ADTEndpointType.eventhub,
        endpoint_resource_name=eventhub_name,
        endpoint_resource_group=eventhub_resource_group,
        endpoint_resource_namespace=eventhub_namespace,
        endpoint_resource_policy=eventhub_policy,
        endpoint_subscription=endpoint_subscription,
        dead_letter_endpoint=dead_letter_endpoint,
        tags=tags,
    )
