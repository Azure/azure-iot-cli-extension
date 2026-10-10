# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import asyncio
from copy import deepcopy
import json
from threading import Event
from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from textual.widgets import Button, Checkbox, Input, Select, SelectionList, TextArea

from azext_iot.adr.workflows import tui as subject
from azext_iot.adr.workflows import tui_model as model
from azext_iot.adr.workflows.models import SetupRequest


SUB = "00000000-0000-4000-8000-000000000001"
CONFIG = {"namespace": {"name": "ns-test", "resourceGroup": "rg-test"}}
REQUEST = SetupRequest("ns-test", "rg-test", subscription_id=SUB)
PLAN = {
    "state": "Planned",
    "items": [{"id": "namespace", "action": "create", "target": "ns-test", "state": "Planned",
               "command": "az iot adr ns create -n ns-test -g rg-test"}],
}


def values(**updates):
    result = {
        "name": " ns-test ", "group": " rg-test ", "location": "", "tags": "", "outbound": "system-assigned",
        "mode": "skip", "link_identity": "system-assigned", "dps_id": "", "hub_ids": [],
        "count": "1", "sku": "S1", "dps_name": "", "hub_prefix": "", "software_updates": False,
        "cms": False, "validity": "30", "root": "", "intermediate": "", "policy": "",
    }
    result.update(updates)
    return result


def test_form_config_preserves_source_and_endpoint_options():
    original = deepcopy(CONFIG)
    original["namespace"]["tags"] = {"env": "prod"}
    original["links"] = {
        "dps": {"resourceName": "dps", "identity": "system-assigned", "createIfMissing": True},
        "hubs": [{"resourceName": "hub", "identity": "system-assigned", "allocationWeight": 7}],
        "softwareUpdates": {"resourceName": "updates", "identity": "system-assigned"},
    }
    previous = deepcopy(original)
    dps = model.endpoint_id(original["links"]["dps"], "dps", original["namespace"], SUB)
    hub = model.endpoint_id(original["links"]["hubs"][0], "hub", original["namespace"], SUB)
    result = model.form_config(original, values(
        mode="existing", dps_id=dps, hub_ids=[hub, hub, ""], tags="env=prod", software_updates=True,
        location="australiaeast", outbound="/identity",
    ), SUB)
    assert result["links"] == original["links"]
    assert result["namespace"]["outboundIdentity"]["userAssignedResourceId"] == "/identity"
    assert result["namespace"]["location"] == "australiaeast"
    assert original == previous
    assert model.endpoint_id({"resourceId": "/resource"}, "hub", {}, SUB) == "/resource"


def test_form_config_new_targets_and_managed_cms():
    result = model.form_config(CONFIG, values(
        mode="new", count="2", sku="S2", cms=True, root="root", intermediate="ica", policy="devices",
        software_updates=True,
    ), SUB)
    assert len(result["links"]["hubs"]) == 2
    assert result["links"]["dps"]["resourceName"] == "ns-test-provisioning"
    assert result["cms"] == {
        "enabled": True, "validityDays": 30, "rootName": "root",
        "intermediateName": "ica", "policyName": "devices",
    }
    assert "tags" not in result["namespace"]
    assert result["links"]["softwareUpdates"]["createIfMissing"]
    explicit = model.form_config(CONFIG, values(mode="new", dps_name="my-dps", hub_prefix="my-hub"), SUB)
    assert explicit["links"]["hubs"][0]["resourceName"] == "my-hub-1"
    assert explicit["links"]["dps"]["resourceName"] == "my-dps"


def test_form_config_replace_links_and_skip_capabilities():
    data = model.form_config(CONFIG, values(mode="existing", dps_id="/dps", hub_ids=["/hub"]), SUB)
    assert data["links"]["hubs"][0]["resourceId"] == "/hub"
    assert data["links"]["dps"]["resourceId"] == "/dps"
    data["cms"] = {"enabled": True}
    empty = model.form_config(data, values(outbound=""), SUB)
    assert "cms" not in empty and empty["links"] == {}
    assert "outboundIdentity" not in empty["namespace"]
    with pytest.raises(InvalidArgumentValueError, match="10"):
        model.form_config(CONFIG, values(mode="existing", hub_ids=[f"/hub-{i}" for i in range(11)]), SUB)


@pytest.mark.parametrize("tags", ["=bad", "missing", "a=b a=c", "'bad"])
def test_invalid_tags(tags):
    with pytest.raises((ValueError, InvalidArgumentValueError)):
        model.parse_tags(tags)


def test_plan_formatting_is_literal_and_roles_are_visible():
    plan = deepcopy(PLAN)
    plan["items"].extend([
        {"id": "roles-hub", "action": "role", "target": "[red]name", "state": "Planned",
         "message": "Contributor at scope", "command": "az role assignment create"},
        {"id": "blocked", "action": "check", "target": "/target", "state": "Blocked", "message": "No access"},
    ])
    compact = model.plan_text(plan).plain
    assert "[red]name" in compact and "May create" in compact and "No access" in compact
    expanded = model.plan_text(plan, roles=True, commands=True).plain
    assert "Contributor at scope" in expanded and "az role assignment" in expanded
    assert model.plan_fingerprint(plan) == model.plan_fingerprint(deepcopy(plan))


def test_progress_stops_before_next_call_and_reports_errors():
    app = MagicMock()
    app.stop_requested = Event()
    app.call_from_thread.side_effect = lambda function, *args: function(*args)
    progress = subject.SetupProgress(app)
    assert progress.run("read", lambda: 7, workflow_scope="cms", mutation=True) == 7
    operation = MagicMock(side_effect=ValueError("bad"))
    with pytest.raises(ValueError):
        progress.run("write", operation)
    app.operation_status.assert_called_with("Failed: write")
    with pytest.raises(ValueError):
        progress.run("missing", operation, handled_error=lambda _: True)
    app.stop_requested.set()
    operation.reset_mock()
    with pytest.raises(subject.SetupStopped):
        progress.run("stop", operation)
    operation.assert_not_called()


def test_provider_quiet_state_is_restored():
    from azext_iot.adr.providers.base import console

    before = console.quiet
    with pytest.raises(ValueError):
        with subject.quiet_providers():
            assert console.quiet
            raise ValueError("failed")
    assert console.quiet == before


def test_mouse_navigation_disclosure_and_typed_review(mocker):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, deepcopy(CONFIG))
        mocker.patch.object(app, "read_plan", return_value=(REQUEST, deepcopy(PLAN)))
        async with app.run_test(size=(90, 36)) as pilot:
            assert app.focused.id == "name"
            await pilot.click("#next")
            assert app.step == 1
            app.query_one("#mode", Select).value = "new"
            await pilot.pause()
            assert app.query_one("#new-targets").display
            app.query_one("#mode", Select).value = "skip"
            await pilot.click("#next")
            assert app.step == 2
            await pilot.click("#cms")
            assert app.query_one("#cms", Checkbox).value
            assert app.query_one("#cms-options").display
            await pilot.click("#next")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.step == 3 and app.plan == PLAN
            assert app.query_one("#next", Button).disabled
            await pilot.click("#commands")
            assert app.show_commands
            await pilot.click("#roles")
            assert app.show_roles
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            assert not app.query_one("#next", Button).disabled
            await pilot.click("#back")
            assert app.step == 2
            await pilot.click("#step-0")
            assert app.step == 0

    asyncio.run(scenario())


def test_review_invalidates_confirmation_and_preserves_edited_json(mocker, tmp_path):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, deepcopy(CONFIG))
        async with app.run_test(size=(80, 30)) as pilot:
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            changed = deepcopy(PLAN)
            changed["items"][0]["state"] = "Satisfied"
            changed["items"][0]["action"] = "reuse"
            config = deepcopy(CONFIG)
            config["namespace"]["name"] = "ns-other"
            other = SetupRequest("ns-other", "rg-test")
            app.accept_plan(config, other, changed)
            assert app.query_one("#confirm", Input).value == ""
            assert app.query_one("#name", Input).value == "ns-other"
            app.query_one("#save-path", Input).value = str(tmp_path / "request.json")
            app.action_save()
            assert json.loads((tmp_path / "request.json").read_text()) == config
            app.action_save()
            assert "exist" in str(app.query_one("#notice").render()).lower()
            app.query_one("#save-path", Input).value = ""
            app.action_save()
            assert "new file" in str(app.query_one("#notice").render())
            prepare = mocker.patch.object(app, "prepare")
            app.action_retry()
            prepare.assert_called_with(config)
            app.set_busy(True)
            app.action_next()
            app.action_previous()
            app.action_retry()
            app.action_close_setup()
            assert app.stop_requested.is_set()
            assert app.step == 3
            app.set_busy(False)

    asyncio.run(scenario())


def test_apply_rechecks_before_writes_and_reports_completion(mocker):
    async def scenario():
        services = MagicMock()
        app = subject.SetupApp(services, SUB, CONFIG)
        workflow = mocker.patch.object(subject, "NamespaceWorkflow").return_value
        workflow.setup.return_value = {"state": "Succeeded", "items": []}
        mocker.patch.object(app, "read_plan", return_value=(REQUEST, deepcopy(PLAN)))
        async with app.run_test(size=(80, 30)) as pilot:
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            app.action_next()
            await app.workers.wait_for_complete()
            assert app.step == 4
            assert app.result["state"] == "Succeeded"
            assert app.timer is None
            workflow.setup.assert_called_once_with(REQUEST)
            app.action_close_setup()
        assert app.return_value["state"] == "Succeeded"

    asyncio.run(scenario())


def test_apply_changed_plan_does_not_write(mocker):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, CONFIG)
        workflow = mocker.patch.object(subject, "NamespaceWorkflow").return_value
        changed = deepcopy(PLAN)
        changed["items"][0]["state"] = "Satisfied"
        mocker.patch.object(app, "read_plan", return_value=(REQUEST, changed))
        async with app.run_test() as pilot:
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            app.action_next()
            await app.workers.wait_for_complete()
            assert app.step == 3
            assert app.query_one("#confirm", Input).value == ""
            workflow.setup.assert_not_called()

    asyncio.run(scenario())


def test_plan_and_apply_failures_have_retry_and_stop_semantics(mocker):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, CONFIG)
        mocker.patch.object(app, "read_plan", side_effect=ValueError("no access"))
        async with app.run_test() as pilot:
            app.prepare(CONFIG)
            app.prepare(CONFIG)
            await app.workers.wait_for_complete()
            assert not app.busy and app.step == 0
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            app.action_next()
            await app.workers.wait_for_complete()
            assert app.result["state"] == "Failed"
            assert app.query_one("#retry").display
            app.stop_requested.set()
            app.finish_error(ValueError("stopped"), True)
            assert app.result["state"] == "Stopped"
            assert not app.stop_requested.is_set()
            app.set_step(0)
            app.query_one("#group", Input).value = ""
            app.action_next()
            assert app.step == 0

    asyncio.run(scenario())


def test_browsing_mouse_choices_and_stale_results(mocker):
    async def scenario():
        services = MagicMock()
        services.list_namespaces.return_value = [{"name": "existing"}]
        services.list_link_targets.side_effect = [
            [{"id": "/dps", "name": "dps"}], [{"id": "/hub", "name": "hub"}],
        ]
        app = subject.SetupApp(services, SUB, CONFIG)
        async with app.run_test(size=(80, 32)) as pilot:
            await pilot.click("#browse-options CollapsibleTitle")
            await pilot.click("#browse")
            await app.workers.wait_for_complete()
            app.query_one("#namespace-choice", Select).value = "existing"
            await pilot.pause()
            assert app.query_one("#name", Input).value == "existing"
            app.set_step(1)
            app.query_one("#mode", Select).value = "existing"
            await pilot.pause()
            await pilot.click("#targets")
            await app.workers.wait_for_complete()
            app.query_one("#dps-choice", Select).value = "/dps"
            app.query_one("#hub-choices", SelectionList).select("/hub")
            await pilot.pause()
            assert app.query_one("#dps-id", Input).value == "/dps"
            assert app.query_one("#hub-ids", TextArea).text == "/hub"
            app.accept_choices([], [], [], "different-group", False)
            app.query_one("#group", Input).value = ""
            app.browse()
            await app.workers.wait_for_complete()
            assert "resource group" in str(app.query_one("#notice").render())
            app.busy = True
            app.browse()
            await app.workers.wait_for_complete()
            app.busy = False

    asyncio.run(scenario())


def test_read_plan_checks_scope_before_plan(mocker):
    services = MagicMock()
    services.show_resource_group.return_value = {"location": "australiaeast"}
    app = subject.SetupApp(services, SUB)
    mocker.patch.object(subject, "build_setup_request", return_value=REQUEST)
    planner = mocker.patch.object(subject, "NamespaceWorkflow").return_value
    planner.plan_setup.return_value = (PLAN, [])
    request, plan = app.read_plan(CONFIG)
    assert request.location is None
    assert REQUEST.location is None
    assert plan == PLAN
    services.show_subscription.return_value = None
    with pytest.raises(InvalidArgumentValueError, match="subscription"):
        app.read_plan(CONFIG)
    services.show_subscription.return_value = {"id": SUB}
    services.show_resource_group.return_value = None
    with pytest.raises(InvalidArgumentValueError, match="Resource group"):
        app.read_plan(CONFIG)


def test_config_review_entry_and_json_edit(mocker):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, CONFIG, review=True)
        mocker.patch.object(app, "read_plan", return_value=(REQUEST, PLAN))
        async with app.run_test(size=(80, 30)) as pilot:
            await app.workers.wait_for_complete()
            assert app.step == 3
            app.query_one("#json-editor", TextArea).load_text("{bad")
            await pilot.pause()
            assert app.plan is None
            assert app.query_one("#next", Button).disabled
            app.use_json()
            assert not app.busy
            app.query_one("#json-editor", TextArea).load_text(json.dumps(CONFIG))
            app.use_json()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.config["namespace"]["name"] == "ns-test"
            app.set_step(0)
            app.query_one("#name", Input).focus()
            await pilot.press("enter")
            assert app.step == 1
            app.on_button_pressed(Button.Pressed(Button("unknown")))
            app.set_step(3)
            app.on_button_pressed(Button.Pressed(app.query_one("#recheck", Button)))
            await app.workers.wait_for_complete()
            app.on_button_pressed(Button.Pressed(app.query_one("#use-json", Button)))
            await app.workers.wait_for_complete()

    asyncio.run(scenario())


@pytest.mark.parametrize("export_state", ["okay", "roles", "missing-command", "io-error"])
def test_export_plan_commands_without_writes(export_state, tmp_path, mocker):
    async def scenario():
        target = tmp_path / "commands.sh"
        app = subject.SetupApp(MagicMock(), SUB, CONFIG, output_script=str(target))
        plan = deepcopy(PLAN)
        if export_state == "missing-command":
            plan["items"][0].pop("command")
        elif export_state == "roles":
            plan["items"].append({"id": "role", "target": "Grant roles", "action": "role", "state": "Planned"})
        elif export_state == "io-error":
            mocker.patch("azext_iot.adr.workflows.input.write_script_file", side_effect=OSError("not writable"))
        async with app.run_test():
            app.accept_plan(CONFIG, REQUEST, plan)
            if export_state in {"okay", "roles"}:
                assert "az iot adr ns create" in target.read_text()
            else:
                assert not target.exists()
                assert str(app.query_one("#notice").render())
    asyncio.run(scenario())


def test_enter_in_save_path_saves_without_applying_approved_plan(tmp_path, mocker):
    async def scenario():
        target = tmp_path / "safe.json"
        app = subject.SetupApp(MagicMock(), SUB, CONFIG)
        apply = mocker.patch.object(app, "apply_plan")
        async with app.run_test(size=(80, 32)) as pilot:
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.query_one("#confirm", Input).value = "ns-test"
            app.query_one("#save-path", Input).value = str(target)
            app.on_input_submitted(Input.Submitted(app.query_one("#save-path", Input), str(target)))
            await pilot.pause()
            assert json.loads(target.read_text()) == CONFIG
            apply.assert_not_called()
    asyncio.run(scenario())


def test_stopping_read_workers_invalidates_approval():
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, CONFIG)
        async with app.run_test():
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.set_busy(True)
            app.action_stop()
            app.accept_plan(CONFIG, REQUEST, PLAN)
            assert app.plan is None
            assert not app.busy
            assert not app.stop_requested.is_set()
            app.set_busy(True)
            app.action_stop()
            app.accept_choices([], [], [], "rg-test", False)
            assert not app.busy
            assert not app.stop_requested.is_set()
    asyncio.run(scenario())


def test_stop_before_apply_does_not_call_workflow(mocker):
    async def scenario():
        app = subject.SetupApp(MagicMock(), SUB, CONFIG)
        mocker.patch.object(app, "read_plan", return_value=(REQUEST, PLAN))
        workflow = mocker.patch.object(subject, "NamespaceWorkflow").return_value
        async with app.run_test() as pilot:
            app.accept_plan(CONFIG, REQUEST, PLAN)
            app.stop_requested.set()
            app.query_one("#confirm", Input).value = "ns-test"
            await pilot.pause()
            app.action_next()
            await app.workers.wait_for_complete()
            assert app.result["state"] == "Stopped"
            workflow.setup.assert_not_called()
    asyncio.run(scenario())


@pytest.mark.parametrize("source", ["config", "flags", "empty", "identity", "uami"])
def test_launches_with_mouse_and_pinned_subscription(source, mocker):
    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUB)
    build = mocker.patch.object(subject, "build_setup_request", return_value=REQUEST)
    mocker.patch("azext_iot.adr.workflows.services.WorkflowServices")
    app_class = mocker.patch.object(subject, "SetupApp")
    arguments = {"namespace_name": "ns-test", "resource_group_name": "rg-test"}
    config = None
    if source == "config":
        config = CONFIG
    elif source == "flags":
        arguments["dps"] = ["resource-name=dps", "identity=system-assigned"]
    elif source in {"identity", "uami"}:
        arguments["namespace_outbound_identity"] = (
            "system-assigned" if source == "identity"
            else f"/subscriptions/{SUB}/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
        )
    result = subject.run_setup(MagicMock(), config=config, **arguments)
    assert result == app_class.return_value.run.return_value
    app_class.return_value.run.assert_called_once_with(mouse=True)
    assert app_class.call_args.args[1] == SUB
    assert app_class.call_args.kwargs["review"] is bool(config)
    if source in {"config", "flags"}:
        build.assert_called_once()
    else:
        build.assert_not_called()


@pytest.mark.parametrize("state", ["Succeeded", "Failed", "Stopped", None])
def test_cli_tui_routing_preserves_result_and_exit_status(state, mocker):
    from azure.cli.core.azclierror import CLIError
    from azext_iot.adr.workflows import commands

    mocker.patch.object(commands.sys.stdin, "isatty", return_value=True)
    mocker.patch.object(commands.sys.stderr, "isatty", return_value=True)
    mocker.patch.object(commands, "_structured_output_requested", return_value=False)
    result = {"state": state, "items": []} if state else None
    launch = mocker.patch.object(subject, "run_setup", return_value=result)
    persist = mocker.patch.object(commands, "_persist_receipt")
    if state in {"Failed", "Stopped"}:
        with pytest.raises(CLIError, match="did not complete"):
            commands.adr_namespace_setup(MagicMock(), config=json.dumps(CONFIG))
    else:
        assert commands.adr_namespace_setup(MagicMock(), config=json.dumps(CONFIG)) == result
    launch.assert_called_once()
    assert persist.call_count == bool(state)


@pytest.mark.parametrize("complete", [False, True])
def test_partial_json_prefills_form_or_reviews_when_flags_complete_scope(complete, mocker):
    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUB)
    mocker.patch("azext_iot.adr.workflows.services.WorkflowServices")
    app = mocker.patch.object(subject, "SetupApp")
    config = {"namespace": {"resourceGroup": "rg-test"}, "cms": {"enabled": True}, "checkStatus": False}
    arguments = {"namespace_name": "ns-test", "tags": {}} if complete else {}
    subject.run_setup(MagicMock(), config=config, **arguments)
    initial = app.call_args.args[2]
    assert initial["cms"]["enabled"] is True
    assert initial["checkStatus"] is False
    assert app.call_args.kwargs["review"] is complete
    if complete:
        assert initial["namespace"]["tags"] == {}
    assert config["namespace"] == {"resourceGroup": "rg-test"}


@pytest.mark.parametrize("config,arguments,error", [
    ({}, {"dps": ["endpoint=dps"]}, "capability"),
    ({"subscriptionId": "00000000-0000-4000-8000-000000000002"}, {}, "subscription"),
    ({"namespace": {"name": "original"}}, {"namespace_name": "different"}, "conflicts"),
])
def test_partial_json_rejects_conflicts_before_constructing_ui(config, arguments, error, mocker):
    from azure.cli.core.azclierror import ArgumentUsageError

    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUB)
    app = mocker.patch.object(subject, "SetupApp")
    with pytest.raises((InvalidArgumentValueError, ArgumentUsageError), match=error):
        subject.run_setup(MagicMock(), config=config, **arguments)
    app.assert_not_called()
