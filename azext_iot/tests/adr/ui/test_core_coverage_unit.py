# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Boundary contracts for command rendering, cached rows and operation tracking."""

import shlex
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from azext_iot.adr.ui.core import commands, ops, rbac
from azext_iot.adr.ui.core.redaction import REDACTED, redact
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.core.spec import ChildRef, SpecError, state_style, validate_spec
from azext_iot.adr.ui.core.store import Store
from azext_iot.adr.ui.core.table import LoadState, TableModel
from azext_iot.tests.adr.ui.conftest import make_payload, widget_spec


@pytest.mark.parametrize("command", [
    r'az rest --url "https://example.test/a b" --body "{\"name\":\"a b\"}"',
    r"az group show --name escaped\ name --query 'a\b'  ",
    "az group show\t --name 'it'\"'\"'s a group'",
])
def test_wrapped_commands_preserve_quoted_and_escaped_shell_arguments(command):
    wrapped = commands.wrap(command, width=16)
    assert " \\\n" in wrapped
    assert shlex.split(wrapped.replace("\\\n", "")) == shlex.split(command)


def test_render_preserves_values_and_avoids_duplicate_name_flags():
    rendered = commands.render(
        "iot adr ns job show", name="job with spaces",
        scope={"namespace_name": "ns;literal", "resource_group_name": "rg", "run_name": "ignored"},
        options={"limit": 0, "enabled": False, "--query": "a[0]", "empty": "", "absent": None},
    )
    assert shlex.split(rendered) == [
        "az", "iot", "adr", "ns", "job", "show", "-n", "job with spaces",
        "--ns", "ns;literal", "-g", "rg", "--limit", "0", "--enabled", "False", "--query", "a[0]",
    ]


def test_operation_terminal_descriptions_and_clear(monkeypatch):
    monkeypatch.setattr(ops.time, "monotonic", lambda: 165.0)
    tracker = ops.OperationTracker()
    completed = tracker.start("Update", "one", refreshes=("namespace", "link"))
    completed.started_at = 100.0
    tracker.succeed(completed)
    duplicate = tracker.start("Update", "two", refreshes=("link", "group"))
    tracker.succeed(duplicate)
    failed = tracker.start("Delete", "three", refreshes=("job",))
    tracker.fail(failed, ValueError("denied"))
    assert ops.OpState.RUNNING.is_terminal is False
    assert completed.state.is_terminal is True
    assert failed.state.is_terminal is True
    assert completed.describe() == "Update one - succeeded in 01:05"
    assert failed.describe() == "Delete three - failed: denied"
    assert tracker.summary() == failed.describe()
    assert tracker.refresh_targets() == ("link", "group", "namespace")
    tracker.clear()
    assert not tracker.operations
    assert tracker.summary() == ""


def test_session_waiter_delegates_terminal_polling_and_propagates_errors():
    provider = Mock()
    provider._await_terminal.return_value = {"state": "Succeeded"}
    session = Mock()
    session.provider.return_value = provider
    poller = object()
    waiter = ops.make_session_waiter(session)
    assert waiter(poller) == {"state": "Succeeded"}
    session.provider.assert_called_once_with("namespace")
    provider._await_terminal.assert_called_once_with(poller)
    provider._await_terminal.side_effect = RuntimeError("endpoint failed")
    with pytest.raises(RuntimeError, match="endpoint failed"):
        waiter(poller)


def test_poller_without_waiter_fails_closed():
    tracker = ops.OperationTracker()
    operation = tracker.start("Update", "ns")
    poller = Mock()
    assert tracker.await_poller(operation, poller) is operation
    assert operation.state is ops.OpState.FAILED
    assert "without a waiter" in operation.error
    poller.result.assert_not_called()


def test_embedded_permissions_cli_inherits_context_without_invoking_azure(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("azext_iot.common.embedded_cli.EmbeddedCLI", factory)
    context = object()
    session = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=context))
    assert rbac._embedded_cli(session) is factory.return_value
    factory.assert_called_once_with(cli_ctx=context, capture_stderr=True)
    factory.return_value.invoke.assert_not_called()


@pytest.mark.parametrize("payload", [None, [], {}, {"value": {}}, {"value": None}])
def test_malformed_permissions_response_is_unknown_not_allowed(monkeypatch, payload):
    result = Mock()
    result.success.return_value = True
    result.as_json.return_value = payload
    cli = Mock()
    cli.invoke.return_value = result
    monkeypatch.setattr(rbac, "_embedded_cli", lambda session: cli)
    context = SimpleNamespace(cloud=SimpleNamespace(
        endpoints=SimpleNamespace(resource_manager="https://arm.example.test/")))
    session = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=context))
    assert rbac.permissions_at_scope(session, "/subscriptions/sub/resourceGroups/rg", ["*/write"]) is None
    assert "--method get" in cli.invoke.call_args.args[0]


def test_permissions_without_scope_never_constructs_cli(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(rbac, "_embedded_cli", factory)
    assert rbac.permissions_at_scope(None, "", ["*/write"]) is None
    factory.assert_not_called()


def test_redaction_copies_nested_tuples_without_touching_original():
    original = ({"PrimaryKey": "secret", "safe": [1, {"SharedAccessKey": "other"}]}, "plain")
    redacted = redact(original)
    assert redacted == ({"PrimaryKey": REDACTED, "safe": [1, {"SharedAccessKey": REDACTED}]}, "plain")
    assert original[0]["PrimaryKey"] == "secret"
    assert redacted[0] is not original[0]


def test_store_clear_evicts_all_scopes_and_kinds(spec):
    store = Store(clock=lambda: 10.0)
    loader = Mock(return_value=[make_payload("old")])
    store.fetch(spec, {"namespace_name": "one"}, loader)
    store.fetch(spec, {"namespace_name": "two"}, loader)
    store.fetch(widget_spec(kind="gadget"), {}, loader)
    store.clear()
    loader.return_value = [make_payload("new")]
    assert store.fetch(spec, {"namespace_name": "one"}, loader)[0]["name"] == "new"
    assert store.entry(spec.kind, {"namespace_name": "two"}).has_loaded is False
    assert store.entry("gadget", {}).has_loaded is False
    assert loader.call_count == 4


def test_spec_summary_defaults_and_declared_relationships(registry, spec):
    assert registry.children_of(spec.kind) == (ChildRef("gadget", "Gadgets", "g"),)
    assert spec.summarize_rows([]) == "None in the current scope"
    assert replace(spec, requires=("namespace_name",)).summarize_rows([]) == "None in this namespace"
    assert spec.summarize_rows([make_payload(str(i)) for i in range(5)]) == "0, 1, 2, +2 more"
    assert state_style({"properties": {"provisioningState": "", "status": "succeeded"}}, "provisioningState", "status") == "ok"


@pytest.mark.parametrize("overrides, message", [
    ({"kind": ""}, "requires a non-empty kind"),
    ({"row_id": None}, "has no row_id"),
    ({"columns": widget_spec().columns * 2}, "duplicate column keys"),
])
def test_invalid_specs_rejected_before_registration(overrides, message):
    with pytest.raises(SpecError, match=message):
        validate_spec(widget_spec(**overrides))


@pytest.mark.parametrize("state, expected", [(state, state in (LoadState.READY, LoadState.STALE)) for state in LoadState])
def test_load_state_only_reports_rows_when_data_is_retained(state, expected):
    assert state.has_rows is expected


def test_table_safe_selection_filter_and_marks(spec):
    model = TableModel(spec)
    model.apply([make_payload("b"), make_payload("a")])
    row = model.row_at(0)
    assert row.id == "a"
    assert row.cell(0) == "a"
    assert row.cell(-1) == row.cell(100) == ""
    assert model.row_at(-1) is model.row_at(2) is None
    assert model.index_of("missing") is None
    assert model.toggle_mark("missing") is False
    model.set_filter(" B ")
    assert model.row_at(0).id == "b"
    assert model.index_of("a") is None
    assert model.status_text() == "1 of 2 widgets"
    model.clear_filter()
    model.cycle_sort("name")
    assert [row.id for row in model.rows] == ["b", "a"]


def test_table_mixed_values_sort_falls_back_to_text_and_ignores_unknown_column(spec):
    model = TableModel(spec)
    model.apply([make_payload("integer", count=10), make_payload("text", count="2"),
                 make_payload("empty", count=None)])
    model.set_sort("count")
    assert [row.id for row in model.rows] == ["empty", "integer", "text"]
    model.set_sort("removed-column")
    assert model.sort_key == "count"
    # A stale persisted sort preference must not prevent a subsequent row refresh.
    model.sort_key = "removed-column"
    diff = model.apply([make_payload("replacement")])
    assert [row.id for row in diff.added] == ["replacement"]
    assert model.row_at(0).id == "replacement"


def test_empty_table_names_namespace_scope(spec):
    model = TableModel(replace(spec, requires=("namespace_name",)))
    model.apply([])
    assert model.status_text() == "This namespace has no widgets."


def test_command_subscription_override_matches_profile_factory_and_planned_resource_scope(monkeypatch):
    from azure.cli.core import get_default_cli
    from azure.cli.core._profile import Profile
    from azext_iot.adr.ui.screens.onboard.create import CreateRequest
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    cli_ctx = get_default_cli()
    subscriptions = [
        {"id": "subscription-a", "name": "Persisted default A", "isDefault": True},
        {"id": "subscription-b", "name": "Command override B", "isDefault": False},
    ]
    monkeypatch.setattr(Profile, "load_cached_subscriptions", lambda self: subscriptions)
    monkeypatch.setitem(cli_ctx.data, "subscription_id", "subscription-b")
    assert Profile(cli_ctx=cli_ctx).get_subscription()["id"] == "subscription-a"
    client_factory = Mock()
    credential = Mock()
    monkeypatch.setattr("azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient", client_factory)
    monkeypatch.setattr("azext_iot._factory.get_cli_credential", credential)
    session = Session(SimpleNamespace(cli_ctx=cli_ctx))
    assert session.resolve_subscription() == "subscription-b"
    assert session.scope.subscription_name == "Command override B"
    provider = session.provider("namespace")
    assert provider is session.provider("namespace")
    assert client_factory.call_args.kwargs["subscription_id"] == "subscription-b"
    credential.assert_called_once_with(cli_ctx, subscription_id="subscription-b")
    screen = OnboardScreen(session, session.scope.as_dict())
    screen.context["create_resource_group"] = CreateRequest("resource_group", "new-rg", "new-rg", "eastus2")
    requirements = screen._permission_requirements()
    assert "/subscriptions/subscription-b" in requirements
    assert all("subscription-a" not in scope for scope in requirements)
    assert Profile(cli_ctx=cli_ctx).get_subscription()["id"] == "subscription-a"
    client_factory.return_value.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("force", [False, True])
def test_loaded_cache_respects_every_backoff_deadline_and_recovers(spec, force):
    now = 100.0
    store = Store(clock=lambda: now)
    payload = make_payload("cached")
    loader = Mock(return_value=[payload])
    assert store.fetch(spec, {}, loader) == [payload]
    loader.side_effect = RuntimeError("throttled")
    now += 5
    for failures, delay in enumerate((5, 10, 20, 40, 80, 120, 120), start=1):
        result = store.fetch_result(spec, {}, loader, force=force)
        assert result.stale and result.payloads == [payload]
        entry = store.entry(spec.kind, {})
        assert entry.failures == failures
        assert entry.next_attempt_at == now + delay
        calls = loader.call_count
        deadline = entry.next_attempt_at
        for tick in range(1, delay):
            now = deadline - delay + tick
            blocked = store.fetch_result(spec, {}, loader, force=force)
            assert blocked.error == "throttled"
            assert blocked.loaded_at == 100.0
            assert loader.call_count == calls
        now = deadline
    loader.side_effect = None
    loader.return_value = [make_payload("fresh")]
    recovered = store.fetch_result(spec, {}, loader, force=force)
    assert not recovered.stale
    assert recovered.error is None
    assert recovered.payloads == [make_payload("fresh")]
    assert recovered.loaded_at == now
    assert store.entry(spec.kind, {}).failures == 0
    assert store.entry(spec.kind, {}).next_attempt_at == 0
    assert loader.call_count == 9
