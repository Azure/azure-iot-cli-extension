# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.twin import TwinProvider
from knack.log import get_logger

logger = get_logger(__name__)


def query_twins(
    cmd, name_or_hostname, query_command, show_cost=False, resource_group_name=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.invoke_query(query=query_command, show_cost=show_cost)


def create_twin(
    cmd,
    name_or_hostname,
    twin_id,
    model_id,
    replace=False,
    properties=None,
    resource_group_name=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.create(
        twin_id=twin_id, model_id=model_id, replace=replace, properties=properties
    )


def show_twin(cmd, name_or_hostname, twin_id, resource_group_name=None):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.get(twin_id)


def update_twin(cmd, name_or_hostname, twin_id, json_patch, resource_group_name=None, etag=None):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.update(twin_id=twin_id, json_patch=json_patch, etag=etag)


def delete_twin(cmd, name_or_hostname, twin_id, resource_group_name=None, etag=None):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.delete(twin_id, etag=etag)


def create_relationship(
    cmd,
    name_or_hostname,
    twin_id,
    target_twin_id,
    relationship_id,
    relationship,
    replace=False,
    properties=None,
    resource_group_name=None,
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.add_relationship(
        twin_id=twin_id,
        target_twin_id=target_twin_id,
        relationship_id=relationship_id,
        relationship=relationship,
        replace=replace,
        properties=properties,
    )


def show_relationship(
    cmd, name_or_hostname, twin_id, relationship_id, resource_group_name=None,
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.get_relationship(
        twin_id=twin_id, relationship_id=relationship_id
    )


def update_relationship(
    cmd,
    name_or_hostname,
    twin_id,
    relationship_id,
    json_patch,
    resource_group_name=None,
    etag=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.update_relationship(
        twin_id=twin_id, relationship_id=relationship_id, json_patch=json_patch, etag=etag
    )


def list_relationships(
    cmd,
    name_or_hostname,
    twin_id,
    incoming_relationships=False,
    relationship=None,
    resource_group_name=None,
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.list_relationships(
        twin_id=twin_id,
        incoming_relationships=incoming_relationships,
        relationship=relationship,
    )


def delete_relationship(
    cmd, name_or_hostname, twin_id, relationship_id, resource_group_name=None, etag=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.delete_relationship(
        twin_id=twin_id, relationship_id=relationship_id, etag=etag
    )


def send_telemetry(
    cmd,
    name_or_hostname,
    twin_id,
    dt_id=None,
    component_path=None,
    telemetry=None,
    resource_group_name=None,
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.send_telemetry(
        twin_id=twin_id, dt_id=dt_id, component_path=component_path, telemetry=telemetry
    )


def show_component(
    cmd, name_or_hostname, twin_id, component_path, resource_group_name=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.get_component(twin_id=twin_id, component_path=component_path)


def update_component(
    cmd, name_or_hostname, twin_id, component_path, json_patch, resource_group_name=None, etag=None
):
    twin_provider = TwinProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return twin_provider.update_component(
        twin_id=twin_id, component_path=component_path, json_patch=json_patch, etag=etag
    )
