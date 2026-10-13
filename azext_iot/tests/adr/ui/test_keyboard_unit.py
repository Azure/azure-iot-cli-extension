# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Every workflow completes with the standard keys only: Tab/Shift+Tab, arrows, Enter, Space, Esc,
plus typing into fields. Letter accelerators are optional and never the only way in."""

from unittest.mock import Mock, patch

from textual.widgets import Button, DataTable, Input, OptionList

from azext_iot.adr.ui.core.actions import Field
from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.spec import Action, ChildRef, Column, Registry
from azext_iot.adr.ui.theme import DARK_THEME, HIGH_CONTRAST_THEME
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, HelpScreen
from azext_iot.adr.ui.widgets.actions import ActionForm, ActionMenu, QuitDialog, ReviewDialog
from azext_iot.adr.ui.widgets.minimal import Clickable, KeysLine
from azext_iot.adr.ui.widgets.scope import GROUP, SUBSCRIPTION, ScopeDialog
from azext_iot.adr.ui.widgets.tray import OperationsScreen
from azext_iot.tests.adr.ui.conftest import widget_spec
from azext_iot.tests.adr.ui.test_app_coverage_unit import settle
from azext_iot.tests.adr.ui.test_navigation_unit import (
    SUB_A, SUB_B, counted_catalog, highlighted, nav_app, option_ids, row_names, rows_for, run, text_of,
)
from azext_iot.adr.ui.widgets.chrome import FlashLine

#: Keys the visible key lines may teach: the standard set plus go-to, quit and help.
STANDARD = {"Tab", "\u2191\u2193", "Enter", "Esc", ":", "q", "?"}
#: Click targets that are deliberately not Tab stops, each with a standard-key equivalent.
NOT_TAB_STOPS = {
    "search-mark": "the search field itself is a Tab stop (Shift+Tab from the table)",
    "title-line": "plain text, no action",
    "tab-group": "Tab switches the picker list",
    "tab-subscription": "Tab switches the picker list",
    "scope-status": "the last list row reloads (\u2191 from the first row), retries after a failure",
}


async def tab_to(app, pilot, widget_id, key="tab", limit=16):
    """Press Tab (or Shift+Tab) until ``widget_id`` has focus; returns how many presses it took."""
    for count in range(limit):
        if app.focused is not None and app.focused.id == widget_id:
            return count
        await pilot.press(key)
        await pilot.pause()
    raise AssertionError(f"{widget_id} is not reachable with {key}; focus={app.focused!r}")


async def choose_in_go_to(app, pilot, option_id):
    """Tab to the prompt, Enter, arrows down to ``option_id``, Enter: no letters, no typing."""
    await tab_to(app, pilot, "resource-selector", key="shift+tab")
    await pilot.press("enter")
    await pilot.pause()
    bar = app.screen
    assert isinstance(bar, CommandBar), bar
    for _ in range(len(option_ids(bar)) + 1):
        if highlighted(bar) == option_id:
            break
        await pilot.press("down")
    await pilot.press("enter")
    await pilot.pause()


def audit_click_targets(screen):
    """Every clickable thing on a screen is a Tab stop or has a documented standard-key equivalent."""
    for widget in screen.query(Clickable):
        if widget.action and widget.display:
            assert widget.can_focus or widget.id in NOT_TAB_STOPS, f"{widget.id} is mouse-only"
    for widget in screen.query("Button, OptionList, DataTable, Input"):
        assert widget.can_focus, f"{widget!r} cannot take focus"
    for line in screen.query(KeysLine):
        for key in line.keys:
            assert key.key in STANDARD, f"key line teaches a special key: {key.key} {key.label}"


def crud_actions():
    update = Action("update", "Update", invoke=Mock(), command="iot adr ns device update",
                    fields=(Field("display_name", "--display-name", "Display name"),))
    delete = Action("delete", "Delete", invoke=Mock(), destructive=True, command="iot adr ns device delete")
    create = Action("create", "Create", invoke=Mock(), collection=True, command="iot adr ns device create",
                    fields=(Field("name", "-n", "Name"),))
    return update, delete, create


def test_scope_selection_with_tab_enter_space_arrows_and_typing_only():
    async def scenario(app, pilot):
        root = app.screen
        assert app.focused is root.query_one("#rows", DataTable), "the table starts with focus"
        assert await tab_to(app, pilot, "group-selector") <= 3, "header controls are the first Tab stops"
        await pilot.press("enter")
        await settle(app, pilot)
        picker = app.screen
        assert isinstance(picker, ScopeDialog) and picker.mode == GROUP
        audit_click_targets(picker)
        await pilot.press(*"edg", "enter")
        await settle(app, pilot)
        assert app.scope["resource_group_name"] == "rg-edge" and app.scope["subscription_id"] == SUB_A
        await tab_to(app, pilot, "subscription-selector")
        await pilot.press("space")
        await settle(app, pilot)
        picker = app.screen
        assert isinstance(picker, ScopeDialog) and picker.mode == SUBSCRIPTION, "Space presses a control too"
        await pilot.press("down", "enter")
        await settle(app, pilot)
        assert picker.mode == GROUP and option_ids(picker) == ["all", "retry"]
        await pilot.press(*"rg-prod", "enter")
        await settle(app, pilot)
        assert app.scope["subscription_id"] == SUB_B and app.scope["resource_group_name"] == "rg-prod"
        # Esc dismisses the picker without changing anything.
        await tab_to(app, pilot, "group-selector", key="shift+tab")
        await pilot.press("enter")
        await settle(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, BrowseScreen) and app.scope["subscription_id"] == SUB_B

    run(nav_app(), scenario)


def test_search_detail_crud_destructive_review_operations_and_exit_with_standard_keys():
    update, delete, create = crud_actions()

    async def scenario(app, pilot):
        root = app.screen
        audit_click_targets(root)
        # Search: Shift+Tab from the table reaches the field; typing narrows; Enter keeps it.
        await pilot.press("shift+tab")
        assert app.focused is root.query_one("#filter-input", Input)
        await pilot.press(*"camera", "enter")
        await pilot.pause()
        assert app.focused is root.query_one("#rows") and root.selected_payload()["name"] == "a-rg-dev-camera"
        # Details start on their first control; Enter opens the actions for that row.
        await pilot.press("enter")
        await settle(app, pilot)
        detail = app.screen
        assert isinstance(detail, DetailScreen) and detail.payload["name"] == "a-rg-dev-camera"
        audit_click_targets(detail)
        assert app.focused is detail.query_one("#actions-control")
        await pilot.press("enter")
        await pilot.pause()
        menu = app.screen
        assert isinstance(menu, ActionMenu) and [a.name for a in menu._actions] == ["update", "delete", "create"]
        audit_click_targets(menu)
        await pilot.press("enter")
        await pilot.pause()
        form = app.screen
        assert isinstance(form, ActionForm) and app.focused is form.query_one("#field-display_name")
        audit_click_targets(form)
        await pilot.press(*"Lobby cam", "enter")
        await pilot.pause()
        review = app.screen
        assert isinstance(review, ReviewDialog) and review.target_name == "a-rg-dev-camera"
        assert app.focused is review.query_one("#confirm", Button), "Review is the focused button"
        audit_click_targets(review)
        await pilot.press("enter")
        await settle(app, pilot)
        assert update.invoke.call_args.args[2]["name"] == "a-rg-dev-camera"
        assert app.screen is detail and app.focused is detail.query_one("#actions-control")
        # Destructive: arrows to Delete; Enter only approves once the exact name is typed.
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        review = app.screen
        assert review.action.name == "delete" and app.focused is review.query_one("#confirm-name", Input)
        error = review.query_one("#confirm-error")
        assert not error.display
        await pilot.press(*"a-rg-dev", "enter")
        await pilot.pause()
        assert app.screen is review and delete.invoke.call_count == 0
        assert error.display and str(error.render()) == "Name does not match; nothing was sent.", "never approves"
        assert app.focused is review.query_one("#confirm-name", Input), "focus stays for correcting"
        await pilot.press("-")
        assert not error.display, "editing clears the message"
        await pilot.press("backspace", *"-camera", "enter")
        await settle(app, pilot)
        assert delete.invoke.call_args.args[2]["name"] == "a-rg-dev-camera"
        # Operations through the header control, dismissed with its own control.
        await tab_to(app, pilot, "operations", key="shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        ops = app.screen
        assert isinstance(ops, OperationsScreen) and len(ops._operations) == 2
        audit_click_targets(ops)
        assert not ops.query_one("#ops-stop").display, "nothing to stop watching"
        assert app.focused is ops.query_one("#ops-reread"), "pages start on their first control, not the header"
        await pilot.press("up")
        await tab_to(app, pilot, "ops-dismiss")
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is detail and not app.tracker.operations
        # Back to the list, a collection action from the title-row control, then Esc cancels.
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root
        await tab_to(app, pilot, "actions-control", key="shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert isinstance(app.screen, ActionForm) and app.screen.action.name == "create"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root
        # Exit stays one visible key away.
        assert "q quit" in str(root.query_one("#keys-line", KeysLine).render())
        with patch.object(app, "exit") as leave:
            await pilot.press("escape", "q")
            await pilot.pause()
        leave.assert_called_once()

    run(nav_app(actions=(update, delete, create)), scenario)


def test_go_to_help_children_and_quit_dialog_are_reachable_without_letters():
    children = (ChildRef("gadget", "Gadgets", "g"),)

    async def scenario(app, pilot):
        root = app.screen
        # Go to: the prompt is the first Tab stop.
        assert await tab_to(app, pilot, "resource-selector") == 1
        await pilot.press("enter")
        await pilot.pause()
        bar = app.screen
        assert isinstance(bar, CommandBar)
        audit_click_targets(bar)
        await pilot.press("escape")
        await pilot.pause()
        # Child lists: open the row, Tab to its child control, Enter.
        await tab_to(app, pilot, "rows")
        await pilot.press("enter")
        await settle(app, pilot)
        detail = app.screen
        await tab_to(app, pilot, "child-gadget")
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen.spec.kind == "gadget"
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert app.screen is root and detail not in app.screen_stack
        # Raw JSON toggles from its own control with Space.
        await pilot.press("enter")
        await settle(app, pilot)
        detail = app.screen
        await tab_to(app, pilot, "json-control")
        await pilot.press("space")
        await pilot.pause()
        assert detail.show_json and str(detail.query_one("#json-control").render()) == "Fields"
        await pilot.press("escape")
        await pilot.pause()
        # Help through the prompt's list: Tab, Enter, arrows to "Help and shortcuts", Enter; Esc closes.
        await choose_in_go_to(app, pilot, "cmd:help")
        assert isinstance(app.screen, HelpScreen)
        audit_click_targets(app.screen)
        await pilot.press("escape")
        await pilot.pause()
        # Quit with a running operation: the dialog starts on the safe choice, so Enter keeps watching.
        app.tracker.start("Pending", "two")
        await choose_in_go_to(app, pilot, "cmd:quit")
        dialog = app.screen
        assert isinstance(dialog, QuitDialog)
        audit_click_targets(dialog)
        assert app.focused is dialog.query_one("#cancel"), "Keep watching is the default"
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen is root
        # Leaving takes one deliberate extra step: Tab to Quit anyway, Enter.
        with patch.object(app, "exit") as leave:
            await choose_in_go_to(app, pilot, "cmd:quit")
            await pilot.press("tab")
            assert app.focused is app.screen.query_one("#quit-anyway")
            await pilot.press("enter")
            await pilot.pause()
        leave.assert_called_once()

    app = nav_app(children=children)
    app.registry.register(widget_spec(kind="gadget", children=(), aliases=("gd",), parent="widget", list=rows_for))
    run(app, scenario)


def test_key_lines_teach_only_standard_keys_and_text_fields_keep_their_letters():
    update, delete, create = crud_actions()

    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("slash", *"qao@:ys")
        await pilot.pause()
        assert root.query_one("#filter-input", Input).value == "qao@:ys", "no shortcut fires while typing"
        assert isinstance(app.screen, BrowseScreen)
        await pilot.press("escape")
        app.tracker.start("Pending", "two")
        await pilot.press("o")
        await pilot.pause()
        ops = app.screen
        audit_click_targets(ops)
        assert ops.query_one("#ops-stop").display and ops.query_one("#ops-reread").display
        assert not ops.query_one("#ops-dismiss").display, "nothing finished yet"
        assert app.focused is ops.query_one("#ops-reread")
        await pilot.press("tab")
        assert app.focused is ops.query_one("#ops-stop"), "Tab skips the hidden dismiss control"
        await pilot.press("o")
        await pilot.pause()
        assert app.screen is root, "o toggles; Esc is the visible way back"

    run(nav_app(actions=(update, delete, create)), scenario)


def test_view_settings_are_in_the_go_to_list_only_where_they_change_something():
    async def scenario(app, pilot):
        root = app.screen
        await tab_to(app, pilot, "resource-selector")
        await pilot.press("enter")
        await pilot.pause()
        bar = app.screen
        assert str(bar.query_one(".dialog-title").render()) == "Go to", "not a kind's title"
        options = bar.query_one(OptionList)
        ids = option_ids(bar)
        assert [i for i in ids if i.startswith("cmd:")] == [
            "cmd:help", "cmd:refresh", "cmd:sort", "cmd:wide", "cmd:theme", "cmd:quit"]
        assert ids[ids.index("cmd:help") - 1] == "None", "a dim 'radar' heading separates them from kinds"
        faces = [str(options.get_option(i).prompt).strip(" \u258e") for i in ids if i.startswith("cmd:")]
        assert faces == ["Help and shortcuts", "Refresh now", "Sort by\u2026", "Show all columns", "Dark theme",
                         "Quit radar"], "plain labels"
        # Typing filters commands by their label; an exact kind alias still wins.
        await pilot.press(*"columns", "enter")
        await pilot.pause()
        assert app.screen is root and root.model.show_wide
        assert "MODEL" in [str(column.label) for column in root.query_one("#rows", DataTable).columns.values()]
        await choose_in_go_to(app, pilot, "cmd:wide")
        assert not root.model.show_wide
        await choose_in_go_to(app, pilot, "cmd:theme")
        assert app._theme_name == DARK_THEME
        await tab_to(app, pilot, "resource-selector", key="shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        assert "Light theme" in str(app.screen.query_one(OptionList).get_option("cmd:theme").prompt)
        await pilot.press("escape")
        await pilot.pause()
        # Details have no columns to widen, so the setting is not offered there.
        await tab_to(app, pilot, "rows")
        await pilot.press("enter")
        await settle(app, pilot)
        await tab_to(app, pilot, "resource-selector", key="shift+tab")
        await pilot.press("enter")
        await pilot.pause()
        assert "cmd:wide" not in option_ids(app.screen) and "cmd:help" in option_ids(app.screen)

    run(nav_app(), scenario)


def test_high_contrast_and_narrow_kinds_do_not_offer_settings_that_do_nothing():
    async def scenario(app, pilot):
        app.action_command_bar()
        await pilot.pause()
        assert [entry for entry in option_ids(app.screen) if entry.startswith("cmd:")] == [
            "cmd:help", "cmd:refresh", "cmd:sort", "cmd:quit"]

    registry = Registry()
    registry.register(widget_spec(columns=(Column("name", "NAME", lambda p: p["name"]),), list=rows_for))
    app = RadrApp(registry=registry, resource_group_name="rg-dev", theme_name=HIGH_CONTRAST_THEME,
                  refresh_interval=900, catalog=counted_catalog())
    app.scope.update(subscription="Contoso Dev", subscription_id=SUB_A)
    run(app, scenario)


def test_every_displayed_column_sorts_from_go_to_with_arrows_and_enter():
    async def scenario(app, pilot):
        root = app.screen
        assert root.model.sort_key == "name" and row_names(root)[0] == "a-rg-dev-camera"
        await choose_in_go_to(app, pilot, "cmd:sort")
        menu = app.screen
        assert isinstance(menu, CommandBar) and str(menu.query_one(".dialog-title").render()) == "Sort by"
        assert option_ids(menu) == ["cmd:sort:name", "cmd:sort:state", "cmd:sort:count"], "displayed columns"
        faces = [str(menu.query_one(OptionList).get_option(i).prompt).strip(" \u258e") for i in option_ids(menu)]
        assert faces == ["Name, reverse order", "State", "Count"], "the current column says it reverses"
        assert "Enter sort" in str(menu.query_one(KeysLine).render()).replace("\u00a0", " ")
        audit_click_targets(menu)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.screen is root and root.model.sort_key == "state" and not root.model.sort_descending
        assert row_names(root) == ["a-rg-dev-camera", "a-rg-dev-gateway", "a-rg-dev-sensor"], "Failed first"
        # Choosing the current column again reverses it; ``s`` is an optional way to the same list.
        await tab_to(app, pilot, "rows")
        await pilot.press("s")
        await pilot.pause()
        assert option_ids(app.screen)[1] == "cmd:sort:state"
        assert "State, reverse order" in str(app.screen.query_one(OptionList).get_option("cmd:sort:state").prompt)
        await pilot.press("down", "enter")
        await pilot.pause()
        assert root.model.sort_key == "state" and root.model.sort_descending
        assert row_names(root)[-1] == "a-rg-dev-camera"
        await choose_in_go_to(app, pilot, "cmd:sort")
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert root.model.sort_key == "count"
        # Arrows still move between rows afterwards; the table keeps a row cursor.
        await tab_to(app, pilot, "rows")
        table = root.query_one("#rows", DataTable)
        assert root.selected_row_id() == "a-rg-dev-camera" == row_names(root)[-1], "selection follows the row"
        await pilot.press("up")
        assert table.cursor_type == "row" and root.selected_row_id() == row_names(root)[-2]
        # Esc closes the list without sorting.
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root and root.model.sort_key == "count"

    run(nav_app(), scenario)


def test_picker_invalid_name_says_why_keeps_the_text_and_reload_is_a_row():
    async def scenario(app, pilot):
        await tab_to(app, pilot, "group-selector")
        await pilot.press("enter")
        await settle(app, pilot)
        picker = app.screen
        field = picker.query_one("#scope-input", Input)
        assert option_ids(picker)[-1] == "reload"
        # The reload row: up from the first row wraps to it; Enter relists and keeps the picker open.
        calls = len(app.catalog.group_calls)
        await pilot.press("up", "up")
        assert highlighted(picker) == "reload"
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is picker and len(app.catalog.group_calls) == calls + 1
        assert app.scope["resource_group_name"] == "rg-dev"
        # An invalid typed name: no rows, an explicit reason, Enter changes nothing, the text stays.
        await pilot.press(*"has space")
        await pilot.pause()
        assert option_ids(picker) == []
        reason = "Not a valid name: use letters, digits, - _ . ( )"
        assert text_of(picker, "#scope-status") == reason
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is picker and app.focused is field and field.value == "has space"
        assert text_of(picker, "#scope-status") == reason and app.scope["resource_group_name"] == "rg-dev"
        # Correcting it offers the typed name (manual fallback), chosen with Enter.
        await pilot.press(*["backspace"] * 6, *"-group")
        await pilot.pause()
        assert option_ids(picker) == ["use:has-group"]
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.scope["resource_group_name"] == "has-group" and app.scope["subscription_id"] == SUB_A

    run(nav_app(), scenario)


def test_picker_invalid_name_with_a_failed_listing_still_says_why():
    def failing(_sub):
        raise RuntimeError("socket closed")

    async def scenario(app, pilot):
        await pilot.press("at")
        await settle(app, pilot)
        picker = app.screen
        assert option_ids(picker) == ["all", "retry"]
        await pilot.press(*"bad name")
        await pilot.pause()
        assert text_of(picker, "#scope-status").startswith("Not a valid name")
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is picker and app.scope["resource_group_name"] == "rg-dev"

    run(nav_app(catalog=counted_catalog(groups=failing)), scenario)


def test_root_escape_points_at_the_standard_key_way_out_and_it_works():
    async def scenario(app, pilot):
        root = app.screen
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is root
        assert root.query_one(FlashLine).text == (
            "This is the first page. To leave: \u276f radar (Tab, Enter), Quit radar.")
        with patch.object(app, "exit") as leave:
            await choose_in_go_to(app, pilot, "cmd:quit")
            await pilot.pause()
        leave.assert_called_once()

    run(nav_app(), scenario)
