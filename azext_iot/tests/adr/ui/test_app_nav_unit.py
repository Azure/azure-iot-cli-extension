# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Headless application and navigation tests (design doc step 5, M0 gate).

Run without a terminal so they work in CI. Each test drives the real app through its
public surface rather than poking at internals.
"""

import asyncio


from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import HelpScreen
from azext_iot.adr.ui.screens.overview import OverviewScreen
from azext_iot.adr.ui.screens.onboard.execution import ExecutionScreen
from azext_iot.adr.ui.screens.onboard.flow import PlanItem
from azext_iot.adr.ui.screens.onboard.identity import (
    SYSTEM_ASSIGNED,
    set_choice,
    system_choice,
)
from azext_iot.adr.ui.screens.onboard.identity_dialog import IdentityChoiceDialog
from textual.widgets import DataTable
from azext_iot.adr.ui.widgets.chrome import Breadcrumbs, ContextBar, HintBar

SIZE = (120, 34)


async def settle(app, pilot):
    """Wait for row-loading workers, then let the UI repaint."""
    await app.workers.wait_for_complete()
    await pilot.pause()


def drive(coro_fn):
    """Run an async pilot interaction from a synchronous test.

    Avoids adding pytest-asyncio to the repository's dev requirements.
    """

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            return await coro_fn(app, pilot)

    return asyncio.run(runner())


# -- boot --------------------------------------------------------------------------


def test_app_boots_to_the_root_kind():
    async def scenario(app, pilot):
        assert isinstance(app.screen, BrowseScreen)
        assert app.screen.spec.kind == "namespace"
        return app.screen.model.total_count

    assert drive(scenario) == 3


def test_identity_chooser_defaults_cleanly_to_sami():
    async def scenario(app, pilot):
        selected = []
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=None,
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
            ),
            selected.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        return selected[0].mode

    assert drive(scenario) == SYSTEM_ASSIGNED


def test_identity_chooser_fills_the_right_side_and_has_a_clear_back_path():
    async def scenario(app, pilot):
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=None,
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
                pane_left=38,
                pane_top=11,
                pane_height=20,
                pane_width=82,
            )
        )
        await pilot.pause()
        panel = app.screen.query_one("#identity-dialog")
        label = str(app.screen.query_one("#identity-cancel").label)
        dimensions = (
            panel.region.x,
            panel.region.y,
            panel.region.width,
            panel.region.height,
            label,
        )
        await pilot.press("escape")
        await pilot.pause()
        return dimensions, isinstance(app.screen, IdentityChoiceDialog)

    (left, top, width, height, label), still_open = drive(scenario)
    assert (left, top, width, height) == (38, 11, 82, 20)
    assert label == "Back to resources"
    assert not still_open


def test_identity_mode_buttons_support_left_and_right_arrows():
    async def scenario(app, pilot):
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=None,
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
            )
        )
        await pilot.pause()
        focused = [app.focused.id]
        await pilot.press("right")
        focused.append(app.focused.id)
        await pilot.press("right")
        focused.append(app.focused.id)
        await pilot.press("left")
        focused.append(app.focused.id)
        return focused

    assert drive(scenario) == [
        "identity-sami",
        "identity-uami",
        "identity-new",
        "identity-uami",
    ]


def test_uami_picker_filters_by_name():
    class Catalog:
        def user_assigned_identities(self):
            return [
                {
                    "name": "alpha-connectivity",
                    "id": (
                        "/subscriptions/sub-1/resourceGroups/rg-alpha/providers/"
                        "Microsoft.ManagedIdentity/userAssignedIdentities/alpha-connectivity"
                    ),
                    "location": "eastus2",
                    "principalId": "pid-alpha",
                },
                {
                    "name": "beta-connectivity",
                    "id": (
                        "/subscriptions/sub-1/resourceGroups/rg-beta/providers/"
                        "Microsoft.ManagedIdentity/userAssignedIdentities/beta-connectivity"
                    ),
                    "location": "westus2",
                    "principalId": "pid-beta",
                },
            ]

    async def scenario(app, pilot):
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=Catalog(),
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
            )
        )
        await pilot.pause()
        await pilot.press("right")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("slash")
        for character in "beta":
            await pilot.press(character)
        await pilot.pause()
        table = app.screen.query_one("#identity-table", DataTable)
        return table.row_count, table.get_row_at(0)[0]

    assert drive(scenario) == (1, "beta-connectivity")


def test_up_from_uami_list_returns_to_identity_mode_row():
    class Catalog:
        def user_assigned_identities(self):
            return [
                {
                    "name": name,
                    "id": (
                        f"/subscriptions/sub-1/resourceGroups/rg/providers/"
                        f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}"
                    ),
                    "location": "eastus2",
                    "principalId": f"pid-{name}",
                }
                for name in ("first", "second")
            ]

    async def scenario(app, pilot):
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=Catalog(),
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
            )
        )
        await pilot.pause()
        await pilot.press("right")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        table = app.screen.query_one("#identity-table", DataTable)
        await pilot.press("down")
        after_down = table.cursor_coordinate.row
        await pilot.press("up")
        after_first_up = (app.focused.id, table.cursor_coordinate.row)
        await pilot.press("up")
        return after_down, after_first_up, app.focused.id

    assert drive(scenario) == (
        1,
        ("identity-table", 0),
        "identity-uami",
    )


def test_up_from_create_name_returns_to_create_mode():
    async def scenario(app, pilot):
        await app.push_screen(
            IdentityChoiceDialog(
                catalog=None,
                resource_label="hub-primary",
                purpose="Identity this Hub uses to call the namespace",
                subscription_id="sub-1",
                resource_group_name="rg1",
                location="eastus2",
            )
        )
        await pilot.pause()
        await pilot.press("right")
        await pilot.press("right")
        await pilot.press("enter")
        await pilot.pause()
        before = app.focused.id
        await pilot.press("up")
        return before, app.focused.id

    assert drive(scenario) == ("identity-name", "identity-new")


def test_execution_page_retains_per_operation_success():
    async def scenario(app, pilot):
        await app.push_screen(
            ExecutionScreen(
                session=object(),
                context={},
                items=[
                    PlanItem(
                        key="identity",
                        description="Configure outbound identity",
                        target="ns1",
                        category="identity",
                        command="az iot adr ns update",
                        invoke=lambda _session, _context: None,
                    )
                ],
            )
        )
        await app.workers.wait_for_complete()
        await pilot.pause()
        table = app.screen.query_one("#execution-table", DataTable)
        return table.row_count, table.get_row_at(0)[1].plain

    assert drive(scenario) == (1, "Succeeded")


def test_boot_screen_renders_rows_and_status():
    async def scenario(app, pilot):
        model = app.screen.model
        return [row.id for row in model.rows], model.status_text()

    ids, status = drive(scenario)
    assert ids == ["factory-eastus2", "lab-westus", "retired-ns"]
    assert "3 namespaces" in status


def test_failed_resource_name_has_bold_error_style_without_a_marker():
    async def scenario(app, pilot):
        table = app.screen.query_one("#rows", DataTable)
        row = table.get_row("retired-ns")
        name = row[0]
        return name.plain, str(name.style)

    name, style = drive(scenario)
    assert name == "retired-ns"
    assert "bold" in style


# -- drill-down and the page stack --------------------------------------------------


def test_enter_drills_into_child_kind():
    async def scenario(app, pilot):
        await pilot.press("enter")
        await settle(app, pilot)
        return app.screen.spec.kind, app.screen.model.total_count

    kind, count = drive(scenario)
    assert kind == "device"
    assert count == 6


def test_enter_opens_a_resource_map_when_the_parent_has_several_children():
    """Enter should present the hierarchy, not arbitrarily choose the first collection."""
    from azext_iot.adr.ui.core.spec import ChildRef, Column, Registry, ResourceSpec

    def spec(kind, title, rows, children=()):
        return ResourceSpec(
            kind=kind,
            title=title,
            title_plural=f"{title}s",
            aliases=(kind,),
            row_id=lambda payload: payload["name"],
            list=lambda _scope, _rows=rows: list(_rows),
            columns=(Column("name", "NAME", lambda payload: payload["name"], width=20),),
            children=children,
        )

    async def runner():
        registry = Registry()
        registry.register(
            spec(
                "root",
                "Root",
                [{"name": "parent"}],
                (
                    ChildRef("first", "First resources", "f", "The first collection."),
                    ChildRef("second", "Second resources", "e", "The second collection."),
                ),
            )
        )
        registry.register(spec("first", "First", [{"name": "one"}, {"name": "two"}]))
        registry.register(spec("second", "Second", [{"name": "three"}]))
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            screen = app.screen
            table = screen.query_one("#resource-map", DataTable)
            rows = [table.get_row_at(index) for index in range(table.row_count)]
            return type(screen), rows

    screen_type, rows = asyncio.run(runner())
    assert screen_type is OverviewScreen
    assert [str(row[0]) for row in rows] == ["First resources", "Second resources"]
    assert [str(row[1]) for row in rows] == ["2", "1"]


def test_resource_map_enter_opens_the_highlighted_collection():
    from azext_iot.adr.ui.core.spec import ChildRef, Column, Registry, ResourceSpec

    column = (Column("name", "NAME", lambda payload: payload["name"], width=20),)
    registry = Registry()
    registry.register(
        ResourceSpec(
            kind="root", title="Root", title_plural="Roots", aliases=("root",),
            row_id=lambda payload: payload["name"], list=lambda _scope: [{"name": "parent"}],
            columns=column,
            children=(
                ChildRef("first", "First", "f"),
                ChildRef("second", "Second", "e"),
            ),
        )
    )
    registry.register(
        ResourceSpec(
            kind="first", title="First", title_plural="First", aliases=("first",),
            row_id=lambda payload: payload["name"], list=lambda _scope: [{"name": "one"}],
            columns=column,
        )
    )
    registry.register(
        ResourceSpec(
            kind="second", title="Second", title_plural="Second", aliases=("second",),
            row_id=lambda payload: payload["name"], list=lambda _scope: [{"name": "two"}],
            columns=column,
        )
    )

    async def runner():
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            table = app.screen.query_one("#resource-map", DataTable)
            table.move_cursor(row=1)
            await pilot.press("enter")
            await settle(app, pilot)
            return app.screen.spec.kind

    assert asyncio.run(runner()) == "second"


def test_resource_map_explains_a_stale_namespace_list_entry():
    from azext_iot.adr.ui.core.spec import ChildRef, Column, Registry, ResourceSpec

    column = (Column("name", "NAME", lambda payload: payload["name"], width=20),)
    registry = Registry()
    registry.register(
        ResourceSpec(
            kind="root",
            title="Namespace",
            title_plural="Namespaces",
            aliases=("root",),
            row_id=lambda payload: payload["name"],
            list=lambda _scope: [{"name": "stale"}],
            columns=column,
            children=(
                ChildRef("first", "First", "f"),
                ChildRef("second", "Second", "e"),
            ),
        )
    )

    def missing(_scope):
        raise RuntimeError("The resource was not found.")

    for kind in ("first", "second"):
        registry.register(
            ResourceSpec(
                kind=kind,
                title=kind.title(),
                title_plural=kind.title(),
                aliases=(kind,),
                row_id=lambda payload: payload["name"],
                list=missing,
                columns=column,
            )
        )

    async def runner():
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            await pilot.press("enter")
            await settle(app, pilot)
            rendered = app.screen.query_one("#status-line").render()
            return rendered.plain if hasattr(rendered, "plain") else str(rendered)

    status = asyncio.run(runner())
    assert "stale list entry" in status
    assert "Esc, then r" in status


def test_drill_down_carries_parent_scope():
    async def scenario(app, pilot):
        await pilot.press("enter")
        await settle(app, pilot)
        return app.screen.scope

    scope = drive(scenario)
    assert scope["namespace_name"] == "factory-eastus2"
    assert scope["resource_group_name"] == "adr-prod-rg", "resource group follows the namespace"


def test_escape_pops_the_stack_back_to_the_parent():
    async def scenario(app, pilot):
        await pilot.press("enter")
        await settle(app, pilot)
        depth_in = len(app.screen_stack)
        await pilot.press("escape")
        await settle(app, pilot)
        return depth_in, len(app.screen_stack), app.screen.spec.kind

    depth_in, depth_out, kind = drive(scenario)
    assert depth_out == depth_in - 1
    assert kind == "namespace"


def test_stack_does_not_pop_below_the_root():
    async def scenario(app, pilot):
        for _ in range(4):
            await pilot.press("escape")
            await settle(app, pilot)
        return app.screen.spec.kind, len(app.screen_stack)

    kind, depth = drive(scenario)
    assert kind == "namespace", "the root screen is never popped"
    assert depth == 2


def test_three_level_drill_down_and_return():
    async def scenario(app, pilot):
        await pilot.press("enter")  # namespace -> device
        await settle(app, pilot)
        await pilot.press("enter")  # device -> attribute
        await settle(app, pilot)
        deepest = app.screen.spec.kind
        await pilot.press("escape")
        await settle(app, pilot)
        await pilot.press("escape")
        await settle(app, pilot)
        return deepest, app.screen.spec.kind

    deepest, back_at = drive(scenario)
    assert deepest == "attribute"
    assert back_at == "namespace", "the stack unwinds cleanly"


# -- detail view --------------------------------------------------------------------


def test_json_view_opens_and_closes():
    async def scenario(app, pilot):
        await pilot.press("y")
        await pilot.pause()
        opened = isinstance(app.screen, DetailScreen)
        name = app.screen.resource_name() if opened else None
        await pilot.press("escape")
        await settle(app, pilot)
        return opened, name, isinstance(app.screen, BrowseScreen)

    opened, name, returned = drive(scenario)
    assert opened and returned
    assert name == "factory-eastus2"


# -- chrome -------------------------------------------------------------------------


def test_hint_bar_is_generated_from_real_bindings():
    async def scenario(app, pilot):
        hints = app.screen.hint_bindings()
        return {key for key, _ in hints}

    keys = drive(scenario)
    # Every hint must correspond to a binding the screen actually declares.
    assert {"/", "escape", "r", "s", "enter"} <= keys


def test_context_bar_reflects_scope_after_drill_down():
    async def scenario(app, pilot):
        await pilot.press("enter")
        await settle(app, pilot)
        bar = app.screen.query_one("#context-bar", ContextBar)
        return bar.text

    assert "factory-eastus2" in drive(scenario)


def test_breadcrumbs_track_the_stack():
    async def scenario(app, pilot):
        await pilot.press("enter")
        await settle(app, pilot)
        crumbs = app.screen.query_one("#breadcrumbs", Breadcrumbs)
        return crumbs.text

    trail = drive(scenario)
    assert "namespaces" in trail and "registry devices" in trail


def test_hint_bar_widget_is_populated():
    async def scenario(app, pilot):
        return app.screen.query_one("#hint-bar", HintBar).text

    assert "r Refresh" in drive(scenario), "hints read as key + action"


# -- filtering, sorting, wide columns ----------------------------------------------


def test_filter_narrows_rows_and_escape_clears_it():
    async def scenario(app, pilot):
        await pilot.press("enter")  # into devices
        await settle(app, pilot)
        await pilot.press("slash")
        await pilot.pause()
        for ch in "fabrikam":
            await pilot.press(ch)
        await pilot.pause()
        filtered = app.screen.model.row_count
        await pilot.press("enter")  # commit the filter
        await pilot.pause()
        await pilot.press("escape")  # first escape clears the filter
        await pilot.pause()
        return filtered, app.screen.model.row_count, app.screen.spec.kind

    filtered, after_clear, kind = drive(scenario)
    assert filtered == 2
    assert after_clear == 6
    assert kind == "device", "clearing a filter must not also pop the screen"


def test_wide_toggle_adds_columns():
    async def scenario(app, pilot):
        before = list(app.screen.model.headers)
        await pilot.press("ctrl+w")
        await pilot.pause()
        return before, list(app.screen.model.headers)

    before, after = drive(scenario)
    assert "IDENTITY" not in before
    assert "IDENTITY" in after


def test_refresh_keeps_the_screen_usable():
    async def scenario(app, pilot):
        await pilot.press("r")
        await settle(app, pilot)
        return app.screen.model.total_count

    assert drive(scenario) == 3


def test_main_page_shows_loading_animation_during_refresh():
    import threading

    from textual.containers import Vertical

    started = threading.Event()
    release = threading.Event()

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = app.screen
            original = screen.source

            def slow_source(scope, force=False):
                started.set()
                release.wait(timeout=5)
                return original(scope, force=force)

            screen.source = slow_source
            screen.refresh_rows(force=True)
            await asyncio.to_thread(started.wait, 2)
            await pilot.pause()
            table = screen.query_one("#rows", DataTable)
            pane = screen.query_one("#rows-pane", Vertical)
            first_frame = str(table.get_row_at(0)[0])
            await pilot.pause(0.25)
            second_frame = str(table.get_row_at(0)[0])
            during = (
                table.display,
                table.row_count,
                first_frame,
                second_frame,
                pane.border_title,
            )
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            return during, table.row_count

    during, rows_after = asyncio.run(runner())
    assert during[:2] == (
        True,
        4,
    ), "the loading row appears above three known resources"
    assert during[2] != during[3], "the loading row must animate"
    assert during[2].endswith("Loading resources...")
    assert during[3].endswith("Loading resources...")
    assert during[4] == "namespaces"
    assert rows_after == 3, "the temporary loading row is removed after refresh"


def test_browse_hint_bar_surfaces_both_onboarding_entries():
    async def scenario(app, pilot):
        hints = dict(app.screen.hint_bindings())
        return hints.get("n"), hints.get("w")

    assert drive(scenario) == ("New setup", "Connect selected")


# -- command bar and help -----------------------------------------------------------


def test_command_bar_resolves_an_alias():
    async def scenario(app, pilot):
        app._run_command("dev")
        await settle(app, pilot)
        return app.screen.spec.kind

    assert drive(scenario) == "device"


def test_command_bar_rejects_unknown_token_without_navigating():
    async def scenario(app, pilot):
        app._run_command("nonsense")
        await settle(app, pilot)
        return app.screen.spec.kind

    assert drive(scenario) == "namespace"


def test_help_screen_opens_and_closes():
    async def scenario(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        opened = isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await settle(app, pilot)
        return opened, isinstance(app.screen, BrowseScreen)

    opened, closed = drive(scenario)
    assert opened and closed


# -- resilience ---------------------------------------------------------------------


def test_source_failure_degrades_instead_of_crashing():
    """A failing lister must leave a usable screen, per the loading/failed state rules."""

    async def runner():
        registry = build_synthetic_registry()
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = app.screen

            def boom(_scope, force=False):
                raise RuntimeError("service unavailable")

            screen.source = boom
            screen.refresh_rows()
            await settle(app, pilot)
            return screen.model.state.value, screen.model.status_text()

    state, status = asyncio.run(runner())
    assert state == "stale", "rows already shown are retained"
    assert "service unavailable" in status


def test_detail_screen_defensively_redacts_credentials():
    detail = DetailScreen(
        None,
        {
            "name": "symmetric",
            "properties": {
                "primaryKey": "secret-one",
                "secondaryKey": "secret-two",
            },
        },
    )
    assert detail.payload["properties"] == {
        "primaryKey": "[REDACTED]",
        "secondaryKey": "[REDACTED]",
    }


def test_screen_renders_at_minimum_terminal_size():
    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(80, 24)) as pilot:
            await settle(app, pilot)
            return app.screen.model.total_count

    assert asyncio.run(runner()) == 3


def test_namespace_without_children_shows_empty_not_loading():
    """The empty-vs-loading distinction, exercised end to end through the UI."""

    async def scenario(app, pilot):
        table = app.screen.query_one("#rows", DataTable)
        table.move_cursor(row=2)  # 'retired-ns' has no devices by design
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        return app.screen.spec.kind, app.screen.model.state.value, app.screen.model.status_text()

    kind, state, status = drive(scenario)
    assert kind == "device"
    assert state == "empty", "an empty collection must not read as still loading"
    assert "No registry devices in the current scope" in status


def test_child_rows_are_scoped_to_the_selected_parent():
    """Different parents yield different children, proving scope is really applied."""

    async def scenario(app, pilot):
        table = app.screen.query_one("#rows", DataTable)
        table.move_cursor(row=1)  # 'lab-westus'
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        return app.screen.scope["namespace_name"], app.screen.model.total_count

    namespace, count = drive(scenario)
    assert namespace == "lab-westus"
    assert count == 3, "lab-westus has fewer devices than factory-eastus2"


def test_command_bar_jump_inherits_the_on_screen_scope():
    """Typing an alias deep in the tree must keep the namespace, not query with none."""

    async def scenario(app, pilot):
        await pilot.press("enter")  # namespaces -> devices, scope gains the namespace
        await settle(app, pilot)
        app._run_command("attr")    # jump sideways to another kind
        await settle(app, pilot)
        return app.screen.spec.kind, app.screen.scope.get("namespace_name")

    kind, namespace = drive(scenario)
    assert kind == "attribute"
    assert namespace == "factory-eastus2", "the alias jump kept the on-screen scope"


def test_child_hotkey_opens_that_child_directly():
    """Every declared child is reachable, not only the one Enter opens."""

    async def scenario(app, pilot):
        await pilot.press("enter")   # namespaces -> devices (primary child)
        await settle(app, pilot)
        await pilot.press("t")       # 't' is the attributes child key
        await settle(app, pilot)
        return app.screen.spec.kind

    assert drive(scenario) == "attribute"


def test_overlapping_refresh_is_dropped_not_queued():
    """Rule C2: a second refresh while one is in flight must not start another request."""

    async def scenario(app, pilot):
        screen = app.screen
        calls = []
        original = screen.source

        def counting(scope, force=False):
            calls.append(force)
            return original(scope, force=force)

        screen.source = counting
        screen._loading = True          # simulate a request already in flight
        screen.refresh_rows(force=True)
        await pilot.pause()
        return calls

    assert drive(scenario) == [], "no request is issued while one is already running"


def test_missing_scope_is_explained_without_calling_the_service():
    """A kind opened out of context must say what to open, not surface a service error."""

    async def runner():
        from azext_iot.adr.ui.core.spec import Column, Registry, ResourceSpec

        called = []

        def lister(scope):
            called.append(scope)
            return []

        registry = Registry()
        registry.register(
            ResourceSpec(
                kind="thing", title="Thing", title_plural="Things", aliases=("th",),
                row_id=lambda p: p["name"], list=lister,
                columns=(Column("name", "NAME", lambda p: p["name"]),),
                requires=("namespace_name",),
            )
        )
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            return app.screen.model.status_text(), called

    status, called = asyncio.run(runner())
    assert "Open a namespace first" in status
    assert called == [], "no request is issued when required scope is absent"


def test_missing_scope_message_does_not_name_the_implied_resource_group():
    """Opening a namespace implies its resource group; naming both reads as noise."""

    async def runner():
        from azext_iot.adr.ui.core.spec import Column, Registry, ResourceSpec

        registry = Registry()
        registry.register(
            ResourceSpec(
                kind="thing", title="Thing", title_plural="Things", aliases=("th",),
                row_id=lambda p: p["name"], list=lambda scope: [],
                columns=(Column("name", "NAME", lambda p: p["name"]),),
                requires=("namespace_name", "resource_group_name", "registry_device_name"),
            )
        )
        app = RadrApp(registry=registry)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            return app.screen.model.status_text()

    status = asyncio.run(runner())
    assert "a namespace and a device" in status
    assert "resource group" not in status


def test_auto_refresh_interval_is_configured():
    """Polling is what keeps a table current; the cache decides if a tick costs a request."""

    async def scenario(app, pilot):
        return app.screen.refresh_interval

    assert drive(scenario) >= 5, "an interval must be set, at or above the floor"


def test_scope_snapshot_comes_from_the_session():
    """Scope is owned by the session; the app must not keep a second copy that can drift."""
    from azext_iot.adr.ui.core.session import Session

    class Cmd:
        cli_ctx = object()

    session = Session(Cmd(), resource_group_name="rg", namespace_name="ns")
    session.scope.subscription_name = "Contoso"
    app = RadrApp(cmd=Cmd(), session=session, registry=build_synthetic_registry(),
                  resource_group_name="rg", namespace_name="ns")
    app._apply_resolved_scope()
    assert app.scope["subscription"] == "Contoso"
    assert app.scope["namespace_name"] == "ns"


def test_guided_setup_key_is_not_case_confusable():
    """'O' vs 'o' was indistinguishable in the hint bar and easy to mis-press."""
    keys = [binding.key for binding in RadrApp.BINDINGS]
    lowered = [key.lower() for key in keys]
    assert len(lowered) == len(set(lowered)), f"case-confusable bindings: {keys}"


def test_guided_setup_uses_the_highlighted_namespace_row():
    """Pressing the key on a namespace row must set that namespace up."""

    async def scenario(app, pilot):
        table = app.screen.query_one("#rows", DataTable)
        table.move_cursor(row=1)  # 'lab-westus'
        await pilot.pause()
        spec = app.screen.spec
        payload = app.screen.selected_payload()
        scope = dict(app._active_scope())
        scope.update(spec.child_scope(payload))
        return scope

    scope = drive(scenario)
    assert scope["namespace_name"] == "lab-westus"
    assert scope["resource_group_name"] == "adr-lab-rg"


def test_fresh_setup_starts_without_adopting_a_namespace():
    """':new' must not inherit the highlighted row, or a fresh start is unreachable."""
    from azext_iot.adr.ui.core.session import Session

    class Cmd:
        cli_ctx = object()

    async def runner():
        app = RadrApp(cmd=Cmd(), session=Session(Cmd()),
                      registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            app._run_command("new")
            await settle(app, pilot)
            screen = app.screen
            return type(screen).__name__, screen.context.get("namespace_name")

    name, namespace = asyncio.run(runner())
    assert name == "OnboardScreen"
    assert not namespace, "a fresh start must begin with no namespace"


def test_n_starts_fresh_setup_without_the_command_bar():
    """The headline workflow must not depend on discovering and typing ':new'."""
    from azext_iot.adr.ui.core.session import Session

    class Cmd:
        cli_ctx = object()

    async def runner():
        app = RadrApp(
            cmd=Cmd(),
            session=Session(Cmd()),
            registry=build_synthetic_registry(),
        )
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            await pilot.press("n")
            await settle(app, pilot)
            return type(app.screen).__name__, app.screen.context.get("namespace_name")

    assert asyncio.run(runner()) == ("OnboardScreen", None)


def test_ctrl_t_switches_between_daylight_and_night_themes():
    async def scenario(app, pilot):
        original_theme = app.theme
        original_tokens = dict(app.theme_tokens)
        await pilot.press("ctrl+t")
        await pilot.pause()
        daylight = app.theme
        daylight_tokens = dict(app.theme_tokens)
        await pilot.press("ctrl+t")
        await pilot.pause()
        return original_theme, daylight, app.theme, original_tokens, daylight_tokens

    night, daylight, restored, night_tokens, daylight_tokens = drive(scenario)
    assert night == "radr-night"
    assert daylight == "radr-daylight"
    assert restored == night
    assert daylight_tokens != night_tokens


def test_mounted_themes_expose_the_exact_css_roles():
    expected = {
        "dark": {
            "background": "#1C2128",
            "surface": "#22272E",
            "panel": "#373E47",
            "primary": "#78A9C8",
            "secondary": "#7294AE",
            "boost": "#343B44",
            "text": "#DADFE7",
            "text-muted": "#768390",
            "primary-darken-1": "#3B4655",
            "primary-background": "#F0F3F6",
            "secondary-background": "#2D333B",
            "foreground-lighten-1": "#E6EDF3",
            "success": "#8FAF8B",
            "warning": "#C7A56A",
            "error": "#C46F79",
        },
        "light": {
            "background": "#ECEFF4",
            "surface": "#F7F9FB",
            "panel": "#D6DCE5",
            "primary": "#5E81AC",
            "secondary": "#4C6E96",
            "boost": "#CBD5E1",
            "text": "#2E3440",
            "text-muted": "#7A869A",
            "primary-darken-1": "#5E81AC",
            "primary-background": "#ECEFF4",
            "secondary-background": "#D8DEE9",
            "foreground-lighten-1": "#2E3440",
            "success": "#5E7A45",
            "warning": "#96702A",
            "error": "#A6474F",
        },
    }

    async def inspect(mode):
        app = RadrApp(registry=build_synthetic_registry(), theme_name=mode)
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            variables = app.get_css_variables()
            return {key: variables[key] for key in expected[mode]}

    for mode in ("dark", "light"):
        assert asyncio.run(inspect(mode)) == expected[mode]


def test_theme_toggle_does_not_discard_high_contrast_mode():
    async def runner():
        app = RadrApp(
            registry=build_synthetic_registry(),
            theme_name="high-contrast",
        )
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            await pilot.press("ctrl+t")
            await pilot.pause()
            return app.theme, app._theme_name

    assert asyncio.run(runner()) == ("textual-ansi", "high-contrast")


def test_multi_hub_selection_keeps_the_cursor_on_the_same_row():
    """Selecting the sixth hub must not send the customer back to the first row."""
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {"type": "SystemAssigned"},
                "properties": {},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "hub"
            screen._candidates = [
                Candidate(name=f"hub-{index}", resource_id=f"id-{index}")
                for index in range(10)
            ]
            screen._candidates_for = "hub"
            screen.refresh_view()
            screen._paint_candidates()
            table = screen.query_one("#candidates", DataTable)
            table.move_cursor(row=5)
            await pilot.pause()
            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            return table.cursor_coordinate.row, screen.context["selected_hubs"][0].name

    assert asyncio.run(runner()) == (5, "hub-5")


def test_onboarding_j_opens_candidate_json_and_returns_in_place():
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {"type": "SystemAssigned"},
                "properties": {"provisioning": {"endpoints": {"dps": {}}}},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "hub"
            screen._candidates = [
                Candidate(
                    name="hub-one",
                    resource_id="/hubs/hub-one",
                    raw={"name": "hub-one", "properties": {"state": "ready"}},
                ),
                Candidate(
                    name="hub-two",
                    resource_id="/hubs/hub-two",
                    raw={"name": "hub-two", "properties": {"state": "failed"}},
                ),
            ]
            screen._candidates_for = "hub"
            screen.refresh_view()
            screen._paint_candidates()
            table = screen.query_one("#candidates", DataTable)
            table.move_cursor(row=1)
            table.focus()
            await pilot.press("j")
            await pilot.pause()
            detail = app.screen
            opened = (
                isinstance(detail, DetailScreen),
                detail.payload,
                detail.resource_name(),
                detail.breadcrumb(),
            )
            await pilot.press("escape")
            await pilot.pause()
            return opened, app.screen is screen, screen.active_step().id, table.cursor_coordinate.row

    opened, returned, step, row = asyncio.run(runner())
    assert opened == (
        True,
        {"name": "hub-two", "properties": {"state": "failed"}},
        "hub-two",
        "iot hub hub-two",
    )
    assert (returned, step, row) == (True, "hub", 1)


def test_namespace_picker_shows_resource_state_links_identity_and_tags():
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(150, 40)) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            raw = {
                "name": "factory",
                "resourceGroup": "rg",
                "location": "centraluseuap",
                "identity": {"type": "SystemAssigned"},
                "tags": {"environment": "dev"},
                "properties": {
                    "provisioningState": "Succeeded",
                    "provisioning": {"endpoints": {"dps": {}}},
                    "messaging": {"endpoints": {"hub-a": {}, "hub-b": {}}},
                    "updating": {"endpoints": {"updates": {}}},
                },
            }
            screen._focus_step = "namespace"
            screen._candidates = [
                Candidate(
                    name="factory",
                    resource_id="/namespaces/factory",
                    resource_group="rg",
                    location="centraluseuap",
                    identity="SystemAssigned",
                    raw=raw,
                )
            ]
            screen._candidates_for = "namespace"
            screen.refresh_view()
            screen._paint_candidates()
            table = screen.query_one("#candidates", DataTable)
            headers = [str(column.label) for column in table.columns.values()]
            row = [cell.plain if hasattr(cell, "plain") else str(cell)
                   for cell in table.get_row_at(0)]
            return headers, row

    headers, row = asyncio.run(runner())
    values = dict(zip(headers, row))
    assert values["NAME"] == "factory"
    assert values["REGION"] == "centraluseuap"
    assert values["STATE"] == "Succeeded"
    assert values["LINK READINESS"] == "ready"
    assert values["HUBS"] == "2"
    assert values["DPS"] == "1"
    assert values["UPDATES"] == "1"
    assert values["IDENTITY"] == "SystemAssigned"
    assert values["TAGS"] == "environment=dev"


def test_planned_namespace_can_be_reopened_and_edited():
    from textual.widgets import Button, Input

    from azext_iot.adr.ui.screens.onboard.create import CreateRequest
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            request = CreateRequest(
                kind="namespace",
                name="planned-ns",
                resource_group_name="rg",
                location="eastus2",
                tags={"environment": "dev"},
            )
            screen._accept_create("namespace", "create_namespace", request)
            screen._focus_step = "namespace"
            screen.refresh_view()
            screen.action_create_new()
            await pilot.pause()
            return (
                screen.query_one("#create-name", Input).value,
                screen.query_one("#create-location", Input).value,
                screen.query_one("#create-tags", Input).value,
                str(screen.query_one("#create-confirm", Button).label),
                len(screen.query("#create-rg")),
            )

    assert asyncio.run(runner()) == (
        "planned-ns",
        "eastus2",
        "environment=dev",
        "Update setup",
        0,
    )


def test_left_and_right_switch_between_setup_rail_and_details():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            candidates = screen.query_one("#candidates", DataTable)
            candidates.focus()
            await pilot.press("left")
            await pilot.pause()
            rail_focused = screen.query_one("#step-list").has_focus
            await pilot.press("right")
            await pilot.pause()
            return rail_focused, candidates.has_focus

    assert asyncio.run(runner()) == (True, True)


def test_left_arrow_still_edits_text_inside_the_create_form():
    from textual.widgets import Input

    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "namespace"
            screen.refresh_view()
            screen.action_create_new()
            await pilot.pause()
            field = screen.query_one("#create-name", Input)
            field.value = "factory"
            field.cursor_position = len(field.value)
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            return field.cursor_position, field.has_focus

    assert asyncio.run(runner()) == (6, True)


def test_tab_moves_through_real_hub_creation_fields():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {"type": "SystemAssigned"},
                "properties": {"provisioning": {"endpoints": {"dps": {}}}},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "hub"
            screen.refresh_view()
            screen.action_create_new()
            await pilot.pause()
            focused = [app.focused.id]
            for _ in range(4):
                await pilot.press("tab")
                await pilot.pause()
                focused.append(app.focused.id)
            return focused

    assert asyncio.run(runner()) == [
        "create-name",
        "create-location",
        "create-sku",
        "create-capacity",
        "create-cancel",
    ]


def test_up_and_down_move_through_creation_fields_and_actions():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {"type": "SystemAssigned"},
                "properties": {"provisioning": {"endpoints": {"dps": {}}}},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "hub"
            screen.refresh_view()
            screen.action_create_new()
            await pilot.pause()
            focused = [app.focused.id]
            for key in (
                "down",
                "down",
                "down",
                "down",
                "down",
                "down",
                "up",
            ):
                await pilot.press(key)
                await pilot.pause()
                focused.append(app.focused.id)
            return focused

    assert asyncio.run(runner()) == [
        "create-name",
        "create-location",
        "create-sku",
        "create-capacity",
        "create-cancel",
        "create-plan",
        "create-confirm",
        "create-plan",
    ]


def test_view_plan_action_works_while_editing_a_field():
    from textual.widgets import Input

    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen, PlanDialog

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "namespace"
            screen.refresh_view()
            screen.action_create_new()
            await pilot.pause()
            field = screen.query_one("#create-name", Input)
            field.value = "planned"
            plan = screen.query_one("#create-plan")
            plan.focus()
            await pilot.press("enter")
            await pilot.pause()
            opened = isinstance(app.screen, PlanDialog)
            await pilot.press("escape")
            await pilot.pause()
            return opened, app.screen is screen, field.value, app.focused.id

    assert asyncio.run(runner()) == (True, True, "planned", "create-plan")


def test_p_opens_the_plan_from_both_setup_panes():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen, PlanDialog

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            opened = []
            for selector in ("#candidates", "#step-list"):
                screen.query_one(selector).focus()
                await pilot.press("p")
                await pilot.pause()
                opened.append(isinstance(app.screen, PlanDialog))
                await pilot.press("escape")
                await pilot.pause()
            return opened

    assert asyncio.run(runner()) == [True, True]


def test_auto_advance_keeps_rail_highlight_and_detail_on_the_same_step():
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {
                    "type": "SystemAssigned",
                    "principalId": "pid-ns",
                },
                "properties": {},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen._focus_step = "dps"
            screen._candidates = [
                Candidate(
                    name="dps",
                    resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/dps/dps",
                    identity="SystemAssigned",
                    raw={"identity": {"principalId": "pid-dps"}},
                )
            ]
            screen._candidates_for = "dps"
            screen.refresh_view()
            screen._paint_candidates()
            screen.query_one("#candidates", DataTable).focus()
            work_region = screen.query_one("#work-pane").region
            await pilot.press("enter")
            await pilot.pause()
            identity_region = app.screen.query_one("#identity-dialog").region
            assert identity_region == work_region
            # Selecting a resource asks for its caller identity; SAMI is the default.
            await pilot.press("enter")
            await pilot.pause()
            active = screen.active_step()
            rail = screen.query_one("#step-list")
            heading = screen.query_one("#step-heading").render()
            heading_text = heading.plain if hasattr(heading, "plain") else str(heading)
            return active.id, rail.index, heading_text

    step_id, rail_index, heading = asyncio.run(runner())
    assert (step_id, rail_index) == ("hub", 4)
    assert "Link Hub" in heading


def test_arrow_navigation_keeps_rail_index_and_detail_heading_together():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            rail = screen.query_one("#step-list")
            rail.focus()
            before = rail.index
            await pilot.press("down")
            await pilot.pause()
            heading = screen.query_one("#step-heading").render()
            text = heading.plain if hasattr(heading, "plain") else str(heading)
            item = rail.children[rail.index]
            title_widget = item.query_one(".step-title")
            return (
                before,
                rail.index,
                screen.active_step().title,
                text,
                str(title_widget.styles.background),
                str(screen.query_one("#step-heading").styles.background),
            )

    before, after, title, heading, rail_background, detail_background = asyncio.run(
        runner()
    )
    assert after == before + 1
    assert title in heading
    assert rail_background == detail_background
    assert "a=0" not in rail_background, "the selected step title needs a visible fill"


def test_number_navigation_highlights_the_step_without_focusing_the_rail():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry(), theme_name="dark")
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(
                None,
                {"subscription_id": "sub-1", "resource_group_name": "rg"},
            )
            await app.push_screen(screen)
            await pilot.pause()
            screen.query_one("#work-pane").focus()
            await pilot.press("5")
            await pilot.pause()
            rail = screen.query_one("#step-list")
            selected = rail.children[4]
            title = selected.query_one(".step-title")
            return (
                screen.active_step().id,
                rail.index,
                selected.has_class("selected-step"),
                str(title.styles.background),
                str(screen.query_one("#step-heading").styles.background),
                rail.has_focus,
            )

    step, index, selected, left_bg, right_bg, rail_focused = asyncio.run(runner())
    assert (step, index, selected) == ("hub", 4, True)
    assert left_bg == right_bg
    assert not rail_focused


def test_candidate_loading_hides_the_previous_table_and_shows_progress():
    import threading

    from textual.widgets import LoadingIndicator

    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    started = threading.Event()
    release = threading.Event()

    class SlowCatalog:
        errors = {}

        def subscriptions(self):
            started.set()
            release.wait(timeout=5)
            return [{"name": "Contoso", "id": "sub-1"}]

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(None, {}, catalog=SlowCatalog())
            await app.push_screen(screen)
            await asyncio.to_thread(started.wait, 2)
            await pilot.pause()
            loading = screen.query_one("#candidate-loading", LoadingIndicator)
            table = screen.query_one("#candidates", DataTable)
            status = screen.query_one("#candidate-status")
            rendered = status.render()
            message = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            during = (loading.display, table.display, message)
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            return during, loading.display, table.display

    during, loading_after, table_after = asyncio.run(runner())
    assert during[0:2] == (True, False)
    assert "Loading subscriptions from Azure" in during[2]
    assert (loading_after, table_after) == (False, True)


def test_slow_old_candidate_load_cannot_overwrite_the_new_step():
    import threading

    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    subscriptions_started = threading.Event()
    release_subscriptions = threading.Event()
    resource_groups_loaded = threading.Event()

    class RacingCatalog:
        errors = {}

        def subscriptions(self):
            subscriptions_started.set()
            release_subscriptions.wait(timeout=5)
            return [{"name": "Old subscription", "id": "old-sub"}]

        def resource_groups(self):
            resource_groups_loaded.set()
            return [{
                "name": "current-rg",
                "id": "/subscriptions/sub-1/resourceGroups/current-rg",
                "location": "eastus2",
            }]

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(None, {}, catalog=RacingCatalog())
            await app.push_screen(screen)
            await asyncio.to_thread(subscriptions_started.wait, 2)
            screen.context["subscription_id"] = "sub-1"
            screen._focus_step = "scope"
            screen.refresh_view()
            screen._reload_candidates()
            # Let the newer resource-group load finish first.
            await asyncio.to_thread(resource_groups_loaded.wait, 2)
            await pilot.pause()
            for _ in range(20):
                if [candidate.name for candidate in screen._candidates] == ["current-rg"]:
                    break
                await pilot.pause()
            before = [candidate.name for candidate in screen._candidates]
            release_subscriptions.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            after = [candidate.name for candidate in screen._candidates]
            return before, after, screen._candidates_for

    before, after, step_id = asyncio.run(runner())
    assert before == after == ["current-rg"]
    assert step_id == "scope"


def test_onboarding_context_bar_tracks_the_selected_scope():
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            screen = OnboardScreen(None, {"subscription_id": "sub-1"})
            await app.push_screen(screen)
            await pilot.pause()
            screen.context.update({
                "subscription_name": "Contoso",
                "resource_group_name": "rg-one",
                "namespace_name": "factory",
            })
            screen.refresh_view()
            await pilot.pause()
            return screen.query_one("#context-bar").text

    text = asyncio.run(runner())
    assert "Contoso" in text and "rg-one" in text and "factory" in text


def test_review_does_not_run_links_before_manual_role_grants():
    from azext_iot.adr.ui.screens.onboard.pickers import Candidate
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=SIZE) as pilot:
            await settle(app, pilot)
            namespace = {
                "name": "factory",
                "identity": {
                    "type": "SystemAssigned",
                    "principalId": "pid-ns",
                },
                "properties": {},
            }
            screen = OnboardScreen(
                None,
                {
                    "subscription_id": "sub-1",
                    "resource_group_name": "rg",
                    "namespace_name": "factory",
                },
                namespace=namespace,
            )
            await app.push_screen(screen)
            await pilot.pause()
            dps = Candidate(
                name="dps",
                resource_id="/subscriptions/sub-1/resourceGroups/rg/providers/dps/dps",
                identity="SystemAssigned",
                raw={
                    "identity": {
                        "type": "SystemAssigned",
                        "principalId": "pid-dps",
                    }
                },
            )
            hub = Candidate(
                name="hub",
                resource_id=(
                    "/subscriptions/sub-1/resourceGroups/rg/providers/"
                    "Microsoft.Devices/IotHubs/hub"
                ),
                identity="SystemAssigned",
                raw={
                    "identity": {
                        "type": "SystemAssigned",
                        "principalId": "pid-hub",
                    }
                },
            )
            screen.context["selected_dps"] = dps
            screen.context["selected_hubs"] = [hub]
            set_choice(screen.context, "dps", system_choice(), dps.resource_id)
            set_choice(screen.context, "hub", system_choice(), hub.resource_id)
            screen.context["can_grant_roles"] = False
            screen.action_apply()
            await pilot.pause()
            return screen.query_one("#flash-line").text, type(app.screen).__name__

    message, screen_name = asyncio.run(runner())
    assert "role grants need administrator access" in message
    assert screen_name == "OnboardScreen", "no confirmation dialog should open"


# -- page guide ----------------------------------------------------------------------


def test_the_page_guide_is_shown_on_arrival():
    """A customer who has never seen this page should not have to ask for the guide."""
    def scenario(app, pilot):
        guide = app.screen.query_one("#page-guide")
        assert guide.display
        assert "VIEW" in guide.text
        return None

    async def wrapped(app, pilot):
        return scenario(app, pilot)

    drive(wrapped)


def test_the_guide_can_be_dismissed_and_restored():
    async def scenario(app, pilot):
        guide = app.screen.query_one("#page-guide")
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert not guide.display, "ctrl+g should hide the guide"
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert guide.display, "ctrl+g should bring it back"

    drive(scenario)


def test_dismissing_the_guide_sticks_when_drilling_in():
    """Re-showing it on every page would make dismissing it pointless."""
    async def scenario(app, pilot):
        await pilot.press("ctrl+g")
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert not app.screen.query_one("#page-guide").display

    drive(scenario)


def test_the_guide_describes_the_kind_being_viewed():
    """Guides come from the spec, so drilling in must change what is explained."""
    async def scenario(app, pilot):
        first = app.screen.query_one("#page-guide").text
        await pilot.press("enter")
        await settle(app, pilot)
        second = app.screen.query_one("#page-guide").text
        assert first and second and first != second

    drive(scenario)
