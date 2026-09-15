# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

import yaml
from azure.cli.core.azclierror import ArgumentUsageError, InvalidArgumentValueError
from msrestazure.tools import parse_resource_id

from azext_iot.adr.workflows.models import EndpointSpec, SetupRequest


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
}


class BackRequested(Exception):
    pass


class WorkflowCancelled(Exception):
    pass


def _select(
    title: str,
    options: Dict[str, Tuple[str, ...]],
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    guidance: Optional[str] = None,
    allow_custom: bool = False,
    show_options: bool = True,
) -> str:
    renderer = getattr(prompt, "__self__", None)
    if renderer and hasattr(renderer, "select"):
        return renderer.select(
            title,
            options,
            guidance=guidance,
            allow_custom=allow_custom,
            show_options=show_options,
        )
    write(title)
    if guidance:
        write(guidance)
    lookup = {}
    for number, (value, label, *aliases) in enumerate(
        options.values(), start=1
    ):
        write(f"  {number}  {label}")
        for key in (str(number), value, label, *aliases):
            lookup[key.casefold()] = value
    while True:
        raw_choice = prompt("Selection: ").strip()
        choice = raw_choice.casefold()
        selected = lookup.get(choice)
        if selected:
            label = next(
                item[1] for item in options.values() if item[0] == selected
            )
            write(f"Selected: {label}")
            return selected
        if allow_custom and choice:
            return raw_choice
        write("Choose a listed number or name. Use :back, :help, or :quit.")


def select_value(
    title,
    options,
    prompt,
    write,
    show_options=False,
):
    return _select(
        title,
        options,
        prompt,
        write,
        show_options=show_options,
    )


def _action(
    title: str,
    actions: Dict[str, str],
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    default: Optional[str] = None,
) -> str:
    renderer = getattr(prompt, "__self__", None)
    if renderer and hasattr(renderer, "action"):
        return renderer.action(title, actions, default=default)
    write(title)
    write(
        " · ".join(
            f"[{key}] {label}" for key, label in actions.items()
        )
    )
    lookup = {
        alias: key
        for index, (key, label) in enumerate(
            actions.items(), start=1
        )
        for alias in (
            key,
            label.casefold(),
            label.casefold().split()[0],
            str(index),
        )
    }
    while True:
        value = prompt("Action: ").strip().casefold()
        if not value and default:
            return default
        selected = lookup.get(value)
        if selected:
            return selected
        write("Choose one of the highlighted keys.")


def _set_prompt_phase(prompt, phase):
    renderer = getattr(prompt, "__self__", None)
    if renderer and hasattr(renderer, "phase"):
        renderer.phase(phase)


def _validation_action(
    error: Exception,
    prompt: Callable[[str], str],
    write: Callable[[str], None],
) -> str:
    if isinstance(error, (BackRequested, WorkflowCancelled)):
        raise error
    detail = str(error) or error.__class__.__name__
    write(f"! {detail}")
    try:
        selected_key = _action(
            "What would you like to do?",
            {
                "r": "retry",
                "e": "edit input",
                "q": "quit",
            },
            prompt,
            write,
        )
        selected = {
            "r": "retry",
            "e": "edit",
            "q": "quit",
        }[selected_key]
    except BackRequested:
        return "edit"
    if selected == "quit":
        raise WorkflowCancelled()
    return selected


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
    if identity.casefold() == _SYSTEM_ASSIGNED:
        return _SYSTEM_ASSIGNED, None
    if not identity.startswith("/"):
        raise InvalidArgumentValueError(
            f"{option_name} identity must be 'system-assigned' or a UAMI ARM resource ID."
        )
    return _USER_ASSIGNED, identity


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
    return EndpointSpec(
        kind=kind,
        endpoint_name=endpoint_name,
        resource_id=resource_id,
        identity_type=identity_type,
        user_assigned_identity=user_identity,
        availability=parsed.get("availability"),
        allocation_weight=weight,
    )


def _required_config_pairs(value: Any, field_name: str) -> List[str]:
    if not isinstance(value, dict) or not value:
        raise InvalidArgumentValueError(
            f"Workflow config '{field_name}' must contain a non-empty object."
        )
    return _config_pairs(value)


def _read_config(path: str) -> Dict[str, Any]:
    try:
        content = Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as error:
        raise InvalidArgumentValueError(
            f"Unable to read workflow config '{path}': {error}."
        ) from error
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise InvalidArgumentValueError(
            f"Workflow config '{path}' is not valid YAML or JSON."
        ) from error
    if not isinstance(parsed, dict):
        raise InvalidArgumentValueError("Workflow config must contain an object.")
    return parsed


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


def _prompt(prompt_text: str) -> str:
    return input(prompt_text).strip()


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


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
    no_input: bool = False,
    interactive: Optional[bool] = None,
    prompt: Callable[[str], str] = _prompt,
    write: Callable[[str], None] = print,
    validate_resource_group: Optional[Callable[[str], None]] = None,
    validate_namespace: Optional[Callable[[str, str], None]] = None,
    browse_resource_groups: Optional[
        Callable[[], List[Dict[str, Any]]]
    ] = None,
    browse_namespaces: Optional[
        Callable[[str], List[Dict[str, Any]]]
    ] = None,
    back_from_resource_group: bool = False,
) -> Tuple[str, str]:
    interactive = not no_input and (
        _is_interactive() if interactive is None else interactive
    )
    while True:
        if not resource_group_name:
            if not interactive:
                raise ArgumentUsageError(
                    "--resource-group is required outside an interactive terminal."
                )
            try:
                _set_prompt_phase(prompt, "Resource group")
                resource_group_name = _browse_or_exact(
                    "resource group",
                    browse_resource_groups,
                    prompt,
                    write,
                )
            except BackRequested:
                if back_from_resource_group:
                    raise
                write("Enter a resource group or use :quit to cancel.")
                continue
        resource_group_name = _resource_group_name(
            resource_group_name, subscription_id
        )
        if validate_resource_group:
            try:
                validate_resource_group(resource_group_name)
            except Exception as error:
                if not interactive:
                    raise
                action = _validation_action(error, prompt, write)
                if action == "retry":
                    continue
                resource_group_name = None
                namespace_name = None
                continue

        if not namespace_name:
            if not interactive:
                raise ArgumentUsageError(
                    "--name is required outside an interactive terminal."
                )
            try:
                _set_prompt_phase(prompt, "Namespace")
                namespace_name = _browse_or_exact(
                    "namespace",
                    (
                        lambda: browse_namespaces(resource_group_name)
                        if browse_namespaces
                        else []
                    ),
                    prompt,
                    write,
                    allow_new=True,
                )
            except BackRequested:
                resource_group_name = None
                continue
        if not resource_group_name or not namespace_name:
            raise ArgumentUsageError(
                "Namespace name and resource group cannot be empty."
            )
        if validate_namespace:
            try:
                validate_namespace(namespace_name, resource_group_name)
            except BackRequested:
                namespace_name = None
                continue
            except Exception as error:
                if not interactive:
                    raise
                action = _validation_action(error, prompt, write)
                if action == "retry":
                    continue
                namespace_name = None
                continue
        return namespace_name, resource_group_name


def _browse_or_exact(
    label,
    browse,
    prompt,
    write,
    allow_new=False,
):
    resources = []
    if browse:
        try:
            resources = browse() or []
        except Exception as error:
            write(
                f"! Unable to browse {label}s: {error}. "
                "Enter an exact name or ARM ID instead."
            )
    if resources:
        options = {
            str(index): (
                str(item.get("name") or item.get("id")),
                _resource_choice_label(item),
            )
            for index, item in enumerate(resources, start=1)
        }
        selected = _select(
            label.capitalize(),
            options,
            prompt,
            write,
            guidance=(
                f"Type a {label} name"
                + (
                    " or ARM ID"
                    if label == "resource group"
                    else ""
                )
                + ". Accessible matches appear after you type; "
                "use ↑/↓ to choose one."
            ),
            allow_custom=True,
            show_options=False,
        )
        return selected
    return prompt(
        f"{label.capitalize()} name"
        + (" or ARM resource ID" if label == "resource group" else "")
        + ": "
    )


def _resource_input(
    label: str,
    kind: str,
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    browse: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
) -> str:
    if browse:
        try:
            resources = browse(kind)
        except Exception as error:
            write(
                f"! Unable to browse {label} resources: {error}. "
                "Enter an exact name or ARM ID instead."
            )
            resources = []
        if resources:
            options = {
                str(index): (
                    str(item.get("id") or item.get("name")),
                    _resource_choice_label(item),
                    str(item.get("name") or ""),
                )
                for index, item in enumerate(resources, start=1)
            }
            selected = _select(
                label,
                options,
                prompt,
                write,
                guidance=(
                    f"Type a {label} name or ARM ID. Accessible matches "
                    "appear after you type; use ↑/↓ to choose one."
                ),
                allow_custom=True,
                show_options=False,
            )
            key = (
                "resource-id"
                if selected.startswith("/")
                else "resource-name"
            )
            return f"{key}={selected}"
    value = prompt(f"{label} name or ARM resource ID: ")
    key = "resource-id" if value.startswith("/") else "resource-name"
    return f"{key}={value}"


def _resource_choice_label(item: Dict[str, Any]) -> str:
    parts = [str(item.get("name") or item.get("id"))]
    for value in (
        item.get("location"),
        item.get("sku"),
        item.get("provisioningState"),
        (
            f"account {item['accountName']}"
            if item.get("accountName")
            else None
        ),
        item.get("allocationPolicy"),
        (
            f"created by {item['createdBy']}"
            if item.get("createdBy")
            else None
        ),
    ):
        if value:
            parts.append(str(value))
    tags = item.get("tags")
    if isinstance(tags, dict) and tags:
        rendered_tags = ", ".join(
            f"{key}={value}"
            for key, value in sorted(tags.items())
        )
        parts.append(
            "tags "
            + (
                rendered_tags
                if len(rendered_tags) <= 64
                else f"{rendered_tags[:61]}..."
            )
        )
    if item.get("linkedHubs"):
        parts.append(f"{len(item['linkedHubs'])} linked hub(s)")
    return " · ".join(parts)


def _guided_endpoint(
    label: str,
    kind: str,
    prompt: Callable[[str], str],
    write: Callable[[str], None],
    validate_resource: Optional[Callable[[str, List[str]], Any]] = None,
    validate_identity: Optional[
        Callable[[str, List[str], Any], None]
    ] = None,
    browse: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
) -> List[str]:
    while True:
        resource = _resource_input(label, kind, prompt, write, browse)
        resolved = None
        edit_resource = False
        if validate_resource:
            while True:
                try:
                    resolved = validate_resource(kind, [resource])
                    break
                except Exception as error:
                    action = _validation_action(error, prompt, write)
                    if action == "retry":
                        continue
                    edit_resource = True
                    break
        if edit_resource:
            continue
        resource_name = (
            resource.split("=", 1)[1].rstrip("/").rsplit("/", 1)[-1]
        )
        write(
            f"Link name: {resource_name} "
            "(use endpoint= in scripted input to override)"
        )

        identity_options = {
            "system": (
                _SYSTEM_ASSIGNED,
                "System-assigned identity",
                "system",
                "system assigned",
            ),
            "user": (
                _USER_ASSIGNED,
                "User-assigned managed identity",
                "uami",
                "user assigned",
            ),
        }
        while True:
            try:
                identity_type = _select(
                    f"{label} identity",
                    identity_options,
                    prompt,
                    write,
                )
            except BackRequested:
                break
            identity = _SYSTEM_ASSIGNED
            if identity_type == _USER_ASSIGNED:
                try:
                    identity = prompt("UAMI ARM ID: ")
                except BackRequested:
                    continue
            values = [
                f"endpoint={resource_name}",
                resource,
                f"identity={identity}",
            ]
            if validate_identity:
                edit_identity = False
                while True:
                    try:
                        validate_identity(kind, values, resolved)
                        break
                    except Exception as error:
                        action = _validation_action(error, prompt, write)
                        if action == "retry":
                            continue
                        edit_identity = True
                        break
                if edit_identity:
                    continue
            return values
        continue


def _guided_values(
    prompt: Callable[[str], str] = _prompt,
    write: Callable[[str], None] = print,
    validate_resource: Optional[
        Callable[[str, List[str]], Any]
    ] = None,
    validate_endpoint_identity: Optional[
        Callable[[str, List[str], Any], None]
    ] = None,
    validate_namespace_identity: Optional[Callable[[str], None]] = None,
    allow_identity_reuse: bool = False,
    browse: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
    selected_choice: Optional[str] = None,
    include_namespace_identity: bool = True,
):
    capabilities = {
        "identity": (
            "identity",
            "Namespace identity",
            "namespace identity",
        ),
        "dps": ("dps", "DPS link"),
        "hub": ("hub", "IoT Hub link", "iot hub", "hub"),
        "updates": (
            "updates",
            "Software Updates link",
            "software updates",
            "su",
        ),
        "complete": (
            "complete",
            "Complete connectivity",
            "connectivity",
        ),
    }
    choice = selected_choice or _select(
        "Configure", capabilities, prompt, write
    )

    def namespace_identity():
        write(
            "Atomic link commands validate and create missing service roles "
            "after final confirmation. Unauthorized callers receive exact "
            "remediation without namespace link mutation."
        )
        options = {
            "system": (
                _SYSTEM_ASSIGNED,
                "System-assigned identity",
                "system",
                "system assigned",
            ),
            "user": (
                _USER_ASSIGNED,
                "User-assigned managed identity",
                "uami",
                "user assigned",
            ),
        }
        if allow_identity_reuse:
            options["reuse"] = (
                "reuse",
                "Reuse current identity",
                "current",
            )
        while True:
            selected = _select(
                "Namespace outbound identity", options, prompt, write
            )
            if selected == "reuse":
                return None
            if selected == _SYSTEM_ASSIGNED:
                return _SYSTEM_ASSIGNED
            try:
                resource_id = prompt("UAMI ARM ID: ")
            except BackRequested:
                continue
            if validate_namespace_identity:
                edit_identity = False
                while True:
                    try:
                        validate_namespace_identity(resource_id)
                        break
                    except Exception as error:
                        action = _validation_action(error, prompt, write)
                        if action == "retry":
                            continue
                        edit_identity = True
                        break
                if edit_identity:
                    continue
            return resource_id

    if choice == "identity":
        identity = namespace_identity()
        return (
            {"outbound_identity": identity}
            if identity
            else {"reuse_identity": True}
        )

    result: Dict[str, Any] = {}
    if choice in {"dps", "complete"}:
        result["dps"] = _guided_endpoint(
            "DPS",
            "dps",
            prompt,
            write,
            validate_resource,
            validate_endpoint_identity,
            browse,
        )
    if choice in {"hub", "complete"}:
        result["hubs"] = []
        while True:
            try:
                hub = _guided_endpoint(
                    "IoT Hub",
                    "hub",
                    prompt,
                    write,
                    validate_resource,
                    validate_endpoint_identity,
                    browse,
                )
            except BackRequested:
                if result["hubs"]:
                    break
                if choice == "complete":
                    result["dps"] = _guided_endpoint(
                        "DPS",
                        "dps",
                        prompt,
                        write,
                        validate_resource,
                        validate_endpoint_identity,
                        browse,
                    )
                    continue
                raise
            result["hubs"].append(hub)
            try:
                another = _select(
                    "Add another IoT Hub?",
                    {
                        "no": ("no", "No", "n"),
                        "yes": ("yes", "Yes", "y"),
                    },
                    prompt,
                    write,
                )
            except BackRequested:
                result["hubs"].pop()
                continue
            if another == "no":
                break
    if choice == "updates":
        result["software_updates"] = _guided_endpoint(
            "Update Instance",
            "software-updates",
            prompt,
            write,
            validate_resource,
            validate_endpoint_identity,
            browse,
        )
    identity = None
    while include_namespace_identity:
        try:
            identity = namespace_identity()
            break
        except BackRequested:
            if choice == "dps":
                result["dps"] = _guided_endpoint(
                    "DPS",
                    "dps",
                    prompt,
                    write,
                    validate_resource,
                    validate_endpoint_identity,
                    browse,
                )
            elif choice == "updates":
                result["software_updates"] = _guided_endpoint(
                    "Update Instance",
                    "software-updates",
                    prompt,
                    write,
                    validate_resource,
                    validate_endpoint_identity,
                    browse,
                )
            elif result.get("hubs"):
                result["hubs"][-1] = _guided_endpoint(
                    "IoT Hub",
                    "hub",
                    prompt,
                    write,
                    validate_resource,
                    validate_endpoint_identity,
                    browse,
                )
            else:
                raise
    if identity:
        result["outbound_identity"] = identity
    return result


def _configured_resource(value):
    if not value:
        return "pending"
    values = value[-1] if isinstance(value, list) and value and isinstance(
        value[0], list
    ) else value
    pairs = _parse_pairs(values, "configuration")
    name = (
        pairs.get("resource-name")
        or pairs.get("resource-id", "").rstrip("/").rsplit("/", 1)[-1]
    )
    return f"{name} · staged" if name else "staged"


def _configuration_display(result, skipped, checked):
    identity = result.get("outbound_identity")
    values = {
        "identity": (
            (
                "SystemAssigned"
                if str(identity).casefold() == _SYSTEM_ASSIGNED
                else str(identity).rstrip("/").rsplit("/", 1)[-1]
            )
            + " · staged"
            if identity
            else "pending"
        ),
        "hub": (
            f"{len(result['hubs'])} Hub(s) · "
            f"{_configured_resource(result['hubs'])}"
            if result.get("hubs")
            else "pending"
        ),
        "dps": _configured_resource(result.get("dps")),
        "updates": _configured_resource(
            result.get("software_updates")
        ),
        "status": "checked" if checked else "optional",
    }
    for key in skipped:
        values[key] = "skipped"
    return values


def _configuration_totals(result, skipped, checked):
    staged = sum(
        bool(result.get(key))
        for key in (
            "outbound_identity",
            "hubs",
            "dps",
            "software_updates",
        )
    )
    parts = []
    if staged:
        parts.append(f"{staged} staged")
    if skipped:
        parts.append(f"{len(skipped)} skipped")
    if checked:
        parts.append("1 checked")
    return " · ".join(parts) or "nothing staged"


def _guided_configuration(
    prompt,
    write,
    validate_resource,
    validate_endpoint_identity,
    validate_namespace_identity,
    allow_identity_reuse,
    browse,
    probe_status=None,
    namespace_name=None,
    resource_group_name=None,
    initial=None,
):
    result: Dict[str, Any] = dict(initial or {})
    skipped = set(result.pop("skipped", ()))
    checked = bool(result.pop("check_status", False))
    labels = {
        "identity": "Outbound identity",
        "hub": "Link IoT Hub",
        "dps": "Link DPS",
        "updates": "Link Software Updates",
        "status": "Check namespace status",
    }
    while True:
        display = _configuration_display(result, skipped, checked)
        options = {
            key: (
                key,
                (
                    f"{'✔' if display[key] not in {'pending', 'optional', 'skipped'} else '–'} "
                    f"{label:<26} {display[key]}"
                ),
                str(index),
            )
            for index, (key, label) in enumerate(
                labels.items(), start=1
            )
        }
        options["done"] = (
            "done",
            "Done → review plan",
            "d",
        )
        key = _select(
            "Configuration"
            f"{'':<28}{_configuration_totals(result, skipped, checked)}"
            "\nEvery item is optional · nothing applied yet",
            options,
            prompt,
            write,
            show_options=True,
        )
        if key == "done":
            break
        try:
            action_key = _action(
                f"configuration › {list(labels).index(key) + 1} "
                f"{labels[key]}",
                {
                    "enter": "configure",
                    "s": "skip",
                    "r": "reset",
                },
                prompt,
                write,
                default="enter",
            )
        except BackRequested:
            continue
        action = {
            "enter": "configure",
            "s": "skip",
            "r": "reset",
        }[action_key]
        if action == "skip":
            skipped.add(key)
            if key == "identity":
                result.pop("outbound_identity", None)
            elif key == "hub":
                result.pop("hubs", None)
            elif key == "dps":
                result.pop("dps", None)
            elif key == "updates":
                result.pop("software_updates", None)
            elif key == "status":
                checked = False
            continue
        if action == "reset":
            skipped.discard(key)
            if key == "identity":
                result.pop("outbound_identity", None)
            elif key == "hub":
                result.pop("hubs", None)
            elif key == "dps":
                result.pop("dps", None)
            elif key == "updates":
                result.pop("software_updates", None)
            elif key == "status":
                checked = False
            continue
        skipped.discard(key)
        if key == "status":
            if probe_status:
                probe_status(namespace_name, resource_group_name)
            checked = True
            continue
        try:
            partial = _guided_values(
                prompt=prompt,
                write=write,
                validate_resource=validate_resource,
                validate_endpoint_identity=validate_endpoint_identity,
                validate_namespace_identity=validate_namespace_identity,
                allow_identity_reuse=allow_identity_reuse,
                browse=browse,
                selected_choice=key,
                include_namespace_identity=(
                    key == "identity"
                    or not result.get("outbound_identity")
                    and not allow_identity_reuse
                ),
            )
        except BackRequested:
            continue
        if partial.pop("reuse_identity", False):
            result.pop("outbound_identity", None)
        result.update(partial)
    result["skipped"] = tuple(sorted(skipped))
    result["check_status"] = checked
    return result


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
    config: Optional[str] = None,
    no_input: bool = False,
    interactive: Optional[bool] = None,
    prompt: Callable[[str], str] = _prompt,
    write: Callable[[str], None] = print,
    validate_resource_group: Optional[Callable[[str], None]] = None,
    validate_namespace: Optional[Callable[[str, str], None]] = None,
    validate_endpoint: Optional[
        Callable[[EndpointSpec, bool], None]
    ] = None,
    validate_endpoint_resource: Optional[
        Callable[[EndpointSpec, bool], Any]
    ] = None,
    validate_endpoint_identity: Optional[
        Callable[[EndpointSpec, Any], None]
    ] = None,
    validate_identity: Optional[Callable[[str], None]] = None,
    can_reuse_identity: Optional[Callable[[str, str], bool]] = None,
    browse_resources: Optional[
        Callable[[str, str], List[Dict[str, Any]]]
    ] = None,
    browse_resource_groups: Optional[
        Callable[[], List[Dict[str, Any]]]
    ] = None,
    browse_namespaces: Optional[
        Callable[[str], List[Dict[str, Any]]]
    ] = None,
    probe_status: Optional[Callable[[], None]] = None,
    initial_request: Optional[SetupRequest] = None,
    back_from_resource_group: bool = False,
) -> SetupRequest:
    if config and any(
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

    if config:
        raw = _read_config(config)
        ns = raw.get("namespace", {})
        links = raw.get("links", {})
        if not isinstance(ns, dict) or not isinstance(links, dict):
            raise InvalidArgumentValueError(
                "Workflow config namespace and links must be objects."
            )
        namespace_name = namespace_name or ns.get("name")
        resource_group_name = (
            resource_group_name or ns.get("resourceGroup")
        )
        location = location or ns.get("location")
        if tags is None:
            tags = ns.get("tags")
        if tags is not None and not isinstance(tags, dict):
            raise InvalidArgumentValueError(
                "Workflow config namespace.tags must be an object."
            )
        identity = ns.get("outboundIdentity") or {}
        namespace_outbound_identity = (
            identity.get("userAssignedResourceId")
            or identity.get("type")
            or namespace_outbound_identity
        )
        dps = (
            _required_config_pairs(links["dps"], "links.dps")
            if "dps" in links
            else None
        )
        hub_values = links.get("hubs", [])
        if not isinstance(hub_values, list):
            raise InvalidArgumentValueError(
                "Workflow config 'links.hubs' must contain a list."
            )
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
        if "assignRoles" in raw:
            raise InvalidArgumentValueError(
                "Workflow config 'assignRoles' is no longer supported. Atomic "
                "link commands always validate and create required service roles."
            )

    namespace_is_fixed = bool(namespace_name)
    namespace_name, resource_group_name = resolve_scope_inputs(
        namespace_name,
        resource_group_name,
        subscription_id=subscription_id,
        no_input=no_input,
        interactive=interactive,
        prompt=prompt,
        write=write,
        validate_resource_group=validate_resource_group,
        validate_namespace=validate_namespace,
        browse_resource_groups=browse_resource_groups,
        browse_namespaces=browse_namespaces,
        back_from_resource_group=back_from_resource_group,
    )

    guided_input = False
    if initial_request or not any(
        (namespace_outbound_identity, dps, hubs, software_updates)
    ):
        is_interactive = (
            _is_interactive() if interactive is None else interactive
        )
        if no_input or not is_interactive:
            raise ArgumentUsageError(
                "Specify a namespace identity, --dps, --hub, --software-updates, "
                "or --config. Interactive input requires a terminal."
            )
        _set_prompt_phase(prompt, "Configuration")

        def validate_guided_resource(kind, values):
            if not validate_endpoint_resource:
                return None
            endpoint = parse_endpoint(
                values + ["identity=system-assigned"],
                kind,
                resource_group_name,
                subscription_id,
            )
            return validate_endpoint_resource(endpoint, False)

        def validate_guided_identity(kind, values, resource):
            if validate_endpoint_identity:
                validate_endpoint_identity(
                    parse_endpoint(
                        values,
                        kind,
                        resource_group_name,
                        subscription_id,
                    ),
                    resource,
                )

        while True:
            try:
                guided = _guided_configuration(
                    prompt=prompt,
                    write=write,
                    validate_resource=validate_guided_resource,
                    validate_endpoint_identity=validate_guided_identity,
                    validate_namespace_identity=validate_identity,
                    allow_identity_reuse=(
                        can_reuse_identity(
                            namespace_name, resource_group_name
                        )
                        if can_reuse_identity
                        else False
                    ),
                    browse=(
                        lambda kind: browse_resources(
                            kind, resource_group_name
                        )
                        if browse_resources
                        else []
                    ),
                    probe_status=probe_status,
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    initial=(
                        _request_guided_values(initial_request)
                        if initial_request
                        else None
                    ),
                )
                break
            except BackRequested:
                if namespace_is_fixed:
                    write(
                        "Namespace came from command input; already at the "
                        "first editable setup choice."
                    )
                else:
                    namespace_name, resource_group_name = resolve_scope_inputs(
                        None,
                        resource_group_name,
                        subscription_id=subscription_id,
                        interactive=interactive,
                        prompt=prompt,
                        write=write,
                        validate_resource_group=validate_resource_group,
                        validate_namespace=validate_namespace,
                        browse_resource_groups=browse_resource_groups,
                        browse_namespaces=browse_namespaces,
                        back_from_resource_group=back_from_resource_group,
                    )
        guided_input = True
        namespace_outbound_identity = guided.get("outbound_identity")
        dps = guided.get("dps")
        hubs = guided.get("hubs")
        software_updates = guided.get("software_updates")

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
            outbound_uami = namespace_outbound_identity
            if validate_identity and not guided_input:
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

    if not guided_input and (
        validate_endpoint
        or validate_endpoint_resource
        or validate_endpoint_identity
    ):
        for endpoint in (
            [dps_spec] + list(hub_specs) + [su_spec]
        ):
            if endpoint:
                allow_missing = endpoint is su_spec and create_su
                if validate_endpoint_resource:
                    resource = validate_endpoint_resource(
                        endpoint, allow_missing
                    )
                    if resource is not None and validate_endpoint_identity:
                        validate_endpoint_identity(endpoint, resource)
                elif validate_endpoint:
                    validate_endpoint(endpoint, allow_missing)

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
        skipped=tuple(guided.get("skipped", ())) if guided_input else (),
        check_status=bool(guided.get("check_status")) if guided_input else False,
    )


def _request_guided_values(request: SetupRequest):
    result: Dict[str, Any] = {
        "skipped": request.skipped,
        "check_status": request.check_status,
    }
    if request.outbound_identity_type == "SystemAssigned":
        result["outbound_identity"] = _SYSTEM_ASSIGNED
    elif request.outbound_user_assigned_identity:
        result["outbound_identity"] = (
            request.outbound_user_assigned_identity
        )
    if request.dps:
        result["dps"] = _endpoint_values(request.dps)
    if request.hubs:
        result["hubs"] = [
            _endpoint_values(endpoint) for endpoint in request.hubs
        ]
    if request.software_updates:
        result["software_updates"] = _endpoint_values(
            request.software_updates
        )
        if request.create_update_instance:
            result["software_updates"].append(
                "create-if-missing=true"
            )
    return result


def _endpoint_values(endpoint: EndpointSpec):
    identity = (
        _SYSTEM_ASSIGNED
        if endpoint.identity_type == _SYSTEM_ASSIGNED
        else endpoint.user_assigned_identity
    )
    values = [
        f"endpoint={endpoint.endpoint_name}",
        f"resource-id={endpoint.resource_id}",
        f"identity={identity}",
    ]
    if endpoint.availability:
        values.append(f"availability={endpoint.availability}")
    if endpoint.allocation_weight is not None:
        values.append(
            f"allocation-weight={endpoint.allocation_weight}"
        )
    return values


def write_json_file(path: str, value: Dict[str, Any]):
    Path(path).expanduser().write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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
