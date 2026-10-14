# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Strict, detached setup configuration shared by interactive and scripted callers."""

import copy
import json
import re
from os import PathLike, fspath
from pathlib import Path

import yaml
from azure.cli.core.azclierror import InvalidArgumentValueError


_TYPES = {
    "hub": "Microsoft.Devices/IotHubs",
    "dps": "Microsoft.Devices/provisioningServices",
    "software-updates": "Microsoft.DeviceUpdate/updateInstances",
    "identity": "Microsoft.ManagedIdentity/userAssignedIdentities",
}
_UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
CMS_DEFAULTS = {
    "rootName": "root", "intermediateName": "intermediate",
    "policyName": "default", "validityDays": 30,
}


def _fail(path, message):
    raise InvalidArgumentValueError(f"Workflow config {path}: {message}.")


def _object(value, path, keys):
    if not isinstance(value, dict):
        _fail(path, "must contain an object")
    for key in value:
        if key not in keys:
            _fail(f"{path}.{key}", "unknown key; assignRoles is no longer supported"
                  if key == "assignRoles" else "unknown key")


def _string(value, path):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail(path, "must be a non-empty string without surrounding whitespace")


def _integer(value, path, minimum, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(path, f"must be an integer in {minimum}..{maximum or 'unbounded'}")


def _boolean(value, path):
    if type(value) is not bool:
        _fail(path, "must be a boolean")


def validate_resource_id(value, kind, path):
    _string(value, path)
    pattern = (
        rf"/subscriptions/{_UUID}/resourceGroups/[^/\s]+/providers/"
        + re.escape(_TYPES[kind]) + r"/[^/\s]+"
    )
    if not re.fullmatch(pattern, value, re.IGNORECASE):
        _fail(path, f"must be a {_TYPES[kind]} ARM resource ID")
    return value


def validate_identity(value, path):
    """Return a canonical identity string, without accepting partial ARM IDs."""
    if isinstance(value, dict):
        _object(value, path, {"type", "userAssignedResourceId"})
        identity_type = value.get("type")
        user_id = value.get("userAssignedResourceId")
        if identity_type in ("SystemAssigned", "system-assigned"):
            if "userAssignedResourceId" in value:
                _fail(path, "SystemAssigned cannot specify userAssignedResourceId")
            return "system-assigned"
        if identity_type not in (None, "UserAssigned", "user-assigned") or not user_id:
            _fail(path, "identity requires SystemAssigned or userAssignedResourceId")
        return validate_resource_id(user_id, "identity", f"{path}.userAssignedResourceId")
    if value in ("SystemAssigned", "system-assigned"):
        return "system-assigned"
    return validate_resource_id(value, "identity", path)


def validate_endpoint(value, kind, path):
    keys = {"resourceName", "resourceId", "resourceGroup", "subscription", "endpointName", "identity", "createIfMissing"}
    if kind == "hub":
        keys.update({"availability", "allocationWeight"})
    if kind in ("hub", "dps"):
        keys.update({"sku", "unit"})
    _object(value, path, keys)
    if not value:
        _fail(path, "must contain a non-empty object")
    for key in ("resourceName", "resourceId", "resourceGroup", "subscription", "endpointName"):
        if key in value:
            _string(value[key], f"{path}.{key}")
            if key in ("resourceName", "resourceGroup", "endpointName") and re.search(r"[/\s]", value[key]):
                _fail(f"{path}.{key}", "must be a name, without slashes or whitespace")
    if ("resourceName" in value) == ("resourceId" in value):
        _fail(path, "specify exactly one of resourceName and resourceId")
    if "resourceId" in value:
        validate_resource_id(value["resourceId"], kind, f"{path}.resourceId")
        if "resourceGroup" in value or "subscription" in value:
            _fail(path, "resourceId cannot be combined with resourceGroup or subscription")
    if "subscription" in value and not re.fullmatch(_UUID, value["subscription"]):
        _fail(f"{path}.subscription", "must be a subscription UUID")
    validate_identity(value.get("identity"), f"{path}.identity")
    if "createIfMissing" in value:
        _boolean(value["createIfMissing"], f"{path}.createIfMissing")
    if "sku" in value:
        allowed = ("S1", "S2", "S3") if kind == "hub" else ("S1",)
        if value["sku"] not in allowed:
            _fail(f"{path}.sku", f"must be one of {', '.join(allowed)}")
    if "unit" in value:
        _integer(value["unit"], f"{path}.unit", 1)
    if ("sku" in value or "unit" in value) and not value.get("createIfMissing"):
        _fail(path, "sku/unit require createIfMissing=true; reuse never updates resources")
    if "availability" in value and value["availability"] not in ("Available", "Disabled"):
        _fail(f"{path}.availability", "must be Available or Disabled")
    if "allocationWeight" in value:
        _integer(value["allocationWeight"], f"{path}.allocationWeight", 1, 1000)
    return value


class _Pairs(list):
    """Preserve mapping pairs until paths are known, including duplicate keys."""


class _Loader(yaml.SafeLoader):
    pass


def _yaml_pairs(loader, node):
    return _Pairs((loader.construct_object(key), loader.construct_object(value)) for key, value in node.value)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_pairs)


def _materialize(value, path="$"):
    if isinstance(value, _Pairs):
        result = {}
        for key, item in value:
            if not isinstance(key, str):
                _fail(path, "object keys must be strings")
            if key in result:
                _fail(f"{path}.{key}", "duplicate key")
            result[key] = _materialize(item, f"{path}.{key}")
        return result
    if isinstance(value, list):
        return [_materialize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    return value


def _read(value):
    if isinstance(value, PathLike):
        value = fspath(value)
    if not isinstance(value, str) or not value.strip():
        _fail("$", "must be a dict, JSON object string, or configuration path")
    content = value.strip()
    inline = (
        content.startswith(("{", "[", '"')) or content in ("null", "true", "false")
        or re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", content)
    )
    if not inline:
        try:
            content = Path(value.removeprefix("@")).expanduser().read_text(encoding="utf-8")
        except (OSError, ValueError, UnicodeError) as error:
            raise InvalidArgumentValueError(f"Unable to read workflow config '{value}': {error}.") from error
    try:
        if inline or value.lower().endswith(".json") or (
            not value.lower().endswith((".yaml", ".yml")) and content.lstrip().startswith(("{", "["))
        ):
            return _materialize(json.loads(content, object_pairs_hook=_Pairs))
        return _materialize(yaml.load(content, Loader=_Loader))
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise InvalidArgumentValueError(f"Workflow config $: not valid YAML or JSON: {error}") from error


def load_config(value):
    """Load one namespace's configuration. Missing scope may be completed by the UI."""
    config = copy.deepcopy(value) if isinstance(value, dict) else _read(value)
    _object(config, "$", {"schemaVersion", "subscriptionId", "namespace", "links", "cms", "checkStatus"})
    version = config.setdefault("schemaVersion", 1)
    if type(version) is not int or version != 1:
        _fail("schemaVersion", "only integer version 1 is supported")
    if "subscriptionId" in config:
        _string(config["subscriptionId"], "subscriptionId")
        if not re.fullmatch(_UUID, config["subscriptionId"]):
            _fail("subscriptionId", "must be a subscription UUID")
    ns = config.get("namespace", {})
    _object(ns, "namespace", {"name", "resourceGroup", "location", "tags", "outboundIdentity"})
    for key in ("name", "resourceGroup", "location"):
        if key in ns:
            _string(ns[key], f"namespace.{key}")
    if "name" in ns and not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", ns["name"]):
        _fail("namespace.name", "must be an ARM resource name")
    if "tags" in ns:
        if not isinstance(ns["tags"], dict):
            _fail("namespace.tags", "must contain an object")
        for key, item in ns["tags"].items():
            _string(key, "namespace.tags")
            if not isinstance(item, str):
                _fail(f"namespace.tags.{key}", "must be a string")
    if "outboundIdentity" in ns:
        validate_identity(ns["outboundIdentity"], "namespace.outboundIdentity")
    links = config.get("links", {})
    _object(links, "links", {"dps", "hubs", "softwareUpdates"})
    for key, kind in (("dps", "dps"), ("softwareUpdates", "software-updates")):
        if key in links:
            validate_endpoint(links[key], kind, f"links.{key}")
    if "hubs" in links:
        if not isinstance(links["hubs"], list):
            _fail("links.hubs", "must contain a list")
        for index, hub in enumerate(links["hubs"]):
            validate_endpoint(hub, "hub", f"links.hubs[{index}]")
    if "checkStatus" in config:
        _boolean(config["checkStatus"], "checkStatus")
    if "cms" in config:
        cms = config["cms"]
        if cms is False:
            config["cms"] = {"enabled": False}
        else:
            _object(cms, "cms", {"enabled", *CMS_DEFAULTS})
            _boolean(cms.get("enabled"), "cms.enabled")
            if not cms["enabled"] and set(cms) != {"enabled"}:
                _fail("cms", "disabled CMS cannot specify names or validityDays")
            if cms["enabled"]:
                for key, default in CMS_DEFAULTS.items():
                    cms.setdefault(key, default)
                for key in ("rootName", "intermediateName", "policyName"):
                    _string(cms[key], f"cms.{key}")
                    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", cms[key]):
                        _fail(f"cms.{key}", "must be an ARM child name (1..64 letters, digits, dots, underscores or hyphens)")
                if cms["rootName"].casefold() == cms["intermediateName"].casefold():
                    _fail("cms.intermediateName", "must differ from rootName")
                _integer(cms["validityDays"], "cms.validityDays", 1, 90)
    return config


def request_config(request):
    """Export a SetupRequest as deterministic, validated setup configuration.

    Skipped guided answers are not desired capabilities and have no schema representation.
    No resource data or service response material is included.
    """
    namespace = {"name": request.namespace_name, "resourceGroup": request.resource_group_name}
    for key, value in (("location", request.location), ("tags", request.tags)):
        if value is not None:
            namespace[key] = value
    if request.outbound_identity_type:
        namespace["outboundIdentity"] = (
            {"type": "SystemAssigned"} if request.outbound_identity_type == "SystemAssigned" else
            {"type": "UserAssigned", "userAssignedResourceId": request.outbound_user_assigned_identity}
        )
    config = {"schemaVersion": 1, "namespace": namespace, "links": {}, "checkStatus": request.check_status}
    if request.subscription_id:
        config["subscriptionId"] = request.subscription_id
    for endpoint in (request.dps, *request.hubs, request.software_updates):
        if endpoint is None:
            continue
        value = {
            "endpointName": endpoint.endpoint_name, "resourceId": endpoint.resource_id,
            "identity": (
                {"type": "SystemAssigned"} if endpoint.identity_type == "system-assigned" else
                {"type": "UserAssigned", "userAssignedResourceId": endpoint.user_assigned_identity}
            ),
        }
        if endpoint.create_if_missing or endpoint.kind == "software-updates" and request.create_update_instance:
            value["createIfMissing"] = True
        for key, option in (("sku", endpoint.sku), ("unit", endpoint.unit), ("availability", endpoint.availability),
                            ("allocationWeight", endpoint.allocation_weight)):
            if option is not None:
                value[key] = option
        if endpoint.kind == "hub":
            config["links"].setdefault("hubs", []).append(value)
        else:
            config["links"]["dps" if endpoint.kind == "dps" else "softwareUpdates"] = value
    if request.cms:
        config["cms"] = {
            "enabled": True, "rootName": request.cms.root_name, "intermediateName": request.cms.intermediate_name,
            "policyName": request.cms.policy_name, "validityDays": request.cms.validity_days,
        }
    return load_config(config)
