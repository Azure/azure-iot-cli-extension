# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Geometry of the minimal radar layout: exact button widths, wrapped links, fitted dialogs."""

import asyncio

from textual.app import App
from textual.widgets import DataTable, OptionList

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.core.spec import ChildRef, Guide, Registry
from azext_iot.adr.ui.screens.detail import DetailScreen
from azext_iot.adr.ui.screens.help import CommandBar
from azext_iot.adr.ui.widgets.minimal import PillButton, fit_dialog_list
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


def _run(app, scenario, size=(80, 24)):
    async def runner():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(runner())


def _radar(**overrides):
    registry = Registry()
    registry.register(widget_spec(list=lambda _scope: [make_payload("one"), make_payload("two")], **overrides))
    app = RadrApp(registry=registry, resource_group_name="rg", refresh_interval=900)
    app.scope["subscription_id"] = "sub"
    return app


def test_pill_button_is_label_plus_one_cell_each_side():
    class Host(App):
        # The radar Button rule: one row, auto width, one cell of padding each side.
        CSS = "Button { height: 1; min-width: 0; width: auto; border: none; padding: 0 1; }"

        def compose(self):
            yield PillButton("Delete \u21b5", id="pill")

    async def scenario(app, _pilot):
        pill = app.query_one("#pill", PillButton)
        assert pill.styles.line_pad == 0
        assert pill.region.width == len("Delete \u21b5") + 2
        assert pill.region.height == 1

    _run(Host(), scenario)


def test_selected_row_keeps_status_colour():
    async def scenario(app, _pilot):
        assert app.screen.query_one("#rows", DataTable).cursor_foreground_priority == "renderable"

    _run(_radar(), scenario)


def test_detail_links_wrap_instead_of_clipping_at_80_columns():
    children = tuple(ChildRef(f"kind{i}", f"Very long child label {i}", chr(ord("a") + i)) for i in range(6))
    detail = DetailScreen(widget_spec(children=children), make_payload("one"))
    lines = detail._link_lines(76)
    assert len(lines) > 1
    assert sum(len(line) for line in lines) == len(children)
    for line in lines:
        width = sum(len(detail._link_label(child)) for child in line) + detail._LINK_GAP * (len(line) - 1)
        assert width <= 76


def test_read_command_is_a_real_az_command_with_known_scope_filled():
    guide = Guide("Widgets.", runs="az iot adr ns widget list --ns <namespace> -g <resource-group>  \u00b7  read-only")
    detail = DetailScreen(
        widget_spec(guide=guide), make_payload("one"), scope={"namespace_name": "ns1", "resource_group_name": "rg1"},
    )
    assert detail._read_command() == "az iot adr ns widget list --ns ns1 -g rg1  \u00b7  read-only"
    prose = DetailScreen(widget_spec(guide=Guide("Widgets.", runs="Nothing - local")), make_payload("one"))
    assert prose._read_command() == ""
    namespace = DetailScreen(
        widget_spec(kind="namespace"),
        {"name": "ns-a", "id": "/subscriptions/s/resourceGroups/rg-a/providers/Microsoft.DeviceRegistry/namespaces/ns-a"},
    )
    assert namespace._read_command() == "az iot adr ns show -n ns-a -g rg-a"


def test_long_switcher_fits_short_terminal_with_buttons_visible():
    entries = [(f"kind{i}", f"k{i}", f"kinds number {i}") for i in range(20)]

    async def scenario(app, pilot):
        app.push_screen(CommandBar(entries, current="kind3"))
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        fit_dialog_list(screen, "#resource-options")
        await pilot.pause()
        dialog = screen.query_one(".dialog")
        assert dialog.region.y >= 1 and dialog.region.bottom <= 23
        keys = screen.query_one("#dialog-keys")
        assert dialog.region.contains_region(keys.region)
        assert not screen.query("#cancel"), "no Close button row in the switcher"
        assert screen.query_one(OptionList).region.height < len(entries)

    _run(_radar(), scenario)
