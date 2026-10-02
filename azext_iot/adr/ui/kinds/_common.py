# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Helpers shared by the resource kinds.

Extractors are deliberately forgiving: the service is in preview and fields come and go,
so a missing value renders blank rather than raising. That is design-doc risk R3 handled
in one place instead of in every column.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from azext_iot.adr.ui.core.spec import (
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_OK,
    STYLE_WARN,
    Column,
    state_style,
)

Payload = Dict[str, Any]


def dig(payload: Payload, *path: str, default: Any = "") -> Any:
    """Walk ``path`` through a payload, returning ``default`` if any hop is missing."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def prop(*path: str, default: Any = "") -> Callable[[Payload], Any]:
    """Extractor for ``properties.<path>``, falling back to the top level.

    Most ADR payloads nest under ``properties``, but endpoint entries and a few
    projections are flat, so both are tried.
    """

    def extract(payload: Payload) -> Any:
        value = dig(payload, "properties", *path, default=None)
        if value is None:
            value = dig(payload, *path, default=None)
        return default if value is None else value

    return extract


def field(*path: str, default: Any = "") -> Callable[[Payload], Any]:
    """Extractor for a top-level field."""

    def extract(payload: Payload) -> Any:
        return dig(payload, *path, default=default)

    return extract


def short_id(resource_id: Any) -> str:
    """Last segment of an ARM id: the readable part of a long resource reference."""
    text = str(resource_id or "")
    return text.rstrip("/").rsplit("/", 1)[-1] if text else ""


def name_of(payload: Payload) -> str:
    """Row identity.

    Every ADR resource is uniquely named within its parent, but list projections
    occasionally omit ``name``; the ARM id's last segment is the same value, so it is used
    rather than the full id, which would render as an unreadable row.
    """
    name = payload.get("name")
    if name:
        return str(name)
    return short_id(payload.get("id"))


def resource_group_of(payload: Payload) -> str:
    """Resource group, from the field when present or parsed out of the ARM id."""
    group = payload.get("resourceGroup") or payload.get("resourceGroupName")
    if group:
        return str(group)
    parts = str(payload.get("id") or "").split("/")
    if "resourceGroups" in parts:
        index = parts.index("resourceGroups")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def humanize_age(value: Any) -> str:
    """Compact relative age, in the style of a resource table: 4d, 3h, 12m."""
    moment = _parse_time(value)
    if moment is None:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 0:
        return "0s"
    for limit, divisor, suffix in (
        (60, 1, "s"),
        (3600, 60, "m"),
        (86400, 3600, "h"),
        (float("inf"), 86400, "d"),
    ):
        if seconds < limit:
            return f"{int(seconds // divisor)}{suffix}"
    return ""


# -- reusable columns ---------------------------------------------------------------


def name_column(label: str = "NAME", width: int = 26) -> Column:
    return Column("name", label, name_of, width=width)


def state_column(width: int = 12) -> Column:
    """Provisioning state, coloured by outcome and always readable as text."""
    return Column(
        "state",
        "STATE",
        prop("provisioningState"),
        width=width,
        style=state_style,
    )


def age_column(width: int = 7) -> Column:
    return Column(
        "age",
        "AGE",
        lambda p: humanize_age(dig(p, "systemData", "createdAt", default="")),
        width=width,
        sort_key=lambda p: str(dig(p, "systemData", "createdAt", default="")),
    )


def enum_style(mapping: Dict[str, str], default: Optional[str] = None) -> Callable[[Any], Optional[str]]:
    """Build a cell styler from a value-to-token mapping."""

    def style(value: Any) -> Optional[str]:
        return mapping.get(str(value), default)

    return style


def value_style(extract: Callable[[Payload], Any], mapping: Dict[str, str],
                default: Optional[str] = None) -> Callable[[Payload], Optional[str]]:
    """Style a cell from its own extracted value."""
    styler = enum_style(mapping, default)

    def style(payload: Payload) -> Optional[str]:
        return styler(extract(payload))

    return style


#: Common state-token mappings, so kinds do not each invent their own colour rules.
ENABLEMENT_STYLES = {"Enabled": STYLE_OK, "Disabled": STYLE_MUTED}
RUN_STATUS_STYLES = {
    "Succeeded": STYLE_OK,
    "Completed": STYLE_OK,
    "Active": STYLE_WARN,
    "Running": STYLE_WARN,
    "Queued": STYLE_WARN,
    "Scheduled": STYLE_WARN,
    "Failed": STYLE_ERROR,
    "Canceled": STYLE_MUTED,
    "Cancelled": STYLE_MUTED,
}
