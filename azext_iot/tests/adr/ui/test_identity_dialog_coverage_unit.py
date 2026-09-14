# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline identity chooser regression tests with real widgets and worker dispatch."""

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from textual.coordinate import Coordinate
from textual.widgets import Button, DataTable, Input, Static

from azext_iot.adr.ui.app import RadrApp
from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
from azext_iot.adr.ui.screens.onboard.identity import USER_ASSIGNED, system_choice
from azext_iot.adr.ui.screens.onboard.identity_dialog import IdentityChoiceDialog, _resource_group


def identity(name="alpha", group="rg-alpha", **extra):
    return {
        "name": name,
        "id": f"/subscriptions/sub-1/resourceGroups/{group}/providers/"
              f"Microsoft.ManagedIdentity/userAssignedIdentities/{name}",
        "location": "eastus2",
        **extra,
    }


def drive(scenario, identities=(), error=None):
    async def run():
        catalog = SimpleNamespace(user_assigned_identities=Mock(return_value=identities, side_effect=error))
        resource = {"identity": {"type": "UserAssigned", "userAssignedIdentities": {identity()["id"]: {}}}}
        before = deepcopy(resource)
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(140, 50)) as pilot:
            await app.workers.wait_for_complete()
            selected = []
            dialog = IdentityChoiceDialog(catalog, "hub-test", "Hub calls namespace", "sub-1", "rg-test", "eastus2",
                                          resource=resource)
            await app.push_screen(dialog, selected.append)
            await pilot.pause()
            await scenario(app, pilot, dialog, selected, catalog)
            assert resource == before, "Choosing an identity must not attach it to Azure's resource payload"

    asyncio.run(run())


@pytest.mark.parametrize("resource_id, expected", [("not-an-arm-id", ""), ("/RESOURCEGROUPS/Case/thing", "Case"),
                                                   ("/subscriptions/s/resourceGroups", "")])
def test_resource_group_extraction_is_case_insensitive_and_tolerates_partial_ids(resource_id, expected):
    assert _resource_group(resource_id) == expected


@pytest.mark.parametrize("error", [None, RuntimeError("list permission denied")])
def test_empty_and_failed_identity_catalog_explain_recovery(error):
    async def scenario(app, pilot, dialog, selected, catalog):
        dialog.query_one("#identity-uami", Button).press()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        catalog.user_assigned_identities.assert_called_once_with()
        status = str(dialog.query_one("#identity-status", Static).render())
        assert ("No user-assigned identities found. Choose Create UAMI." if error is None
                else "Could not list user-assigned identities: list permission denied") in status
        assert not dialog.query_one("#identity-loading").display
        assert not dialog.query_one("#identity-table").display
        assert selected == []
        dialog.query_one("#identity-filter", Input).value = "unavailable"
        await pilot.pause()
        assert str(dialog.query_one("#identity-status", Static).render()) == status
        assert dialog.query_one("#identity-table", DataTable).row_count == 0
        await pilot.press("escape")
        assert selected == [None]

    drive(scenario, error=error)


def test_existing_identity_table_filter_keyboard_selection_and_principal_fallback():
    rows = [identity(principalId="principal-alpha"), identity("beta", "rg-beta", principal_id="principal-beta")]

    async def scenario(app, pilot, dialog, selected, catalog):
        # Hidden filters cannot steal focus from the initial choice.
        dialog.action_filter_uamis()
        assert app.focused.id == "identity-sami"
        await pilot.press("right", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        table = dialog.query_one("#identity-table", DataTable)
        assert table.row_count == 2
        assert table.get_row_at(0)[3:] == ["yes", "principal-alpha"]
        assert table.get_row_at(1)[3:] == ["no", "principal-beta"]
        await pilot.press("down", "up")
        assert table.cursor_coordinate.row == 0
        assert app.focused is table
        await pilot.press("up")
        assert app.focused.id == "identity-uami"
        await pilot.press("slash")
        assert app.focused.id == "identity-filter"
        field = dialog.query_one("#identity-filter", Input)
        for value, count in [("missing", 0), ("RG-BETA", 1), ("userAssignedIdentities/alpha", 1), ("beta", 1)]:
            field.value = value
            await pilot.pause()
            assert table.row_count == count
            status = str(dialog.query_one("#identity-status", Static).render())
            assert ("No identities match" if not count else "1 of 2 identities") in status
        await pilot.press("up")
        assert app.focused.id == "identity-uami"
        await pilot.press("slash", "enter")
        assert app.focused is table
        await pilot.press("enter")
        await pilot.pause()
        assert len(selected) == 1
        assert (selected[0].mode, selected[0].uami_id, selected[0].principal_id) == (
            USER_ASSIGNED, rows[1]["id"], "principal-beta"
        )
        assert not selected[0].create_uami
        catalog.user_assigned_identities.assert_called_once_with()

    drive(scenario, rows)


@pytest.mark.parametrize(
    "field, problem",
    [("identity-name", "a name is required"), ("identity-rg", "a resource group is required"),
     ("identity-location", "an Azure region is required")],
)
def test_new_identity_validates_before_returning_a_plan_only_choice(field, problem):
    async def scenario(app, pilot, dialog, selected, catalog):
        dialog.query_one("#identity-new", Button).press()
        await pilot.pause()
        assert app.focused.id == "identity-name"
        assert dialog.query_one("#identity-new-form").display
        assert not dialog.query_one("#identity-footer").display
        dialog.query_one("#identity-name", Input).value = " connectivity "
        dialog.query_one(f"#{field}", Input).value = " "
        dialog.query_one("#identity-new-confirm", Button).press()
        await pilot.pause()
        assert app.screen is dialog
        assert selected == []
        assert problem in str(dialog.query_one("#identity-error", Static).render())
        values = {"identity-name": " connectivity ", "identity-rg": " rg-test ", "identity-location": " eastus2 "}
        dialog.query_one(f"#{field}", Input).value = values[field]
        dialog.query_one("#identity-new-confirm", Button).press()
        await pilot.pause()
        assert app.screen is not dialog
        choice = selected[0]
        assert choice.mode == USER_ASSIGNED
        assert choice.create_uami
        assert choice.uami_id == identity("connectivity", "rg-test")["id"]
        assert (choice.uami_name, choice.uami_resource_group, choice.uami_location) == ("connectivity", "rg-test", "eastus2")
        catalog.user_assigned_identities.assert_not_called()

    drive(scenario)


def test_new_identity_back_and_mode_focus_do_not_commit_a_choice():
    async def scenario(app, pilot, dialog, selected, catalog):
        await pilot.press("left")
        assert app.focused.id == "identity-new"
        dialog.query_one("#identity-new", Button).press()
        await pilot.pause()
        dialog.query_one("#identity-name", Input).value = "draft"
        await pilot.press("enter")
        assert app.screen is dialog
        assert selected == []
        dialog.action_focus_identity_mode(1)
        await pilot.pause()
        assert app.focused.id == "identity-sami"
        dialog.query_one("#identity-new-back", Button).press()
        await pilot.pause()
        assert not dialog.query_one("#identity-new-form").display
        assert dialog.query_one("#identity-footer").display
        assert app.focused.id == "identity-sami"
        assert selected == []
        dialog.query_one("#identity-cancel", Button).press()
        await pilot.pause()
        assert selected == [None]
        catalog.user_assigned_identities.assert_not_called()

    drive(scenario)


def test_unrelated_or_stale_row_events_cannot_dismiss_the_dialog():
    async def scenario(app, pilot, dialog, selected, catalog):
        unrelated = DataTable(id="unrelated-table")
        dialog.on_data_table_row_selected(DataTable.RowSelected(unrelated, 0, "stale"))
        table = dialog.query_one("#identity-table", DataTable)
        dialog.on_data_table_row_selected(DataTable.RowSelected(table, 0, "stale"))
        assert table.cursor_coordinate == Coordinate(0, 0)
        assert app.screen is dialog
        assert selected == []
        dialog.query_one("#identity-sami", Button).press()
        await pilot.pause()
        assert selected == [system_choice()]
        catalog.user_assigned_identities.assert_not_called()

    drive(scenario)


def test_slow_existing_identity_load_does_not_replace_the_new_identity_form():
    async def scenario(app, pilot, dialog, selected, catalog):
        started, release = threading.Event(), threading.Event()

        def load():
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test did not release the identity catalog")
            return [identity()]

        catalog.user_assigned_identities.side_effect = load
        try:
            await pilot.press("right", "enter")
            assert await asyncio.to_thread(started.wait, 5)
            assert dialog.query_one("#identity-loading").display
            dialog.query_one("#identity-new", Button).press()
            await pilot.pause()
            dialog.query_one("#identity-name", Input).value = "draft-mi"
            assert app.focused.id == "identity-name"
        finally:
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert dialog.query_one("#identity-new-form").display
        assert not dialog.query_one("#identity-loading").display
        assert not dialog.query_one("#identity-table").display
        assert not dialog.query_one("#identity-filter").display
        assert app.focused.id == "identity-name"
        assert dialog.query_one("#identity-name", Input).value == "draft-mi"
        assert selected == []
        catalog.user_assigned_identities.assert_called_once_with()

    drive(scenario)
