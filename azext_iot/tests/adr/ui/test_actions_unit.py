# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Provider-bound CRUD, exact previews, release guards and link recovery contracts."""

import shlex
from unittest.mock import Mock

import pytest

from azext_iot.adr.ui.core.actions import Field, TAGS, VALIDITY, provider_action
from azext_iot.adr.ui.core.session import Session, SessionError
from azext_iot.adr.ui.kinds import build_registry
from azext_iot.adr.ui.kinds.link_actions import TYPES, build_actions

SCOPE = {"subscription_id": "sub", "namespace_name": "ns", "resource_group_name": "rg",
         "certificate_authority_name": "ica"}


def session_for(provider, creating=False):
    session = Session(None)
    session.scope.subscription_id = "sub"
    target = Mock()
    target.show.return_value = {"name": "one", "etag": "v1", "properties": {
        "certificateAuthorityType": "ICA", "issuer": {"issuerType": "Microsoft", "status": "Active"},
    }}
    if creating:
        target.show.side_effect = SessionError("missing", status_code=404)
    session._providers[provider] = target
    return session, target


@pytest.mark.parametrize("kind,provider", [
    ("namespace", "namespace"), ("device", "device"), ("group", "group"),
    ("job", "job"), ("ca", "certificate_authority"), ("policy", "certificate_policy"),
    ("su", "update_instance"),
])
def test_every_crud_action_passes_same_values_as_preview(kind, provider):
    registry = build_registry(None)
    for action in registry.get(kind).actions:
        session, target = session_for(provider, action.collection)
        values = {
            field.key: field.parse(field.default or (
                "*" if field.key == "query_string" else "" if field.optional else "one"
            ))
            for field in action.fields
        }
        payload = {"name": "one", "etag": "v1", "_inputs": values}
        getattr(target, action.name).return_value = {"sent": True}
        command = shlex.split(action.preview(SCOPE, payload))
        assert command[:4] == ["az", "iot", "adr", "ns"]
        assert command[command.index("--subscription") + 1] == "sub"
        assert command[command.index("-g") + 1] == "rg"
        assert command[command.index("-n") + 1] == "one"
        assert ("--yes" in command) == action.destructive
        assert action.invoke(session, SCOPE, payload) == {"sent": True}
        sent = getattr(target, action.name).call_args.kwargs
        assert sent["resource_group_name"] == "rg"
        if kind not in {"namespace", "su"}:
            assert sent["namespace_name"] == "ns"
        for field in action.fields:
            if field.key != "name" and values[field.key] is not None:
                assert sent[field.key] == values[field.key]
        session.read_only = True
        with pytest.raises(SessionError, match="Read-only"):
            action.invoke(session, SCOPE, payload)
        session.read_only = False
        with pytest.raises(SessionError, match="Subscription"):
            action.invoke(session, dict(SCOPE, subscription_id="other"), payload)


@pytest.mark.parametrize("field,text", [
    (Field("name", "-n", "Name"), ""), (VALIDITY, "0"), (VALIDITY, "91"), (VALIDITY, "1.2"),
    (TAGS, "[]"), (TAGS, '{"a": 1}'), (TAGS, "{"),
    (Field("state", "--state", "State", choices=("Enabled",)), "Other"),
])
def test_forms_reject_invalid_values(field, text):
    with pytest.raises(ValueError):
        field.parse(text)


def test_tags_preview_quotes_each_pair_without_executing_shell_input():
    action = build_registry(None).get("namespace").action("update")
    payload = {"name": "O'Brien;name", "_inputs": {"tags": {"a": "two words", "b": "$(false)"}}}
    command = shlex.split(action.preview(SCOPE, payload))
    assert command[-3:] == ["--tags", "a=two words", "b=$(false)"]
    assert "O'Brien;name" in command
    assert Field("optional", "", "Optional", optional=True).parse("  ") is None


def test_create_existing_or_unknown_read_failure_never_overwrites():
    action = build_registry(None).get("device").action("create")
    session, target = session_for("device")
    payload = {"_inputs": {"name": "one"}}
    with pytest.raises(SessionError, match="already exists"):
        action.invoke(session, SCOPE, payload)
    target.show.side_effect = SessionError("forbidden", status_code=403)
    with pytest.raises(SessionError, match="forbidden"):
        action.invoke(session, SCOPE, payload)
    target.create.assert_not_called()


def test_changed_etag_or_applicability_invalidates_review():
    action = build_registry(None).get("ca").action("revoke")
    session, target = session_for("certificate_authority")
    with pytest.raises(SessionError, match="changed"):
        action.invoke(session, SCOPE, {"name": "one", "etag": "old"})
    target.show.return_value = {"name": "one", "properties": {"certificateAuthorityType": "Root"}}
    with pytest.raises(SessionError, match="Microsoft-issued"):
        action.invoke(session, SCOPE, {"name": "one"})
    target.revoke.assert_not_called()


@pytest.mark.parametrize("kind", list(TYPES))
@pytest.mark.parametrize("method", ["add", "wait", "update", "remove"])
def test_link_release_calls_and_role_disclosure(kind, method, monkeypatch):
    action = next(action for action in build_actions() if action.name == f"{kind}_{method}")
    endpoint = {"name": "endpoint", "endpointType": TYPES[kind], "resourceId": "/target",
                "provisioningStatus": {"status": "Accepted" if method == "wait" else "Failed"}}
    payload = dict(endpoint, _inputs={"name": "endpoint", "target": "/target"})
    session, provider = session_for("link")
    provider.list_all.return_value = [] if method == "add" else [endpoint]
    waiter = Mock(return_value=None)
    monkeypatch.setattr(f"azext_iot.adr.commands_wait.adr_link_{kind}_wait", waiter)
    command = shlex.split(action.preview(SCOPE, payload))
    assert command[:7] == ["az", "iot", "adr", "ns", "link", kind, method]
    assert command[command.index("--subscription") + 1] == "sub"
    assert command[command.index("--endpoint-name") + 1] == "endpoint"
    if method == "add":
        assert "--system-assigned-mi" in command
        assert command[command.index(f"--{kind}-id") + 1] == "/target"
    note = action.review_note(SCOPE, payload)
    if method in ("add", "update"):
        assert note.count("ROLE ") == 3
        assert "roleAssignments/write" in note and "/target" in note
        assert "/subscriptions/sub/resourceGroups/rg/" in note
    action.invoke(session, SCOPE, payload)
    if method == "wait":
        waiter.assert_called_once()
        assert waiter.call_args.kwargs["timeout"] == 300
    else:
        sent = getattr(provider, f"{kind}_{method}").call_args.kwargs
        assert sent["endpoint_name"] == "endpoint"
        if method == "add":
            assert sent[f"{kind}_resource_id"] == "/target"
    provider.reset_mock()
    session.read_only = True
    if method != "wait":
        with pytest.raises(SessionError, match="Read-only"):
            action.invoke(session, SCOPE, payload)
    session.read_only = False
    with pytest.raises(SessionError, match="Subscription"):
        action.invoke(session, dict(SCOPE, subscription_id="other"), payload)
    provider.list_all.return_value = [endpoint] if method == "add" else []
    with pytest.raises(SessionError, match="already exists|changed"):
        action.invoke(session, SCOPE, payload)
    for write in ("add", "update", "remove"):
        getattr(provider, f"{kind}_{write}").assert_not_called()


def test_pending_link_update_and_failed_link_wait_are_not_applicable():
    for action in build_actions():
        if action.name.endswith(("wait", "update")):
            assert not action.is_applicable({"name": "unknown"})
    action = provider_action("group", "iot adr ns group delete", "delete", "group_name", no_wait=False)
    assert action.label == "Delete"


@pytest.mark.parametrize("kind,provider,method,payload", [
    ("schema-registry", "schema_registry", "list", {"id": "/schema", "name": "schema", "location": "australiaeast"}),
    ("device-class", "device_class", "list", {"deviceClassId": "sensor", "friendlyName": "Sensor"}),
    ("software-update", "software_update", "list_updates", {"updateId": {"provider": "p", "name": "n", "version": "v"}}),
])
def test_secondary_inventory_metadata_remains_readonly(kind, provider, method, payload):
    session = Mock()
    session.list_from.return_value = [payload]
    spec = build_registry(session).get(kind)
    assert spec.list(SCOPE) == [payload]
    assert spec.row_id(payload)
    assert all(isinstance(column.text(payload), str) for column in spec.columns)
    assert not spec.actions
    assert session.list_from.call_args.args == (provider, method)


def test_unknown_current_field_does_not_invent_an_update_default():
    assert Field("unknown", "", "Unknown", default="new").current({}) == ""


def test_update_instance_uses_its_own_provider_wait_budget():
    action = build_registry(None).get("su").action("create")
    session, provider = session_for("update_instance", creating=True)
    action.invoke(session, SCOPE, {"_inputs": {"name": "updates", "location": "australiaeast"}})
    assert "no_wait" not in provider.create.call_args.kwargs
