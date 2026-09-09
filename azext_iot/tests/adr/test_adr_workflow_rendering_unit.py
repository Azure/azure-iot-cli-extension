# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from io import StringIO
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from azext_iot.adr.workflows import rendering as subject
from azext_iot.adr.workflows.models import EndpointSpec, SetupRequest


def _console(stream, force_terminal=False):
    return Console(
        file=stream,
        force_terminal=force_terminal,
        color_system="standard" if force_terminal else None,
        theme=subject._THEME,
        width=100,
    )


def _plain_terminal(stream):
    return subject.Text.from_ansi(stream.getvalue()).plain


def _request():
    return SetupRequest(
        "ns",
        "rg",
        outbound_identity_type="SystemAssigned",
        dps=EndpointSpec(
            "dps", "primary", "/subscriptions/s/dps", "system-assigned"
        ),
        hubs=(
            EndpointSpec(
                "hub",
                "primary",
                "/subscriptions/s/hub",
                "user-assigned",
                "/subscriptions/s/uami",
            ),
        ),
    )


def _plan():
    return {
        "state": "Planned",
        "summary": {
            "Satisfied": 1,
            "Planned": 2,
            "Manual": 1,
            "Blocked": 1,
        },
        "items": [
            {
                "id": "namespace",
                "state": "Planned",
                "action": "create",
                "target": "ns",
                "details": {"location": "eastus"},
            },
            {
                "id": "resource-hub-primary",
                "state": "Planned",
                "action": "validate",
                "target": "hub",
                "message": "exact GET",
            },
            {
                "id": "role-hub-namespace-access",
                "state": "Manual",
                "action": "grant",
                "target": "/hub",
                "command": "az role assignment create",
                "details": {
                    "principalId": "principal",
                    "role": "Contributor",
                },
            },
            {
                "id": "link-hub-primary",
                "state": "Blocked",
                "action": "link",
                "target": "hub",
                "message": "missing role",
            },
            {
                "id": "unknown",
                "state": "Unknown",
                "action": "verify",
                "target": "hub",
            },
        ],
    }


def test_plain_renderer_outputs_all_views(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(stream),
    )
    mocker.patch("builtins.input", return_value="answer")
    assert renderer.prompt("Value: ") == "answer"
    renderer.write("message")
    renderer.header("sub", "rg", "ns")
    renderer.journey("Prepare", "Resources", "Access")
    renderer.phase("Prepare")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    renderer.phase("Prepare")
    renderer.phase("Resources")
    renderer.input_status("Resource group", "rg", "Satisfied", "Found")
    renderer.validation(_plan())
    renderer.trust(_plan())
    renderer.plan(_plan())
    renderer.confirmation(_plan())
    renderer.receipt({
        "namespace": "ns",
        "state": "Succeeded",
        "summary": {"Succeeded": 2},
    })
    renderer.error(RuntimeError("failed"), _plan())
    output = _plain_terminal(stream)
    assert "Azure IoT · Device Registry" in output
    assert output.count("step 1/3") == 1
    assert "✓ subscription" in output
    assert "create      namespace" in output
    assert "location" in output
    assert "link        hub link" in output
    assert "3 change(s)" in output
    assert "Namespace setup complete" in output
    assert "Fix: az role assignment create" in output


def test_plain_execution_reports_success_and_failure():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(stream),
    )
    original_quiet = subject.provider_console.quiet
    with renderer.execution() as execution:
        assert subject.provider_console.quiet is True
        assert execution.run("Successful", lambda: "result") == "result"
        with pytest.raises(RuntimeError, match="boom"):
            execution.run(
                "Failed", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
            )
    assert subject.provider_console.quiet is original_quiet
    output = _plain_terminal(stream)
    assert "[running] Successful" in output
    assert "[done] Successful" in output
    assert "[failed] Failed" in output


def test_rich_execution_and_symbols():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    assert renderer.rich
    renderer.header("sub", "rg", "ns")
    renderer.journey("Prepare", "Resources", "Access")
    renderer.phase("Prepare")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    renderer.phase("Resources")
    workspace = renderer._workspace_ansi("")
    assert "Software Updates" not in workspace
    renderer.validation(_plan())
    renderer.trust(_plan())
    renderer.plan(_plan())
    renderer.confirmation(_plan())
    renderer.receipt({
        "namespace": "ns",
        "state": "Warning",
        "summary": {"Warning": 1},
    })
    renderer.error(RuntimeError("failed"), _plan())
    with renderer.execution() as execution:
        assert execution.run("Successful", lambda: 1) == 1
        with pytest.raises(ValueError):
            execution.run(
                "Failed", lambda: (_ for _ in ()).throw(ValueError("bad"))
            )
    output = _plain_terminal(stream)
    assert "✓" in output
    assert "Successful" in output
    assert "Failed" in output
    assert "step 2/3" in output
    assert "resources" in output


def test_prompt_navigation_commands(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(stream),
    )
    mocker.patch("builtins.input", side_effect=[":help", "value"])
    assert renderer.prompt("Input: ") == "value"
    assert ":back previous input" in stream.getvalue()

    mocker.patch("builtins.input", return_value=":back")
    with pytest.raises(subject.BackRequested):
        renderer.prompt("Input: ")

    mocker.patch("builtins.input", return_value=":quit")
    with pytest.raises(subject.WorkflowCancelled):
        renderer.prompt("Input: ")


def test_rich_renderer_escapes_dynamic_markup():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.write("! bad [value] [/]")
    renderer.input_status(
        "IoT Hub",
        "hub[value]",
        "Blocked",
        "bad [/]",
    )
    output = stream.getvalue()
    assert "[value]" in output
    assert "[/]" in output
    assert "[y/n]" in renderer._workspace_ansi(
        "Apply namespace setup? [y/n]: "
    )


def test_rich_prompt_reuses_workspace(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.header("sub", None, None)
    renderer.journey("Prepare", "Resources")
    renderer.phase("Prepare")
    renderer.write("Configure")
    renderer.write("  1  Namespace identity")
    live_class = mocker.patch.object(subject, "Live")
    prompt = mocker.patch.object(
        renderer._prompt_session,
        "prompt",
        side_effect=[":help", "1"],
    )
    assert renderer.prompt("Selection: ") == "1"
    assert prompt.call_count == 2
    assert prompt.call_args.kwargs["bottom_toolbar"]
    output = _plain_terminal(stream)
    assert output.count("$ az iot adr ns setup") == 1
    assert "step 1/2  ● prepare ── ○ resources" in output
    live_class.return_value.start.assert_called_once_with(refresh=True)
    assert renderer._body.count(
        ":back previous input  ·  :help commands  ·  :quit cancel"
    ) == 1

    renderer.write("Namespace identity configured")
    assert "configured" in renderer._body[-1]
    renderer.close()
    live_class.return_value.stop.assert_called_once()


def test_launch_header_prints_once_and_prompt_is_transient(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.header("sub", None, None)
    renderer.header("sub", "rg", "ns")
    reset = mocker.patch.object(
        renderer._prompt_session.default_buffer, "reset"
    )
    mocker.patch.object(
        renderer._prompt_session, "prompt", return_value="value"
    )

    assert renderer.prompt("Value: ") == "value"
    reset.assert_called_once_with()
    output = _plain_terminal(stream)
    assert output.count("$ az iot adr ns setup") == 1
    assert "$ az iot adr ns setup" not in renderer._workspace_ansi(
        "Value: "
    )


def test_action_mode_accepts_keys_and_labels(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    prompt = mocker.patch.object(
        renderer, "_prompt", side_effect=["retry", "2"]
    )
    actions = {"r": "retry", "q": "quit"}
    assert renderer.action("Recover?", actions) == "r"
    assert renderer.action("Recover?", actions) == "q"
    assert prompt.call_args.kwargs["action_keys"] == {
        "r": "r",
        "q": "q",
    }

    prompt.side_effect = ["", "invalid", "r"]
    assert renderer.action(
        "Default?", actions, default="q"
    ) == "q"
    assert renderer.action("Invalid?", actions) == "r"


def test_action_mode_rotates_prompt_session(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    original = renderer._prompt_session
    mocker.patch.object(original, "prompt", return_value="p")

    assert renderer.action("Review?", {"p": "save"}) == "p"
    assert renderer._prompt_session is not original


def test_action_bindings_submit_single_key():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    event = MagicMock()
    bindings = renderer._action_bindings({"s": "s"})
    binding = next(
        item for item in bindings.bindings if "s" in item.keys
    )
    binding.handler(event)
    event.app.exit.assert_called_with(result="s")
    help_binding = next(
        item for item in bindings.bindings if "?" in item.keys
    )
    help_binding.handler(event)
    event.app.exit.assert_called_with(result="?")


def test_rich_selection_supports_number_and_clears_menu(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    prompt = mocker.patch.object(
        renderer, "_prompt", return_value="2"
    )
    selected = renderer.select(
        "Resources",
        {
            "one": ("one", "First"),
            "two": ("two", "Second"),
        },
    )
    assert selected == "two"
    assert not renderer._body
    assert prompt.call_args.kwargs["completer"]

    prompt.side_effect = ["invalid", "q"]
    with pytest.raises(subject.WorkflowCancelled):
        renderer.select(
            "Resources", {"one": ("one", "First")}
        )

    prompt.side_effect = None
    prompt.return_value = "Exact-Resource"
    assert renderer.select(
        "Resource",
        {"one": ("one", "First")},
        guidance="Type a name or ARM ID.",
        allow_custom=True,
    ) == "Exact-Resource"


def test_configuration_selection_shows_all_options(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.header("sub", "rg", "ns")
    renderer.journey(
        "Subscription",
        "Resource group",
        "Namespace",
        "Configuration",
    )
    renderer.phase("Configuration")
    snapshots = []

    def prompt(*_, **__):
        snapshots.append(renderer._workspace().plain)
        return "done"

    mocker.patch.object(renderer, "_prompt", side_effect=prompt)
    assert renderer.select(
        "Configuration — every item is optional",
        {
            "identity": ("identity", "Outbound identity          pending"),
            "hub": ("hub", "Link IoT Hub               pending"),
            "done": ("done", "Done → review plan"),
        },
    ) == "done"
    assert "1  Outbound identity" in snapshots[0]
    assert "2  Link IoT Hub" in snapshots[0]
    assert "3  Done → review plan" in snapshots[0]
    assert "Workflow  ─" not in snapshots[0]


def test_prompt_reserves_space_for_completions_below_input(mocker):
    session = mocker.patch.object(subject, "PromptSession")
    subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    assert session.call_args.kwargs["reserve_space_for_menu"] == 8


def test_plain_selection_prints_choices(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup", plain=True, console=_console(stream)
    )
    mocker.patch("builtins.input", return_value="1")
    assert renderer.select(
        "Resources", {"one": ("one", "First")}
    ) == "one"
    assert "1  First" in stream.getvalue()

    mocker.patch("builtins.input", side_effect=["invalid", "1"])
    assert renderer.select(
        "Resources", {"one": ("one", "First")}
    ) == "one"
    assert "Choose a listed number or name" in stream.getvalue()


def test_plain_action_feedback_is_visible(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup", plain=True, console=_console(stream)
    )
    mocker.patch(
        "builtins.input", side_effect=["invalid", "r"]
    )
    assert renderer.action(
        "Recover?", {"r": "retry", "q": "quit"}
    ) == "r"
    renderer.write("! resource not found")
    renderer.busy("loading resources…")
    output = stream.getvalue()
    assert "[r] retry · [q] quit" in output
    assert "Choose one of the highlighted keys" in output
    assert "! resource not found" in output
    assert "[working] loading resources" in output


def test_resource_choices_hidden_until_filtering():
    base = subject.FuzzyWordCompleter(["hub-one", "hub-two"])
    completer = subject.InputFilteredCompleter(base)
    assert not list(
        completer.get_completions(
            Document(""), CompleteEvent()
        )
    )
    completions = list(
        completer.get_completions(
            Document("one"), CompleteEvent()
        )
    )
    assert any(item.text == "hub-one" for item in completions)


def test_picker_has_one_completion_per_resource(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    captured = {}

    def prompt(*_, **kwargs):
        captured["completer"] = kwargs["completer"]
        captured["workspace"] = renderer._workspace().plain
        return "adr-vnext-scale-rg-10"

    mocker.patch.object(renderer, "_prompt", side_effect=prompt)
    assert renderer.select(
        "Resource group",
        {
            "one": (
                "adr-vnext-scale-rg-10",
                "adr-vnext-scale-rg-10 · centraluseuap",
                "adr-vnext-scale-rg-10",
            )
        },
        allow_custom=True,
        show_options=False,
    ) == "adr-vnext-scale-rg-10"
    completions = list(
        captured["completer"].get_completions(
            Document("adr-vnext"), CompleteEvent()
        )
    )
    assert len(completions) == 1
    assert completions[0].text == (
        "adr-vnext-scale-rg-10 · centraluseuap"
    )
    assert "1  adr-vnext-scale-rg-10" not in captured["workspace"]


def test_picker_shows_search_context_and_notice(mocker):
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.account({
        "subscriptionId": "sub",
        "subscriptionName": "Production",
    })
    renderer.search_context("rg")
    snapshots = []

    def prompt(*_, **__):
        snapshots.append(renderer._workspace().plain)
        return "1"

    mocker.patch.object(renderer, "_prompt", side_effect=prompt)
    assert renderer.select(
        "IoT Hub", {"one": ("hub", "hub")}
    ) == "hub"
    renderer.notice("Plan saved: plan.json")
    assert "searched         rg · Production" in snapshots[0]
    assert "Plan saved: plan.json" in _plain_terminal(stream)
    renderer.search_context("rg")
    renderer.clear_search_context()
    assert renderer._search_context is None


def test_picker_keybindings_do_not_traverse_history():
    event = MagicMock()
    buffer = event.current_buffer
    buffer.complete_state = None
    buffer.text = ""
    subject.WorkflowRenderer._up_key(event)
    subject.WorkflowRenderer._down_key(event)
    buffer.start_completion.assert_not_called()
    buffer.history_backward.assert_not_called()

    buffer.text = "hub"
    subject.WorkflowRenderer._up_key(event)
    subject.WorkflowRenderer._down_key(event)
    assert buffer.start_completion.call_count == 2

    buffer.complete_state = object()
    subject.WorkflowRenderer._up_key(event)
    subject.WorkflowRenderer._down_key(event)
    buffer.complete_previous.assert_called_once()
    buffer.complete_next.assert_called_once()

    subject.WorkflowRenderer._back_key(event)
    event.app.exit.assert_called_once_with(result=":back")


def test_validation_error_stays_with_visible_actions(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.write("! resource not found")
    snapshots = []

    def prompt(*_, **__):
        snapshots.append(renderer._workspace().plain)
        return "2"

    mocker.patch.object(renderer, "_prompt", side_effect=prompt)
    assert renderer.select(
        "Next action",
        {
            "retry": ("retry", "Retry"),
            "edit": ("edit", "Edit input"),
            "quit": ("quit", "Quit"),
        },
    ) == "edit"
    assert "! resource not found" in snapshots[0]
    assert "1  Retry" in snapshots[0]
    assert "2  Edit input" in snapshots[0]
    assert "3  Quit" in snapshots[0]


def test_busy_status_and_step_bar_follow_scope():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.journey(
        "Subscription",
        "Resource group",
        "Namespace",
        "Configuration",
    )
    renderer.phase("Resource group")
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.busy("validating resource group…")
    workspace = renderer._workspace()
    output = workspace.plain
    assert "⠋ validating resource group" in output
    history = _plain_terminal(stream)
    assert "✓ subscription      sub · Found" in history
    assert (
        "step 2/4  ✔ subscription ── ● resource group "
        "── ○ namespace ── ○ configuration"
    ) in history
    for token in ("⠋", ":back", ":help", ":quit"):
        offset = output.index(token)
        assert any(
            span.start <= offset < span.end and span.style == "active"
            for span in workspace.spans
        )
    renderer.idle()
    assert renderer._busy is None
    renderer.close()


def test_summary_deduplicates_and_marks_staged_input():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.input_status(
        "Namespace", "new", "Planned", "Will be created"
    )
    renderer.input_status(
        "Namespace", "new", "Planned", "Will be created"
    )
    renderer.input_status("Other", "value", "Planned")
    output = _plain_terminal(stream)
    assert output.count("namespace         new") == 1
    assert "Will be created · nothing written yet" in output
    assert "other             value · nothing written yet" in output


def test_subphases_map_to_real_steps():
    setup = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    setup.journey(
        "Subscription", "Resource group", "Namespace", "Configuration"
    )
    setup.phase("Apply")
    assert setup._active_stage() == "Configuration"

    check = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(StringIO(), force_terminal=True),
    )
    check.journey("Scope", "Resources", "Access", "Results")
    check.phase("Subscription")
    assert check._active_stage() == "Scope"
    check.phase("Links")
    assert check._active_stage() == "Results"


def test_rich_prompt_hands_visible_card_to_next_prompt(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    live_class = mocker.patch.object(subject, "Live")
    mocker.patch.object(
        renderer._prompt_session,
        "prompt",
        side_effect=["first", "second"],
    )
    assert renderer.prompt("First: ") == "first"
    first_live = live_class.return_value
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    first_live.stop.assert_called_once()

    assert renderer.prompt("Second: ") == "second"
    assert first_live.stop.call_count == 1
    assert live_class.call_count == 2
    renderer.close()


def test_plain_renderer_close_is_noop():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    renderer.close()


def test_renderer_cancelled_is_neutral():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.cancelled()
    output = stream.getvalue()
    assert "Namespace setup cancelled" in output
    assert "Nothing was changed." in output
    assert "failed" not in output
    assert "nonzero" not in output


def test_workspace_reset_preserves_scope():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.input_status("Subscription", "sub", "Satisfied", "Found")
    renderer.input_status("Resource group", "rg", "Satisfied", "Found")
    renderer.input_status("Namespace", "ns", "Satisfied", "Found")
    renderer.input_status("IoT Hub", "hub", "Satisfied", "Found")
    renderer._tasks.append({"state": "Succeeded", "target": "task"})
    renderer._body.append("old")

    renderer.reset_setup()

    assert not renderer._tasks
    assert not renderer._body
    assert renderer._phase == "Configuration"


def test_workspace_plan_is_bounded():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.journey("Review", "Apply")
    renderer.phase("Review")
    plan = {
        "summary": {"Planned": 10},
        "items": [
            {
                "state": "Planned",
                "action": "create",
                "target": f"item-{index}",
            }
            for index in range(10)
        ],
    }
    renderer.plan(plan)
    output = stream.getvalue()
    assert "╭" not in output
    assert "item-7" in output
    assert "item-9" in output
    assert "10 actions · awaiting confirmation" in output


def test_dense_plan_tags_confirmation_and_elapsed():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    plan = {
        "summary": {"Planned": 1},
        "items": [{
            "id": "namespace",
            "state": "Planned",
            "action": "create",
            "target": "factory",
            "details": {
                "location": "eastus",
                "tags": {"env": "prod", "team": "devices"},
            },
        }],
    }
    renderer.plan(plan)
    renderer.confirmed()
    renderer._execution_started = subject.time.monotonic() - 2
    renderer.receipt({
        "namespace": "factory",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Succeeded": 1},
        "items": [],
    })
    output = _plain_terminal(stream)
    assert "create      namespace" in output
    assert "tags" in output
    assert "env=prod, team=devices" in output
    assert "1 actions · awaiting confirmation" in output
    assert "1 actions · confirmed" in output
    assert "Elapsed:" in output


@pytest.mark.parametrize(
    "item_id, subject_name",
    [
        ("namespace-outbound-identity", "outbound identity"),
        ("namespace-tags", "namespace tags"),
        ("resource-hub-main", "target resource"),
        ("link-hub-main", "hub link"),
        ("role-hub-main", "access"),
        ("skip-dps", "target"),
        ("namespace-status", "namespace status"),
        ("other", "target"),
    ],
)
def test_dense_plan_column_mapping(item_id, subject_name):
    _, actual_subject, _ = subject.WorkflowRenderer._plan_columns({
        "id": item_id,
        "state": "Planned",
        "action": "configure",
        "target": "target",
        "details": {"identityType": "SystemAssigned"},
    })
    assert actual_subject == subject_name


def test_structured_failure_metadata_and_partial_count():
    class ServiceError(RuntimeError):
        error_code = "AuthorizationFailed"
        status_code = 403
        retry_count = 3

    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer._plan_actions = 5
    renderer.error(
        ServiceError("access denied"),
        {
            "items": [
                {"state": "Succeeded", "target": f"kept-{index}"}
                for index in range(4)
            ] + [{"state": "Failed", "target": "access"}],
        },
    )
    output = _plain_terminal(stream)
    assert "1 of 5 actions failed · 4 of 5 kept" in output
    assert "code          AuthorizationFailed" in output
    assert "status        403" in output
    assert "retries       3" in output


def test_failure_includes_step_elapsed_and_response_status():
    error = RuntimeError("failed")
    error.response = MagicMock(status_code=429)
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer._failure = {
        "label": "Configure access",
        "elapsed": 1.25,
        "error": error,
    }
    renderer.error(error)
    output = _plain_terminal(stream)
    assert "step          Configure access" in output
    assert "elapsed       1.2s" in output
    assert "status        429" in output


def test_recovery_and_active_workspace_variants(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    action = mocker.patch.object(renderer, "action", return_value="c")
    assert renderer.recovery(can_continue=True) == "c"
    assert "c" in action.call_args.args[1]
    assert renderer.failure is None

    renderer._tasks[:] = [{"target": "task"}]
    renderer._execution_started = subject.time.monotonic()
    renderer._execution_total = 2
    renderer._execution_completed = 1
    renderer._body[:] = ["body", "second"]
    renderer._busy = "busy"
    renderer._alert = "! alert"
    output = renderer._workspace().plain
    assert "Applying  1/2" in output
    assert "body\nsecond" in output
    assert "⠋ busy" in output
    assert "! alert" in output


def test_check_trust_and_phase_fallbacks():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(stream, force_terminal=True),
    )
    renderer.trust({
        "items": [{
            "state": "Manual",
            "action": "grant",
            "target": "/scope",
            "details": {"role": "Contributor"},
        }],
    })
    output = _plain_terminal(stream)
    assert "resolved at apply" in output
    assert "Contributor" in output

    renderer.journey("Scope", "Results")
    renderer.phase("Namespace")
    assert renderer._active_stage() == "Scope"
    renderer.phase("Links")
    assert renderer._active_stage() == "Results"
    renderer.phase("Other")
    assert renderer._active_stage() == "Scope"


def test_execution_exit_stops_active_live():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    execution = subject.WorkflowExecution(renderer)
    live = MagicMock()
    execution.live = live
    assert not execution.__exit__(None, None, None)
    live.stop.assert_called_once()


def test_failure_scope_and_retry_timing_are_cumulative(mocker):
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    execution = subject.WorkflowExecution(renderer)

    clock = mocker.patch.object(
        subject.time, "monotonic", side_effect=[10.0, 20.0]
    )
    execution.__enter__()  # pylint: disable=unnecessary-dunder-call
    renderer._execution_completed = 4
    execution.__enter__()  # pylint: disable=unnecessary-dunder-call
    assert renderer._execution_started == 10.0
    assert renderer._execution_completed == 0
    assert clock.call_count == 1


def test_execution_records_explicit_failure_scope():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    execution = subject.WorkflowExecution(renderer)
    with pytest.raises(RuntimeError):
        execution.run(
            "Wait for updates",
            lambda: (_ for _ in ()).throw(RuntimeError("failed")),
            workflow_scope="software-updates",
        )
    assert renderer.failure["scope"] == "software-updates"


def test_execution_suppresses_expected_branch_failure():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    execution = subject.WorkflowExecution(renderer)
    with pytest.raises(ValueError):
        execution.run(
            "Find optional resource",
            lambda: (_ for _ in ()).throw(ValueError("missing")),
            workflow_scope="software-updates",
            handled_error=lambda error: isinstance(error, ValueError),
        )
    assert renderer.failure is None


def test_execution_tracks_successful_mutated_scopes():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        plain=True,
        console=_console(StringIO()),
    )
    execution = subject.WorkflowExecution(renderer)
    execution.run(
        "Create role",
        lambda: None,
        workflow_scope="software-updates",
        mutation=True,
    )
    assert renderer.mutated_scopes == frozenset(
        {"software-updates"}
    )


def test_workspace_confirmation_replaces_ephemeral_body():
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.write("old input")
    renderer.confirmation(_plan())
    renderer.write("invalid answer")
    renderer.confirmation(_plan())
    assert renderer._body == [
        "3 change(s) · Atomic link commands own service role validation and creation.",
        "Successful operations are preserved if a later step fails.",
    ]


@pytest.mark.parametrize(
    "item_id, action, expected",
    [
        ("namespace", "reuse", "Use namespace"),
        (
            "namespace-outbound-identity",
            "configure",
            "Configure namespace outbound identity",
        ),
        (
            "resource-software-updates-main",
            "create",
            "Create Update Instance",
        ),
        (
            "resource-software-updates-main",
            "validate",
            "Validate Update Instance",
        ),
        ("resource-dps-main", "validate", "Validate DPS"),
        ("resource-hub-main", "validate", "Validate IoT Hub"),
        ("link-dps-main", "link", "Configure DPS link"),
        ("link-hub-main", "link", "Configure IoT Hub link"),
        (
            "link-software-updates-main",
            "link",
            "Configure Software Updates link",
        ),
        ("roles-hub-main", "grant", "Configure access"),
        ("hub-prerequisite", "validate", "Check Hub prerequisite"),
        ("skip-dps", "skip", "Skip target"),
        ("namespace-status", "check", "Check namespace status"),
        ("other", "update", "Update target"),
    ],
)
def test_workspace_plan_labels(item_id, action, expected):
    assert expected in subject.WorkflowRenderer._plan_label({
        "id": item_id,
        "action": action,
        "target": "target",
    })


def test_workspace_plan_details_and_empty_sections():
    item = {
        "id": "link-hub-main",
        "state": "Planned",
        "action": "link",
        "target": "main",
        "message": "needed",
        "details": {
            "resourceId": "/hub",
            "userAssignedIdentity": "/uami",
            "role": "Contributor",
            "principalId": "principal",
            "location": "eastus",
        },
    }
    details = subject.WorkflowRenderer._plan_details(item)
    assert details == [
        ("Target", "/hub"),
        ("Identity", "/uami"),
        ("Role", "Contributor"),
        ("Principal", "principal"),
        ("Location", "eastus"),
        ("Reason", "needed"),
    ]
    content = subject.WorkflowRenderer._plan_row(item)
    assert "hub link" in content.plain
    assert "principal" in content.plain

    renderer = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(StringIO(), force_terminal=True),
    )
    renderer.validation({"items": []})
    renderer.trust({"items": []})

    renderer.account({
        "subscriptionId": "sub",
        "userName": "user@example.com",
        "tenantId": "tenant",
    })
    renderer.journey("One", "Two")
    renderer.phase("Unknown")
    output = _plain_terminal(renderer.console.file)
    assert "account" in output
    assert "user@example.com · tenant" in output
    assert "account" in output


def test_manual_receipt_includes_rbac_and_resume():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(stream, force_terminal=True),
    )
    renderer.header("sub", "rg", "ns")
    renderer.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Manual",
        "summary": {"Manual": 1},
        "items": [{
            "id": "role-hub",
            "state": "Manual",
            "action": "grant",
            "target": "/hub",
            "command": "az role assignment create",
        }],
        "receipt": "/tmp/receipt.json",
    })
    output = stream.getvalue()
    assert "az role assignment create" in output
    assert "Resume: az iot adr ns setup" in output
    assert "Receipt: /tmp/receipt.json" in output


def test_receipts_render_check_and_link_details():
    check_stream = StringIO()
    check = subject.WorkflowRenderer(
        "Namespace check",
        console=_console(check_stream, force_terminal=True),
    )
    check.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Satisfied": 1},
        "items": [{
            "state": "Satisfied",
            "target": "namespace",
            "message": "ready",
        }],
    })
    assert "namespace: ready" in check_stream.getvalue()

    setup_stream = StringIO()
    setup = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(setup_stream, force_terminal=True),
    )
    setup.header("sub", "rg", "ns")
    setup.receipt({
        "namespace": "ns",
        "resourceGroup": "rg",
        "state": "Succeeded",
        "summary": {"Succeeded": 1},
        "items": [{
            "id": "link-hub-main",
            "state": "Succeeded",
            "action": "link",
            "target": "main",
            "details": {"principalId": "principal"},
        }],
    })
    output = setup_stream.getvalue()
    assert "Configure IoT Hub link: main" in output
    assert "Identity principal: principal" in output
    assert "Resource ID:" in output

    error_stream = StringIO()
    error_renderer = subject.WorkflowRenderer(
        "Namespace setup",
        console=_console(error_stream, force_terminal=True),
    )
    error_renderer.error(
        RuntimeError("failed"),
        {
            "receipt": "/tmp/failure.json",
            "receiptError": "secondary write failed",
            "items": [{
                "state": "Succeeded",
                "target": "namespace",
            }],
        },
    )
    error_output = error_stream.getvalue()
    assert "1 of 2 kept" in error_output
    assert "Receipt: /tmp/failure.json" in error_output
    assert "Receipt write failed: secondary write failed" in error_output


def test_plain_account_and_role_confirmation():
    stream = StringIO()
    renderer = subject.WorkflowRenderer(
        "Namespace setup", plain=True, console=_console(stream)
    )
    renderer.account({
        "userName": "user@example.com",
        "tenantId": "tenant",
    })
    renderer.confirmation({
        "summary": {"Planned": 1},
        "items": [{
            "action": "grant",
            "state": "Planned",
        }],
    })
    output = stream.getvalue()
    assert "account" in output
    assert "user@example.com · tenant" in output
    assert "1 missing role assignment(s) will be created" in output


def test_renderer_creates_default_console():
    renderer = subject.WorkflowRenderer("Namespace check", plain=True)
    assert renderer.console


def test_redirected_stdin_disables_rich(mocker):
    mocker.patch.object(subject.sys.stdin, "isatty", return_value=False)
    renderer = subject.WorkflowRenderer("Namespace check")
    assert not renderer.rich
