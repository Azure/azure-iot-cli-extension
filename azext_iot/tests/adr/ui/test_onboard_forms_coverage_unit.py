# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Creation dialog validation must never queue an invalid or cancelled resource."""

import asyncio

import pytest
from textual.widgets import Input, Static

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.onboard.create import CreateRequest
from azext_iot.adr.ui.screens.onboard.forms import (
    CreateResourceDialog,
    parse_tags,
    validate_name,
)


def drive(scenario):
    async def run():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(120, 42)) as pilot:
            await app.workers.wait_for_complete()
            selected = []
            dialog = CreateResourceDialog("hub", "IoT Hub", "rg-test", "eastus2", "hub-test")
            await app.push_screen(dialog, selected.append)
            await pilot.pause()
            await scenario(app, pilot, dialog, selected)

    asyncio.run(run())


@pytest.mark.parametrize(
    "value, expected, error",
    [
        (None, {}, None),
        ("  ", {}, None),
        ('owner="two people" empty= token=a=b owner=last', {"owner": "last", "empty": "", "token": "a=b"}, None),
        ('owner="unfinished', {}, "invalid tags:"),
        ("good=value bad", {}, "tag 'bad' must use key=value"),
        ("=value", {}, "tag keys cannot be empty"),
    ],
)
def test_tags_are_atomic_and_support_shell_quoting(value, expected, error):
    tags, problem = parse_tags(value)
    assert tags == expected
    if error is None:
        assert problem is None
    else:
        assert problem.startswith(error)


@pytest.mark.parametrize(
    "kind, name, problem",
    [
        ("namespace", None, "a name is required"),
        ("namespace", "ab", "3-64 characters"),
        ("namespace", "a" * 65, "3-64 characters"),
        ("namespace", "-abc", "3-64 characters"),
        ("dps", "abc-", "3-64 characters"),
        ("hub", "a" * 51, "3-50 characters"),
        ("su", "a" * 37, "3-36 characters"),
        ("resource_group", "team.", "cannot end with"),
        ("resource_group", "team/name", "1-90 characters"),
        ("resource_group", "a" * 91, "1-90 characters"),
        ("unrecognized", "ab", "3-64 characters"),
    ],
)
def test_invalid_resource_names_explain_the_service_rule(kind, name, problem):
    assert problem in validate_name(name, kind)


@pytest.mark.parametrize(
    "kind, name",
    [
        ("resource_group", " équipe_(west).1 "),
        ("resource_group", "a" * 90),
        ("namespace", "a" * 64),
        ("dps", "Dps-123"),
        ("hub", "a" * 50),
        ("su", "a" * 36),
        ("unrecognized", "abc"),
    ],
)
def test_valid_resource_name_boundaries(kind, name):
    assert validate_name(name, kind) is None


@pytest.mark.parametrize(
    "field, value, problem",
    [
        ("name", " ", "a name is required"),
        ("rg", " ", "a resource group is required"),
        ("location", " ", "a region is required"),
    ],
)
def test_invalid_form_stays_open_then_enter_submits_trimmed_request(field, value, problem):
    async def scenario(app, pilot, dialog, selected):
        assert app.focused.id == "name"
        widget = dialog.query_one(f"#{field}", Input)
        widget.value = value
        await pilot.click("#create")
        assert app.screen is dialog
        assert not selected
        assert problem in str(dialog.query_one("#create-error", Static).render())
        widget.value = {"name": " hub-test ", "rg": " rg-test ", "location": " eastus2 "}[field]
        widget.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert selected == [CreateRequest("hub", "hub-test", "rg-test", "eastus2")]
        assert app.screen is not dialog

    drive(scenario)


@pytest.mark.parametrize("trigger", ["escape", "cancel", "create"])
def test_create_and_cancel_have_distinct_results(trigger):
    async def scenario(app, pilot, dialog, selected):
        if trigger == "escape":
            await pilot.press("escape")
        else:
            await pilot.click(f"#{trigger}")
        await pilot.pause()
        expected = CreateRequest("hub", "hub-test", "rg-test", "eastus2") if trigger == "create" else None
        assert selected == [expected]
        assert app.screen is not dialog

    drive(scenario)


def test_enter_does_not_dismiss_invalid_form():
    async def scenario(app, pilot, dialog, selected):
        dialog.query_one("#name", Input).value = ""
        await pilot.press("enter")
        assert app.screen is dialog
        assert selected == []
        assert "a name is required" in str(dialog.query_one("#create-error", Static).render())

    drive(scenario)
