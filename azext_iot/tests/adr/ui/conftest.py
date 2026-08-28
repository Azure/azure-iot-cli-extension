# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared fixtures for terminal UI tests.

Kept local to this directory: the UI must not modify shared ADR test fixtures.
"""

import pytest

from azext_iot.adr.ui.core.spec import Action, ChildRef, Column, Registry, ResourceSpec, state_style


def make_payload(name, state="Succeeded", model="GW-100", count=0):
    return {
        "name": name,
        "properties": {"provisioningState": state, "model": model, "count": count},
    }


def widget_spec(kind="widget", **overrides):
    """A small, self-contained spec used to exercise the generic machinery."""
    options = {
        "kind": kind,
        "title": "Widget",
        "title_plural": "Widgets",
        "aliases": ("wg",),
        "row_id": lambda p: p["name"],
        "columns": (
            Column("name", "NAME", lambda p: p["name"]),
            Column(
                "state",
                "STATE",
                lambda p: p["properties"]["provisioningState"],
                style=lambda p: state_style(p),
            ),
            Column("model", "MODEL", lambda p: p["properties"]["model"], wide=True),
            Column(
                "count",
                "COUNT",
                lambda p: p["properties"]["count"],
                sort_key=lambda p: p["properties"]["count"],
            ),
        ),
        "sort": ("name", False),
        "children": (ChildRef("gadget", "Gadgets", "g"),),
        "actions": (
            Action("delete", "Delete", key="ctrl+d", destructive=True),
            Action(
                "disable",
                "Disable",
                applies_to=lambda p: p["properties"]["provisioningState"] == "Succeeded",
            ),
        ),
    }
    options.update(overrides)
    return ResourceSpec(**options)


@pytest.fixture
def spec():
    return widget_spec()


@pytest.fixture
def registry(spec):
    reg = Registry()
    reg.register(spec)
    return reg
