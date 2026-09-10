# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=no-member,line-too-long,too-few-public-methods,too-many-lines,too-many-arguments,too-many-locals
# TODO: tighten the broad lint disables above
# flake8: noqa
import json
import re
from copy import deepcopy
from datetime import timedelta
from enum import Enum
from typing import List, Optional

from azure.cli.core.azclierror import (
    ArgumentUsageError,
    BadRequestError,
    CLIInternalError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
    UnclassifiedUserFault,
)
from azure.cli.core.commands import LongRunningOperation
from azure.cli.core.commands.arm import assign_identity
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from knack.util import CLIError

from azext_iot._factory import iot_hub_service_factory, resource_service_factory
from azext_iot.common.arm import (
    adapt_modeless_lro_poller,
    hub_description_for_write as _hub_description_for_write,
    hub_etag_arguments,
    sanitize_arm_identity as _sanitize_arm_identity,
)
from azext_iot.common._azure import IOT_SERVICE_CS_TEMPLATE
from azext_iot.common.utility import validate_key_value_pairs
from azext_iot.constants import IOT_HUB_DEFAULT_POLICY
from azext_iot.common.certops import open_certificate
from azext_iot.core.shared import (
    AccessRights,
    AuthenticationType,
    EncodingFormat,
    EndpointType,
    IdentityType,
    IotDpsSku,
    IotHubAuthenticationType,
    IotHubSku,
    ManagedServiceIdentityType,
    RenewKeyType,
)
from azext_iot.iothub.common import SYSTEM_ASSIGNED_IDENTITY

logger = get_logger(__name__)

# Identity types
SYSTEM_ASSIGNED = 'SystemAssigned'
NONE_IDENTITY = 'None'


# CUSTOM TYPE
class KeyType(Enum):
    primary = 'primary'
    secondary = 'secondary'


# This is a work around to simplify the permission parameter for access policy creation, and also align with the other
# command modules.
# The original AccessRights enum is a combination of below four basic access rights.
# In order to avoid asking for comma- & space-separated strings from the user, a space-separated list is supported for
# assigning multiple permissions.
# The underlying IoT SDK should handle this. However it isn't right now. Remove this after it is fixed in IoT SDK.
class SimpleAccessRights(Enum):
    registry_read = AccessRights.REGISTRY_READ
    registry_write = AccessRights.REGISTRY_WRITE
    service_connect = AccessRights.SERVICE_CONNECT
    device_connect = AccessRights.DEVICE_CONNECT


def _get_resource_group_from_hub(hub):
    """Extract resource group from an IoT Hub resource dict."""
    return hub["resourcegroup"]


def _resolve_linked_hub_hostname(hub, hostname_type="auto"):
    """Resolve IoT Hub hostname for DPS linked hub based on hostname type."""
    if hostname_type == "classic":
        return hub["properties"]["hostName"]
    device_hostname = hub["properties"].get("deviceHostName")
    if hostname_type == "device" and not device_hostname:
        hub_name = hub.get("name", "unknown")
        raise InvalidArgumentValueError(
            f"The device hostname is not available for IoT Hub '{hub_name}'. "
            "This hostname type is only supported on GWv2 IoT Hubs. "
            "Use '--hostname-type classic' or '--hostname-type auto' instead."
        )
    # "auto" or "device" with available deviceHostName
    return device_hostname or hub["properties"]["hostName"]


def _ensure_linked_hub_hostnames(linked_hubs):
    for entry in linked_hubs or []:
        if not entry.get("hostName") and entry.get("name"):
            entry["hostName"] = entry["name"]
    return linked_hubs


def _warn_mixed_endpoint_types(linked_hubs):
    """Warn if DPS dynamic allocation references hubs with mixed hostname types."""
    types = set()
    for hub in linked_hubs:
        # Only check hubs participating in allocation
        if hub.get("applyAllocationPolicy") is False:
            continue
        hostname = hub.get("hostName", "")
        if not hostname:
            cs = hub.get("connectionString", "")
            for part in cs.split(";"):
                if part.lower().startswith("hostname="):
                    hostname = part.split("=", 1)[1]
                    break
        if not hostname:
            hostname = hub.get("name", "")
        parts = hostname.split(".")
        if len(parts) > 1 and parts[1] == "device":
            types.add("device")
        elif hostname:
            types.add("classic")
    if len(types) > 1:
        logger.warning(
            "DPS has linked hubs with mixed hostname types (device and classic). "
            "This may cause inconsistent behavior during device provisioning."
        )


def _find_linked_hub_entry(linked_hubs, hub_name=None, linked_hub=None):
    """Find a linked-hub entry by short hub-name (prefix) or full hostname (exact).

    Raises ResourceNotFoundError if no entry matches, or
    InvalidArgumentValueError if --hub-name resolves to multiple entries
    (caller must disambiguate with --linked-hub <full-hostname>).
    """
    if linked_hub:
        for entry in linked_hubs:
            if entry["name"].lower() == linked_hub.lower():
                return entry
        raise ResourceNotFoundError(
            f"Linked hub '{linked_hub}' does not exist. "
            "Use 'iot dps linked-hub list' to see all linked hubs."
        )

    short_name = hub_name.lower()
    matches = [
        entry for entry in linked_hubs
        if entry["name"].lower().startswith(f"{short_name}.")
    ]
    if not matches:
        raise ResourceNotFoundError(
            f"No linked hub found for IoT Hub '{hub_name}'. "
            "Use 'iot dps linked-hub list' to see all linked hubs."
        )
    if len(matches) > 1:
        names = ", ".join(m["name"] for m in matches)
        raise InvalidArgumentValueError(
            f"Multiple linked-hub entries found for IoT Hub '{hub_name}': {names}. "
            "Specify --linked-hub <full-hostname> to disambiguate."
        )
    return matches[0]


# CUSTOM METHODS FOR DPS
def iot_dps_list(client, resource_group_name=None):
    if resource_group_name is None:
        return client.iot_dps_resource.list_by_subscription()
    return client.iot_dps_resource.list_by_resource_group(resource_group_name)


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
    mi_system_assigned=None,
    mi_user_assigned=None,
):
    """Create a DPS instance with optional managed identities."""
    cli_ctx = cmd.cli_ctx
    _check_dps_name_availability(client.iot_dps_resource, dps_name)
    location = _ensure_location(cli_ctx, resource_group_name, location)
    dps_property = {"enableDataResidency": enable_data_residency}

    dps_description = {
        "location": location,
        "properties": dps_property,
        "sku": {"name": sku, "capacity": unit},
        "tags": tags,
    }

    if mi_system_assigned is not None or mi_user_assigned:
        dps_description["identity"] = _construct_identity_info(mi_system_assigned, mi_user_assigned)

    return client.iot_dps_resource.begin_create_or_update(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps_description
    )


def iot_dps_update(
    client,
    dps_name,
    parameters,
    resource_group_name=None,
    tags=None,
    mi_system_assigned=None,
    mi_user_assigned=None,
    cmd=None,
):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    if tags is not None:
        parameters["tags"] = tags

    if mi_system_assigned is not None or mi_user_assigned is not None:
        parameters["identity"] = _merge_dps_identity(
            parameters.get("identity"),
            mi_system_assigned,
            mi_user_assigned,
        )

    # Generic update mutates the object returned by its getter before invoking
    # this setter. Re-read the current resource so --remove identity (including
    # a nested UAMI removal) and --system-assigned-mi false are protected by
    # the same active-link guard as `iot dps identity remove`.
    current = client.iot_dps_resource.get(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
    )
    remove_system, remove_user_identities = _dps_identity_removals(
        (current or {}).get("identity"),
        parameters.get("identity"),
    )
    if remove_system or remove_user_identities:
        _protect_dps_link_identity(
            cmd,
            current,
            remove_system=remove_system,
            remove_user_identities=remove_user_identities,
        )

    return adapt_modeless_lro_poller(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            provisioning_service_name=dps_name,
            iot_dps_description=_dps_description_for_write(parameters),
        )
    )


def iot_dps_delete(client, dps_name, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.iot_dps_resource.begin_delete(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name
    )


# DPS policy methods
def iot_dps_policy_list(client, dps_name, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.iot_dps_resource.list_keys(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name
    )


def iot_dps_policy_get(client, dps_name, access_policy_name, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.iot_dps_resource.list_keys_for_key_name(
        resource_group_name=resource_group_name, provisioning_service_name=dps_name, key_name=access_policy_name
    )


def iot_dps_policy_create(
    cmd,
    client,
    dps_name,
    access_policy_name,
    rights,
    resource_group_name=None,
    primary_key=None,
    secondary_key=None,
    no_wait=False
):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps_access_policies = []
    dps_access_policies.extend(iot_dps_policy_list(client, dps_name, resource_group_name))
    if _does_policy_exist(dps_access_policies, access_policy_name):
        raise BadRequestError("Access policy {} already exists.".format(access_policy_name))

    dps = iot_dps_get(client, dps_name, resource_group_name)
    access_policy_rights = _convert_rights_to_access_rights(rights)
    dps_access_policies.append({"keyName": access_policy_name, "rights": access_policy_rights, "primaryKey": primary_key, "secondaryKey": secondary_key})
    dps["properties"]["authorizationPolicies"] = dps_access_policies

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    )
    return iot_dps_policy_get(client, dps_name, access_policy_name, resource_group_name)


def iot_dps_policy_update(
    cmd,
    client,
    dps_name,
    access_policy_name,
    resource_group_name=None,
    primary_key=None,
    secondary_key=None,
    rights=None,
    no_wait=False
):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps_access_policies = []
    dps_access_policies.extend(iot_dps_policy_list(client, dps_name, resource_group_name))

    if not _does_policy_exist(dps_access_policies, access_policy_name):
        raise ResourceNotFoundError("Access policy {} doesn't exist.".format(access_policy_name))

    for policy in dps_access_policies:
        if policy["keyName"] == access_policy_name:
            if primary_key is not None:
                policy["primaryKey"] = primary_key
                if policy["primaryKey"] == '':
                    policy["primaryKey"] = None
            if secondary_key is not None:
                policy["secondaryKey"] = secondary_key
                if policy["secondaryKey"] == '':
                    policy["secondaryKey"] = None
            if rights is not None:
                policy["rights"] = _convert_rights_to_access_rights(rights)

    dps = iot_dps_get(client, dps_name, resource_group_name)
    dps["properties"]["authorizationPolicies"] = dps_access_policies

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    )
    return iot_dps_policy_get(client, dps_name, access_policy_name, resource_group_name)


def iot_dps_policy_delete(cmd, client, dps_name, access_policy_name, resource_group_name=None, no_wait=False):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps_access_policies = []
    dps_access_policies.extend(iot_dps_policy_list(client, dps_name, resource_group_name))

    if not _does_policy_exist(dps_access_policies, access_policy_name):
        raise ResourceNotFoundError("Access policy {0} doesn't exist.".format(access_policy_name))
    updated_policies = [p for p in dps_access_policies if p["keyName"].lower() != access_policy_name.lower()]

    dps = iot_dps_get(client, dps_name, resource_group_name)
    dps["properties"]["authorizationPolicies"] = updated_policies

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    )
    return iot_dps_policy_list(client, dps_name, resource_group_name)


# DPS linked hub methods
def _warn_namespace_linked_dps(dps):
    links = ((dps or {}).get("properties") or {}).get(
        "deviceRegistryNamespaces"
    ) or []
    if links:
        logger.warning(
            "This DPS is linked to a Device Registry namespace. "
            "'az iot dps linked-hub' manages the classic DPS properties.iotHubs "
            "allocation list only; namespace-side 'az iot adr ns link hub' "
            "relationships are authoritative for ADR."
        )


def iot_dps_linked_hub_list(client, dps_name, resource_group_name=None):
    dps = iot_dps_get(client, dps_name, resource_group_name)
    _warn_namespace_linked_dps(dps)
    return dps["properties"]["iotHubs"]


def iot_dps_linked_hub_get(cmd, client, dps_name, linked_hub, resource_group_name=None):
    if '.' not in linked_hub:
        hub_client = iot_hub_service_factory(cmd.cli_ctx)
        linked_hub = _get_iot_hub_hostname(hub_client, linked_hub)

    dps = iot_dps_get(client, dps_name, resource_group_name)
    _warn_namespace_linked_dps(dps)
    for hub in dps["properties"]["iotHubs"]:
        if hub["name"] == linked_hub:
            return hub
    raise ResourceNotFoundError("Linked hub '{0}' does not exist. Use 'iot dps linked-hub show to see all linked hubs.".format(linked_hub))


def iot_dps_linked_hub_create(
    cmd,
    client,
    dps_name,
    hub_name=None,
    hub_resource_group=None,
    connection_string=None,
    location=None,
    resource_group_name=None,
    authentication_type=None,
    user_assigned_identity=None,
    hostname_type="auto",
    apply_allocation_policy=None,
    allocation_weight=None,
    no_wait=False
):
    is_mi = authentication_type in (
        IotHubAuthenticationType.SYSTEM_ASSIGNED.value,
        IotHubAuthenticationType.USER_ASSIGNED.value,
    )

    # MI based Hub Linking in DPS
    if is_mi:
        if connection_string:
            raise MutuallyExclusiveArgumentError(
                "--connection-string cannot be used with --authentication-type. "
                "Use --hub-name instead for managed identity authentication."
            )
        if not hub_name:
            raise RequiredArgumentMissingError(
                "Please provide --hub-name for managed identity authentication."
            )
        if authentication_type == IotHubAuthenticationType.USER_ASSIGNED.value and not user_assigned_identity:
            raise RequiredArgumentMissingError(
                "--user-assigned-identity is required when --authentication-type is UserAssigned."
            )

        hub_client = iot_hub_service_factory(cmd.cli_ctx)
        hub = iot_hub_get(cmd, hub_client, hub_name=hub_name, resource_group_name=hub_resource_group)
        host_name = _resolve_linked_hub_hostname(hub, hostname_type)

        # Validate MI is enabled on DPS
        resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
        dps = iot_dps_get(client, dps_name, resource_group_name)
        identity = dps.get("identity") or {}
        identity_type = identity.get("type", "None") if isinstance(identity, dict) else "None"
        if authentication_type == IotHubAuthenticationType.SYSTEM_ASSIGNED.value and "SystemAssigned" not in identity_type:
            raise InvalidArgumentValueError(
                f"System-assigned managed identity is not enabled on DPS '{dps_name}'. "
                "Please enable it before linking with SystemAssigned authentication."
            )
        if authentication_type == IotHubAuthenticationType.USER_ASSIGNED.value and "UserAssigned" not in identity_type:
            raise InvalidArgumentValueError(
                f"User-assigned managed identity is not configured on DPS '{dps_name}'. "
                "Please assign a user identity before linking with UserAssigned authentication."
            )

        linked_hub_entry = {
            "location": location or hub["location"],
            "authenticationType": authentication_type,
            "hostName": host_name,
        }
        if user_assigned_identity:
            linked_hub_entry["selectedUserAssignedIdentityResourceId"] = user_assigned_identity

    # KeyBased Hub Linking in DPS
    else:
        if not any([connection_string, hub_name]):
            raise RequiredArgumentMissingError("Please provide the IoT Hub name or connection string.")
        if not connection_string:
            hub_client = iot_hub_service_factory(cmd.cli_ctx)
            hub = iot_hub_get(cmd, hub_client, hub_name=hub_name, resource_group_name=hub_resource_group)
            host_name = _resolve_linked_hub_hostname(hub, hostname_type)
            location = location or hub["location"]
            # Build connection string with resolved hostname
            policies = iot_hub_policy_get(hub_client, hub_name, IOT_HUB_DEFAULT_POLICY,
                                         _get_resource_group_from_hub(hub))
            connection_string = IOT_SERVICE_CS_TEMPLATE.format(
                host_name, policies["keyName"], policies["primaryKey"]
            )
        else:
            if ".service.azure-devices" in connection_string.lower():
                raise InvalidArgumentValueError(
                    "Service hostname is not supported for DPS hub linking. "
                    "Use a connection string with device or classic hostname."
                )
            parsed_cs = validate_key_value_pairs(connection_string)
            host_name = parsed_cs.get("HostName")
            if not location:
                if not hub_name:
                    try:
                        hub_name = re.search(r"hostname=(.[^\;\.]+)?", connection_string, re.IGNORECASE).group(1)
                    except AttributeError:
                        raise InvalidArgumentValueError("Please provide a valid IoT Hub connection string.")

                hub_client = iot_hub_service_factory(cmd.cli_ctx)
                try:
                    location = iot_hub_get(cmd, hub_client, hub_name=hub_name, resource_group_name=hub_resource_group)["location"]
                except CLIError:
                    raise RequiredArgumentMissingError("Please provide the IoT Hub location.")

        resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
        dps = iot_dps_get(client, dps_name, resource_group_name)

        linked_hub_entry = {
            "connectionString": connection_string,
            "location": location,
            "hostName": host_name,
        }

    _warn_namespace_linked_dps(dps)
    if apply_allocation_policy is not None:
        linked_hub_entry["applyAllocationPolicy"] = apply_allocation_policy
    if allocation_weight is not None:
        linked_hub_entry["allocationWeight"] = allocation_weight

    dps["properties"]["iotHubs"].append(linked_hub_entry)

    # Warn if linked hubs have mixed hostname types (device + classic)
    _warn_mixed_endpoint_types(dps["properties"]["iotHubs"])

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    )
    return iot_dps_linked_hub_list(client, dps_name, resource_group_name)


def iot_dps_linked_hub_update(
    cmd,
    client,
    dps_name,
    linked_hub=None,
    hub_name=None,
    authentication_type=None,
    user_assigned_identity=None,
    connection_string=None,
    resource_group_name=None,
    apply_allocation_policy=None,
    allocation_weight=None,
    no_wait=False,
):
    """Update a linked IoT Hub on a DPS — allocation policy/weight and/or
    authentication type.
    """
    if not hub_name and not linked_hub:
        raise RequiredArgumentMissingError(
            "Specify --hub-name (preferred) or --linked-hub to identify the linked hub."
        )
    if hub_name and linked_hub:
        raise MutuallyExclusiveArgumentError(
            "Specify either --hub-name or --linked-hub, not both."
        )

    mutation_args = {
        "--authentication-type": authentication_type,
        "--connection-string": connection_string,
        "--user-assigned-identity": user_assigned_identity,
        "--allocation-weight": allocation_weight,
        "--apply-allocation-policy": apply_allocation_policy,
    }
    if all(v is None for v in mutation_args.values()):
        raise RequiredArgumentMissingError(
            "Provide at least one update parameter: " + ", ".join(mutation_args.keys()) + "."
        )

    if linked_hub and '.' not in linked_hub:
        hub_name = linked_hub
        linked_hub = None

    if not hub_name:
        hub_name = linked_hub.split(".")[0]

    is_mi = authentication_type in (
        IotHubAuthenticationType.SYSTEM_ASSIGNED.value,
        IotHubAuthenticationType.USER_ASSIGNED.value,
    )
    if is_mi and connection_string:
        raise MutuallyExclusiveArgumentError(
            "--connection-string cannot be used with --authentication-type SystemAssigned "
            "or UserAssigned. Managed identity links do not use a connection string."
        )
    if authentication_type == IotHubAuthenticationType.USER_ASSIGNED.value and not user_assigned_identity:
        raise RequiredArgumentMissingError(
            "--user-assigned-identity is required when --authentication-type is UserAssigned."
        )
    if user_assigned_identity and authentication_type != IotHubAuthenticationType.USER_ASSIGNED.value:
        raise MutuallyExclusiveArgumentError(
            "--user-assigned-identity only applies with --authentication-type UserAssigned."
        )

    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps = iot_dps_get(client, dps_name, resource_group_name)
    _warn_namespace_linked_dps(dps)
    linked_hubs = dps["properties"]["iotHubs"]
    _ensure_linked_hub_hostnames(linked_hubs)
    target_entry = _find_linked_hub_entry(linked_hubs, hub_name=hub_name, linked_hub=linked_hub)

    if is_mi:
        identity_type = (dps.get("identity") or {}).get("type", "None")
        if authentication_type == IotHubAuthenticationType.SYSTEM_ASSIGNED.value and "SystemAssigned" not in identity_type:
            raise InvalidArgumentValueError(
                f"System-assigned managed identity is not enabled on DPS '{dps_name}'. "
                "Enable it before linking with SystemAssigned authentication."
            )
        if authentication_type == IotHubAuthenticationType.USER_ASSIGNED.value and "UserAssigned" not in identity_type:
            raise InvalidArgumentValueError(
                f"User-assigned managed identity is not configured on DPS '{dps_name}'. "
                "Assign a user identity before linking with UserAssigned authentication."
            )

    hub = None
    hub_client = None
    needs_hub_fetch = (
        authentication_type == IotHubAuthenticationType.KEY_BASED.value and not connection_string
    )
    if needs_hub_fetch:
        hub_client = iot_hub_service_factory(cmd.cli_ctx)
        hub = iot_hub_get(cmd, hub_client, hub_name=hub_name)

    if authentication_type:
        target_entry["authenticationType"] = authentication_type
        if authentication_type == IotHubAuthenticationType.USER_ASSIGNED.value:
            target_entry["selectedUserAssignedIdentityResourceId"] = user_assigned_identity
        else:
            target_entry.pop("selectedUserAssignedIdentityResourceId", None)
        if authentication_type != IotHubAuthenticationType.KEY_BASED.value:
            target_entry["connectionString"] = ""

    target_auth = target_entry["authenticationType"]
    if connection_string and target_auth != IotHubAuthenticationType.KEY_BASED.value:
        raise MutuallyExclusiveArgumentError(
            "--connection-string only applies to KeyBased authentication. "
            "The linked hub uses managed identity; provide --authentication-type KeyBased "
            "to switch, or omit --connection-string."
        )

    cs_needs_rebuild = (
        target_auth == IotHubAuthenticationType.KEY_BASED.value
        and (authentication_type or connection_string)
    )
    if cs_needs_rebuild:
        if connection_string:
            if ".service.azure-devices" in connection_string.lower():
                raise InvalidArgumentValueError(
                    "Service hostname is not supported for DPS hub linking. "
                    "Use a connection string with device or classic hostname."
                )
            target_entry["connectionString"] = connection_string
        else:
            parsed_existing_cs = validate_key_value_pairs(target_entry.get("connectionString")) or {}
            existing_policy = parsed_existing_cs.get("SharedAccessKeyName") or IOT_HUB_DEFAULT_POLICY
            policies = iot_hub_policy_get(
                hub_client, hub_name, existing_policy, _get_resource_group_from_hub(hub)
            )
            target_entry["connectionString"] = IOT_SERVICE_CS_TEMPLATE.format(
                target_entry["hostName"], policies["keyName"], policies["primaryKey"]
            )

    if apply_allocation_policy is not None:
        target_entry["applyAllocationPolicy"] = apply_allocation_policy
    if allocation_weight is not None:
        target_entry["allocationWeight"] = allocation_weight

    _warn_mixed_endpoint_types(linked_hubs)

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            provisioning_service_name=dps_name,
            iot_dps_description=dps,
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            provisioning_service_name=dps_name,
            iot_dps_description=dps,
        )
    )
    return iot_dps_linked_hub_get(cmd, client, dps_name, target_entry["name"], resource_group_name)


def iot_dps_linked_hub_delete(cmd, client, dps_name, linked_hub, resource_group_name=None, no_wait=False):
    if '.' not in linked_hub:
        hub_client = iot_hub_service_factory(cmd.cli_ctx)
        linked_hub = _get_iot_hub_hostname(hub_client, linked_hub)

    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps_linked_hubs = []
    dps_linked_hubs.extend(iot_dps_linked_hub_list(client, dps_name, resource_group_name))
    if not _is_linked_hub_existed(dps_linked_hubs, linked_hub):
        raise ResourceNotFoundError("Linked hub {0} doesn't exist.".format(linked_hub))
    updated_hubs = [p for p in dps_linked_hubs if p["name"].lower() != linked_hub.lower()]

    dps = iot_dps_get(client, dps_name, resource_group_name)
    dps["properties"]["iotHubs"] = updated_hubs

    if no_wait:
        return client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name, provisioning_service_name=dps_name, iot_dps_description=dps
        )
    )
    return iot_dps_linked_hub_list(client, dps_name, resource_group_name)


# DPS certificate methods
def iot_dps_certificate_list(client, dps_name, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.dps_certificate.list(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name
    )


def iot_dps_certificate_get(client, dps_name, certificate_name, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.dps_certificate.get(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
        certificate_name=certificate_name
    )


def iot_dps_certificate_create(client, dps_name, certificate_name, certificate_path, resource_group_name=None, is_verified=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    cert_list = client.dps_certificate.list(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name
    )
    for cert in cert_list["value"]:
        if cert["name"] == certificate_name:
            raise CLIError("Certificate '{0}' already exists. Use 'iot dps certificate update'"
                           " to update an existing certificate.".format(certificate_name))
    certificate = open_certificate(certificate_path)
    if not certificate:
        raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
    certificate_bytes = certificate.encode('utf-8')
    properties = {"certificate": certificate_bytes}
    if is_verified is not None:
        properties["isVerified"] = is_verified
    certificate_description = {"properties": properties}
    return client.dps_certificate.create_or_update(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
        certificate_name=certificate_name,
        certificate_description=certificate_description
    )


def iot_dps_certificate_update(client, dps_name, certificate_name, certificate_path, etag, resource_group_name=None, is_verified=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    cert_list = client.dps_certificate.list(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name
    )
    for cert in cert_list["value"]:
        if cert["name"] == certificate_name:
            certificate = open_certificate(certificate_path)
            if not certificate:
                raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
            certificate_bytes = certificate.encode('utf-8')
            properties = {"certificate": certificate_bytes}
            if is_verified is not None:
                properties["isVerified"] = is_verified
            certificate_description = {"properties": properties}
            return client.dps_certificate.create_or_update(
                resource_group_name=resource_group_name,
                provisioning_service_name=dps_name,
                certificate_name=certificate_name,
                certificate_description=certificate_description,
                etag=etag,
                match_condition=MatchConditions.IfNotModified
            )
    raise CLIError("Certificate '{0}' does not exist. Use 'iot dps certificate create' to create a new certificate."
                   .format(certificate_name))


def iot_dps_certificate_delete(client, dps_name, certificate_name, etag, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.dps_certificate.delete(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
        certificate_name=certificate_name,
        etag=etag,
        match_condition=MatchConditions.IfNotModified
    )


def iot_dps_certificate_gen_code(client, dps_name, certificate_name, etag, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    return client.dps_certificate.generate_verification_code(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
        certificate_name=certificate_name,
        etag=etag,
        match_condition=MatchConditions.IfNotModified
    )


def iot_dps_certificate_verify(client, dps_name, certificate_name, certificate_path, etag, resource_group_name=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    certificate = open_certificate(certificate_path)
    if not certificate:
        raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
    request = {"certificate": certificate}
    return client.dps_certificate.verify_certificate(
        resource_group_name=resource_group_name,
        provisioning_service_name=dps_name,
        certificate_name=certificate_name,
        request=request,
        etag=etag,
        match_condition=MatchConditions.IfNotModified
    )


# CUSTOM METHODS
def iot_hub_certificate_list(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.certificates.list_by_iot_hub(
        resource_group_name=resource_group_name,
        resource_name=hub_name
    )


def iot_hub_certificate_get(client, hub_name, certificate_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.certificates.get(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        certificate_name=certificate_name
    )


def iot_hub_certificate_create(client, hub_name, certificate_name, certificate_path, resource_group_name=None, is_verified=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    # Get list of certs
    cert_list = client.certificates.list_by_iot_hub(
        resource_group_name=resource_group_name,
        resource_name=hub_name
    )
    for cert in cert_list["value"]:
        if cert["name"] == certificate_name:
            raise CLIError("Certificate '{0}' already exists. Use 'iot hub certificate update'"
                           " to update an existing certificate.".format(certificate_name))
    certificate = open_certificate(certificate_path)
    if not certificate:
        raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
    cert_properties = {"certificate": certificate}
    if is_verified is not None:
        cert_properties["isVerified"] = is_verified

    cert_description = {"properties": cert_properties}
    return client.certificates.create_or_update(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        certificate_name=certificate_name,
        certificate_description=cert_description
    )


def iot_hub_certificate_update(client, hub_name, certificate_name, certificate_path, etag, resource_group_name=None, is_verified=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    cert_list = client.certificates.list_by_iot_hub(
        resource_group_name=resource_group_name,
        resource_name=hub_name
    )
    for cert in cert_list["value"]:
        if cert["name"] == certificate_name:
            certificate = open_certificate(certificate_path)
            if not certificate:
                raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
            cert_properties = {"certificate": certificate}
            if is_verified is not None:
                cert_properties["isVerified"] = is_verified

            cert_description = {"properties": cert_properties}
            return client.certificates.create_or_update(
                resource_group_name=resource_group_name,
                resource_name=hub_name,
                certificate_name=certificate_name,
                certificate_description=cert_description,
                etag=etag,
                match_condition=MatchConditions.IfNotModified
            )
    raise CLIError("Certificate '{0}' does not exist. Use 'iot hub certificate create' to create a new certificate."
                   .format(certificate_name))


def iot_hub_certificate_delete(client, hub_name, certificate_name, etag, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.certificates.delete(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        certificate_name=certificate_name,
        etag=etag,
        match_condition=MatchConditions.IfNotModified
    )


def iot_hub_certificate_gen_code(client, hub_name, certificate_name, etag, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.certificates.generate_verification_code(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        certificate_name=certificate_name,
        etag=etag,
        match_condition=MatchConditions.IfNotModified
    )


def iot_hub_certificate_verify(client, hub_name, certificate_name, certificate_path, etag, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    certificate = open_certificate(certificate_path)
    if not certificate:
        raise CLIError("Error uploading certificate '{0}'.".format(certificate_path))
    certificate_verify_body = {"certificate": certificate}
    return client.certificates.verify(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        certificate_name=certificate_name,
        etag=etag,
        certificate_verification_body=certificate_verify_body,
        match_condition=MatchConditions.IfNotModified
    )


# pylint: disable=too-many-statements
def iot_hub_create(
    cmd,
    client,
    hub_name,
    resource_group_name,
    location=None,
    sku=IotHubSku.S1.value,
    unit=1,
    partition_count=4,
    retention_day=1,
    c2d_ttl=1,
    c2d_max_delivery_count=10,
    disable_local_auth=None,
    disable_device_sas=None,
    disable_module_sas=None,
    enable_data_residency=None,
    feedback_lock_duration=5,
    feedback_ttl=1,
    feedback_max_delivery_count=10,
    enable_fileupload_notifications=False,
    fileupload_notification_lock_duration=5,
    fileupload_notification_max_delivery_count=10,
    fileupload_notification_ttl=1,
    fileupload_storage_connectionstring=None,
    fileupload_storage_container_name=None,
    fileupload_sas_ttl=1,
    fileupload_storage_authentication_type=None,
    fileupload_storage_identity=None,
    min_tls_version=None,
    tags=None,
    system_identity=None,
    user_identities=None,
    identity_role=None,
    identity_scopes=None,
):
    cli_ctx = cmd.cli_ctx
    # Preview's create is a PUT. Preserve the ADR identity guard when that PUT
    # targets an existing Hub; general upsert/option merging belongs separately.
    availability = client.iot_hub_resource.check_name_availability(
        operation_inputs={"name": hub_name}
    )
    existing_hub = None
    if isinstance(availability, dict) and availability.get("nameAvailable") is False:
        try:
            existing_hub = client.iot_hub_resource.get(
                resource_group_name=resource_group_name, resource_name=hub_name
            )
        except HttpResponseError as error:
            if error.status_code != 404:
                raise
    desired_identity = None
    if existing_hub:
        existing_identity = existing_hub.get("identity") or {}
        desired_identity = _build_identity(
            system=(
                _identity_has_type(existing_identity, SYSTEM_ASSIGNED)
                if system_identity is None else bool(system_identity)
            ),
            identities=(
                list(existing_identity.get("userAssignedIdentities") or {})
                if user_identities is None else user_identities
            ),
        )
        remove_system, remove_users = _identity_removals(existing_identity, desired_identity)
        if remove_system or remove_users:
            _protect_hub_link_identity(
                existing_hub, cmd=cmd, remove_system=remove_system,
                remove_user_identities=remove_users,
            )
    if enable_fileupload_notifications:
        if not fileupload_storage_connectionstring or not fileupload_storage_container_name:
            raise RequiredArgumentMissingError('Please specify storage endpoint (storage connection string and storage container name).')
    if fileupload_storage_connectionstring and not fileupload_storage_container_name:
        raise RequiredArgumentMissingError('Please mention storage container name.')
    if fileupload_storage_container_name and not fileupload_storage_connectionstring:
        raise RequiredArgumentMissingError('Please mention storage connection string.')
    identity_based_file_upload = fileupload_storage_authentication_type and fileupload_storage_authentication_type == AuthenticationType.IdentityBased
    if not identity_based_file_upload and fileupload_storage_identity:
        raise RequiredArgumentMissingError('In order to set a fileupload storage identity, please set file upload storage authentication (--fsa) to IdentityBased')

    if identity_based_file_upload or fileupload_storage_identity:
        # Not explicitly setting fileupload_storage_identity assumes system-assigned managed identity for file upload
        if fileupload_storage_identity in [None, SYSTEM_ASSIGNED_IDENTITY] and not system_identity:
            raise ArgumentUsageError('System managed identity [--system-assigned-mi] must be enabled in order to use managed identity for file upload')
        if fileupload_storage_identity and fileupload_storage_identity != SYSTEM_ASSIGNED_IDENTITY and not user_identities:
            raise ArgumentUsageError('User identity [--user-assigned-mi] must be added in order to use it for file upload')
    location = _ensure_location(cli_ctx, resource_group_name, location)

    if location.lower() == 'qatarcentral' and not enable_data_residency:
        raise InvalidArgumentValueError(
            "Data Residency enforcement must be enabled for IoT Hubs created in this region. Please use the '--enforce-data-residency' (--edr) argument "
            "to enable it. Check command help (-h) for more information on this property's usage and implications."
        )

    sku = {"name": sku, "capacity": unit}

    event_hub_dic = {}
    event_hub_dic['events'] = {"retentionTimeInDays": retention_day,
                                  "partitionCount": partition_count}
    feedback_Properties = {"lockDurationAsIso8601": timedelta(seconds=feedback_lock_duration),
                              "ttlAsIso8601": timedelta(hours=feedback_ttl),
                              "maxDeliveryCount": feedback_max_delivery_count}
    cloud_to_device_properties = {"maxDeliveryCount": c2d_max_delivery_count,
                                      "defaultTtlAsIso8601": timedelta(hours=c2d_ttl),
                                      "feedback": feedback_Properties}
    msg_endpoint_dic = {}
    msg_endpoint_dic['fileNotifications'] = {"maxDeliveryCount": fileupload_notification_max_delivery_count,
                                                "ttlAsIso8601": timedelta(hours=fileupload_notification_ttl),
                                                "lockDurationAsIso8601": timedelta(seconds=fileupload_notification_lock_duration)}
    storage_endpoint_dic = {}
    storage_endpoint_dic['$default'] = {
        "sasTtlAsIso8601": timedelta(hours=fileupload_sas_ttl),
        "connectionString": fileupload_storage_connectionstring if fileupload_storage_connectionstring else '',
        "containerName": fileupload_storage_container_name if fileupload_storage_container_name else '',
        "authenticationType": fileupload_storage_authentication_type if fileupload_storage_authentication_type else None,
        "identity": {"userAssignedIdentity": fileupload_storage_identity} if fileupload_storage_identity else None}

    properties = {"eventHubEndpoints": event_hub_dic,
                    "messagingEndpoints": msg_endpoint_dic,
                    "storageEndpoints": storage_endpoint_dic,
                    "cloudToDevice": cloud_to_device_properties,
                    "minTlsVersion": min_tls_version,
                    "enableDataResidency": enable_data_residency,
                    "disableLocalAuth": disable_local_auth,
                    "disableDeviceSAS": disable_device_sas,
                    "disableModuleSAS": disable_module_sas}
    properties["enableFileUploadNotifications"] = enable_fileupload_notifications

    hub_description = {"location": location,
                       "sku": sku,
                       "properties": properties,
                       "tags": tags}
    if (system_identity or user_identities):
        hub_description["identity"] = _build_identity(system=bool(system_identity), identities=user_identities)
    if desired_identity is not None:
        hub_description["identity"] = desired_identity
    if bool(identity_role) ^ bool(identity_scopes):
        raise RequiredArgumentMissingError('At least one scope (--scopes) and one role (--role) required for system-assigned managed identity role assignment')

    def identity_assignment(lro):
        try:
            instance = lro.resource()
            identity = instance.get("identity")
            if identity:
                principal_id = identity.get("principalId")
                if principal_id:
                    hub_description["identity"]["principalId"] = principal_id
                    for scope in identity_scopes:
                        assign_identity(cmd.cli_ctx, lambda: hub_description, lambda hub: hub_description, identity_role=identity_role, identity_scope=scope)
        except HttpResponseError as e:
            raise e

    create = client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name,
        iot_hub_description=hub_description, **hub_etag_arguments(existing_hub)
    )
    if identity_role and identity_scopes:
        create.add_done_callback(identity_assignment)
    return create


def iot_hub_get(cmd, client, hub_name, resource_group_name=None):
    cli_ctx = cmd.cli_ctx
    if resource_group_name is None:
        return _get_iot_hub_by_name(client, hub_name)
    if not _ensure_resource_group_existence(cli_ctx, resource_group_name):
        raise CLIError("Resource group '{0}' could not be found.".format(resource_group_name))
    name_availability = client.iot_hub_resource.check_name_availability(operation_inputs={"name": hub_name})
    if name_availability is not None and name_availability["nameAvailable"]:
        raise CLIError("An IotHub '{0}' under resource group '{1}' was not found."
                       .format(hub_name, resource_group_name))
    return client.iot_hub_resource.get(resource_group_name=resource_group_name, resource_name=hub_name)


def iot_hub_list(client, resource_group_name=None):
    if resource_group_name is None:
        return client.iot_hub_resource.list_by_subscription()
    return client.iot_hub_resource.list_by_resource_group(resource_group_name=resource_group_name)


def update_iot_hub_custom(instance,
    sku=None,
    unit=None,
    retention_day=None,
    c2d_ttl=None,
    c2d_max_delivery_count=None,
    disable_local_auth=None,
    disable_device_sas=None,
    disable_module_sas=None,
    feedback_lock_duration=None,
    feedback_ttl=None,
    feedback_max_delivery_count=None,
    enable_fileupload_notifications=None,
    fileupload_notification_lock_duration=None,
    fileupload_notification_max_delivery_count=None,
    fileupload_notification_ttl=None,
    fileupload_storage_connectionstring=None,
    fileupload_storage_container_name=None,
    fileupload_sas_ttl=None,
    fileupload_storage_authentication_type=None,
    fileupload_storage_container_uri=None,
    fileupload_storage_identity=None,
    min_tls_version=None,
    tags=None,
):
    if tags is not None:
        instance["tags"] = tags
    if unit is not None:
        instance["sku"]["capacity"] = unit
    if retention_day is not None:
        instance["properties"]["eventHubEndpoints"]['events']["retentionTimeInDays"] = retention_day
    if c2d_ttl is not None:
        instance["properties"]["cloudToDevice"]["defaultTtlAsIso8601"] = timedelta(hours=c2d_ttl)
    if c2d_max_delivery_count is not None:
        instance["properties"]["cloudToDevice"]["maxDeliveryCount"] = c2d_max_delivery_count
    if feedback_lock_duration is not None:
        duration = timedelta(seconds=feedback_lock_duration)
        instance["properties"]["cloudToDevice"]["feedback"]["lockDurationAsIso8601"] = duration
    if feedback_ttl is not None:
        instance["properties"]["cloudToDevice"]["feedback"]["ttlAsIso8601"] = timedelta(hours=feedback_ttl)
    if feedback_max_delivery_count is not None:
        instance["properties"]["cloudToDevice"]["feedback"]["maxDeliveryCount"] = feedback_max_delivery_count
    if enable_fileupload_notifications is not None:
        instance["properties"]["enableFileUploadNotifications"] = enable_fileupload_notifications
    if fileupload_notification_lock_duration is not None:
        lock_duration = timedelta(seconds=fileupload_notification_lock_duration)
        instance["properties"]["messagingEndpoints"]['fileNotifications']["lockDurationAsIso8601"] = lock_duration
    if fileupload_notification_max_delivery_count is not None:
        count = fileupload_notification_max_delivery_count
        instance["properties"]["messagingEndpoints"]['fileNotifications']["maxDeliveryCount"] = count
    if fileupload_notification_ttl is not None:
        ttl = timedelta(hours=fileupload_notification_ttl)
        instance["properties"]["messagingEndpoints"]['fileNotifications']["ttlAsIso8601"] = ttl
    if min_tls_version is not None:
        instance["properties"]["minTlsVersion"] = min_tls_version
    # only bother with $default storage endpoint checking if modifying fileupload params
    if any([
            fileupload_storage_connectionstring, fileupload_storage_container_name, fileupload_sas_ttl,
            fileupload_storage_authentication_type, fileupload_storage_container_uri, fileupload_storage_identity]):
        default_storage_endpoint = instance["properties"]["storageEndpoints"].get('$default', None)
        # no default storage endpoint, either recreate with existing params or throw an error
        if not default_storage_endpoint:
            if not all([fileupload_storage_connectionstring, fileupload_storage_container_name]):
                raise UnclassifiedUserFault('This hub has no default storage endpoint for file upload.\n'
                                            'Please recreate your default storage endpoint by running '
                                            '`az iot hub update --name {hub_name} --fcs {storage_connection_string} --fc {storage_container_name}`')
            default_storage_endpoint = {"containerName": fileupload_storage_container_name, "connectionString": fileupload_storage_connectionstring}

        # if setting a fileupload storage identity or changing fileupload to identity-based
        if fileupload_storage_identity or fileupload_storage_authentication_type == AuthenticationType.IdentityBased:
            _validate_fileupload_identity(instance, fileupload_storage_identity)

        instance["properties"]["storageEndpoints"]['$default'] = _process_fileupload_args(
            default_storage_endpoint,
            fileupload_storage_connectionstring,
            fileupload_storage_container_name,
            fileupload_sas_ttl,
            fileupload_storage_authentication_type,
            fileupload_storage_container_uri,
            fileupload_storage_identity,
        )

    _update_iot_hub_auth(
        instance=instance,
        disable_local_auth=disable_local_auth,
        disable_device_sas=disable_device_sas,
        disable_module_sas=disable_module_sas
    )

    if sku is not None:
        instance["sku"]["name"] = sku
    return instance


def _update_iot_hub_auth(instance, disable_local_auth=None, disable_device_sas=None, disable_module_sas=None):
    # sas token authentication switches
    if disable_local_auth is not None:
        instance["properties"]["disableLocalAuth"] = disable_local_auth
    if disable_device_sas is not None:
        instance["properties"]["disableDeviceSAS"] = disable_device_sas
    if disable_module_sas is not None:
        instance["properties"]["disableModuleSAS"] = disable_module_sas


def iot_hub_update(client, hub_name, parameters, resource_group_name=None, cmd=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    current = client.iot_hub_resource.get(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
    )
    remove_system, remove_user_identities = _identity_removals(
        (current or {}).get("identity"),
        (parameters or {}).get("identity"),
    )
    if remove_system or remove_user_identities:
        _protect_hub_link_identity(
            current,
            remove_system=remove_system,
            remove_user_identities=remove_user_identities,
            cmd=cmd,
        )
    return adapt_modeless_lro_poller(
        client.iot_hub_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            resource_name=hub_name,
            iot_hub_description=_hub_description_for_write(parameters),
            **hub_etag_arguments(parameters),
        )
    )


def iot_hub_delete(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.begin_delete(resource_group_name=resource_group_name, resource_name=hub_name)


# pylint: disable=inconsistent-return-statements
def iot_hub_show_connection_string(client, hub_name=None, resource_group_name=None, policy_name='iothubowner',
                                   key_type=KeyType.primary.value, show_all=False):
    if hub_name is None:
        hubs = iot_hub_list(client, resource_group_name)
        if hubs is None:
            raise CLIError("No IoT Hub found.")

        def conn_str_getter(h):
            return _get_hub_connection_string(client, h["name"], _get_resource_group_from_hub(h), policy_name, key_type, show_all)
        return [{'name': h["name"], 'connectionString': conn_str_getter(h)} for h in hubs]
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    conn_str = _get_hub_connection_string(client, hub_name, resource_group_name, policy_name, key_type, show_all)
    return {'connectionString': conn_str if show_all else conn_str[0]}


def _get_hub_connection_string(client, hub_name, resource_group_name, policy_name, key_type, show_all):
    policies = []
    if show_all:
        policies.extend(iot_hub_policy_list(client, hub_name, resource_group_name))
    else:
        policies.append(iot_hub_policy_get(client, hub_name, policy_name, resource_group_name))
    hostname = _get_iot_hub_hostname(client, hub_name)
    conn_str_template = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'
    return [conn_str_template.format(hostname,
                                     p["keyName"],
                                     p["secondaryKey"] if key_type == KeyType.secondary else p["primaryKey"]) for p in policies]


def iot_hub_sku_list(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.get_valid_skus(resource_group_name=resource_group_name, resource_name=hub_name)


def iot_hub_consumer_group_create(client, hub_name, consumer_group_name, resource_group_name=None, event_hub_name='events'):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    consumer_group_body = {"properties": {"name": consumer_group_name}}
    # Fix for breaking change argument in track 1 SDK method.
    from azure.cli.core.util import get_arg_list
    create_cg_op = client.iot_hub_resource.create_event_hub_consumer_group
    if "consumer_group_body" not in get_arg_list(create_cg_op):
        return create_cg_op(
            resource_group_name=resource_group_name,
            resource_name=hub_name,
            event_hub_endpoint_name=event_hub_name,
            name=consumer_group_name,
        )
    return create_cg_op(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        event_hub_endpoint_name=event_hub_name,
        name=consumer_group_name,
        consumer_group_body=consumer_group_body,
    )


def iot_hub_consumer_group_list(client, hub_name, resource_group_name=None, event_hub_name='events'):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.list_event_hub_consumer_groups(
        resource_group_name=resource_group_name, resource_name=hub_name, event_hub_endpoint_name=event_hub_name
    )


def iot_hub_consumer_group_get(client, hub_name, consumer_group_name, resource_group_name=None, event_hub_name='events'):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.get_event_hub_consumer_group(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        event_hub_endpoint_name=event_hub_name,
        name=consumer_group_name,
    )


def iot_hub_consumer_group_delete(client, hub_name, consumer_group_name, resource_group_name=None, event_hub_name='events'):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.delete_event_hub_consumer_group(
        resource_group_name=resource_group_name,
        resource_name=hub_name,
        event_hub_endpoint_name=event_hub_name,
        name=consumer_group_name,
    )


def iot_hub_identity_assign(cmd, client, hub_name, system_identity=None, user_identities=None, identity_role=None, identity_scopes=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)

    def getter():
        return iot_hub_get(cmd, client, hub_name, resource_group_name)

    def setter(hub):
        hub["identity"] = hub.get("identity") or {"type": IdentityType.none.value}
        if user_identities and not hub["identity"].get("userAssignedIdentities"):
            hub["identity"]["userAssignedIdentities"] = {}
        if user_identities:
            existing_user_ids = {
                resource_id.rstrip("/").casefold(): resource_id
                for resource_id in hub["identity"]["userAssignedIdentities"]
            }
            for identity in user_identities:
                if identity.rstrip("/").casefold() not in existing_user_ids:
                    hub["identity"]["userAssignedIdentities"][identity] = {}
                    existing_user_ids[identity.rstrip("/").casefold()] = identity

        has_system_identity = _identity_has_type(
            hub["identity"], IdentityType.system_assigned.value
        )

        if system_identity or has_system_identity:
            hub["identity"]["type"] = IdentityType.system_assigned_user_assigned.value if hub["identity"].get("userAssignedIdentities") else IdentityType.system_assigned.value
        else:
            hub["identity"]["type"] = IdentityType.user_assigned.value if hub["identity"].get("userAssignedIdentities") else IdentityType.none.value

        poller = adapt_modeless_lro_poller(
            client.iot_hub_resource.begin_create_or_update(
                resource_group_name=resource_group_name,
                resource_name=hub_name,
                iot_hub_description=_hub_description_for_write(hub),
                **hub_etag_arguments(hub),
            )
        )
        return LongRunningOperation(cmd.cli_ctx)(poller)

    if bool(identity_role) ^ bool(identity_scopes):
        raise RequiredArgumentMissingError('At least one scope (--scopes) and one role (--role) required for system-managed identity role assignment.')
    if not system_identity and not user_identities:
        raise RequiredArgumentMissingError('No identities provided to assign. Please provide system (--system) or user-assigned identities (--user).')
    if identity_role and identity_scopes:
        for scope in identity_scopes:
            hub = assign_identity(cmd.cli_ctx, getter, setter, identity_role=identity_role, identity_scope=scope)
        return hub["identity"]
    result = setter(getter())
    return result["identity"]


def iot_hub_identity_show(cmd, client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    return hub["identity"]


def iot_hub_identity_remove(cmd, client, hub_name, system_identity=None, user_identities=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    hub_identity = hub["identity"]

    if not system_identity and user_identities is None:
        raise RequiredArgumentMissingError('No identities provided to remove. Please provide system (--system) or user-assigned identities (--user).')
    _protect_hub_link_identity(
        hub,
        remove_system=bool(system_identity),
        remove_user_identities=user_identities,
        cmd=cmd,
    )
    # Turn off system managed identity
    if system_identity:
        if not _identity_has_type(
            hub_identity, IdentityType.system_assigned.value
        ):
            raise ArgumentUsageError('Hub {} is not currently using a system-assigned identity'.format(hub_name))
        hub_identity["type"] = (
            IdentityType.user_assigned.value
            if hub_identity.get("userAssignedIdentities")
            else IdentityType.none.value
        )

    if user_identities:
        # loop through user_identities to remove
        identities_to_remove = user_identities if isinstance(user_identities, (list, tuple)) else [user_identities]
        for identity in identities_to_remove:
            attached = {
                resource_id.rstrip("/").casefold(): resource_id
                for resource_id in (
                    hub_identity.get("userAssignedIdentities") or {}
                )
            }
            normalized = identity.rstrip("/").casefold()
            if normalized not in attached:
                raise ArgumentUsageError('Hub {0} is not currently using a user-assigned identity with id: {1}'.format(hub_name, identity))
            del hub_identity["userAssignedIdentities"][attached[normalized]]
        if not hub_identity.get("userAssignedIdentities"):
            hub_identity.pop("userAssignedIdentities", None)
    elif isinstance(user_identities, list):
        hub_identity.pop("userAssignedIdentities", None)

    if _identity_has_type(hub_identity, IdentityType.system_assigned.value):
        hub_identity["type"] = IdentityType.system_assigned_user_assigned.value if hub_identity.get("userAssignedIdentities") else IdentityType.system_assigned.value
    else:
        hub_identity["type"] = IdentityType.user_assigned.value if hub_identity.get("userAssignedIdentities") else IdentityType.none.value

    hub["identity"] = hub_identity
    if not hub["identity"].get("userAssignedIdentities"):
        hub["identity"]["userAssignedIdentities"] = None
    poller = adapt_modeless_lro_poller(
        client.iot_hub_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            resource_name=hub_name,
            iot_hub_description=_hub_description_for_write(hub),
            **hub_etag_arguments(hub),
        )
    )
    lro = LongRunningOperation(cmd.cli_ctx)(poller)
    return lro["identity"]


def _adr_identity_target(cmd, resource, kind):
    """Read authoritative ADR projections before a legacy identity removal.

    General commands retain preview's management API and endpoint. Only this
    safety read uses the canary target contract, in the resource's subscription.
    Preserve direct Python callers that already supply an authoritative object.
    """
    if cmd is None:
        return resource

    from msrestazure.tools import parse_resource_id
    from azext_iot._factory import (
        adr_iot_hub_service_factory,
        adr_iot_service_provisioning_factory,
    )

    resource_id = (resource or {}).get("id")
    parsed = parse_resource_id(resource_id) if isinstance(resource_id, str) else {}
    if not all(parsed.get(key) for key in ("subscription", "resource_group", "name")):
        raise ArgumentUsageError(
            "Cannot validate the ADR link identity without a target resource ID."
        )
    try:
        if kind == "hub":
            client = adr_iot_hub_service_factory(
                cmd.cli_ctx, subscription_id=parsed["subscription"]
            )
            target = client.iot_hub_resource.get(
                resource_group_name=parsed["resource_group"], resource_name=parsed["name"]
            )
        else:
            client = adr_iot_service_provisioning_factory(
                cmd.cli_ctx, subscription_id=parsed["subscription"]
            )
            target = client.iot_dps_resource.get(
                resource_group_name=parsed["resource_group"],
                provisioning_service_name=parsed["name"],
            )
        if not isinstance(target, dict) or str(target.get("id", "")).rstrip("/").casefold() != resource_id.rstrip("/").casefold():
            raise ValueError("The ADR target response did not identify the requested resource.")
        return target
    except Exception as error:
        raise ArgumentUsageError(
            "The ADR link identity could not be validated. Do not remove identities "
            "until you can read the target and rotate or delete its namespace link."
        ) from error


def _protect_hub_link_identity(
    hub: dict,
    *,
    remove_system: bool,
    remove_user_identities,
    cmd=None,
) -> None:
    hub = _adr_identity_target(cmd, hub, "hub")
    device_registry = ((hub or {}).get("properties") or {}).get(
        "deviceRegistry"
    ) or {}
    linking_state = str(
        (device_registry.get("linkingProperties") or {}).get("state") or ""
    ).casefold()
    if not device_registry.get("namespaceResourceId") or linking_state == "failed":
        return

    selected = device_registry.get("identity") or {}
    selected_type = str(selected.get("type") or "").casefold()
    if remove_system and selected_type == "systemassigned":
        raise ArgumentUsageError(
            "The Hub system-assigned identity is used by an active ADR link. "
            "Rotate it first with 'az iot adr ns link hub update --user-assigned-mi ...' "
            "or permanently delete the link."
        )
    selected_uami = selected.get("userAssignedIdentity")
    removals = {
        identity.rstrip("/").casefold()
        for identity in (remove_user_identities or [])
    }
    if (
        selected_type == "userassigned"
        and selected_uami
        and (
            selected_uami.rstrip("/").casefold() in removals
            or remove_user_identities == []
        )
    ):
        raise ArgumentUsageError(
            "The selected Hub user-assigned identity is used by an active ADR "
            "link. Rotate it first with 'az iot adr ns link hub update' or "
            "permanently delete the link."
        )


def iot_hub_policy_list(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.list_keys(resource_group_name=resource_group_name, resource_name=hub_name)


def iot_hub_policy_get(client, hub_name, policy_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.get_keys_for_key_name(
        resource_group_name=resource_group_name, resource_name=hub_name, key_name=policy_name
    )


def iot_hub_policy_create(cmd, client, hub_name, policy_name, permissions, resource_group_name=None):
    rights = _convert_perms_to_access_rights(permissions)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    policies = []
    policies.extend(iot_hub_policy_list(client, hub_name, _get_resource_group_from_hub(hub)))
    if _does_policy_exist(policies, policy_name):
        raise CLIError("Policy {0} already existed.".format(policy_name))
    policies.append({"keyName": policy_name, "rights": rights})
    hub["properties"]["authorizationPolicies"] = policies
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=_get_resource_group_from_hub(hub),
        resource_name=hub_name,
        iot_hub_description=hub,
        etag=hub["etag"],
    )


def iot_hub_policy_delete(cmd, client, hub_name, policy_name, resource_group_name=None):
    import copy
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    policies = iot_hub_policy_list(client, hub_name, _get_resource_group_from_hub(hub))
    if not _does_policy_exist(copy.deepcopy(policies), policy_name):
        raise CLIError("Policy {0} not found.".format(policy_name))
    updated_policies = [p for p in policies if p["keyName"].lower() != policy_name.lower()]
    hub["properties"]["authorizationPolicies"] = updated_policies
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=_get_resource_group_from_hub(hub),
        resource_name=hub_name,
        iot_hub_description=hub,
        etag=hub["etag"],
    )


def iot_hub_policy_key_renew(cmd, client, hub_name, policy_name, regenerate_key, resource_group_name=None, no_wait=False):
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    policies = []
    policies.extend(iot_hub_policy_list(client, hub_name, _get_resource_group_from_hub(hub)))
    if not _does_policy_exist(policies, policy_name):
        raise CLIError("Policy {0} not found.".format(policy_name))
    updated_policies = [p for p in policies if p["keyName"].lower() != policy_name.lower()]
    requested_policy = [p for p in policies if p["keyName"].lower() == policy_name.lower()]
    if regenerate_key == RenewKeyType.Primary.value:
        requested_policy[0]["primaryKey"] = None
    if regenerate_key == RenewKeyType.Secondary.value:
        requested_policy[0]["secondaryKey"] = None
    if regenerate_key == RenewKeyType.Swap.value:
        temp = requested_policy[0]["primaryKey"]
        requested_policy[0]["primaryKey"] = requested_policy[0]["secondaryKey"]
        requested_policy[0]["secondaryKey"] = temp
    updated_policies.append({"keyName": requested_policy[0]["keyName"],
                             "rights": requested_policy[0]["rights"],
                             "primaryKey": requested_policy[0]["primaryKey"],
                             "secondaryKey": requested_policy[0]["secondaryKey"]})
    hub["properties"]["authorizationPolicies"] = updated_policies
    if no_wait:
        return client.iot_hub_resource.begin_create_or_update(
            resource_group_name=_get_resource_group_from_hub(hub),
            resource_name=hub_name,
            iot_hub_description=hub,
            etag=hub["etag"],
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_hub_resource.begin_create_or_update(
            resource_group_name=_get_resource_group_from_hub(hub),
            resource_name=hub_name,
            iot_hub_description=hub,
            etag=hub["etag"],
        )
    )
    return iot_hub_policy_get(client, hub_name, policy_name, resource_group_name)


def _does_policy_exist(policies, policy_name):
    policy_set = {p["keyName"].lower() for p in policies}
    return policy_name.lower() in policy_set


def iot_hub_get_quota_metrics(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    iotHubQuotaMetricCollection = []
    iotHubQuotaMetricCollection.extend(
        client.iot_hub_resource.get_quota_metrics(resource_group_name=resource_group_name, resource_name=hub_name)
    )
    for quotaMetric in iotHubQuotaMetricCollection:
        if quotaMetric["name"] == 'TotalDeviceCount':
            quotaMetric["maxValue"] = 'Unlimited'
    return iotHubQuotaMetricCollection


def iot_hub_get_stats(client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    return client.iot_hub_resource.get_stats(resource_group_name=resource_group_name, resource_name=hub_name)


def validate_authentication_type_input(endpoint_type, connection_string=None, authentication_type=None, endpoint_uri=None, entity_path=None):
    is_keyBased = (AuthenticationType.KeyBased == authentication_type) or (authentication_type is None)
    has_connection_string = connection_string is not None
    if is_keyBased and not has_connection_string:
        raise CLIError("Please provide a connection string '--connection-string/-c'")

    has_endpoint_uri = endpoint_uri is not None
    has_endpoint_uri_and_path = (has_endpoint_uri) and (entity_path is not None)
    if EndpointType.AzureStorageContainer.value == endpoint_type.lower() and not has_endpoint_uri:
        raise CLIError("Please provide an endpoint uri '--endpoint-uri'")
    if not has_endpoint_uri_and_path:
        raise CLIError("Please provide an endpoint uri '--endpoint-uri' and entity path '--entity-path'")


def iot_hub_routing_endpoint_create(cmd, client, hub_name, endpoint_name, endpoint_type,
                                    endpoint_resource_group, endpoint_subscription_id,
                                    connection_string=None, container_name=None, encoding=None,
                                    resource_group_name=None, batch_frequency=300, chunk_size_window=300,
                                    file_name_format='{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}',
                                    authentication_type=None, endpoint_uri=None, entity_path=None,
                                    identity=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    if identity and authentication_type != AuthenticationType.IdentityBased:
        raise ArgumentUsageError("In order to use an identity for authentication, you must select --auth-type as 'identityBased'")

    if EndpointType.EventHub.value == endpoint_type.lower():
        hub["properties"]["routing"]["endpoints"]["eventHubs"].append(
            {"connectionString": connection_string,
             "name": endpoint_name,
             "subscriptionId": endpoint_subscription_id,
             "resourceGroup": endpoint_resource_group,
             "authenticationType": authentication_type,
             "endpointUri": endpoint_uri,
             "entityPath": entity_path,
             "identity": {"userAssignedIdentity": identity} if identity and identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY] else None}
        )
    elif EndpointType.ServiceBusQueue.value == endpoint_type.lower():
        hub["properties"]["routing"]["endpoints"]["serviceBusQueues"].append(
            {"connectionString": connection_string,
             "name": endpoint_name,
             "subscriptionId": endpoint_subscription_id,
             "resourceGroup": endpoint_resource_group,
             "authenticationType": authentication_type,
             "endpointUri": endpoint_uri,
             "entityPath": entity_path,
             "identity": {"userAssignedIdentity": identity} if identity and identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY] else None}
        )
    elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
        hub["properties"]["routing"]["endpoints"]["serviceBusTopics"].append(
            {"connectionString": connection_string,
             "name": endpoint_name,
             "subscriptionId": endpoint_subscription_id,
             "resourceGroup": endpoint_resource_group,
             "authenticationType": authentication_type,
             "endpointUri": endpoint_uri,
             "entityPath": entity_path,
             "identity": {"userAssignedIdentity": identity} if identity and identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY] else None}
        )
    elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
        if not container_name:
            raise CLIError("Container name is required.")
        hub["properties"]["routing"]["endpoints"]["storageContainers"].append(
            {"connectionString": connection_string,
             "name": endpoint_name,
             "subscriptionId": endpoint_subscription_id,
             "resourceGroup": endpoint_resource_group,
             "containerName": container_name,
             "encoding": encoding.lower() if encoding else EncodingFormat.AVRO.value,
             "fileNameFormat": file_name_format,
             "batchFrequencyInSeconds": batch_frequency,
             "maxChunkSizeInBytes": (chunk_size_window * 1048576),
             "authenticationType": authentication_type,
             "endpointUri": endpoint_uri,
             "identity": {"userAssignedIdentity": identity} if identity and identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY] else None}
        )

    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_hub_routing_endpoint_list(cmd, client, hub_name, endpoint_type=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    if not endpoint_type:
        return hub["properties"]["routing"]["endpoints"]
    if EndpointType.EventHub.value == endpoint_type.lower():
        return hub["properties"]["routing"]["endpoints"]["eventHubs"]
    if EndpointType.ServiceBusQueue.value == endpoint_type.lower():
        return hub["properties"]["routing"]["endpoints"]["serviceBusQueues"]
    if EndpointType.ServiceBusTopic.value == endpoint_type.lower():
        return hub["properties"]["routing"]["endpoints"]["serviceBusTopics"]
    if EndpointType.AzureStorageContainer.value == endpoint_type.lower():
        return hub["properties"]["routing"]["endpoints"]["storageContainers"]


def iot_hub_routing_endpoint_show(cmd, client, hub_name, endpoint_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    for event_hub in hub["properties"]["routing"]["endpoints"]["eventHubs"]:
        if event_hub["name"].lower() == endpoint_name.lower():
            return event_hub
    for service_bus_queue in hub["properties"]["routing"]["endpoints"]["serviceBusQueues"]:
        if service_bus_queue["name"].lower() == endpoint_name.lower():
            return service_bus_queue
    for service_bus_topic in hub["properties"]["routing"]["endpoints"]["serviceBusTopics"]:
        if service_bus_topic["name"].lower() == endpoint_name.lower():
            return service_bus_topic
    for storage_container in hub["properties"]["routing"]["endpoints"]["storageContainers"]:
        if storage_container["name"].lower() == endpoint_name.lower():
            return storage_container
    raise CLIError("No endpoint found.")


def iot_hub_routing_endpoint_delete(cmd, client, hub_name, endpoint_name=None, endpoint_type=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    hub["properties"]["routing"]["endpoints"] = _delete_routing_endpoints(endpoint_name, endpoint_type, hub["properties"]["routing"]["endpoints"])
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_hub_route_create(cmd, client, hub_name, route_name, source_type, endpoint_name, enabled=None, condition=None,
                         resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    hub["properties"]["routing"]["routes"].append(
        {"source": source_type,
         "name": route_name,
         "endpointNames": endpoint_name.split(),
         "condition": ('true' if condition is None else condition),
         "isEnabled": (True if enabled is None else enabled)}
    )
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_hub_route_list(cmd, client, hub_name, source_type=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    if source_type:
        return [route for route in hub["properties"]["routing"]["routes"] if route["source"].lower() == source_type.lower()]
    return hub["properties"]["routing"]["routes"]


def iot_hub_route_show(cmd, client, hub_name, route_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    for route in hub["properties"]["routing"]["routes"]:
        if route["name"].lower() == route_name.lower():
            return route
    raise CLIError("No route found.")


def iot_hub_route_delete(cmd, client, hub_name, route_name=None, source_type=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    if not route_name and not source_type:
        hub["properties"]["routing"]["routes"] = []
    if route_name:
        hub["properties"]["routing"]["routes"] = [route for route in hub["properties"]["routing"]["routes"]
                                          if route["name"].lower() != route_name.lower()]
    if source_type:
        hub["properties"]["routing"]["routes"] = [route for route in hub["properties"]["routing"]["routes"]
                                          if route["source"].lower() != source_type.lower()]
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_hub_route_update(cmd, client, hub_name, route_name, source_type=None, endpoint_name=None, enabled=None,
                         condition=None, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    updated_route = next((route for route in hub["properties"]["routing"]["routes"]
                          if route["name"].lower() == route_name.lower()), None)
    if updated_route:
        updated_route["source"] = updated_route["source"] if source_type is None else source_type
        updated_route["endpointNames"] = updated_route["endpointNames"] if endpoint_name is None else endpoint_name.split()
        updated_route["condition"] = updated_route["condition"] if condition is None else condition
        updated_route["isEnabled"] = updated_route["isEnabled"] if enabled is None else enabled
    else:
        raise CLIError("No route found.")
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_hub_route_test(cmd, client, hub_name, route_name=None, source_type=None, body=None, app_properties=None,
                       system_properties=None, resource_group_name=None):
    if app_properties:
        app_properties = json.loads(app_properties)
    if system_properties:
        system_properties = json.loads(system_properties)
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    route_message = {
        "body": body,
        "appProperties": app_properties,
        "systemProperties": system_properties
    }

    if route_name:
        route = iot_hub_route_show(cmd, client, hub_name, route_name, resource_group_name)
        test_route_input = {
            "message": route_message,
            "twin": None,
            "route": route
        }
        return client.iot_hub_resource.test_route(
            iot_hub_name=hub_name, resource_group_name=resource_group_name, input=test_route_input
        )
    test_all_routes_input = {
        "routingSource": source_type,
        "message": route_message,
        "twin": None
    }
    return client.iot_hub_resource.test_all_routes(
        iot_hub_name=hub_name, resource_group_name=resource_group_name, input=test_all_routes_input
    )


def iot_message_enrichment_create(cmd, client, hub_name, key, value, endpoints, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    if hub["properties"]["routing"].get("enrichments") is None:
        hub["properties"]["routing"]["enrichments"] = []
    hub["properties"]["routing"]["enrichments"].append({"key": key, "value": value, "endpointNames": endpoints})
    return client.iot_hub_resource.begin_create_or_update(
        resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
    )


def iot_message_enrichment_update(cmd, client, hub_name, key, value, endpoints, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    to_update = next((endpoint for endpoint in hub["properties"]["routing"]["enrichments"] if endpoint["key"] == key), None)
    if to_update:
        to_update["key"] = key
        to_update["value"] = value
        to_update["endpointNames"] = endpoints
        return client.iot_hub_resource.begin_create_or_update(
            resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
        )
    raise CLIError('No message enrichment with that key exists')


def iot_message_enrichment_delete(cmd, client, hub_name, key, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    to_remove = next((endpoint for endpoint in hub["properties"]["routing"]["enrichments"] if endpoint["key"] == key), None)
    if to_remove:
        hub["properties"]["routing"]["enrichments"].remove(to_remove)
        return client.iot_hub_resource.begin_create_or_update(
            resource_group_name=resource_group_name, resource_name=hub_name, iot_hub_description=hub, etag=hub["etag"]
        )
    raise CLIError('No message enrichment with that key exists')


def iot_message_enrichment_list(cmd, client, hub_name, resource_group_name=None):
    resource_group_name = _ensure_hub_resource_group_name(client, resource_group_name, hub_name)
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    return hub["properties"]["routing"]["enrichments"]


def iot_hub_manual_failover(cmd, client, hub_name, resource_group_name=None, no_wait=False):
    hub = iot_hub_get(cmd, client, hub_name, resource_group_name)
    resource_group_name = _get_resource_group_from_hub(hub)
    failover_region = next(x["location"] for x in hub["properties"]["locations"] if x["role"].lower() == 'secondary')
    failover_input = {"failoverRegion": failover_region}
    if no_wait:
        return client.iot_hub.begin_manual_failover(
            iot_hub_name=hub_name, resource_group_name=resource_group_name, failover_input=failover_input
        )
    LongRunningOperation(cmd.cli_ctx)(
        client.iot_hub.begin_manual_failover(
            iot_hub_name=hub_name, resource_group_name=resource_group_name, failover_input=failover_input
        )
    )
    return iot_hub_get(cmd, client, hub_name, resource_group_name)


def _get_iot_hub_by_name(client, hub_name):
    all_hubs = iot_hub_list(client)
    if all_hubs is None:
        raise CLIInternalError("No IoT Hub found in current subscription.")
    try:
        target_hub = next(x for x in all_hubs if hub_name.lower() == x["name"].lower())
    except StopIteration:
        raise CLIInternalError("No IoT Hub found with name {} in current subscription.".format(hub_name))
    return target_hub


def _get_iot_hub_hostname(client, hub_name):
    # Intermediate fix to support domains beyond azure-devices.net properly
    hub = _get_iot_hub_by_name(client, hub_name)
    return hub["properties"]["hostName"]


def _ensure_resource_group_existence(cli_ctx, resource_group_name):
    resource_group_client = resource_service_factory(cli_ctx).resource_groups
    return resource_group_client.check_existence(resource_group_name)


def _ensure_hub_resource_group_name(client, resource_group_name, hub_name):
    if resource_group_name is None:
        return _get_resource_group_from_hub(_get_iot_hub_by_name(client, hub_name))
    return resource_group_name


# Convert permission list to AccessRights from IoT SDK.
def _convert_perms_to_access_rights(perm_list):
    perm_set = set(perm_list)  # remove duplicate
    sorted_perm_list = sorted(perm_set)
    perm_key = '_'.join(sorted_perm_list)
    access_rights_mapping = {
        'registryread': AccessRights.REGISTRY_READ,
        'registrywrite': AccessRights.REGISTRY_WRITE,
        'serviceconnect': AccessRights.SERVICE_CONNECT,
        'deviceconnect': AccessRights.DEVICE_CONNECT,
        'registryread_registrywrite': AccessRights.REGISTRY_READ_REGISTRY_WRITE,
        'registryread_serviceconnect': AccessRights.REGISTRY_READ_SERVICE_CONNECT,
        'deviceconnect_registryread': AccessRights.REGISTRY_READ_DEVICE_CONNECT,
        'registrywrite_serviceconnect': AccessRights.REGISTRY_WRITE_SERVICE_CONNECT,
        'deviceconnect_registrywrite': AccessRights.REGISTRY_WRITE_DEVICE_CONNECT,
        'deviceconnect_serviceconnect': AccessRights.SERVICE_CONNECT_DEVICE_CONNECT,
        'registryread_registrywrite_serviceconnect': AccessRights.REGISTRY_READ_REGISTRY_WRITE_SERVICE_CONNECT,
        'deviceconnect_registryread_registrywrite': AccessRights.REGISTRY_READ_REGISTRY_WRITE_DEVICE_CONNECT,
        'deviceconnect_registryread_serviceconnect': AccessRights.REGISTRY_READ_SERVICE_CONNECT_DEVICE_CONNECT,
        'deviceconnect_registrywrite_serviceconnect': AccessRights.REGISTRY_WRITE_SERVICE_CONNECT_DEVICE_CONNECT,
        'deviceconnect_registryread_registrywrite_serviceconnect': AccessRights.REGISTRY_READ_REGISTRY_WRITE_SERVICE_CONNECT_DEVICE_CONNECT
    }
    return access_rights_mapping[perm_key]


def _is_linked_hub_existed(hubs, hub_name):
    hub_set = {h["name"].lower() for h in hubs}
    return hub_name.lower() in hub_set


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


def _convert_rights_to_access_rights(right_list):
    right_set = set(right_list)  # remove duplicate
    return ",".join(list(right_set))


def _delete_routing_endpoints(endpoint_name, endpoint_type, endpoints):
    if endpoint_type:
        if EndpointType.ServiceBusQueue.value == endpoint_type.lower():
            endpoints["serviceBusQueues"] = []
        elif EndpointType.ServiceBusTopic.value == endpoint_type.lower():
            endpoints["serviceBusTopics"] = []
        elif EndpointType.AzureStorageContainer.value == endpoint_type.lower():
            endpoints["storageContainers"] = []
        elif EndpointType.EventHub.value == endpoint_type.lower():
            endpoints["eventHubs"] = []

    if endpoint_name:
        if any(e["name"].lower() == endpoint_name.lower() for e in endpoints["serviceBusQueues"]):
            sbq_endpoints = [e for e in endpoints["serviceBusQueues"] if e["name"].lower() != endpoint_name.lower()]
            endpoints["serviceBusQueues"] = sbq_endpoints
        elif any(e["name"].lower() == endpoint_name.lower() for e in endpoints["serviceBusTopics"]):
            sbt_endpoints = [e for e in endpoints["serviceBusTopics"] if e["name"].lower() != endpoint_name.lower()]
            endpoints["serviceBusTopics"] = sbt_endpoints
        elif any(e["name"].lower() == endpoint_name.lower() for e in endpoints["storageContainers"]):
            sc_endpoints = [e for e in endpoints["storageContainers"] if e["name"].lower() != endpoint_name.lower()]
            endpoints["storageContainers"] = sc_endpoints
        elif any(e["name"].lower() == endpoint_name.lower() for e in endpoints["eventHubs"]):
            eh_endpoints = [e for e in endpoints["eventHubs"] if e["name"].lower() != endpoint_name.lower()]
            endpoints["eventHubs"] = eh_endpoints

    if not endpoint_type and not endpoint_name:
        endpoints["serviceBusQueues"] = []
        endpoints["serviceBusTopics"] = []
        endpoints["storageContainers"] = []
        endpoints["eventHubs"] = []

    return endpoints


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


def _process_fileupload_args(
        default_storage_endpoint,
        fileupload_storage_connectionstring=None,
        fileupload_storage_container_name=None,
        fileupload_sas_ttl=None,
        fileupload_storage_authentication_type=None,
        fileupload_storage_container_uri=None,
        fileupload_storage_identity=None,
):
    from datetime import timedelta
    if fileupload_storage_authentication_type and fileupload_storage_authentication_type == AuthenticationType.IdentityBased:
        default_storage_endpoint["authenticationType"] = AuthenticationType.IdentityBased
        if fileupload_storage_container_uri:
            default_storage_endpoint["containerUri"] = fileupload_storage_container_uri
    elif fileupload_storage_authentication_type and fileupload_storage_authentication_type == AuthenticationType.KeyBased:
        default_storage_endpoint["authenticationType"] = AuthenticationType.KeyBased
        default_storage_endpoint["identity"] = None
    elif fileupload_storage_authentication_type is not None:
        default_storage_endpoint["authenticationType"] = None
        default_storage_endpoint["containerUri"] = None
    # TODO - remove connection string and set containerURI once fileUpload SAS URL is enabled
    if fileupload_storage_connectionstring is not None and fileupload_storage_container_name is not None:
        default_storage_endpoint["connectionString"] = fileupload_storage_connectionstring
        default_storage_endpoint["containerName"] = fileupload_storage_container_name
    elif fileupload_storage_connectionstring is not None:
        raise RequiredArgumentMissingError('Please mention storage container name.')
    elif fileupload_storage_container_name is not None:
        raise RequiredArgumentMissingError('Please mention storage connection string.')
    if fileupload_sas_ttl is not None:
        default_storage_endpoint["sasTtlAsIso8601"] = timedelta(hours=fileupload_sas_ttl)

    # Fix for identity/authentication-type params missing on hybrid profile api
    if "authenticationType" in default_storage_endpoint:
        # If we are now (or will be) using fsa=identity AND we've set a new identity
        if default_storage_endpoint["authenticationType"] == AuthenticationType.IdentityBased and fileupload_storage_identity:
            # setup new fsi
            default_storage_endpoint["identity"] = {"userAssignedIdentity": fileupload_storage_identity} if fileupload_storage_identity not in [IdentityType.none.value, SYSTEM_ASSIGNED_IDENTITY] else None
        # otherwise - let them know they need identity-based auth enabled
        elif fileupload_storage_identity:
            raise ArgumentUsageError('In order to set a file upload storage identity, you must set the file upload storage authentication type (--fsa) to IdentityBased')

    return default_storage_endpoint


def _validate_fileupload_identity(instance, fileupload_storage_identity):
    instance_identity = _get_hub_identity_type(instance)

    # if hub has no identity
    if not instance_identity or instance_identity == IdentityType.none.value:
        raise ArgumentUsageError('Hub has no identity assigned, please assign a system or user-assigned managed identity to use for file-upload with `az iot hub identity assign`')

    has_system_identity = instance_identity in [IdentityType.system_assigned.value, IdentityType.system_assigned_user_assigned.value]
    has_user_identity = instance_identity in [IdentityType.user_assigned.value, IdentityType.system_assigned_user_assigned.value]

    # if changing storage identity to '[system]'
    if fileupload_storage_identity in [None, SYSTEM_ASSIGNED_IDENTITY]:
        if not has_system_identity:
            raise ArgumentUsageError('System managed identity must be enabled in order to use managed identity for file upload')
    # if changing to user identity and hub has no user identities
    elif fileupload_storage_identity and not has_user_identity:
        raise ArgumentUsageError('User identity {} must be added to hub in order to use it for file upload'.format(fileupload_storage_identity))


def _get_hub_identity_type(instance):
    identity = instance.get("identity") or {}
    return identity.get("type")


def _build_identity(system=False, identities=None):
    identity_type = IdentityType.none.value
    if not (system or identities):
        return {"type": identity_type}
    if system:
        identity_type = IdentityType.system_assigned.value
    user_identities = list(identities) if identities else None
    if user_identities and identity_type == IdentityType.system_assigned.value:
        identity_type = IdentityType.system_assigned_user_assigned.value
    elif user_identities:
        identity_type = IdentityType.user_assigned.value

    identity = {"type": identity_type}
    if user_identities:
        identity["userAssignedIdentities"] = {i: {} for i in user_identities}  # pylint: disable=not-an-iterable

    return identity


def _construct_identity_info(enable_system_identity, user_identities) -> Optional[dict]:
    if enable_system_identity and user_identities:
        identity_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED_USER_ASSIGNED
    elif enable_system_identity:
        identity_type = ManagedServiceIdentityType.SYSTEM_ASSIGNED
    elif user_identities:
        identity_type = ManagedServiceIdentityType.USER_ASSIGNED
    else:
        return None

    user_identities_dict = {}
    if user_identities:
        for identity_id in user_identities:
            user_identities_dict[identity_id] = {}

    return {
        "type": identity_type,
        "userAssignedIdentities": (
            user_identities_dict if user_identities else None
        ),
    }


def _identity_has_type(identity: Optional[dict], identity_type: str) -> bool:
    values = {
        item.strip().casefold()
        for item in str((identity or {}).get("type") or "").split(",")
    }
    return identity_type.casefold() in values


def _merge_dps_identity(
        existing_identity: Optional[dict],
        system_assigned: Optional[bool],
        user_identities: Optional[List[str]],
) -> dict:
    """Merge DPS identity additions without dropping unmentioned identities."""
    existing_identity = existing_identity or {}
    has_system = _identity_has_type(existing_identity, SYSTEM_ASSIGNED)
    if system_assigned is not None:
        has_system = bool(system_assigned)

    identities = {
        resource_id.rstrip("/").casefold(): resource_id
        for resource_id in (
            existing_identity.get("userAssignedIdentities") or {}
        )
    }
    for resource_id in user_identities or []:
        identities.setdefault(resource_id.rstrip("/").casefold(), resource_id)

    result = _construct_identity_info(
        has_system, list(identities.values()) or None
    )
    return result or {"type": ManagedServiceIdentityType.NONE}


def _identity_removals(
    current_identity: Optional[dict], desired_identity: Optional[dict]
):
    """Return the SAMI/UAMI identities removed by a desired ARM identity."""
    remove_system = _identity_has_type(
        current_identity, SYSTEM_ASSIGNED
    ) and not _identity_has_type(desired_identity, SYSTEM_ASSIGNED)
    desired_uamis = {
        resource_id.rstrip("/").casefold()
        for resource_id in (
            (desired_identity or {}).get("userAssignedIdentities") or {}
        )
    }
    removed_uamis = [
        resource_id
        for resource_id in (
            (current_identity or {}).get("userAssignedIdentities") or {}
        )
        if resource_id.rstrip("/").casefold() not in desired_uamis
    ]
    return remove_system, removed_uamis or None


# Retain the existing private name for callers and tests outside the Hub path.
_dps_identity_removals = _identity_removals


def _dps_description_for_write(dps: dict) -> dict:
    """Strip server projections before sending a modeless DPS PUT body."""
    body = {
        key: deepcopy(dps[key])
        for key in ("location", "tags", "sku")
        if key in dps
    }
    if "identity" in dps:
        body["identity"] = _sanitize_arm_identity(dps.get("identity"))
    properties = deepcopy(dps.get("properties") or {})
    for key in (
        "state",
        "provisioningState",
        "privateEndpointConnections",
        "deviceRegistryNamespaces",
        "serviceOperationsHostName",
        "deviceProvisioningHostName",
        "idScope",
        "portalOperationsHostName",
    ):
        properties.pop(key, None)
    body["properties"] = properties
    return body
# DPS Identity management functions
def dps_identity_assign(client, dps_name: str, resource_group_name:Optional[str]=None,
                        system_assigned:Optional[bool]=None, user_assigned:Optional[List[str]]=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps = client.iot_dps_resource.get(resource_group_name=resource_group_name, provisioning_service_name=dps_name)

    if system_assigned is None and user_assigned is None:
        raise RequiredArgumentMissingError("Specify --system-assigned and/or --user-assigned")

    dps["identity"] = _merge_dps_identity(
        dps.get("identity"),
        True if system_assigned else None,
        user_assigned,
    )

    return adapt_modeless_lro_poller(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            provisioning_service_name=dps_name,
            iot_dps_description=_dps_description_for_write(dps),
        )
    )


def dps_identity_remove(client, dps_name: str, resource_group_name:Optional[str]=None,
                        system_assigned:Optional[bool]=None, user_assigned:Optional[List[str]]=None,
                        cmd=None):
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps = client.iot_dps_resource.get(resource_group_name=resource_group_name, provisioning_service_name=dps_name)

    if system_assigned is None and user_assigned is None:
        raise RequiredArgumentMissingError("Specify --system-assigned and/or --user-assigned")

    existing_identity = dps.get("identity")
    if not existing_identity or existing_identity["type"] == ManagedServiceIdentityType.NONE:
        # No identity to remove
        return dps

    _protect_dps_link_identity(
        cmd,
        dps,
        remove_system=bool(system_assigned),
        remove_user_identities=user_assigned,
    )

    has_system_identity = _identity_has_type(existing_identity, SYSTEM_ASSIGNED)

    if system_assigned is True and has_system_identity:
        enable_system = False
    else:
        enable_system = has_system_identity

    # Handle user identities
    existing_user_identities = []
    if existing_identity.get("userAssignedIdentities"):
        existing_user_identities = list(existing_identity["userAssignedIdentities"].keys())

    if user_assigned is not None:
        remove_ids = (
            {identity_id.rstrip("/").casefold() for identity_id in user_assigned}
            if user_assigned
            else {
                identity_id.rstrip("/").casefold()
                for identity_id in existing_user_identities
            }
        )
        existing_user_identities = [
            identity_id
            for identity_id in existing_user_identities
            if identity_id.rstrip("/").casefold() not in remove_ids
        ]

    # If no identities remain, set to None type
    if not enable_system and not existing_user_identities:
        dps["identity"] = {"type": ManagedServiceIdentityType.NONE}
    else:
        dps["identity"] = _construct_identity_info(
            enable_system, existing_user_identities if existing_user_identities else None
        )

    return adapt_modeless_lro_poller(
        client.iot_dps_resource.begin_create_or_update(
            resource_group_name=resource_group_name,
            provisioning_service_name=dps_name,
            iot_dps_description=_dps_description_for_write(dps),
        )
    )


def dps_identity_show(client, dps_name: str, resource_group_name: Optional[str] = None) -> dict:
    resource_group_name = _ensure_dps_resource_group_name(client, resource_group_name, dps_name)
    dps = client.iot_dps_resource.get(resource_group_name=resource_group_name, provisioning_service_name=dps_name)
    return dps.get("identity")


def _protect_dps_link_identity(
    cmd,
    dps: dict,
    *,
    remove_system: bool,
    remove_user_identities,
) -> None:
    """Block removal of identities selected by canonical namespace links."""
    dps = _adr_identity_target(cmd, dps, "dps")
    namespace_links = ((dps or {}).get("properties") or {}).get(
        "deviceRegistryNamespaces"
    ) or []
    if not namespace_links:
        return

    from msrestazure.tools import parse_resource_id
    from azext_iot._factory import adr_service_factory

    dps_id = (dps or {}).get("id")
    if not dps_id:
        raise ArgumentUsageError(
            "DPS has an active ADR namespace projection but its resource ID is "
            "missing. Rotate or delete the link before removing identities."
        )
    requested_uamis = {
        value.rstrip("/").casefold() for value in (remove_user_identities or [])
    }
    remove_all_uamis = remove_user_identities == []
    for namespace_link in namespace_links:
        if cmd is None:
            raise ArgumentUsageError(
                "DPS is namespace-linked. Run identity removal through Azure CLI "
                "so the active link identity can be validated."
            )
        namespace_id = namespace_link.get("resourceId")
        parsed = parse_resource_id(namespace_id) if namespace_id else {}
        if not all(
            parsed.get(key)
            for key in ("subscription", "resource_group", "name")
        ):
            raise ArgumentUsageError(
                "DPS has an active ADR namespace projection that could not be "
                "validated. Rotate or delete the namespace link before removing identities."
            )
        try:
            namespace = adr_service_factory(
                cmd.cli_ctx, subscription_id=parsed["subscription"]
            ).namespaces.get(
                resource_group_name=parsed["resource_group"],
                namespace_name=parsed["name"],
            )
        except Exception as error:
            raise ArgumentUsageError(
                "DPS is namespace-linked, but the active link identity could "
                "not be read. Do not remove identities until you can run "
                "'az iot adr ns link dps show' and rotate the link."
            ) from error

        endpoints = (
            (((namespace or {}).get("properties") or {}).get("provisioning") or {})
            .get("endpoints")
            or {}
        )
        for endpoint in endpoints.values():
            if (
                str((endpoint or {}).get("resourceId") or "")
                .rstrip("/")
                .casefold()
                != str(dps_id or "").rstrip("/").casefold()
            ):
                continue
            inbound = (endpoint or {}).get("inboundCallerIdentity") or {}
            inbound_type = str(inbound.get("type") or "").casefold()
            if remove_system and inbound_type == "systemassigned":
                raise ArgumentUsageError(
                    "The DPS system-assigned identity is used by an active ADR "
                    "link. Rotate it first with 'az iot adr ns link dps update' "
                    "or permanently delete the link."
                )
            selected_uami = inbound.get("userAssignedIdentity")
            if (
                inbound_type == "userassigned"
                and selected_uami
                and (
                    remove_all_uamis
                    or selected_uami.rstrip("/").casefold() in requested_uamis
                )
            ):
                raise ArgumentUsageError(
                    "The selected DPS user-assigned identity is used by an active "
                    "ADR link. Rotate it first with "
                    "'az iot adr ns link dps update' or permanently delete the link."
                )
