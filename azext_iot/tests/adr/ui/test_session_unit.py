# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Session: provider caching, scope resolution and the error boundary (step 6)."""

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.ui.core.session import Session, SessionError, translate_error


class _Cmd:
    cli_ctx = object()


def make_session(**kwargs):
    return Session(_Cmd(), **kwargs)


# -- error boundary ------------------------------------------------------------------


def test_cli_errors_keep_their_actionable_message():
    error = translate_error(InvalidArgumentValueError("--ns must be a valid name"))
    assert "--ns must be a valid name" in error.message


def test_provider_not_found_keeps_its_own_guidance():
    """Providers write these messages for humans, so the boundary must not overwrite them."""
    message = "No certificate authority 'ca1' exists on namespace 'ns'. Create one using..."
    assert translate_error(ResourceNotFoundError(message)).message == message


@pytest.mark.parametrize(
    "status, expected",
    [
        (401, "not authorized"),
        (403, "not authorized"),
        (404, "not found"),
        (429, "throttling"),
        (500, "service reported an error"),
    ],
)
def test_http_errors_are_translated_by_status(status, expected):
    error = HttpResponseError(message="raw service text")
    error.status_code = status
    translated = translate_error(error)
    assert expected in translated.message.lower()
    assert translated.detail, "the raw text is preserved as detail, not discarded"


def test_unknown_errors_fall_back_to_their_text():
    assert translate_error(RuntimeError("something odd")).message == "something odd"


def test_call_wraps_failures_in_session_error():
    session = make_session()

    def boom():
        raise RuntimeError("provider exploded")

    with pytest.raises(SessionError, match="provider exploded"):
        session.call(boom)


def test_call_passes_through_session_errors_unchanged():
    session = make_session()
    original = SessionError("already translated")

    def boom():
        raise original

    with pytest.raises(SessionError) as caught:
        session.call(boom)
    assert caught.value is original


def test_call_returns_the_result_when_nothing_fails():
    session = make_session()
    assert session.call(lambda value: value * 2, 21) == 42


# -- provider cache ------------------------------------------------------------------


def test_providers_are_constructed_once(monkeypatch):
    """Each provider constructor builds a service client, so reuse is not an optimisation."""
    constructed = []

    class FakeProvider:
        def __init__(self, cmd):
            constructed.append(cmd)

    import azext_iot.adr.providers.namespace as namespace_module

    monkeypatch.setattr(namespace_module, "NamespaceProvider", FakeProvider)
    session = make_session()
    first = session.provider("namespace")
    second = session.provider("namespace")
    assert first is second
    assert len(constructed) == 1


def test_unknown_provider_is_reported_clearly():
    with pytest.raises(SessionError, match="No provider is registered"):
        make_session().provider("does-not-exist")


def test_list_from_reports_a_missing_operation(monkeypatch):
    class FakeProvider:
        def __init__(self, cmd):
            pass

    import azext_iot.adr.providers.group as group_module

    monkeypatch.setattr(group_module, "GroupProvider", FakeProvider)
    session = make_session()
    with pytest.raises(SessionError, match="has no operation"):
        session.list_from("group", "list")


def test_list_from_normalises_none_to_empty(monkeypatch):
    class FakeProvider:
        def __init__(self, cmd):
            pass

        def list(self, **kwargs):
            return None

    import azext_iot.adr.providers.group as group_module

    monkeypatch.setattr(group_module, "GroupProvider", FakeProvider)
    assert not make_session().list_from("group", "list")


def test_list_from_forwards_arguments(monkeypatch):
    seen = {}

    class FakeProvider:
        def __init__(self, cmd):
            pass

        def list(self, **kwargs):
            seen.update(kwargs)
            return [{"name": "a"}]

    import azext_iot.adr.providers.group as group_module

    monkeypatch.setattr(group_module, "GroupProvider", FakeProvider)
    result = make_session().list_from("group", "list", namespace_name="ns", resource_group_name="rg")
    assert result == [{"name": "a"}]
    assert seen == {"namespace_name": "ns", "resource_group_name": "rg"}


# -- scope ---------------------------------------------------------------------------


def test_scope_serialises_for_kinds():
    session = make_session(resource_group_name="rg", namespace_name="ns")
    scope = session.scope.as_dict()
    assert scope["resource_group_name"] == "rg"
    assert scope["namespace_name"] == "ns"


def test_subscription_resolution_failure_is_not_fatal(monkeypatch):
    """A broken profile must degrade to a blank subscription, not stop the UI."""
    session = make_session()

    import azure.cli.core._profile as profile_module

    class BrokenProfile:
        def __init__(self, cli_ctx=None):
            raise RuntimeError("no profile")

    monkeypatch.setattr(profile_module, "Profile", BrokenProfile)
    assert session.resolve_subscription() is None


def test_subscription_is_resolved_once(monkeypatch):
    calls = []

    import azure.cli.core._profile as profile_module

    class FakeProfile:
        def __init__(self, cli_ctx=None):
            pass

        def get_subscription(self):
            calls.append(1)
            return {"id": "sub-123", "name": "Contoso Dev"}

    monkeypatch.setattr(profile_module, "Profile", FakeProfile)
    session = make_session()
    assert session.resolve_subscription() == "sub-123"
    assert session.resolve_subscription() == "sub-123"
    assert len(calls) == 1
    assert session.scope.subscription_name == "Contoso Dev"
