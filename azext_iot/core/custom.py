# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core.azclierror import (
    BadRequestError,
    CLIInternalError,
)

from azext_iot._factory import resource_service_factory
from azext_iot.core.shared import IotDpsSku


def iot_dps_get(client, dps_name, resource_group_name=None):
    if resource_group_name is None:
        return _get_iot_dps_by_name(client, dps_name, resource_group_name)
    return client.iot_dps_resource.get(provisioning_service_name=dps_name, resource_group_name=resource_group_name)


def iot_dps_create(
    cmd,
    client,
    dps_name,
    resource_group_name,
    location=None,
    sku=IotDpsSku.S1.value,
    unit=1,
    tags=None,
    enable_data_residency=None,
    disable_local_auth=None,
):
    cli_ctx = cmd.cli_ctx
    _check_dps_name_availability(client.iot_dps_resource, dps_name)
    location = _ensure_location(cli_ctx, resource_group_name, location)
    dps_property = {}
    if enable_data_residency is not None:
        dps_property["enableDataResidency"] = enable_data_residency

    if disable_local_auth is not None:
        dps_property["disableLocalAuth"] = disable_local_auth

    dps_description = {
        "location": location,
        "properties": dps_property,
        "sku": {"name": sku, "capacity": unit},
    }

    if tags is not None:
        dps_description["tags"] = tags

    return client.iot_dps_resource.begin_create_or_update(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name,
        iot_dps_description=dps_description
    )


def iot_dps_update(
    client,
    dps_name,
    parameters,
    resource_group_name=None,
    tags=None,
    disable_local_auth=None,
):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    if tags is not None:
        parameters["tags"] = tags

    if disable_local_auth is not None:
        parameters["properties"]["disableLocalAuth"] = disable_local_auth

    return client.iot_dps_resource.begin_create_or_update(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=parameters
    )


def iot_dps_list(client, resource_group_name=None):
    if resource_group_name is None:
        return client.iot_dps_resource.list_by_subscription()
    return client.iot_dps_resource.list_by_resource_group(resource_group_name)


def _get_iot_dps_by_name(client, dps_name, resource_group=None):
    all_dps = iot_dps_list(client, resource_group)
    if all_dps is None:
        raise CLIInternalError("No DPS found in current subscription.")
    try:
        target_dps = next(x for x in all_dps if dps_name.lower() == x["name"].lower())
    except StopIteration:
        raise CLIInternalError("No DPS found with name {} in current subscription.".format(dps_name))
    return target_dps


def _ensure_dps_resource_group_name(client, resource_group_name, dps_name):
    if resource_group_name is None:
        return _get_iot_dps_by_name(client, dps_name)["resourcegroup"]
    return resource_group_name


def _check_dps_name_availability(iot_dps_resource, dps_name):
    name_availability = iot_dps_resource.check_provisioning_service_name_availability({"name": dps_name})
    if name_availability is not None and not name_availability["nameAvailable"]:
        raise BadRequestError(name_availability["message"])


def _ensure_location(cli_ctx, resource_group_name, location):
    """Check to see if a location was provided. If not,
        fall back to the resource group location.
    :param object cli_ctx: CLI Context
    :param str resource_group_name: Resource group name
    :param str location: Location to create the resource
    """
    if location is None:
        resource_group_client = resource_service_factory(cli_ctx).resource_groups
        return resource_group_client.get(resource_group_name).location
    return location
