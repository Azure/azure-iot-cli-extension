# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Groups: query-defined device cohorts, and the members they currently resolve to."""

from azext_iot.adr.ui.core.spec import (
    STYLE_OK,
    STYLE_WARN,
    ChildRef,
    Column,
    Guide,
    ResourceSpec,
)
from azext_iot.adr.ui.kinds._common import (
    age_column,
    name_column,
    name_of,
    prop,
    short_id,
    state_column,
    value_style,
)

_MEMBERSHIP_STYLES = {"Resolved": STYLE_OK, "Refreshing": STYLE_WARN, "Stale": STYLE_WARN}


def build(session) -> ResourceSpec:
    def list_groups(scope):
        return session.list_from(
            "group",
            "list",
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    return ResourceSpec(
        kind="group",
        title="Group",
        title_plural="Groups",
        aliases=("grp",),
        parent="namespace",
        guide=Guide(
            about=(
                "Device groups in this namespace. A group is a saved query, so its membership changes as devices "
                "change."
            ),
            runs="az iot adr ns group list --ns <namespace> -g <resource-group>  ·  read-only",
            note=(
                "Membership is evaluated by the service, not here; a group may be briefly stale after devices change."
            ),
        ),
        row_id=name_of,
        list=list_groups,
        columns=(
            name_column(width=24),
            Column("display", "DISPLAY NAME", prop("displayName"), width=22),
            Column("members", "MEMBERS", prop("memberCount"), width=9,
                   sort_key=lambda p: prop("memberCount", default=0)(p) or 0),
            Column(
                "membership",
                "MEMBERSHIP",
                prop("membershipState"),
                width=13,
                style=value_style(prop("membershipState"), _MEMBERSHIP_STYLES),
            ),
            Column("query", "QUERY", prop("queryString"), width=34, wide=True),
            Column("type", "TYPE", prop("groupType"), width=16, wide=True),
            state_column(),
            age_column(),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name"),
        scope_key="group_name",
        children=(ChildRef("member", "Members", "m"),),
    )


def build_member(session) -> ResourceSpec:
    def list_members(scope):
        return session.list_from(
            "group",
            "list_members",
            group_name=scope.get("group_name"),
            namespace_name=scope.get("namespace_name"),
            resource_group_name=scope.get("resource_group_name"),
        )

    def member_name(payload) -> str:
        # Members come back as resource references, not full device payloads.
        return name_of(payload) or short_id(payload.get("resourceId") or payload.get("id"))

    return ResourceSpec(
        kind="member",
        title="Member",
        title_plural="Members",
        aliases=("mem",),
        parent="group",
        guide=Guide(
            about="Devices that currently match this group's query.",
            runs="az iot adr ns group list-members -n <group> --ns <namespace>  ·  read-only",
            note="Membership is derived, not assigned - to change it, change the query or the devices.",
        ),
        row_id=member_name,
        list=list_members,
        columns=(
            Column("name", "DEVICE", member_name, width=30),
            Column(
                "id",
                "RESOURCE ID",
                lambda p: p.get("resourceId") or p.get("id") or "",
                width=60,
                wide=True,
            ),
        ),
        sort=("name", False),
        requires=("namespace_name", "resource_group_name", "group_name"),
        scope_key="member_name",
    )
