# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError
from msrestazure.tools import parse_resource_id

from azext_iot.adr.workflows.configuration import (
    load_config, validate_endpoint, validate_identity as config_identity, validate_resource_id,
)
from azext_iot.adr.workflows.models import CmsSpec, EndpointSpec, SetupRequest


_SYSTEM_ASSIGNED = "system-assigned"
_USER_ASSIGNED = "user-assigned"
_ENDPOINT_KEYS = {
    "name",
    "endpoint",
    "endpoint-name",
    "resource-id",
    "resource-name",
    "resource-group",
    "subscription",
    "identity",
    "availability",
    "allocation-weight",
    "create-if-missing",
    "sku",
    "unit",
}


class BackRequested(Exception):
    """Guided setup: return to the previous question (Esc, or :back in --plain)."""


class WorkflowCancelled(Exception):
    """Guided setup: the user cancelled before approval; nothing was written."""


def _parse_pairs(values: Optional[Iterable[str]], option_name: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise InvalidArgumentValueError(
                f"{option_name} values must use key=value syntax: {value!r}."
            )
        key, item_value = value.split("=", 1)
        key = key.strip().lower()
        item_value = item_value.strip()
        if not key or not item_value:
            raise InvalidArgumentValueError(
                f"{option_name} keys and values cannot be empty."
            )
        if key not in _ENDPOINT_KEYS:
            raise InvalidArgumentValueError(
                f"Unsupported {option_name} key '{key}'."
            )
        if key in parsed:
            raise InvalidArgumentValueError(
                f"{option_name} key '{key}' was provided more than once."
            )
        parsed[key] = item_value
    return parsed


def _identity(values: Dict[str, str], option_name: str):
    identity = values.get("identity")
    if not identity:
        raise InvalidArgumentValueError(
            f"{option_name} requires identity=system-assigned or identity=<uami-resource-id>."
        )
    if identity.casefold() in (_SYSTEM_ASSIGNED, "systemassigned"):
        return _SYSTEM_ASSIGNED, None
    if not identity.startswith("/"):
        raise InvalidArgumentValueError(
            f"{option_name} identity must be 'system-assigned' or a UAMI ARM resource ID."
        )
    return _USER_ASSIGNED, validate_resource_id(identity, "identity", f"{option_name}.identity")


def _resource_id(
    values: Dict[str, str],
    kind: str,
    default_resource_group: str,
    default_subscription: str,
) -> str:
    resource_id = values.get("resource-id")
    if resource_id:
        return resource_id
    resource_name = values.get("resource-name")
    if not resource_name:
        raise InvalidArgumentValueError(
            f"--{kind} requires resource-id=<ARM_ID> or resource-name=<NAME>."
        )
    resource_group = values.get("resource-group") or default_resource_group
    subscription = values.get("subscription") or default_subscription
    types = {
        "dps": ("Microsoft.Devices", "provisioningServices"),
        "hub": ("Microsoft.Devices", "IotHubs"),
        "software-updates": ("Microsoft.DeviceUpdate", "updateInstances"),
    }
    namespace, resource_type = types[kind]
    return (
        f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
        f"/providers/{namespace}/{resource_type}/{resource_name}"
    )


def parse_endpoint(
    values: Optional[Iterable[str]],
    kind: str,
    default_resource_group: str,
    default_subscription: str,
) -> Optional[EndpointSpec]:
    if not values:
        return None
    parsed = _parse_pairs(values, f"--{kind}")
    identity_type, user_identity = _identity(parsed, f"--{kind}")
    endpoint_name = (
        parsed.get("endpoint")
        or parsed.get("name")
        or parsed.get("endpoint-name")
    )
    resource_id = _resource_id(
        parsed, kind, default_resource_group, default_subscription
    )
    if not endpoint_name:
        endpoint_name = resource_id.rstrip("/").rsplit("/", 1)[-1]
    allocation_weight = parsed.get("allocation-weight")
    try:
        weight = int(allocation_weight) if allocation_weight is not None else None
    except ValueError as error:
        raise InvalidArgumentValueError(
            "--hub allocation-weight must be an integer."
        ) from error
    create = parsed.get("create-if-missing", "false").casefold()
    if create not in ("true", "false"):
        raise InvalidArgumentValueError(f"--{kind}.create-if-missing must be true or false.")
    unit = parsed.get("unit")
    try:
        unit = int(unit) if unit is not None else None
    except ValueError as error:
        raise InvalidArgumentValueError(f"--{kind}.unit must be an integer.") from error
    aliases = [key for key in ("endpoint", "name", "endpoint-name") if key in parsed]
    if len(aliases) > 1:
        raise InvalidArgumentValueError(f"--{kind}.endpoint-name was specified more than once.")
    canonical = {
        {"resource-id": "resourceId", "resource-name": "resourceName", "resource-group": "resourceGroup",
         "endpoint-name": "endpointName", "endpoint": "endpointName", "name": "endpointName",
         "create-if-missing": "createIfMissing", "allocation-weight": "allocationWeight"}.get(key, key): value
        for key, value in parsed.items()
    }
    canonical["createIfMissing"] = create == "true"
    if weight is not None:
        canonical["allocationWeight"] = weight
    if unit is not None:
        canonical["unit"] = unit
    validate_endpoint(canonical, kind, f"--{kind}")
    validate_resource_id(resource_id, kind, f"--{kind}.resourceId")
    return EndpointSpec(
        kind=kind,
        endpoint_name=endpoint_name,
        resource_id=resource_id,
        identity_type=identity_type,
        user_assigned_identity=user_identity,
        availability=parsed.get("availability"),
        allocation_weight=weight,
        create_if_missing=create == "true",
        sku=parsed.get("sku"),
        unit=unit,
    )


def _required_config_pairs(value: Any, field_name: str) -> List[str]:
    if not isinstance(value, dict) or not value:
        raise InvalidArgumentValueError(
            f"Workflow config '{field_name}' must contain a non-empty object."
        )
    return _config_pairs(value)


def _read_config(value) -> Dict[str, Any]:
    return load_config(value)


def _validate_callback(callback, endpoint, allow_missing):
    """Read an endpoint target; a missing DPS or IoT Hub is accepted only when creation was requested."""
    try:
        return callback(endpoint, allow_missing)
    except (ResourceNotFoundError, HttpResponseError) as error:
        if not (
            allow_missing and endpoint.kind in ("hub", "dps")
            and (isinstance(error, ResourceNotFoundError) or error.status_code == 404)
        ):
            raise
        # Missing is an explicitly requested state, not a default. Plan performs
        # subscription, region, name availability and identity checks before writes.
        return None


def _config_pairs(value: Optional[Dict[str, Any]]) -> Optional[List[str]]:
    if not value:
        return None
    result = []
    for key, item in value.items():
        if key == "identity" and isinstance(item, dict):
            item = (
                item.get("userAssignedResourceId")
                or (
                    _SYSTEM_ASSIGNED
                    if str(item.get("type", "")).casefold()
                    in {"systemassigned", _SYSTEM_ASSIGNED}
                    else None
                )
            )
            if not item:
                raise InvalidArgumentValueError(
                    "Config endpoint identity must specify SystemAssigned "
                    "or userAssignedResourceId."
                )
        if isinstance(item, bool):
            item = str(item).lower()
        normalized_key = {
            "endpointName": "endpoint",
            "resourceId": "resource-id",
            "resourceName": "resource-name",
            "resourceGroup": "resource-group",
            "allocationWeight": "allocation-weight",
            "createIfMissing": "create-if-missing",
        }.get(key, key.replace("_", "-"))
        result.append(f"{normalized_key}={item}")
    return result


def _resource_group_name(value: str, subscription_id: Optional[str]) -> str:
    if not value.startswith("/"):
        return value
    parsed = parse_resource_id(value)
    resource_group = parsed.get("resource_group")
    subscription = parsed.get("subscription")
    if (
        not resource_group
        or parsed.get("namespace")
        or (
            subscription_id
            and str(subscription).casefold()
            != subscription_id.casefold()
        )
    ):
        raise InvalidArgumentValueError(
            "Resource group must be a name or an ARM ID in the active "
            "subscription."
        )
    return resource_group


def resolve_scope_inputs(
    namespace_name: Optional[str],
    resource_group_name: Optional[str],
    subscription_id: Optional[str] = None,
    validate_resource_group: Optional[Callable[[str], None]] = None,
    validate_namespace: Optional[Callable[[str, str], None]] = None,
) -> Tuple[str, str]:
    """Normalize explicit scope; prompting belongs to guided setup only."""
    if not resource_group_name:
        raise ArgumentUsageError("--resource-group is required outside guided setup.")
    if not namespace_name:
        raise ArgumentUsageError("--name is required outside guided setup.")
    resource_group_name = _resource_group_name(resource_group_name, subscription_id)
    if validate_resource_group:
        validate_resource_group(resource_group_name)
    if validate_namespace:
        validate_namespace(namespace_name, resource_group_name)
    return namespace_name, resource_group_name


def build_setup_request(
    namespace_name: str,
    resource_group_name: str,
    subscription_id: str,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    namespace_outbound_identity: Optional[str] = None,
    dps: Optional[List[str]] = None,
    hubs: Optional[List[List[str]]] = None,
    software_updates: Optional[List[str]] = None,
    complete_connectivity: bool = False,
    config: Any = None,
    validate_resource_group: Optional[Callable[[str], None]] = None,
    validate_namespace: Optional[Callable[[str, str], None]] = None,
    validate_endpoint_resource: Optional[
        Callable[[EndpointSpec, bool], Any]
    ] = None,
    validate_endpoint_identity: Optional[
        Callable[[EndpointSpec, Any], None]
    ] = None,
    validate_identity: Optional[Callable[[str], None]] = None,
) -> SetupRequest:
    """Strict, prompt-free request from arguments or configuration; guided setup composes configuration."""
    if config is not None and any(
        (
            namespace_outbound_identity,
            dps,
            hubs,
            software_updates,
            complete_connectivity,
        )
    ):
        raise ArgumentUsageError(
            "--config cannot be combined with workflow capability arguments."
        )

    raw = {}
    if config is not None:
        raw = _read_config(config)
        ns = raw.get("namespace", {})
        links = raw.get("links", {})
        if raw.get("subscriptionId", subscription_id).casefold() != subscription_id.casefold():
            raise InvalidArgumentValueError(
                "Workflow config subscriptionId does not match the selected subscription. "
                "Select it explicitly with --subscription; setup does not switch accounts."
            )
        for key, explicit in (("name", namespace_name), ("resourceGroup", resource_group_name),
                              ("location", location), ("tags", tags)):
            configured = ns.get(key)
            if explicit is not None and configured is not None and explicit != configured:
                raise InvalidArgumentValueError(f"Workflow config namespace.{key} conflicts with explicit CLI input.")
        namespace_name = namespace_name or ns.get("name")
        resource_group_name = (
            resource_group_name or ns.get("resourceGroup")
        )
        location = location or ns.get("location")
        if tags is None:
            tags = ns.get("tags")
        if "outboundIdentity" in ns:
            namespace_outbound_identity = config_identity(ns["outboundIdentity"], "namespace.outboundIdentity")
        dps = (
            _required_config_pairs(links["dps"], "links.dps")
            if "dps" in links
            else None
        )
        hub_values = links.get("hubs", [])
        hubs = [
            _required_config_pairs(item, f"links.hubs[{index}]")
            for index, item in enumerate(hub_values)
        ]
        software_updates = (
            _required_config_pairs(
                links["softwareUpdates"], "links.softwareUpdates"
            )
            if "softwareUpdates" in links
            else None
        )

    namespace_name, resource_group_name = resolve_scope_inputs(
        namespace_name,
        resource_group_name,
        subscription_id=subscription_id,
        validate_resource_group=validate_resource_group,
        validate_namespace=validate_namespace,
    )
    if config is None and not any((namespace_outbound_identity, dps, hubs, software_updates)):
        raise ArgumentUsageError(
            "Specify --outbound-identity, --dps, --hub, --software-updates, or --config. "
            "Run setup in a terminal without --yes or --no-input to be guided."
        )

    outbound_type = None
    outbound_uami = None
    if namespace_outbound_identity:
        if namespace_outbound_identity.casefold() in {
            _SYSTEM_ASSIGNED,
            "systemassigned",
        }:
            outbound_type = "SystemAssigned"
        elif namespace_outbound_identity.startswith("/"):
            outbound_type = "UserAssigned"
            outbound_uami = validate_resource_id(namespace_outbound_identity, "identity", "--outbound-identity")
            if validate_identity:
                validate_identity(outbound_uami)
        else:
            raise InvalidArgumentValueError(
                "--outbound-identity must be 'system-assigned' "
                "or a UAMI ARM resource ID."
            )

    dps_spec = parse_endpoint(
        dps, "dps", resource_group_name, subscription_id
    )
    hub_specs = tuple(
        parse_endpoint(hub, "hub", resource_group_name, subscription_id)
        for hub in (hubs or [])
    )
    su_values = _parse_pairs(software_updates, "--software-updates") if software_updates else {}
    su_spec = parse_endpoint(
        software_updates, "software-updates", resource_group_name, subscription_id
    )
    create_su = str(su_values.get("create-if-missing", "")).casefold() == "true"
    update_instance_name = None
    if su_spec:
        update_instance_name = su_spec.resource_id.rstrip("/").rsplit("/", 1)[-1]

    if validate_endpoint_resource:
        for endpoint in [dps_spec, *hub_specs, su_spec]:
            if endpoint:
                resource = _validate_callback(
                    validate_endpoint_resource, endpoint, endpoint.create_if_missing,
                )
                if resource is not None and validate_endpoint_identity:
                    validate_endpoint_identity(endpoint, resource)

    if complete_connectivity and (not dps_spec or not hub_specs):
        raise ArgumentUsageError(
            "--complete-connectivity requires both --dps and at least one --hub."
        )

    return SetupRequest(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        subscription_id=subscription_id,
        location=location,
        tags=(dict(tags) if tags is not None else None),
        outbound_identity_type=outbound_type,
        outbound_user_assigned_identity=outbound_uami,
        dps=dps_spec,
        hubs=hub_specs,
        software_updates=su_spec,
        create_update_instance=create_su,
        update_instance_name=update_instance_name,
        check_status=raw.get("checkStatus", False),
        cms=(
            CmsSpec(
                raw["cms"]["rootName"], raw["cms"]["intermediateName"],
                raw["cms"]["policyName"], raw["cms"]["validityDays"],
            )
            if raw.get("cms", {}).get("enabled") else None
        ),
    )


def check_script_destination(path: str):
    """Fail early, without creating anything, when a script can't be written to path."""
    target = Path(path).expanduser()
    if target.is_dir():
        raise ArgumentUsageError(f"{path} is a folder. Choose a file path for --output-script.")
    folder = target.parent if str(target.parent) else Path(".")
    if not folder.is_dir():
        raise ArgumentUsageError(f"The folder for {path} doesn't exist. Create it or choose another --output-script.")
    if not os.access(target if target.exists() else folder, os.W_OK):
        raise ArgumentUsageError(f"{path} isn't writable. Choose another --output-script.")


def write_script_file(path: str, commands: Iterable[str]):
    lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    lines.extend(command for command in commands if command)
    Path(path).expanduser().write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def write_receipt_file(value: Dict[str, Any]) -> str:
    root = Path(
        os.getenv("AZURE_CONFIG_DIR", str(Path.home() / ".azure"))
    ) / "adr"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"setup-{timestamp}-{uuid4().hex[:8]}.json"
    with path.open("x", encoding="utf-8") as receipt:
        receipt.write(
            json.dumps(value, indent=2, sort_keys=True) + "\n"
        )
    return str(path)
