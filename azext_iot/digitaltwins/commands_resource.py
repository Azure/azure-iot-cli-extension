# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import List, Optional
from azext_iot.digitaltwins.commands_twins import delete_all_twin
from azext_iot.digitaltwins.commands_models import delete_all_models
from azext_iot.digitaltwins.providers.resource import ResourceProvider
from azext_iot.digitaltwins.common import (
    ADX_DEFAULT_TABLE,
    DEFAULT_CONSUMER_GROUP,
    ADTEndpointType,
    ADTEndpointAuthType,
    ADTPublicNetworkAccessType,
)
from azure.cli.core.azclierror import MutuallyExclusiveArgumentError
from knack.log import get_logger

logger = get_logger(__name__)


def create_instance(
    cmd,
    name: str,
    resource_group_name: str,
    location: Optional[str] = None,
    tags: Optional[List[str]] = None,
    assign_identity: Optional[bool] = None,
    scopes: Optional[List[str]] = None,
    role_type: str = "Contributor",
    public_network_access: str = ADTPublicNetworkAccessType.enabled.value,
    system_identity: Optional[bool] = None,
    user_identities: Optional[List[str]] = None,
    no_wait: bool = False,
):
    if no_wait and scopes:
        raise MutuallyExclusiveArgumentError(
            "Cannot assign scopes in a no wait operation. Please run the command without --no-wait."
        )
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
        system_identity=system_identity,
        user_identities=user_identities
    )


def list_instances(cmd, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)

    if not resource_group_name:
        return rp.list()
    return rp.list_by_resouce_group(resource_group_name)


def show_instance(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.find_instance(name=name, resource_group_name=resource_group_name)


def delete_instance(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.delete(name=name, resource_group_name=resource_group_name)


def wait_instance(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.find_instance(name=name, resource_group_name=resource_group_name, wait=True)


def reset_instance(cmd, name: str, resource_group_name: Optional[str] = None):
    delete_all_models(cmd, name, resource_group_name)
    delete_all_twin(cmd, name, resource_group_name)


def list_endpoints(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.list_endpoints(name=name, resource_group_name=resource_group_name)


def show_endpoint(cmd, name: str, endpoint_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_endpoint(
        name=name, endpoint_name=endpoint_name, resource_group_name=resource_group_name
    )


def delete_endpoint(cmd, name: str, endpoint_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.delete_endpoint(
        name=name, endpoint_name=endpoint_name, resource_group_name=resource_group_name
    )


def wait_endpoint(cmd, name: str, endpoint_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_endpoint(
        name=name,
        endpoint_name=endpoint_name,
        resource_group_name=resource_group_name,
        wait=True
    )


def add_endpoint_eventgrid(
    cmd,
    name: str,
    endpoint_name: str,
    eventgrid_topic_name: str,
    eventgrid_resource_group: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    endpoint_subscription: Optional[str] = None,
    dead_letter_uri: Optional[str] = None,
    dead_letter_secret: Optional[str] = None,
    auth_type: str = ADTEndpointAuthType.keybased.value,
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
    name: str,
    endpoint_name: str,
    servicebus_topic_name: str,
    servicebus_namespace: str,
    servicebus_resource_group: Optional[str] = None,
    servicebus_policy: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    endpoint_subscription: Optional[str] = None,
    dead_letter_uri: Optional[str] = None,
    dead_letter_secret: Optional[str] = None,
    auth_type: str = ADTEndpointAuthType.keybased.value,
    system_identity: Optional[bool] = None,
    user_identity: Optional[List[str]] = None,
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
        system_identity=system_identity,
        user_identity=user_identity
    )


def add_endpoint_eventhub(
    cmd,
    name: str,
    endpoint_name: str,
    eventhub_name: str,
    eventhub_namespace: str,
    eventhub_resource_group: Optional[str] = None,
    eventhub_policy: Optional[str] = None,
    resource_group_name: Optional[str] = None,
    endpoint_subscription: Optional[str] = None,
    dead_letter_uri: Optional[str] = None,
    dead_letter_secret: Optional[str] = None,
    auth_type: str = ADTEndpointAuthType.keybased.value,
    system_identity: Optional[bool] = None,
    user_identity: Optional[List[str]] = None,
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
        system_identity=system_identity,
        user_identity=user_identity
    )


def show_private_link(cmd, name: str, link_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_private_link(
        name=name, resource_group_name=resource_group_name, link_name=link_name
    )


def list_private_links(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.list_private_links(name=name, resource_group_name=resource_group_name)


def set_private_endpoint_conn(
    cmd,
    name: str,
    conn_name: str,
    status: str,
    description: Optional[str] = None,
    group_ids=None,
    actions_required: Optional[str] = None,
    resource_group_name: Optional[str] = None,
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


def show_private_endpoint_conn(cmd, name: str, conn_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_private_endpoint_conn(
        name=name, resource_group_name=resource_group_name, conn_name=conn_name
    )


def list_private_endpoint_conns(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.list_private_endpoint_conns(
        name=name, resource_group_name=resource_group_name
    )


def delete_private_endpoint_conn(cmd, name: str, conn_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.delete_private_endpoint_conn(
        name=name, resource_group_name=resource_group_name, conn_name=conn_name
    )


def wait_private_endpoint_conn(cmd, name: str, conn_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_private_endpoint_conn(
        name=name,
        resource_group_name=resource_group_name,
        conn_name=conn_name,
        wait=True
    )


def create_adx_data_connection(
    cmd,
    name: str,
    conn_name: str,
    adx_cluster_name: str,
    adx_database_name: str,
    eh_namespace: str,
    eh_entity_path: str,
    adx_table_name: str = ADX_DEFAULT_TABLE,
    adx_twin_lifecycle_events_table_name: Optional[str] = None,
    adx_relationship_lifecycle_events_table_name: Optional[str] = None,
    adx_resource_group: Optional[str] = None,
    adx_subscription: Optional[str] = None,
    eh_consumer_group: str = DEFAULT_CONSUMER_GROUP,
    eh_resource_group: Optional[str] = None,
    eh_subscription: Optional[str] = None,
    user_identity: Optional[str] = None,
    record_property_and_item_removals: bool = False,
    resource_group_name: Optional[str] = None,
    yes: bool = False,
):
    rp = ResourceProvider(cmd)
    return rp.create_adx_data_connection(
        name=name,
        conn_name=conn_name,
        adx_cluster_name=adx_cluster_name,
        adx_database_name=adx_database_name,
        adx_table_name=adx_table_name,
        adx_twin_lifecycle_events_table_name=adx_twin_lifecycle_events_table_name,
        adx_relationship_lifecycle_events_table_name=adx_relationship_lifecycle_events_table_name,
        adx_resource_group=adx_resource_group,
        adx_subscription=adx_subscription,
        eh_namespace=eh_namespace,
        eh_entity_path=eh_entity_path,
        eh_consumer_group=eh_consumer_group,
        eh_resource_group=eh_resource_group,
        eh_subscription=eh_subscription,
        user_identity=user_identity,
        record_property_and_item_removals=record_property_and_item_removals,
        resource_group_name=resource_group_name,
        yes=yes,
    )


def show_data_connection(cmd, name: str, conn_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_data_connection(name=name, conn_name=conn_name, resource_group_name=resource_group_name)


def wait_data_connection(cmd, name: str, conn_name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.get_data_connection(name=name, conn_name=conn_name, resource_group_name=resource_group_name, wait=True)


def list_data_connection(cmd, name: str, resource_group_name: Optional[str] = None):
    rp = ResourceProvider(cmd)
    return rp.list_data_connection(name=name, resource_group_name=resource_group_name)


def delete_data_connection(
    cmd,
    name: str,
    conn_name: str,
    resource_group_name: Optional[str] = None,
    cleanup_connection_artifacts: bool = False,
):
    rp = ResourceProvider(cmd)
    return rp.delete_data_connection(name=name, conn_name=conn_name, resource_group_name=resource_group_name)
