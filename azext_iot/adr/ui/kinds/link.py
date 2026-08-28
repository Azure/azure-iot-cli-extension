# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Endpoint links.

The CLI splits these across `link hub`, `link dps` and `link su`, but they are three
sections of one namespace and are read together far more often than separately. They are
presented as a single table with a TYPE column, which is also what makes the ordering rule
(a DPS endpoint must exist before a Hub) visible at a glance.
"""

from azext_iot.adr.ui.core.spec import (
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_OK,
    STYLE_WARN,
    Column,
    Guide,
    ResourceSpec,
)
from azext_iot.adr.ui.kinds._common import dig, name_of, prop, short_id, value_style

#: Endpoint type discriminator -> short label shown in the TYPE column.
_TYPE_LABELS = {
    "Microsoft.Devices/IotHubs": "IoT Hub",
    "Microsoft.Devices/provisioningServices": "DPS",
    "Microsoft.DeviceUpdate/updateInstances": "Software Updates",
}
_TYPE_STYLES = {
    "DPS": STYLE_WARN,
    "IoT Hub": STYLE_OK,
    "Software Updates": STYLE_MUTED,
}

#: The order the endpoints must be established in, which is also the most useful reading
#: order: provisioning first, then messaging, then updating.
_TYPE_ORDER = {"DPS": 0, "IoT Hub": 1, "Software Updates": 2}


def _endpoint_type(payload) -> str:
    return _TYPE_LABELS.get(str(payload.get("endpointType") or ""), "other")


def _identity(payload) -> str:
    identity = payload.get("inboundCallerIdentity") or {}
    kind = str(identity.get("type") or "")
    if not kind:
        return "none"
    assigned = identity.get("userAssignedIdentity")
    return f"{kind}:{short_id(assigned)}" if assigned else kind


def _overview(payloads) -> str:
    counts = {"DPS": 0, "IoT Hub": 0, "Software Updates": 0}
    for payload in payloads:
        kind = _endpoint_type(payload)
        if kind in counts:
            counts[kind] += 1
    return (
        f"DPS {counts['DPS']}  ·  "
        f"IoT Hubs {counts['IoT Hub']}  ·  "
        f"Updates {counts['Software Updates']}"
    )


def build(session) -> ResourceSpec:
    def list_endpoints(scope):
        """Project all endpoint sections from one namespace request."""
        return session.list_from(
            "link",
            "list_all",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="link",
        title="Linked resource",
        title_plural="Linked resources",
        aliases=("ep", "endpoint"),
        parent="namespace",
        # Endpoint names are unique only within their section, so identity includes type.
        guide=Guide(
            about=(
                "Resources linked to this namespace: the DPS that assigns devices, the IoT Hubs they "
                "are assigned to, and any update instances."
            ),
            runs="az iot adr ns link dps|hub|su list --ns <namespace> -g <resource-group>  ·  read-only",
            note=(
                "Exactly one DPS may be linked, and it must be linked before any hub. Press w for guided setup, which "
                "handles the ordering and the role assignments."
            ),
        ),
        row_id=lambda p: f"{_endpoint_type(p)}/{name_of(p)}",
        list=list_endpoints,
        columns=(
            Column("name", "NAME", name_of, width=24),
            Column(
                "type",
                "TYPE",
                _endpoint_type,
                width=14,
                style=value_style(_endpoint_type, _TYPE_STYLES),
                sort_key=lambda p: (_TYPE_ORDER.get(_endpoint_type(p), 9), name_of(p)),
            ),
            Column("target", "TARGET", lambda p: short_id(p.get("resourceId")), width=26),
            Column("identity", "IDENTITY", _identity, width=22),
            Column(
                "linking",
                "LINKING",
                lambda p: dig(p, "provisioningStatus", "status", default="")
                or p.get("linkingState", ""),
                width=12,
                style=value_style(
                    lambda p: dig(p, "provisioningStatus", "status", default="")
                    or p.get("linkingState", ""),
                    {"Succeeded": STYLE_OK, "Failed": STYLE_ERROR, "Accepted": STYLE_WARN},
                ),
            ),
            Column("availability", "AVAILABILITY", prop("availability"), width=13, wide=True),
            Column("weight", "WEIGHT", prop("allocationWeight"), width=8, wide=True),
            Column("resource", "RESOURCE ID", lambda p: p.get("resourceId", ""), width=60, wide=True),
        ),
        sort=("type", False),
        requires=("namespace_name", "resource_group_name"),
        scope_key="endpoint_name",
        summarize=_overview,
    )
