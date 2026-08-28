# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Namespace: the root kind, and the scope every other kind hangs from."""

from azext_iot.adr.ui.core.spec import (
    STYLE_ACTIVE,
    STYLE_ERROR,
    STYLE_WARN,
    ChildRef,
    Column,
    Guide,
    ResourceSpec,
)
from azext_iot.adr.ui.kinds._common import (
    age_column,
    dig,
    name_column,
    name_of,
    resource_group_of,
    state_column,
)


def endpoint_count(payload, section: str) -> int:
    endpoints = dig(payload, "properties", section, "endpoints", default={}) or {}
    return len(endpoints)


def tag_summary(payload) -> str:
    tags = payload.get("tags") or {}
    return " ".join(f"{key}={value}" for key, value in sorted(tags.items()))


def link_readiness(payload) -> str:
    state = str(dig(payload, "properties", "provisioningState", default=""))
    if state.casefold() in ("failed", "canceled"):
        return "blocked"
    identity = str(dig(payload, "identity", "type", default="None"))
    if identity.casefold() in ("", "none"):
        return "needs identity"
    if endpoint_count(payload, "provisioning") == 0:
        return "needs DPS"
    if endpoint_count(payload, "messaging") == 0:
        return "needs Hub"
    return "ready"


_READINESS_STYLES = {
    "ready": STYLE_ACTIVE,
    "needs identity": STYLE_WARN,
    "needs DPS": STYLE_WARN,
    "needs Hub": STYLE_WARN,
    "blocked": STYLE_ERROR,
}


def readiness_style(payload):
    return _READINESS_STYLES.get(link_readiness(payload))


def build(session) -> ResourceSpec:
    def list_namespaces(scope):
        return session.list_from(
            "namespace",
            "list",
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="namespace",
        title="Namespace",
        title_plural="Namespaces",
        aliases=("ns",),
        guide=Guide(
            about="Device Registry namespaces in the current subscription.",
            action=(
                "Enter explore  \u00b7  n new namespace  \u00b7  w connect selected namespace"
            ),
            runs="Read-only; refreshes in the background.",
            note=(
                "Linked resources counts DPS, IoT Hubs and update instances."
            ),
        ),
        row_id=name_of,
        list=list_namespaces,
        columns=(
            name_column(width=32),
            Column("rg", "RESOURCE GROUP", resource_group_of, width=24),
            Column("location", "LOCATION", lambda p: p.get("location", ""), width=18),
            state_column(width=14),
            Column(
                "readiness",
                "LINK READINESS",
                link_readiness,
                width=16,
                style=readiness_style,
            ),
            Column(
                "hubs",
                "HUBS",
                lambda payload: endpoint_count(payload, "messaging"),
                width=7,
            ),
            Column(
                "dps",
                "DPS",
                lambda payload: endpoint_count(payload, "provisioning"),
                width=6,
            ),
            Column(
                "updates",
                "UPDATES",
                lambda payload: endpoint_count(payload, "updating"),
                width=9,
            ),
            Column("tags", "TAGS", tag_summary, width=32),
            Column(
                "identity",
                "IDENTITY",
                lambda p: dig(p, "identity", "type", default="None"),
                width=20,
                wide=True,
            ),
            age_column(),
        ),
        sort=("name", False),
        scope_key="namespace_name",
        # Children live in the namespace's own resource group, which may differ from the
        # one the session started in.
        scope_extra=lambda p: {"resource_group_name": resource_group_of(p)},
        children=(
            ChildRef(
                "link", "Linked resources", "l",
                "DPS, IoT Hubs and Software Updates endpoints attached to this namespace.",
            ),
            ChildRef(
                "device", "Devices", "d",
                "Registry records, enablement and provisioning state.",
            ),
            ChildRef(
                "group", "Groups", "g",
                "Saved device queries and their current membership.",
            ),
            ChildRef(
                "job", "Jobs", "j",
                "Job definitions, schedules and execution runs.",
            ),
            ChildRef(
                "ca", "Certificate authorities", "c",
                "X.509 trust roots and certificate policies.",
            ),
        ),
    )
