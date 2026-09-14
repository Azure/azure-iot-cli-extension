# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Independent collection errors, stale data and navigation on the resource map."""

import asyncio
from unittest.mock import Mock

from textual.widgets import DataTable, Static

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.spec import ChildRef
from azext_iot.adr.ui.core.store import FetchResult
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec
from azext_iot.tests.adr.ui.test_app_coverage_unit import settle


def test_resource_map_distinguishes_failed_empty_and_cached_collections_then_refreshes():
    sources = [
        Mock(return_value=FetchResult([], error="permission denied")),
        Mock(return_value=FetchResult([make_payload("cached")], error="throttled", loaded_at=10.0)),
        Mock(return_value=[]),
        Mock(side_effect=RuntimeError("transport failed")),
    ]
    children = [
        (ChildRef(kind, kind.title(), key), widget_spec(kind=kind), source)
        for kind, key, source in zip(("first", "second", "third", "fourth"), ("a", "b", "c", "d"), sources)
    ]

    async def scenario():
        app = RadrApp()
        screen = OverviewScreen(widget_spec(), make_payload("parent"), {"namespace_name": "ns"}, children)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            await app.push_screen(screen)
            await settle(app, pilot)
            assert screen._results == {
                "first": ("!", "permission denied"),
                "second": ("1", "Stale data: throttled"),
                "third": ("0", "None in the current scope"),
                "fourth": ("!", "transport failed"),
            }
            assert "4 collections" in str(screen.query_one("#status-line", Static).render())
            table = screen.query_one(DataTable)
            table.move_cursor(row=2)
            for source in sources:
                source.assert_called_once_with(screen.scope, force=False)
                source.side_effect = None
                source.return_value = [make_payload("recovered")]
            await pilot.press("r")
            await settle(app, pilot)
            assert table.cursor_row == 2
            assert all(value == ("1", "recovered") for value in screen._results.values())
            for source in sources:
                assert source.call_args.kwargs == {"force": True}
            await pilot.press("escape")
            assert app.screen is not screen
    asyncio.run(scenario())


def test_all_not_found_invalidates_parent_once_and_keeps_recovery_instructions(monkeypatch):
    children = [
        (ChildRef(kind, kind.title()), widget_spec(kind=kind), Mock(side_effect=RuntimeError("Parent NOT FOUND")))
        for kind in ("one", "two")
    ]

    async def scenario():
        app = RadrApp()
        screen = OverviewScreen(widget_spec(), make_payload("parent"), {}, children)
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            invalidate = Mock(wraps=app.store.invalidate)
            monkeypatch.setattr(app.store, "invalidate", invalidate)
            await app.push_screen(screen)
            await settle(app, pilot)
            assert "Namespace is unavailable" in str(screen.query_one("#status-line", Static).render())
            invalidate.assert_called_once_with("widget")
            screen._paint()
            await pilot.press("r")
            await settle(app, pilot)
            invalidate.assert_called_once_with("widget")
            assert "press Esc, then r" in str(screen.query_one("#status-line", Static).render())
    asyncio.run(scenario())


def test_child_shortcut_inherits_scope_and_unknown_key_leaves_map_open():
    async def scenario():
        app = RadrApp()
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            root = app.screen
            group = root.spec.children[0]
            app.open_overview(root.spec, root.selected_payload(), [group])
            await settle(app, pilot)
            overview = app.screen
            scope = dict(overview.scope)
            await pilot.press("z")
            assert app.screen is overview
            await pilot.press(group.key)
            await settle(app, pilot)
            assert isinstance(app.screen, BrowseScreen)
            assert app.screen.spec.kind == group.kind
            assert app.screen.scope == scope
            await pilot.press("escape")
            assert app.screen is overview
            await pilot.press("escape")
            assert app.screen is root
    asyncio.run(scenario())


def test_collection_callbacks_after_teardown_do_not_repaint_or_retain_results():
    async def scenario():
        app = RadrApp()
        screen = OverviewScreen(widget_spec(), make_payload("parent"), {}, [])
        screen._child_loaded("before", "1", "not mounted")
        screen._child_failed("before", "not mounted")
        assert not screen._results
        async with app.run_test(size=(120, 40)) as pilot:
            await settle(app, pilot)
            await app.push_screen(screen)
            assert screen._selected_child() is None
            screen.action_open()
            assert app.screen is screen
            await pilot.press("escape")
            await pilot.pause()
            assert not screen.is_attached
            screen._child_loaded("after", "1", "late completion")
            screen._child_failed("after", "late failure")
            assert not screen._results
    asyncio.run(scenario())
