# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Table model: diffing, sorting, filtering and load state (design doc step 2)."""

from azext_iot.adr.ui.core.spec import STYLE_ERROR, STYLE_OK
from azext_iot.adr.ui.core.table import LoadState, TableModel
from azext_iot.tests.adr.ui.conftest import make_payload


def model_with(spec, *names, **kwargs):
    model = TableModel(spec)
    model.apply([make_payload(name, **kwargs) for name in names])
    return model


# -- load state: the "loading vs empty" distinction ---------------------------------


def test_never_loaded_is_not_empty(spec):
    model = TableModel(spec)
    assert model.state is LoadState.NEVER_LOADED
    assert "Loading" in model.status_text()
    assert "No widgets" not in model.status_text()


def test_empty_result_is_reported_as_empty(spec):
    model = TableModel(spec)
    model.apply([])
    assert model.state is LoadState.EMPTY
    assert "No widgets in the current scope" in model.status_text()


def test_failure_before_any_load_is_failed(spec):
    model = TableModel(spec)
    model.fail("boom")
    assert model.state is LoadState.FAILED
    assert "boom" in model.status_text()


def test_failure_after_a_load_keeps_rows_and_goes_stale(spec):
    model = model_with(spec, "a", "b")
    model.fail("network down")
    assert model.state is LoadState.STALE
    assert model.row_count == 2, "rows are retained so the screen does not blank out"
    assert "last known data" in model.status_text()


def test_recovery_after_failure_returns_to_ready(spec):
    model = model_with(spec, "a")
    model.fail("network down")
    model.apply([make_payload("a")])
    assert model.state is LoadState.READY
    assert model.error is None


# -- diffing: the property that keeps the cursor still ------------------------------


def test_first_load_reports_all_rows_added(spec):
    model = TableModel(spec)
    diff = model.apply([make_payload("a"), make_payload("b")])
    assert [row.id for row in diff.added] == ["a", "b"]
    assert not diff.updated and not diff.removed


def test_unchanged_refresh_produces_empty_diff(spec):
    model = model_with(spec, "a", "b")
    diff = model.apply([make_payload("a"), make_payload("b")])
    assert diff.is_empty, "identical data must not repaint any row"


def test_changed_row_is_updated_not_re_added(spec):
    model = model_with(spec, "a", "b")
    diff = model.apply([make_payload("a", state="Failed"), make_payload("b")])
    assert [row.id for row in diff.updated] == ["a"]
    assert not diff.added and not diff.removed


def test_failed_resource_marks_the_whole_row_as_failed(spec):
    model = model_with(spec, "broken", state="Failed")
    assert model.rows[0].status_style == STYLE_ERROR


def test_added_and_removed_rows_are_detected(spec):
    model = model_with(spec, "a", "b")
    diff = model.apply([make_payload("b"), make_payload("c")])
    assert [row.id for row in diff.added] == ["c"]
    assert diff.removed == ["a"]


def test_marks_survive_refresh_but_drop_for_removed_rows(spec):
    model = model_with(spec, "a", "b")
    model.toggle_mark("a")
    model.toggle_mark("b")
    model.apply([make_payload("a"), make_payload("c")])
    assert model.marks == {"a"}, "marks on vanished rows must not linger"


def test_row_identity_is_stable_across_refresh(spec):
    """Index lookup by id is what lets a screen restore the cursor after a refresh."""
    model = model_with(spec, "a", "b", "c")
    before = model.index_of("b")
    model.apply([make_payload(n) for n in ("a", "b", "c")])
    assert model.index_of("b") == before


# -- sorting -----------------------------------------------------------------------


def test_default_sort_is_applied(spec):
    model = TableModel(spec)
    model.apply([make_payload(n) for n in ("c", "a", "b")])
    assert [row.id for row in model.rows] == ["a", "b", "c"]


def test_sort_toggles_direction_on_repeat(spec):
    model = model_with(spec, "a", "b", "c")
    model.set_sort("name")
    assert [row.id for row in model.rows] == ["c", "b", "a"]
    model.set_sort("name")
    assert [row.id for row in model.rows] == ["a", "b", "c"]


def test_sort_by_numeric_column_uses_sort_key(spec):
    model = TableModel(spec)
    model.apply(
        [make_payload("a", count=10), make_payload("b", count=2), make_payload("c", count=33)]
    )
    model.set_sort("count")
    assert [row.id for row in model.rows] == ["b", "a", "c"], "numeric, not lexicographic"


def test_sort_on_unknown_column_is_ignored(spec):
    model = model_with(spec, "a", "b")
    model.set_sort("nonexistent")
    assert model.sort_key == "name"


# -- filtering ---------------------------------------------------------------------


def test_filter_matches_any_visible_cell(spec):
    model = TableModel(spec)
    model.apply([make_payload("alpha"), make_payload("beta", state="Failed")])
    model.set_filter("fail")
    assert [row.id for row in model.rows] == ["beta"]
    assert model.total_count == 2 and model.row_count == 1
    assert "1 of 2" in model.status_text()


def test_filter_is_case_insensitive_and_clearable(spec):
    model = model_with(spec, "Alpha", "beta")
    model.set_filter("ALPHA")
    assert [row.id for row in model.rows] == ["Alpha"]
    model.clear_filter()
    assert model.row_count == 2


# -- columns -----------------------------------------------------------------------


def test_wide_toggle_changes_visible_cells(spec):
    model = model_with(spec, "a")
    assert model.headers == ["NAME", "STATE", "COUNT"]
    model.toggle_wide()
    assert model.headers == ["NAME", "STATE", "MODEL", "COUNT"]
    assert model.rows[0].cells == ("a", "Succeeded", "GW-100", "0")


def test_cell_styles_come_from_the_spec(spec):
    model = TableModel(spec)
    model.apply([make_payload("a", state="Succeeded"), make_payload("b", state="Failed")])
    assert model.rows[0].styles[1] == STYLE_OK
    assert model.rows[1].styles[1] == STYLE_ERROR


def test_marked_payloads_follow_sort_order(spec):
    model = model_with(spec, "a", "b", "c")
    model.toggle_mark("c")
    model.toggle_mark("a")
    assert [p["name"] for p in model.marked_payloads()] == ["a", "c"]
    assert model.toggle_mark("a") is False, "toggling an existing mark clears it"
    model.clear_marks()
    assert model.marked_payloads() == []


def test_failure_during_first_load_is_failed_not_stale(spec):
    """A collection that never produced rows is failed; 'stale' would imply data exists."""
    model = TableModel(spec)
    model.begin_load()
    model.fail("namespace_name is required")
    assert model.state is LoadState.FAILED
    assert "Could not load" in model.status_text()


def test_failure_after_rows_exist_is_stale(spec):
    model = model_with(spec, "a")
    model.begin_load()
    model.fail("network down")
    assert model.state is LoadState.STALE
