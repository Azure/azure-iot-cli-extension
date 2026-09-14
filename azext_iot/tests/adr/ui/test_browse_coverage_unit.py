# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Browse load, stale-data, filtering and transient selection regressions."""

import asyncio
import threading
from unittest.mock import Mock

import pytest
from textual.widgets import DataTable, Input
from textual.widgets.data_table import RowDoesNotExist

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.spec import ChildRef
from azext_iot.adr.ui.core.store import FetchResult
from azext_iot.adr.ui.core.table import LoadState
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.adr.ui.widgets.chrome import FlashLine
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec
from azext_iot.tests.adr.ui.test_app_coverage_unit import settle


def run_browse(spec, source, scenario):
    async def runner():
        app = RadrApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            screen = BrowseScreen(spec, source, {"namespace_name": "ns", "resource_group_name": "rg"})
            await app.push_screen(screen)
            await settle(app, pilot)
            await scenario(app, pilot, screen)
    asyncio.run(runner())


@pytest.mark.parametrize("loaded_at, payloads, expected_state, expected_flash", [
    (12.0, [make_payload("cached")], LoadState.STALE, "refresh failed; showing cached data: throttled"),
    (None, [], LoadState.FAILED, "refresh failed: throttled"),
])
def test_cache_result_error_is_visible_and_does_not_masquerade_as_fresh_rows(
    loaded_at, payloads, expected_state, expected_flash,
):
    source = Mock(return_value=FetchResult(payloads, error="throttled", loaded_at=loaded_at))

    async def scenario(app, pilot, screen):
        assert screen.model.state is expected_state
        assert screen.model.last_loaded_at == loaded_at
        assert screen.model.error == "throttled"
        assert screen.query_one(FlashLine).text == expected_flash
        assert screen.model.total_count == len(payloads)
        assert not screen._loading
        source.assert_called_once_with(screen.scope, force=False)
        source.return_value = FetchResult([make_payload("recovered")], loaded_at=20.0)
        await pilot.press("r")
        await settle(app, pilot)
        assert screen.model.state is LoadState.READY
        assert screen.model.error is None
        assert screen.selected_payload()["name"] == "recovered"
        assert source.call_args.kwargs == {"force": True}

    run_browse(widget_spec(), source, scenario)


def test_missing_parent_failure_is_actionable_and_refresh_can_recover():
    source = Mock(side_effect=RuntimeError("Parent not found"))

    async def scenario(app, pilot, screen):
        assert screen.model.state is LoadState.FAILED
        assert "parent resource is no longer available" in screen.model.error
        assert "Return and refresh the parent list" in screen.query_one(FlashLine).text
        assert screen.selected_payload() is None
        screen.action_show_json()
        assert app.screen is screen
        source.side_effect = None
        source.return_value = [make_payload("restored")]
        screen.action_refresh()
        await settle(app, pilot)
        assert screen.model.state is LoadState.READY
        assert screen.model.error is None
        assert screen.selected_payload()["name"] == "restored"

    run_browse(widget_spec(parent="namespace"), source, scenario)


def test_wide_sort_filter_submit_and_escape_preserve_row_identity():
    source = Mock(return_value=[make_payload("alpha"), make_payload("beta")])

    async def scenario(app, pilot, screen):
        table = screen.query_one(DataTable)
        table.move_cursor(row=1)
        assert screen.selected_row_id() == "beta"
        await pilot.press("ctrl+w")
        assert screen.model.show_wide
        assert len(table.columns) == 4
        assert screen.selected_row_id() == "beta"
        await pilot.press("s")
        assert screen.model.sort_descending
        assert screen.selected_row_id() == "beta"
        await pilot.press("slash")
        field = screen.query_one(Input)
        assert app.focused is field and field.display
        field.value = "alpha"
        await pilot.pause()
        assert screen.model.row_count == 1
        assert screen.selected_row_id() == "alpha"
        await pilot.press("enter")
        assert not field.display and not screen._filtering
        assert screen.model.filter_text == "alpha"
        await pilot.press("escape")
        assert screen.model.filter_text == ""
        assert screen.model.row_count == 2
        await pilot.press("slash")
        field.value = "nonexistent"
        await pilot.pause()
        assert screen.selected_payload() is None
        await pilot.press("escape")
        assert not field.display
        assert screen.model.filter_text == "nonexistent"
        await pilot.press("escape")
        assert screen.model.row_count == 2
        await pilot.press("ctrl+w")
        assert not screen.model.show_wide
        assert len(table.columns) == 3
        assert source.call_count == 1

    run_browse(widget_spec(children=()), source, scenario)


def test_invalid_cursor_during_repaint_does_not_open_json(monkeypatch):
    async def scenario(app, pilot, screen):
        table = screen.query_one(DataTable)
        with monkeypatch.context() as transient:
            transient.setattr(table, "coordinate_to_cell_key", Mock(side_effect=RowDoesNotExist("repainting")))
            assert screen.selected_row_id() is None
            screen.action_show_json()
            assert app.screen is screen
        screen.action_show_json()
        await pilot.pause()
        assert isinstance(app.screen, DetailScreen)
        assert app.screen.resource_name() == "one"
        # A standalone JSON record can also name itself without a resource spec.
        assert DetailScreen(None, {"name": "standalone"}).resource_name() == "standalone"
    run_browse(widget_spec(), Mock(return_value=[make_payload("one")]), scenario)


def test_overlapping_refresh_is_dropped_and_loading_animation_tolerates_repaint_gap():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def source(scope, force=False):
        calls.append((scope, force))
        started.set()
        if not release.wait(timeout=10):
            raise RuntimeError("test did not release loader")
        return [make_payload("loaded")]

    async def runner():
        app = RadrApp()
        try:
            async with app.run_test(size=(120, 40)) as pilot:
                await settle(app, pilot)
                screen = BrowseScreen(widget_spec(), source)
                await app.push_screen(screen)
                try:
                    assert await asyncio.to_thread(started.wait, 5)
                    screen.refresh_rows(force=True)
                    assert len(calls) == 1
                    table = screen.query_one(DataTable)
                    assert screen.selected_payload() is None
                    screen._animate_loading_row()
                    assert "Loading resources" in table.get_row("__loading__")[0].plain
                    table.remove_row("__loading__")
                    screen._animate_loading_row()
                    assert table.row_count == 0
                    assert screen._loading
                finally:
                    release.set()
                await settle(app, pilot)
                assert screen.model.state is LoadState.READY
                assert screen.selected_row_id() == "loaded"
                assert not screen._loading
                assert len(calls) == 1
        finally:
            release.set()
    asyncio.run(runner())


def test_declared_multiple_children_open_overview_but_filter_input_does_not_navigate():
    children = (ChildRef("group", "Groups", "g"), ChildRef("member", "Members", "m"))

    async def scenario(app, pilot, screen):
        await pilot.press("slash", "g")
        assert app.screen is screen
        assert screen.model.filter_text == "g"
        await pilot.press("escape", "escape")
        assert screen.model.row_count == 1
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert [entry[0] for entry in app.screen.child_entries] == list(children)
        assert app.screen.scope["widget_name"] == "one"
    run_browse(widget_spec(children=children), Mock(return_value=[make_payload("one")]), scenario)
