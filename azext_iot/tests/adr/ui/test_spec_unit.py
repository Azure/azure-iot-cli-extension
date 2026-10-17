# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry and spec validation (design doc step 1)."""

import pytest

from azext_iot.adr.ui.core.spec import (
    STYLE_ERROR,
    STYLE_OK,
    STYLE_WARN,
    Action,
    Column,
    Registry,
    SpecError,
    state_style,
)
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


def test_registry_resolves_kind_and_aliases(registry, spec):
    assert registry.resolve("widget") is spec
    assert registry.resolve("wg") is spec
    assert registry.resolve("  WG  ") is spec, "resolution is trimmed and case-insensitive"
    assert registry.resolve("nope") is None
    assert "widget" in registry and len(registry) == 1


def test_registry_rejects_duplicate_kind(registry):
    with pytest.raises(SpecError, match="already registered"):
        registry.register(widget_spec())


def test_registry_rejects_alias_collision(registry):
    colliding = widget_spec(kind="other", aliases=("wg",))
    with pytest.raises(SpecError, match="already bound"):
        registry.register(colliding)


def test_registry_tracks_roots_and_children(registry):
    child = widget_spec(kind="gadget", aliases=("gd",), parent="widget")
    registry.register(child)
    assert [s.kind for s in registry.roots()] == ["widget"]
    assert registry.children_of("widget")[0].kind == "gadget"


def test_collection_summary_lists_a_few_names_then_the_remainder():
    rows = [{"name": name} for name in ("one", "two", "three", "four", "five")]
    assert widget_spec().summarize_rows(rows) == "one, two, three, +2 more"


def test_unknown_kind_raises(registry):
    with pytest.raises(SpecError, match="unknown kind"):
        registry.get("missing")


# -- validation: a malformed kind must fail at registration, not at render time ----


def test_spec_requires_columns():
    with pytest.raises(SpecError, match="no columns"):
        Registry().register(widget_spec(columns=()))


def test_spec_rejects_duplicate_column_keys():
    duplicated = (
        Column("name", "NAME", lambda p: p["name"]),
        Column("name", "AGAIN", lambda p: p["name"]),
    )
    with pytest.raises(SpecError, match="duplicate column keys"):
        Registry().register(widget_spec(columns=duplicated))


def test_spec_rejects_sort_on_unknown_column():
    with pytest.raises(SpecError, match="unknown column"):
        Registry().register(widget_spec(sort=("nonexistent", False)))


def test_spec_rejects_duplicate_action_names():
    actions = (Action("delete", "Delete"), Action("delete", "Delete again"))
    with pytest.raises(SpecError, match="duplicate action names"):
        Registry().register(widget_spec(actions=actions))


def test_every_registered_spec_is_well_formed(registry):
    """The guard that catches a malformed new kind before it reaches a screen."""
    for spec in registry.all():
        assert spec.row_id is not None
        assert spec.columns
        assert spec.column(spec.default_sort()[0]) is not None


# -- spec helpers ------------------------------------------------------------------


def test_visible_columns_respects_wide_flag(spec):
    assert [c.key for c in spec.visible_columns()] == ["name", "state", "count"]
    assert [c.key for c in spec.visible_columns(show_wide=True)] == [
        "name",
        "state",
        "model",
        "count",
    ]


def test_action_applicability(spec):
    assert spec.action("disable").is_applicable(make_payload("a", state="Succeeded"))
    assert not spec.action("disable").is_applicable(make_payload("a", state="Failed"))
    assert spec.action("delete").is_applicable(make_payload("a")), "no predicate means always"
    assert spec.action("missing") is None


def test_state_style_maps_provisioning_states():
    assert state_style(make_payload("a", state="Succeeded")) == STYLE_OK
    assert state_style(make_payload("a", state="Failed")) == STYLE_ERROR
    assert state_style(make_payload("a", state="failed")) == STYLE_ERROR
    assert state_style(make_payload("a", state="Canceled")) == STYLE_ERROR
    assert state_style(make_payload("a", state="Accepted")) == STYLE_WARN
    assert state_style(make_payload("a", state="")) is None


def test_column_sort_value_is_case_insensitive_for_text():
    column = Column("name", "NAME", lambda p: p["name"])
    assert column.sort_value({"name": "Zeta"}) == "zeta"


# -- child scope: declared on the spec, never inferred by the application ----------


def test_child_scope_defaults_to_kind_name():
    spec = widget_spec()
    assert spec.child_scope(make_payload("w1")) == {"widget_name": "w1"}


def test_child_scope_uses_declared_scope_key():
    spec = widget_spec(scope_key="namespace_name")
    assert spec.child_scope(make_payload("ns1")) == {"namespace_name": "ns1"}


def test_child_scope_merges_extra_contribution():
    spec = widget_spec(
        scope_key="namespace_name",
        scope_extra=lambda p: {"resource_group_name": p.get("rg")},
    )
    payload = make_payload("ns1")
    payload["rg"] = "my-rg"
    assert spec.child_scope(payload) == {
        "namespace_name": "ns1",
        "resource_group_name": "my-rg",
    }


def test_child_scope_tolerates_empty_extra():
    spec = widget_spec(scope_extra=lambda p: {})
    assert spec.child_scope(make_payload("w1")) == {"widget_name": "w1"}
