# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Pure presentation helpers for the keyboard and mouse setup surface."""

from copy import deepcopy
import json
import shlex

from azure.cli.core.azclierror import InvalidArgumentValueError
from rich.text import Text


def endpoint_id(endpoint, kind, namespace, subscription):
    if endpoint.get("resourceId"):
        return endpoint["resourceId"]
    types = {
        "dps": "Microsoft.Devices/provisioningServices",
        "hub": "Microsoft.Devices/IotHubs",
        "softwareUpdates": "Microsoft.DeviceUpdate/updateInstances",
    }
    return (
        f"/subscriptions/{endpoint.get('subscription', subscription)}"
        f"/resourceGroups/{endpoint.get('resourceGroup', namespace.get('resourceGroup', ''))}"
        f"/providers/{types[kind]}/{endpoint.get('resourceName', '')}"
    )


def parse_tags(value):
    result = {}
    for item in shlex.split(value):
        name, separator, content = item.partition("=")
        if not name or not separator or name in result:
            raise InvalidArgumentValueError("Tags must be unique name=value entries.")
        result[name] = content
    return result


def form_config(original, values, subscription):
    """Project the form onto its source without discarding unexposed options."""
    result = deepcopy(original)
    result.setdefault("schemaVersion", 1)
    result["subscriptionId"] = subscription
    ns = result.setdefault("namespace", {})
    ns.update(name=values["name"].strip(), resourceGroup=values["group"].strip())
    for key in ("location", "outboundIdentity"):
        result["namespace"].pop(key, None)
    if values["location"].strip():
        ns["location"] = values["location"].strip()
    if values["tags"] or "tags" in ns:
        ns["tags"] = parse_tags(values["tags"])
    identity = values["outbound"].strip()
    if identity:
        ns["outboundIdentity"] = (
            {"type": "SystemAssigned"}
            if identity == "system-assigned"
            else {"type": "UserAssigned", "userAssignedResourceId": identity}
        )
    links = {}
    old_links = original.get("links", {})
    link_identity = values["link_identity"].strip() or "system-assigned"
    if values["mode"] == "new":
        count = int(values["count"])
        prefix = ns["name"]
        links["dps"] = {
            "resourceName": values["dps_name"].strip() or f"{prefix}-provisioning",
            "identity": link_identity,
            "createIfMissing": True,
        }
        links["hubs"] = [
            {
                "resourceName": f"{values['hub_prefix'].strip() or prefix + '-hub'}-{index + 1}",
                "identity": link_identity,
                "createIfMissing": True,
                "sku": values["sku"],
                "unit": 1,
            }
            for index in range(count)
        ]
    elif values["mode"] == "existing":
        dps_id = values["dps_id"].strip()
        if dps_id:
            old = old_links.get("dps", {})
            links["dps"] = (
                deepcopy(old)
                if endpoint_id(old, "dps", ns, subscription).casefold() == dps_id.casefold()
                else {"resourceId": dps_id, "identity": link_identity}
            )
        existing = {
            endpoint_id(item, "hub", ns, subscription).casefold(): item
            for item in old_links.get("hubs", [])
        }
        ids = list(dict.fromkeys(
            item.strip() for item in values["hub_ids"] if item.strip()
        ))
        if len(ids) > 10:
            raise InvalidArgumentValueError("Select no more than 10 IoT Hubs.")
        links["hubs"] = [
            deepcopy(existing.get(resource_id.casefold()))
            if resource_id.casefold() in existing
            else {"resourceId": resource_id, "identity": link_identity}
            for resource_id in ids
        ]
    if values["software_updates"]:
        links["softwareUpdates"] = deepcopy(old_links.get("softwareUpdates")) or {
            "resourceName": f"{ns['name']}-su",
            "identity": link_identity,
            "createIfMissing": True,
        }
    result["links"] = links
    if values["cms"]:
        cms = deepcopy(original.get("cms") or {})
        cms.update(enabled=True, validityDays=int(values["validity"]))
        for key, field in (
            ("rootName", "root"), ("intermediateName", "intermediate"), ("policyName", "policy")
        ):
            if values[field].strip():
                cms[key] = values[field].strip()
        result["cms"] = cms
    else:
        result.pop("cms", None)
    return result


def plan_fingerprint(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"))


def plan_text(plan, *, commands=False, roles=False):
    text = Text()
    for item in plan.get("items", []):
        is_role = item["id"].startswith("roles-") or item["action"] in {"role", "assign"}
        action = "ROLE" if is_role else item["action"].upper()
        state = item["state"]
        style = "#f47067" if state in {"Blocked", "Failed"} else "#e3b341" if is_role else ""
        text.append(f"{action:<10} {item['target']}  {state}\n", style=style)
        if item.get("message") and (not is_role or roles):
            text.append(f"           {item['message']}\n")
        if is_role and not roles:
            text.append("           May create missing service-role grants; expand role details.\n", "#e3b341")
        if commands and item.get("command"):
            text.append(f"           {item['command']}\n", "#7cc4fa")
    return text
