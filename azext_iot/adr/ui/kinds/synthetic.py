# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Synthetic kinds for M0.

These specs use the same contract the real kinds will use, so the entire navigation model,
diffing and chrome can be exercised before any service call exists. Replaced kind by kind
in M1; the screens do not change when that happens.
"""

from typing import Any, Dict, List

from azext_iot.adr.ui.core.spec import (
    STYLE_MUTED,
    STYLE_OK,
    Action,
    ChildRef,
    Column,
    Guide,
    Registry,
    ResourceSpec,
    state_style,
)

_NAMESPACES = [
    {
        "name": "factory-eastus2",
        "location": "eastus2",
        "resourceGroup": "adr-prod-rg",
        "properties": {"provisioningState": "Succeeded"},
        "identity": {"type": "SystemAssigned"},
    },
    {
        "name": "lab-westus",
        "location": "westus2",
        "resourceGroup": "adr-lab-rg",
        "properties": {"provisioningState": "Accepted"},
        "identity": {"type": "None"},
    },
    {
        "name": "retired-ns",
        "location": "eastus",
        "resourceGroup": "adr-old-rg",
        "properties": {"provisioningState": "Failed"},
        "identity": {"type": "None"},
    },
]

_DEVICES = [
    ("edge-0001", "Enabled", "Contoso", "GW-100", "1.2.3", "Succeeded"),
    ("edge-0002", "Enabled", "Contoso", "GW-100", "1.2.3", "Succeeded"),
    ("edge-0003", "Disabled", "Contoso", "GW-100", "1.2.2", "Succeeded"),
    ("edge-0004", "Enabled", "Fabrikam", "RTU-7", "0.9.1", "Succeeded"),
    ("edge-0005", "Enabled", "Contoso", "GW-200", "2.0.0", "Accepted"),
    ("edge-0006", "Disabled", "Fabrikam", "RTU-7", "0.9.0", "Failed"),
]

_ATTRIBUTES = [
    ("update", "Microsoft.DeviceUpdate", "1.2.3"),
    ("site", "User", "plant-a"),
    ("line", "User", "assembly-3"),
]


#: How many synthetic devices each namespace has. 'retired-ns' has none on purpose:
#: it is the only way to see the empty state without breaking the service.
_DEVICE_COUNTS = {"factory-eastus2": 6, "lab-westus": 3, "retired-ns": 0}


def _device_payloads(namespace: str) -> List[Dict[str, Any]]:
    limit = _DEVICE_COUNTS.get(namespace, len(_DEVICES))
    payloads = []
    for name, enablement, manufacturer, model, software, state in _DEVICES[:limit]:
        payloads.append(
            {
                "name": f"{name}",
                "namespace": namespace,
                "properties": {
                    "enablementState": enablement,
                    "manufacturer": manufacturer,
                    "model": model,
                    "softwareRevision": software,
                    "provisioningState": state,
                },
            }
        )
    return payloads


def _enablement_style(payload: Dict[str, Any]) -> str:
    state = (payload.get("properties") or {}).get("enablementState")
    return STYLE_OK if state == "Enabled" else STYLE_MUTED


def build_synthetic_registry() -> Registry:
    """Register the synthetic kinds and return the registry."""
    registry = Registry()

    registry.register(
        ResourceSpec(
            kind="namespace",
            title="Namespace",
            title_plural="Namespaces",
            aliases=("ns",),
            guide=Guide(
                about="Sample namespaces. This is the offline demo registry, not live Azure.",
                runs="Nothing - rows are generated locally",
                note="Use 'az iot adr ns ui' without --demo to browse real resources.",
            ),
            row_id=lambda p: p["name"],
            list=lambda scope: list(_NAMESPACES),
            columns=(
                Column("name", "NAME", lambda p: p["name"], width=24),
                Column("rg", "RESOURCE GROUP", lambda p: p.get("resourceGroup", ""), width=18),
                Column("location", "LOCATION", lambda p: p.get("location", ""), width=12),
                Column(
                    "state",
                    "STATE",
                    lambda p: (p.get("properties") or {}).get("provisioningState", ""),
                    style=state_style,
                    width=12,
                ),
                Column(
                    "identity",
                    "IDENTITY",
                    lambda p: (p.get("identity") or {}).get("type", "None"),
                    wide=True,
                    width=18,
                ),
            ),
            sort=("name", False),
            children=(ChildRef("device", "Devices", "d"),),
            scope_key="namespace_name",
            # Children of a namespace live in the namespace's own resource group.
            scope_extra=lambda p: (
                {"resource_group_name": p["resourceGroup"]} if p.get("resourceGroup") else {}
            ),
        )
    )

    registry.register(
        ResourceSpec(
            kind="device",
            title="Registry device",
            title_plural="Registry devices",
            aliases=("dev", "rd"),
            guide=Guide(
                about="Sample devices for the selected namespace.",
                runs="Nothing - rows are generated locally",
            ),
            parent="namespace",
            row_id=lambda p: p["name"],
            list=lambda scope: _device_payloads(scope.get("namespace_name", "")),
            columns=(
                Column("name", "NAME", lambda p: p["name"], width=14),
                Column(
                    "enablement",
                    "STATE",
                    lambda p: (p.get("properties") or {}).get("enablementState", ""),
                    style=_enablement_style,
                    width=10,
                ),
                Column(
                    "manufacturer",
                    "MANUFACTURER",
                    lambda p: (p.get("properties") or {}).get("manufacturer", ""),
                    width=14,
                ),
                Column(
                    "model",
                    "MODEL",
                    lambda p: (p.get("properties") or {}).get("model", ""),
                    width=10,
                ),
                Column(
                    "software",
                    "SOFTWARE",
                    lambda p: (p.get("properties") or {}).get("softwareRevision", ""),
                    width=10,
                ),
                Column(
                    "provisioning",
                    "PROVISIONING",
                    lambda p: (p.get("properties") or {}).get("provisioningState", ""),
                    style=state_style,
                    wide=True,
                    width=14,
                ),
            ),
            sort=("name", False),
            scope_key="registry_device_name",
            children=(ChildRef("attribute", "Attributes", "t"),),
            actions=(
                Action("disable", "Disable", destructive=False),
                Action("delete", "Delete", key="ctrl+d", destructive=True),
            ),
        )
    )

    registry.register(
        ResourceSpec(
            kind="attribute",
            title="Attribute",
            title_plural="Attributes",
            aliases=("attr",),
            parent="device",
            row_id=lambda p: p["name"],
            list=lambda scope: [
                {"name": name, "reportedBy": source, "value": value}
                for name, source, value in _ATTRIBUTES
            ],
            columns=(
                Column("name", "NAME", lambda p: p["name"], width=20),
                Column("reported", "REPORTED BY", lambda p: p.get("reportedBy", ""), width=24),
                Column("value", "VALUE", lambda p: p.get("value", ""), width=20),
            ),
            sort=("name", False),
        )
    )

    return registry
