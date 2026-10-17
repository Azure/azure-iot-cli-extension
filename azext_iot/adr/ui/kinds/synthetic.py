# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline namespace, group and membership navigation using supported ADR surfaces."""

from typing import Any, Dict, List

from azext_iot.adr.ui.core.spec import (
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

_GROUPS = [
    ("plant-0001", "Resolved", 12, "Succeeded"),
    ("plant-0002", "Resolved", 24, "Succeeded"),
    ("plant-0003", "Stale", 8, "Succeeded"),
    ("plant-0004", "Resolved", 17, "Succeeded"),
    ("plant-0005", "Refreshing", 3, "Accepted"),
    ("plant-0006", "Stale", 0, "Failed"),
]

#: How many synthetic groups each namespace has. 'retired-ns' has none on purpose:
#: it is the only way to see the empty state without breaking the service.
_GROUP_COUNTS = {"factory-eastus2": 6, "lab-westus": 3, "retired-ns": 0}


def _group_payloads(namespace: str) -> List[Dict[str, Any]]:
    limit = _GROUP_COUNTS.get(namespace, len(_GROUPS))
    payloads = []
    for name, membership, count, state in _GROUPS[:limit]:
        payloads.append(
            {
                "name": f"{name}",
                "namespace": namespace,
                "properties": {
                    "membershipState": membership,
                    "memberCount": count,
                    "groupType": "RegistryDevice",
                    "provisioningState": state,
                },
            }
        )
    return payloads


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
                note="Run 'az iot adr ns ui' to browse real Azure resources.",
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
            children=(ChildRef("group", "Groups", "g"),),
            scope_key="namespace_name",
            # Children of a namespace live in the namespace's own resource group.
            scope_extra=lambda p: (
                {"resource_group_name": p["resourceGroup"]} if p.get("resourceGroup") else {}
            ),
        )
    )

    registry.register(
        ResourceSpec(
            kind="group",
            title="Group",
            title_plural="Groups",
            aliases=("grp",),
            guide=Guide(
                about="Sample groups for the selected namespace.",
                runs="Nothing - rows are generated locally",
            ),
            parent="namespace",
            row_id=lambda p: p["name"],
            list=lambda scope: _group_payloads(scope.get("namespace_name", "")),
            columns=(
                Column("name", "NAME", lambda p: p["name"], width=14),
                Column(
                    "membership",
                    "MEMBERSHIP",
                    lambda p: (p.get("properties") or {}).get("membershipState", ""),
                    width=14,
                ),
                Column(
                    "members",
                    "MEMBERS",
                    lambda p: (p.get("properties") or {}).get("memberCount", 0),
                    width=14,
                ),
                Column(
                    "type",
                    "TYPE",
                    lambda p: (p.get("properties") or {}).get("groupType", ""),
                    width=18,
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
            scope_key="group_name",
            children=(ChildRef("member", "Members", "m"),),
        )
    )

    registry.register(
        ResourceSpec(
            kind="member",
            title="Member",
            title_plural="Members",
            aliases=("mem",),
            parent="group",
            row_id=lambda p: p["name"],
            list=lambda scope: [
                {"name": f"edge-{index:04}", "resourceId": f"/demo/members/edge-{index:04}"}
                for index in range(1, 4)
            ],
            columns=(
                Column("name", "NAME", lambda p: p["name"], width=20),
                Column("id", "RESOURCE ID", lambda p: p.get("resourceId", ""), width=40),
            ),
            sort=("name", False),
        )
    )

    return registry
