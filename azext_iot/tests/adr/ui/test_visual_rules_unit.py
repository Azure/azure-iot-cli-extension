# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Presentation rules of the minimal radar: metadata-driven columns and labels, the switcher's
"more kinds" grouping, dialog key lines, the operations gutter, and defensive paint paths."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from rich.text import Text
from textual.widgets import DataTable, Input, OptionList, Static
from textual.widgets.data_table import RowDoesNotExist

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core import diagnostics
from azext_iot.adr.ui.core.ops import OperationTracker
from azext_iot.adr.ui.core.spec import Action, ChildRef, Column, Guide, Registry
from azext_iot.adr.ui.core.table import Diff, LoadState, TableModel
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.kinds.certificate import _ca_type_label
from azext_iot.adr.ui.kinds.link import _type_label
from azext_iot.adr.ui.screens.base import BACK, QUIT, ChromeScreen
from azext_iot.adr.ui.screens.browse import BrowseScreen
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar, switcher_entries
from azext_iot.adr.ui.theme import APP_CSS, FRAME_WIDTH, HIGH_CONTRAST_THEME, resolve_palette
from azext_iot.adr.ui.widgets.actions import ActionMenu, ReviewDialog, scope_context
from azext_iot.adr.ui.widgets.minimal import Key, KeysLine, dialog_keys, fit_dialog_list, palette_of
from azext_iot.adr.ui.widgets.tray import OperationRow, OperationsScreen
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


def _run(app, scenario, size=(80, 24)):
    async def runner():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(runner())


def _radar(*specs, read_only=False):
    registry = Registry()
    for spec in specs:
        registry.register(spec)
    app = RadrApp(registry=registry, resource_group_name="rg", read_only=read_only, refresh_interval=900)
    app.scope["subscription_id"] = "sub"
    return app


def _headers(screen):
    return [str(column.label).strip() for column in screen.query_one("#rows", DataTable).columns.values()]


# -- metadata: labels and columns ------------------------------------------------------------


def test_display_labels_are_concise_and_display_only():
    assert ChildRef("link", "Linked resources", "l", short="links").display_label == "links"
    assert ChildRef("device", "Devices", "d").display_label == "devices"
    assert _type_label({"endpointType": "Microsoft.Devices/IotHubs"}) == "hub"
    assert _type_label({"endpointType": "Microsoft.Devices/provisioningServices"}) == "dps"
    namespace = build_registry(Mock()).get("namespace")
    assert [child.display_label for child in namespace.children] == [
        "links", "devices", "groups", "jobs", "certificates",
    ]


def test_primary_tables_match_the_reference_columns():
    registry = build_registry(Mock())

    def primary(kind):
        return [column.label for column in registry.get(kind).visible_columns(False) if not column.disambiguates]

    assert primary("namespace") == ["NAME", "STATUS", "LOCATION"]
    assert primary("link") == ["NAME", "TYPE", "STATUS"]
    assert primary("ca")[:3] == ["NAME", "STATUS", "TYPE"]
    assert all(column.wide for column in registry.get("link").columns if column.key in ("target", "identity"))


def test_distinguishes_only_when_same_named_rows_differ():
    spec = widget_spec(row_id=lambda p: f"{p['rg']}/{p['name']}",
                       columns=(Column("name", "NAME", lambda p: p["name"]),
                                Column("rg", "RESOURCE GROUP", lambda p: p["rg"], disambiguates=True)))
    model = TableModel(spec)
    model.apply([{"name": "a", "rg": "x"}, {"name": "b", "rg": "y"}])
    assert not model.distinguishes(1), "different resource groups alone do not need the column"
    model.apply([{"name": "a", "rg": "x"}, {"name": "a", "rg": "y"}])
    assert model.distinguishes(1)


def test_disambiguating_column_appears_only_for_name_collisions_or_in_wide_mode():
    rows = [{"name": "a", "rg": "rg-1", "properties": {}}, {"name": "a", "rg": "rg-1", "properties": {}}]
    spec = widget_spec(children=(), list=lambda _scope: [dict(row) for row in rows],
                       row_id=lambda p: f"{p['rg']}/{p['name']}", columns=(
        Column("name", "NAME", lambda p: p["name"]),
        Column("rg", "RESOURCE GROUP", lambda p: p["rg"], disambiguates=True),
    ))

    async def scenario(app, pilot):
        screen = app.screen
        assert _headers(screen)[1:] == ["NAME"]
        rows[1]["rg"] = "rg-2"
        screen.refresh_rows(force=True)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "RESOURCE GROUP" in _headers(screen)
        rows[1]["rg"] = "rg-1"
        screen.refresh_rows(force=True)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "RESOURCE GROUP" not in _headers(screen)
        screen.action_toggle_wide()
        await pilot.pause()
        assert "RESOURCE GROUP" in _headers(screen)

    _run(_radar(spec), scenario)


# -- switcher ----------------------------------------------------------------------------------


def test_switcher_entries_lead_with_roots_and_their_children_from_registry_metadata():
    entries = switcher_entries(build_registry(Mock()).all())
    assert [kind for kind, *_rest in entries if not _rest[-1]] == ["namespace", "link", "device", "group", "job", "ca"]
    assert all(entry[3] for entry in entries[6:])
    assert "namespace" not in [entry[0] for entry in entries[6:]]


def _switcher(result):
    entries = [("a", "a", "alphas", False), "plain", ("t", "t", "threes"),
               ("b", "b", "betas", True), ("c", "c", "gammas", True)]
    bar = CommandBar(entries, current="t")

    async def push(app, pilot):
        app.push_screen(bar, result.append)
        await pilot.pause()
        await pilot.pause()
        return bar
    return push


def test_switcher_groups_more_kinds_and_moves_over_the_heading():
    result = []
    push = _switcher(result)

    async def scenario(app, pilot):
        bar = await push(app, pilot)
        options = bar.query_one(OptionList)
        assert [str(options.get_option_at_index(i).prompt).strip() for i in range(options.option_count)][3] == "more kinds"
        assert options.get_option_at_index(3).disabled
        assert "current" in str(options.get_option_at_index(2).prompt)
        bar.action_move(-1)
        assert options.highlighted == 0
        bar.action_move(1)
        bar.action_move(1)
        bar.action_move(1)
        assert options.highlighted == 4, "the heading is skipped going down"
        bar.action_move(-1)
        assert options.highlighted == 2, "and going up"
        options.highlighted = None
        bar.action_move(1)
        assert options.highlighted == 0
        assert not bar.query("#cancel")
        keys = bar.query_one("#dialog-keys", KeysLine)
        assert keys.separator == " \u00b7 "
        bar.action_move(1)
        bar.action_move(1)
        bar.action_move(1)
        await pilot.click("#dialog-keys", offset=keys.offset_of("switch"))
        await pilot.pause()
        assert result == ["b"]

    _run(_radar(widget_spec()), scenario)


def test_switcher_filtering_hides_heading_and_resolves_matches():
    result = []
    push = _switcher(result)

    async def scenario(app, pilot):
        bar = await push(app, pilot)
        bar.query_one(Input).value = "gam"
        await pilot.pause()
        options = bar.query_one(OptionList)
        assert options.option_count == 1
        bar.action_choose()
        await pilot.pause()
        bar = await push(app, pilot)
        bar.query_one(Input).value = "zzz"
        await pilot.pause()
        bar.action_move(1)
        assert bar.query_one(OptionList).option_count == 0
        bar.action_choose()
        await pilot.pause()
        bar = await push(app, pilot)
        keys = bar.query_one("#dialog-keys", KeysLine)
        await pilot.click("#dialog-keys", offset=keys.offset_of("close"))
        await pilot.pause()
        assert result == ["c", "zzz", ""]

    _run(_radar(widget_spec()), scenario)


def test_app_switcher_uses_registry_grouping():
    extra = widget_spec(kind="extra", children=(), aliases=("ex",), title_plural="Extras")
    gadget = widget_spec(kind="gadget", children=(), aliases=("gd",), title_plural="Gadgets", parent="widget")

    async def scenario(app, pilot):
        app.action_command_bar()
        await pilot.pause()
        kinds = [entry for entry in app.screen._entries if not entry[0].startswith("cmd:")]
        assert [entry[0] for entry in kinds] == ["widget", "gadget", "extra"]
        assert [entry[3] for entry in kinds] == ["", "", "more kinds"]
        assert [entry[3] for entry in app.screen._entries[3:]] == ["radar"] * 6, "radar commands come last"

    _run(_radar(widget_spec(), extra, gadget), scenario)


# -- action menu and review --------------------------------------------------------------------


def test_action_menu_has_key_line_not_close_button_and_enter_chooses():
    invoke = Mock(return_value=None)
    action = Action("delete", "Delete", destructive=True, command="iot adr ns widget delete", invoke=invoke)
    spec = widget_spec(children=(), list=lambda _scope: [make_payload("one")], actions=(action,))

    async def scenario(app, pilot):
        app.action_actions()
        await pilot.pause()
        menu = app.screen
        assert isinstance(menu, ActionMenu) and not menu.query("#cancel")
        keys = menu.query_one("#dialog-keys", KeysLine)
        await pilot.click("#dialog-keys", offset=keys.offset_of("select"))
        await pilot.pause()
        assert isinstance(app.screen, ReviewDialog)
        await pilot.click("#confirm-name")
        await pilot.press("o", "n", "e", "enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert invoke.call_count == 1

    _run(_radar(spec), scenario)


def test_action_menu_choose_ignores_disabled_and_empty_menus():
    spec = widget_spec(children=(), actions=(Action("delete", "Delete", destructive=True, invoke=Mock()),))
    empty = widget_spec(kind="bare", children=(), actions=())

    async def scenario(app, pilot):
        menu = ActionMenu(spec, make_payload("one"), True, app.scope)
        app.push_screen(menu)
        await pilot.pause()
        menu.action_choose()
        assert app.screen is menu
        bare = ActionMenu(empty, make_payload("one"), False, app.scope)
        app.push_screen(bare)
        await pilot.pause()
        bare.action_choose()
        assert app.screen is bare

    _run(_radar(widget_spec()), scenario)


def test_action_preview_never_blocks_the_menu():
    action = Action("disable", "Disable", command="iot adr ns widget update", invoke=Mock())
    spec = widget_spec(children=(), actions=(action,))

    async def scenario(app, pilot):
        menu = ActionMenu(spec, {"properties": {}}, False, app.scope)
        app.push_screen(menu)
        await pilot.pause()
        assert menu._preview(action) == ""

    _run(_radar(widget_spec()), scenario)


def test_scope_context_names_namespace_when_target_differs():
    assert scope_context({"namespace_name": "ns", "resource_group_name": "rg", "subscription": "s"}, "dev") == \
        scope_context({"namespace_name": "ns", "resource_group_name": "rg", "subscription": "s"}, "dev")
    text = str(scope_context({"namespace_name": "ns"}, "dev"))
    assert "ns" in text and "resource group unresolved" in text


# -- detail ------------------------------------------------------------------------------------


def _detail_spec(**overrides):
    children = tuple(
        ChildRef(f"kind{i}", f"Children number {i}", str(i), short=f"children-{i}") for i in range(6)
    )
    columns = (
        Column("name", "NAME", lambda p: p["name"]),
        Column("state", "STATE", lambda p: p["properties"]["provisioningState"], style=lambda p: 1 / 0),
        Column("broken", "BROKEN", lambda p: p["missing"]["deep"]),
    )
    options = {
        "children": children,
        "columns": columns,
        "guide": Guide(about="x", runs="az iot adr ns widget list --ns <namespace> -g <resource-group> \u00b7 read"),
    }
    options.update(overrides)
    return widget_spec(**options)


def test_detail_fields_read_command_raw_json_and_wrapping_links():
    spec = _detail_spec()
    payload = {"name": "one", "id": "/subscriptions/s/resourceGroups/from-id/providers/x",
               "properties": {"provisioningState": "Succeeded"}}

    async def scenario(app, pilot):
        detail = DetailScreen(spec, payload, scope={"namespace_name": "ns"})
        app.push_screen(detail)
        await pilot.pause()
        fields = detail._fields()
        assert [row[0] for row in fields] == ["name", "state"]
        assert fields[1][2] is None, "a failing style hook falls back to plain text"
        assert detail._read_command() == "az iot adr ns widget list --ns ns -g from-id  \u00b7  read"
        assert "read" in str(detail.query_one("#detail-read", Static).render())
        await pilot.press("y")
        assert detail.show_json and detail.query_one("#json-body").display
        assert not detail.query_one("#detail-fields").display
        await pilot.press("y")
        assert not detail.show_json
        narrow = len(detail.query(".link-row"))
        await pilot.resize_terminal(140, 30)
        await pilot.pause()
        await pilot.pause()
        assert len(detail.query(".link-row")) < narrow
        detail.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="child-kind0")))
        await pilot.pause()

    _run(_radar(spec), scenario, size=(60, 30))


def test_detail_without_spec_or_children_degrades_quietly():
    plain = _detail_spec(children=(), columns=(Column("broken", "BROKEN", lambda p: p["missing"]),),
                         row_id=lambda p: "row-id", guide=Guide(about="x", runs="not a command"))

    async def scenario(app, pilot):
        detail = DetailScreen(plain, {"id": "x"})
        app.push_screen(detail)
        await pilot.pause()
        assert detail._fields() == [("name", "row-id", None)]
        assert detail._read_command() == ""
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        bare = DetailScreen(None, {}, title="Thing")
        app.push_screen(bare)
        await pilot.pause()
        assert bare.resource_name() == "" and bare._read_command() == ""
        assert bare.title_parts() == ("Thing", None)

    _run(_radar(widget_spec()), scenario)


def test_detail_link_width_defaults_before_mount():
    assert DetailScreen(None, {})._links_width() == FRAME_WIDTH - 4


# -- operations gutter ---------------------------------------------------------------------------


def test_operations_rows_have_gutter_and_click_to_select():
    tracker = OperationTracker()
    first = tracker.start("Update", "one", command="az iot adr ns widget update -n one")
    tracker.fail(first, "Denied")
    second = tracker.start("Delete", "two")
    second.detail = "still running"

    async def scenario(app, pilot):
        screen = OperationsScreen(tracker)
        app.push_screen(screen)
        await pilot.pause()
        rows = list(screen.query(OperationRow))
        selected = [row for row in rows if row.has_class("-selected")]
        assert len(selected) == 1 and screen._operations[selected[0].index] is second
        other = next(row for row in rows if row is not selected[0])
        assert selected[0].styles.border_left[0] == "wide"
        assert other.styles.border_left[0] == "blank"
        assert other.region.x == selected[0].region.x, "the gutter never shifts the selected row"
        await pilot.click(offset=(other.region.x + 3, other.region.y))
        await pilot.pause()
        assert screen._selected == other.index and other.has_class("-selected")
        screen.select(9)
        assert screen._selected == other.index
        screen.action_move(-1 if other.index else 1)
        assert screen._selected == selected[0].index
        assert screen.breadcrumb() == "operations"
        screen.action_dismiss_finished()
        await pilot.pause()
        assert not tracker.failed

    _run(_radar(widget_spec()), scenario, size=(100, 30))


# -- defensive paint paths -----------------------------------------------------------------------


def test_unmounted_screens_and_widgets_never_raise():
    spec = widget_spec()

    async def scenario(app, pilot):
        chrome = ChromeScreen()
        assert chrome.content_rows() >= 3
        chrome.fit_layout()
        chrome.refresh_title()
        chrome.refresh_keys()
        assert chrome.title_parts()[0] == chrome.breadcrumb()
        assert chrome.keys()
        browse = BrowseScreen(spec, Mock(), scope={})
        browse.fit_layout()
        browse.refresh_title()
        app.push_screen(ChromeScreen())
        await pilot.pause()
        app.screen.action_back()
        await pilot.pause()
        assert isinstance(app.screen, BrowseScreen)

    _run(_radar(spec), scenario)


def test_browse_cell_truncation_gutter_errors_and_filter_submit():
    async def scenario(app, pilot):
        screen = app.screen
        assert screen._cell_text("abcdef", "", 4).plain == "abc\u2026"
        table = screen.query_one("#rows", DataTable)
        screen._gutter_key = "ghost"
        screen._paint_gutter()
        original = table.coordinate_to_cell_key

        def missing(_coordinate):
            raise RowDoesNotExist("gone")

        table.coordinate_to_cell_key = missing
        screen._paint_gutter()
        assert screen._gutter_key is None
        table.coordinate_to_cell_key = original
        await pilot.press("slash", "o")
        screen.action_submit_filter()
        await pilot.pause()
        assert screen.model.filter_text == "o"

    _run(_radar(widget_spec(list=lambda _scope: [make_payload("one"), make_payload("two")])), scenario)


def test_small_helpers():
    assert resolve_palette(HIGH_CONTRAST_THEME)["background"] == "black"
    assert palette_of(Static()) == resolve_palette()
    line = KeysLine([Key("a", "a", "alpha")], separator=" \u00b7 ")
    assert line.keys == [Key("a", "a", "alpha")]
    assert line.visible_keys(0) == line.keys
    assert dialog_keys(Key("a", "a", "alpha")).id == "dialog-keys"
    try:
        line.offset_of("missing")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown key groups must raise")
    same = SimpleNamespace(outer_size=SimpleNamespace(height=3))
    screen = Mock()
    screen.query.return_value.first.return_value = same
    screen.query_one.return_value = same
    fit_dialog_list(screen, "#x")
    assert "Diff(added=0" in repr(Diff())
    assert not Registry().aliases()
    diagnostics.exception("visual rules %s", "ok")
    model = TableModel(widget_spec())
    for state, expected in ((LoadState.NEVER_LOADED, "Loading"), (LoadState.LOADING, "Loading"),
                            (LoadState.STALE, "Showing last known data")):
        model.state = state
        assert model.status_text().startswith(expected)
    assert isinstance(Text("x"), Text)


# -- measured geometry, actions relevance, root key, switcher overflow --------------------------

_LINK_TYPES = {"dps": "Microsoft.Devices/provisioningServices", "hub": "Microsoft.Devices/IotHubs",
               "su": "Microsoft.DeviceUpdate/updateInstances"}


def _link(name, kind, status):
    return {"name": name, "endpointType": _LINK_TYPES[kind], "resourceId": f"/subscriptions/s/x/{name}",
            "provisioningStatus": {"status": status}}


def _real_radar(rows):
    real = build_registry(Mock())
    registry = Registry()
    for spec in real.all():
        registry.register(replace(spec, list=lambda _scope, data=rows.get(spec.kind, []): list(data)))
    app = RadrApp(registry=registry, resource_group_name="rg", refresh_interval=900)
    app.scope.update(subscription_id="00000000-0000-4000-8000-000000000001")
    return app


def _text_starts(screen):
    """Column text start, relative to the frame, keyed by header label."""
    table = screen.query_one("#rows", DataTable)
    starts, x = {}, 0
    for column in table.columns.values():
        starts[str(column.label).strip()] = x
        x += column.width
    return starts


def test_frame_width_is_the_measured_reference_width():
    assert FRAME_WIDTH == 92 and f"#frame {{ width: {FRAME_WIDTH};" in APP_CSS


def test_table_columns_start_where_the_reference_places_them():
    namespaces = [{"name": f"ns-{i}", "location": "westus2", "properties": {"provisioningState": "Succeeded"}}
                  for i in range(2)]
    links = [_link("dps-a", "dps", "Succeeded"), _link("hub-a", "hub", "Failed")]
    cas = [{"name": "root", "properties": {"certificateAuthorityType": "Root", "provisioningState": "Active"}}]

    async def scenario(app, pilot):
        starts = _text_starts(app.screen)
        assert (starts["NAME"], starts["STATUS"], starts["LOCATION"]) == (1, 61, 74)
        assert app.screen.query_one("#frame").region.width == FRAME_WIDTH
        app.open_scoped_child(ChildRef("link", "Linked resources"), {"namespace_name": "ns-0", "resource_group_name": "rg"})
        await app.workers.wait_for_complete()
        await pilot.pause()
        starts = _text_starts(app.screen)
        assert (starts["TYPE"], starts["STATUS"]) == (66, 79)
        scope = {"namespace_name": "ns-0", "resource_group_name": "rg"}
        app.open_scoped_child(ChildRef("ca", "Certificate authorities"), scope)
        await app.workers.wait_for_complete()
        await pilot.pause()
        starts = _text_starts(app.screen)
        assert (starts["STATUS"], starts["TYPE"]) == (53, 74)

    _run(_real_radar({"namespace": namespaces, "link": links, "ca": cas}), scenario, size=(120, 40))


def test_ca_type_carries_the_intermediate_issuer():
    assert _ca_type_label({"properties": {"certificateAuthorityType": "Root"}}) == "Root"
    assert _ca_type_label({"properties": {"certificateAuthorityType": "ICA", "issuer": {"issuerType": "Microsoft"}}}) \
        == "ICA \u00b7 Microsoft"


def test_link_menu_lists_only_this_endpoints_actions_with_the_review_command():
    links = [_link("hub-a", "hub", "Failed"), _link("dps-a", "dps", "Succeeded")]

    async def scenario(app, pilot):
        app.open_scoped_child(ChildRef("link", "Linked resources"),
                              dict(app.scope, namespace_name="ns", resource_group_name="rg"))
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        screen.query_one("#rows", DataTable).move_cursor(row=1)
        await pilot.pause()
        assert screen.selected_payload()["name"] == "hub-a"
        app.action_actions()
        await pilot.pause()
        menu = app.screen
        labels = [action.label for action in menu._actions]
        # Only what can run on this Failed hub row: "Wait" (Accepted only) is hidden with its rule.
        assert labels == ["Retry failed link (update)", "Remove link",
                          "Link an IoT Hub", "Link a DPS", "Link Software Updates"]
        assert menu._notes == ["Wait for link: only when the link is Accepted."]
        assert str(menu.query_one("#action-hidden", Static).render()) == menu._notes[0]
        assert menu.query_one(OptionList).highlighted == 0, "opens on the first row action"
        assert str(menu.query_one("#action-command", Static).render()).startswith("az iot adr ns link hub update")
        assert not any(option.disabled for option in menu.query_one(OptionList)._options)
        by_label = {action.label: action for action in menu._actions}
        remove = by_label["Remove link"]
        assert menu._preview(by_label["Link an IoT Hub"]) == ""
        preview = menu._preview(remove)
        assert preview.startswith("az iot adr ns link hub remove") and "--endpoint-name hub-a" in preview
        assert "--subscription 00000000-0000-4000-8000-000000000001" in preview and "--yes" in preview
        menu.query_one(OptionList).highlighted = labels.index("Remove link")
        await pilot.pause()
        assert str(menu.query_one("#action-command", Static).render()).replace("\n", " ").startswith(
            "az iot adr ns link hub remove")
        menu.action_choose()
        await pilot.pause()
        assert isinstance(app.screen, ReviewDialog) and app.screen.command == preview

    _run(_real_radar({"link": links}), scenario, size=(120, 40))


def test_action_relevance_defaults():
    action = Action("x", "X", relevant_to=lambda p: False)
    assert action.is_relevant({}) and not action.is_relevant({"name": "a"})
    assert replace(action, collection=True).is_relevant({"name": "a"})
    assert Action("y", "Y").is_relevant({"name": "a"})


def test_first_page_offers_quit_and_children_offer_back():
    async def scenario(app, pilot):
        root = app.screen
        assert root.is_root() and QUIT in root.keys() and BACK not in root.keys()
        keys = root.query_one("#keys-line", KeysLine)
        assert "q quit" in keys.render().plain
        assert ChromeScreen().back_key() is BACK, "a page not yet on the stack has a parent"
        app.push_screen(DetailScreen(None, {"name": "x"}))
        await pilot.pause()
        assert app.screen.back_key() is BACK
        app.screen.action_back()
        await pilot.pause()
        app.push_screen(ChromeScreen())
        await pilot.pause()
        assert app.screen.keys()[1] is BACK and app.screen.keys()[0].key == "Tab"

    _run(_radar(widget_spec()), scenario)


def test_short_terminal_switcher_shrinks_its_list_not_the_dialog_and_shows_the_hidden_count():
    async def scenario(app, pilot):
        await pilot.press("colon")
        for _ in range(4):
            await pilot.pause()
        bar = app.screen
        frame, body = bar.query_one(".dialog-frame"), bar.query_one(".dialog")
        options = bar.query_one(OptionList)
        assert frame.region.y >= 1 and frame.region.bottom <= app.size.height - 1, "a free row above and below"
        assert body.max_scroll_y == 0, "the list scrolls, not the dialog body"
        assert options.max_scroll_y > 0
        more = bar.query_one("#list-more", Static)
        assert str(more.render()) == f"\u2193 {options.max_scroll_y} more"
        assert body.region.y <= more.region.y < body.region.bottom, "the indicator is on screen"
        assert options.virtual_size.height == options.option_count, "no prompt wraps (e.g. the current tag)"

    _run(_real_radar({}), scenario, size=(80, 18))


def test_switcher_says_how_many_kinds_are_out_of_view():
    entries = [(f"kind{i}", f"k{i}", f"kinds number {i}", i > 5) for i in range(20)]

    async def scenario(app, pilot):
        bar = CommandBar(entries)
        app.push_screen(bar)
        for _ in range(4):
            await pilot.pause()
        more = bar.query_one("#list-more", Static)
        assert str(more.render()).startswith("\u2193 ")
        options = bar.query_one(OptionList)
        options.scroll_to(y=2, animate=False)
        for _ in range(3):
            await pilot.pause()
        below = options.option_count - 2 - int(options.styles.max_height.value)
        assert str(more.render()) == f"\u2191 2 more \u00b7 \u2193 {below} more", "both directions, with counts"
        options.scroll_end(animate=False)
        for _ in range(3):
            await pilot.pause()
        assert str(more.render()).startswith("\u2191 ") and "\u2193" not in str(more.render())
        bar.query_one(Input).value = "kinds number 19"
        for _ in range(3):
            await pilot.pause()
        assert str(more.render()) == ""

    _run(_radar(widget_spec()), scenario)
