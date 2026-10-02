# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Mounted dialog, chrome and operations-tray lifecycle regressions."""

import asyncio
from unittest.mock import Mock

import pytest
from textual.app import App
from textual.widgets import Button, Input, Static

from azext_iot.adr.ui.core.ops import OperationTracker, OpState
from azext_iot.adr.ui.screens.base import ChromeScreen
from azext_iot.adr.ui.theme import APP_CSS, resolve_palette, resolve_theme
from azext_iot.adr.ui.widgets.chrome import Breadcrumbs, FlashLine, HintBar, InfoPanel, PageGuide
from azext_iot.adr.ui.widgets.dialogs import ConfirmDialog, ErrorDialog, ModalBox, TypeNameConfirmDialog
from azext_iot.adr.ui.widgets.tray import CommandPreviewDialog, OperationsDialog, OperationsTray


class WidgetApp(App):
    CSS = APP_CSS
    theme_tokens = resolve_theme("dark")
    theme_palette = resolve_palette("dark")


def run_modal(dialog, scenario):
    async def runner():
        app = WidgetApp()
        results = []
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(dialog, results.append)
            await pilot.pause()
            await scenario(app, pilot, results)
    asyncio.run(runner())


@pytest.mark.parametrize("choice, expected", [("confirm", True), ("cancel", False), ("escape", False)])
@pytest.mark.parametrize("danger", [False, True])
def test_confirmation_only_approves_explicit_confirm(choice, expected, danger):
    dialog = ConfirmDialog("Change resource", "This changes Azure.", confirm_label="Apply", danger=danger)

    async def scenario(app, pilot, results):
        assert dialog.query_one(ModalBox).has_class("danger") is danger
        button = dialog.query_one("#confirm", Button)
        assert str(button.label) == "Apply"
        assert button.variant == ("error" if danger else "primary")
        if choice == "escape":
            await pilot.press("escape")
        else:
            await pilot.click(f"#{choice}")
        await pilot.pause()
        assert results == [expected]
        assert app.screen is not dialog

    run_modal(dialog, scenario)


@pytest.mark.parametrize("choice, expected", [
    ("enter", True), ("confirm", True), ("cancel", False), ("escape", False),
])
def test_destructive_dialog_requires_exact_name_before_approval(choice, expected):
    dialog = TypeNameConfirmDialog("Delete widget", "Irreversible", "Case-Sensitive")

    async def scenario(app, pilot, results):
        field = dialog.query_one("#name-input", Input)
        confirm = dialog.query_one("#confirm", Button)
        assert app.focused is field
        assert confirm.disabled
        field.value = "case-sensitive"
        await pilot.pause()
        await pilot.press("enter")
        assert results == []
        assert confirm.disabled
        # The event handler must also reject a stale queued button press.
        dialog.on_button_pressed(Button.Pressed(confirm))
        await pilot.pause()
        assert results == []
        field.value = "  Case-Sensitive  "
        await pilot.pause()
        assert not confirm.disabled
        if choice in ("enter", "escape"):
            await pilot.press(choice)
        else:
            await pilot.click(f"#{choice}")
        await pilot.pause()
        assert results == [expected]

    run_modal(dialog, scenario)


@pytest.mark.parametrize("detail", [None, "Endpoint principal lacks the required role"])
@pytest.mark.parametrize("choice", ["close", "escape", "enter"])
def test_error_dialog_displays_optional_detail_and_closes(detail, choice):
    dialog = ErrorDialog("Operation failed", "Permission denied", detail)

    async def scenario(app, pilot, results):
        rendered = " ".join(str(widget.render()) for widget in dialog.query(Static).results())
        assert "Permission denied" in rendered
        if detail:
            assert detail in rendered
        if choice == "close":
            await pilot.click("#close")
        else:
            await pilot.press(choice)
        await pilot.pause()
        assert results == [None]
        assert app.screen is not dialog

    run_modal(dialog, scenario)


@pytest.mark.parametrize("choice, expected", [("run", True), ("cancel", False), ("escape", False)])
@pytest.mark.parametrize("clipboard_available", [False, True])
def test_command_preview_copy_never_approves_and_handles_unavailable_clipboard(
    monkeypatch, choice, expected, clipboard_available,
):
    command = "az iot adr ns show -n 'namespace with spaces' -g rg"
    dialog = CommandPreviewDialog("Preview", command, note="Review before running", danger=True)

    async def scenario(app, pilot, results):
        copy = Mock(side_effect=None if clipboard_available else RuntimeError("SSH clipboard unavailable"))
        notify = Mock()
        monkeypatch.setattr(app, "copy_to_clipboard", copy)
        monkeypatch.setattr(dialog, "notify", notify)
        assert command in str(dialog.query_one("#command-text", Static).render())
        assert dialog.query_one("#run", Button).variant == "error"
        await pilot.press("ctrl+y")
        copy.assert_called_once_with(command)
        if clipboard_available:
            notify.assert_called_once_with("command copied")
        else:
            notify.assert_called_once_with("clipboard unavailable", severity="warning")
        assert results == []
        if choice == "escape":
            await pilot.press("escape")
        else:
            await pilot.click(f"#{choice}")
        await pilot.pause()
        assert results == [expected]

    run_modal(dialog, scenario)


def test_operations_tray_shows_running_failure_and_completion_then_hides():
    async def scenario():
        app = WidgetApp()
        tracker = OperationTracker()
        screen = ChromeScreen()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(screen)
            tray = screen.query_one("#ops-tray", OperationsTray)
            tray.refresh_display()
            assert not tray.display and tray.text == ""
            tray.tracker = tracker
            running = tracker.start("Update", "ns")
            failed = tracker.start("Delete", "group", command="az iot adr ns group delete")
            tracker.fail(failed, RuntimeError("denied"))
            tray.refresh_display()
            assert tray.display
            assert "1 running" in tray.text and "1 failed" in tray.text
            assert "Delete group - failed: denied" in tray.text
            assert "<o> details" in tray.text
            tracker.acknowledge(failed.id)
            tracker.prune()
            tracker.succeed(running)
            tray.refresh_display()
            assert "Update ns - succeeded" in tray.text
            assert "failed" not in tray.text
            tracker.prune(keep_seconds=0)
            tray.refresh_display()
            await pilot.pause()
            assert not tray.display and tray.text == ""
    asyncio.run(scenario())


@pytest.mark.parametrize("choice", ["ack", "close", "escape", "o"])
def test_operations_dialog_acknowledges_only_finished_work(choice):
    tracker = OperationTracker()
    running = tracker.start("Update", "in-flight")
    succeeded = tracker.start("Update", "done")
    tracker.succeed(succeeded)
    failed = tracker.start("Delete", "blocked", command="az iot adr ns group delete -n blocked")
    error = RuntimeError("Forbidden")
    error.detail = "Missing resource-write permission"
    tracker.fail(failed, error)
    dialog = OperationsDialog(tracker)

    async def scenario(app, pilot, results):
        text = dialog._format().plain
        assert "Update in-flight - running" in text
        assert "Update done - succeeded" in text
        assert "Delete blocked - failed: Forbidden" in text
        assert failed.command in text
        assert error.detail in text
        if choice in ("escape", "o"):
            await pilot.press(choice)
        else:
            await pilot.click(f"#{choice}")
        await pilot.pause()
        assert results == [None]
        if choice == "ack":
            assert tracker.operations == [running]
            assert failed.acknowledged
        else:
            assert tracker.operations == [failed, succeeded, running]
            assert not failed.acknowledged
        assert running.state is OpState.RUNNING

    run_modal(dialog, scenario)


def test_operations_dialog_empty_state():
    dialog = OperationsDialog(OperationTracker())

    async def scenario(app, pilot, results):
        assert dialog._format().plain == "no operations yet"
        await pilot.click("#ack")
        await pilot.pause()
        assert results == [None]

    run_modal(dialog, scenario)


def test_chrome_collapse_filter_hints_and_flash_timer_lifecycle(monkeypatch):
    async def scenario():
        app = WidgetApp()
        screen = ChromeScreen()
        # Safe before mounting: no flash widget exists yet.
        assert screen.flash("before mount") is None
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(screen)
            assert screen.guide() is None
            assert screen.breadcrumb() == "chrome"
            info = screen.query_one(InfoPanel)
            info.set_facts([("kind", "Widgets"), ("rows", "2")])
            assert info.display and "rows 2" in info.text
            assert info.toggle() is True
            assert not info.display
            assert info.toggle() is False
            assert info.display
            guide = screen.query_one(PageGuide)
            guide.set_guide([("about", "Widgets"), ("action", "Enter opens"),
                             ("runs", "Read-only"), ("note", "No changes")])
            assert "Read-only  ·  No changes" in guide.text
            assert guide.toggle() is True
            assert guide.collapsed and not guide.display
            assert guide.toggle() is False
            assert not guide.collapsed and guide.display
            hints = screen.query_one(HintBar)
            hints.set_bindings([("ignored", ""), ("y", "JSON")])
            assert hints.text == "y JSON"
            crumbs = screen.query_one(Breadcrumbs)
            crumbs.set_path(["namespaces", "widgets"], "needle")
            assert crumbs.text == "namespaces  ›  widgets   [filter: needle]"
            flash = screen.query_one(FlashLine)
            timers = [Mock(), Mock()]
            schedule = Mock(side_effect=timers)
            monkeypatch.setattr(flash, "set_timer", schedule)
            flash.flash("first")
            flash.flash("second", "success")
            timers[0].stop.assert_called_once_with()
            assert "OK  second" in str(flash.render())
            # Drive the registered callback explicitly rather than sleeping six seconds.
            schedule.call_args.args[1]()
            timers[1].stop.assert_called_once_with()
            assert flash.text == ""
            flash.flash("denied", "error")
            assert "ERR denied" in str(flash.render())
            assert schedule.call_count == 2
            await pilot.pause()
        assert screen.flash("after teardown") is None
    asyncio.run(scenario())
