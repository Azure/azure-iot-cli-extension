# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Scope discovery (subscriptions, resource groups) and per-scope sessions: no UI involved."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from azext_iot.adr.ui.core.scope import (
    ERROR_TTL_SEC, GROUP_LIMIT, GROUP_TTL_SEC, SUBSCRIPTIONS, Choice, ListState, ScopeCatalog, group_key,
    valid_group_name,
)
from azext_iot.adr.ui.core.session import Session

SUB_A = "00000000-0000-4000-8000-00000000000a"
SUB_B = "00000000-0000-4000-8000-00000000000b"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class HttpError(Exception):
    def __init__(self, status, text="boom"):
        super().__init__(text)
        self.status_code = status


def catalog(subs=None, groups=None, clock=None):
    subs = subs if subs is not None else [{"id": SUB_A, "name": "Contoso Dev", "state": "Enabled"}]
    default = [{"name": "rg-b", "location": "westus"}, {"name": "rg-a", "location": "eastus"}]
    groups = groups if groups is not None else (lambda _sub: default)
    list_subs = subs if callable(subs) else (lambda: subs)
    return ScopeCatalog(list_subs, groups, clock or Clock())


def test_group_names_follow_arm_rules():
    assert valid_group_name("rg-prod_01.(eu)")
    assert not valid_group_name("ends.")
    assert not valid_group_name("has space")
    assert not valid_group_name("x" * 91)
    assert not valid_group_name("")
    assert group_key(SUB_A.upper()) == ("groups", SUB_A)


def test_subscriptions_come_from_the_profile_enabled_first_and_never_expire():
    clock = Clock()
    rows = [
        {"id": SUB_B, "name": "Zeta", "state": "Disabled"},
        {"id": SUB_A, "name": "alpha", "state": "Enabled", "isDefault": True},
        {"name": "no id is skipped"},
    ]
    scopes = catalog(rows, clock=clock)
    listing = scopes.fetch(SUBSCRIPTIONS)
    assert listing.state is ListState.READY and listing.usable
    assert [c.name for c in listing.items] == ["alpha", "Zeta"]
    assert listing.items[0] == Choice(SUB_A, "alpha", SUB_A, "Enabled", True)
    clock.now += 10 * GROUP_TTL_SEC
    assert scopes.is_fresh(SUBSCRIPTIONS)
    assert scopes.fetch(SUBSCRIPTIONS) is listing and scopes.calls == 1
    assert scopes.fetch(SUBSCRIPTIONS, force=True) is not listing and scopes.calls == 2


@pytest.mark.parametrize("rows, error, state, message", [
    ([], None, ListState.EMPTY, "No subscriptions in the az login profile"),
    (None, OSError("profile locked"), ListState.FAILED, "Could not read the az login profile: profile locked"),
])
def test_subscription_failures_are_explicit(rows, error, state, message):
    def subs():
        if error:
            raise error
        return rows
    listing = catalog(subs).fetch(SUBSCRIPTIONS)
    assert listing.state is state and message in listing.message and not listing.items


def test_groups_are_sorted_cached_for_a_ttl_and_listed_with_the_explicit_subscription():
    clock = Clock()
    seen = []

    def groups(sub):
        seen.append(sub)
        return [{"name": "rg-b", "location": "westus"}, SimpleNamespace(name="RG-a", location=None)]

    scopes = catalog(groups=groups, clock=clock)
    key = group_key(SUB_A)
    assert scopes.peek(key) is None and not scopes.is_fresh(key)
    listing = scopes.fetch(key)
    assert seen == [SUB_A]
    assert [(c.name, c.detail) for c in listing.items] == [("RG-a", ""), ("rg-b", "westus")]
    clock.now += GROUP_TTL_SEC - 1
    assert scopes.fetch(key) is listing
    clock.now += 2
    assert not scopes.is_fresh(key)
    scopes.fetch(key)
    assert seen == [SUB_A, SUB_A]


def test_group_listing_is_bounded_and_reports_truncation():
    pulled = []

    def endless(_sub):
        index = 0
        while True:
            pulled.append(index)
            yield {"name": f"rg-{index:05d}"}
            index += 1

    listing = catalog(groups=endless).fetch(group_key(SUB_A))
    assert listing.truncated and len(listing.items) == GROUP_LIMIT
    assert len(pulled) == GROUP_LIMIT + 1, "never pages past the cap"


@pytest.mark.parametrize("error, state, text", [
    (HttpError(403), ListState.DENIED, "Not authorized to list resource groups; type a name."),
    (HttpError(401), ListState.DENIED, "Not authorized"),
    (Exception("AuthorizationFailed: no read"), ListState.DENIED, "Not authorized"),
    (HttpError(500), ListState.FAILED, "Could not list resource groups: The service reported"),
    (RuntimeError("socket closed"), ListState.FAILED, "socket closed"),
])
def test_group_failures_are_denied_or_failed_never_empty_and_retry_after_a_short_ttl(error, state, text):
    clock = Clock()
    groups = Mock(side_effect=error)
    scopes = catalog(groups=groups, clock=clock)
    listing = scopes.fetch(group_key(SUB_A))
    assert listing.state is state and not listing.usable and text in listing.message
    assert scopes.fetch(group_key(SUB_A)) is listing
    clock.now += ERROR_TTL_SEC
    groups.side_effect = None
    groups.return_value = []
    retried = scopes.fetch(group_key(SUB_A))
    assert retried.state is ListState.EMPTY and retried.message == "No resource groups in this subscription."


def test_concurrent_fetches_share_one_request_and_invalidate_never_mixes_results(monkeypatch):
    started, release, joined = threading.Event(), threading.Event(), threading.Event()
    calls = []

    class Pending(threading.Event):
        def wait(self, timeout=None):
            joined.set()
            return super().wait(timeout)

    monkeypatch.setattr("azext_iot.adr.ui.core.scope.Event", Pending)

    def groups(sub):
        calls.append(sub)
        started.set()
        release.wait(5)
        return [{"name": f"rg-{len(calls)}"}]

    scopes = catalog(groups=groups)
    key = group_key(SUB_A)
    results = []
    owner = threading.Thread(target=lambda: results.append(scopes.fetch(key)))
    owner.start()
    assert started.wait(5)
    joiner = threading.Thread(target=lambda: results.append(scopes.fetch(key)))
    joiner.start()
    assert joined.wait(5)
    scopes.invalidate(key)
    assert scopes.peek(key) is None
    release.set()
    owner.join(5)
    joiner.join(5)
    assert calls == [SUB_A], "the second caller joined the first request"
    assert results[0] is results[1] and results[0].items[0].name == "rg-1"
    assert scopes.peek(key) is None, "an invalidated listing is not resurrected"
    scopes.fetch(key)
    scopes.invalidate()
    assert scopes.peek(key) is None and len(calls) == 2


def test_joiner_times_out_with_an_explicit_failure():
    scopes = catalog()
    key = group_key(SUB_A)
    entry = scopes._entries.setdefault(key, Mock(listing=None, pending=Mock(wait=Mock(return_value=False))))
    listing = scopes.fetch(key)
    entry.pending.wait.assert_called_once()
    assert listing.state is ListState.FAILED and "timed out" in listing.message


def test_for_cli_reads_the_profile_and_lists_groups_with_an_explicit_subscription():
    cli_ctx = SimpleNamespace(data={"subscription_id": SUB_A})
    client = MagicMock()
    client.resource_groups.list.return_value = iter([{"name": "rg-one"}])
    with patch("azure.cli.core._profile.Profile") as profile, \
            patch("azure.cli.core.commands.client_factory.get_mgmt_service_client", return_value=client) as factory:
        profile.return_value.load_cached_subscriptions.return_value = [{"id": SUB_B, "name": "B"}]
        scopes = ScopeCatalog.for_cli(cli_ctx)
        assert [c.id for c in scopes.fetch(SUBSCRIPTIONS).items] == [SUB_B]
        assert [c.name for c in scopes.fetch(group_key(SUB_B)).items] == ["rg-one"]
    profile.assert_called_once_with(cli_ctx=cli_ctx)
    assert factory.call_args.kwargs == {"subscription_id": SUB_B}
    profile.return_value.set_active_subscription.assert_not_called()
    assert cli_ctx.data == {"subscription_id": SUB_A}, "the CLI default is never retargeted"


def _cmd():
    return SimpleNamespace(cli_ctx=SimpleNamespace(data={"subscription_id": SUB_A, "other": 1}))


def test_session_for_scope_retargets_only_its_own_context_copy():
    cmd = _cmd()
    session = Session(cmd, "rg-a", "ns", read_only=True)
    session.scope.subscription_id, session.scope.subscription_name = SUB_A, "A"
    same = session.for_scope(SUB_A, "A", "rg-other")
    assert same._providers is session._providers and same._io_slots is session._io_slots
    assert same.scope.as_dict() == {"subscription": "A", "subscription_id": SUB_A,
                                    "resource_group_name": "rg-other", "namespace_name": None}
    other = session.for_scope(SUB_B, None, None)
    assert other._providers is not session._providers and other._provider_lock is not session._provider_lock
    assert other.read_only and other.scope.as_dict()["subscription"] == SUB_B
    assert other.cmd.cli_ctx.data == {"subscription_id": SUB_B, "other": 1}
    assert session.cmd.cli_ctx.data["subscription_id"] == SUB_A
    assert cmd.cli_ctx.data == {"subscription_id": SUB_A, "other": 1}, "caller context untouched"
    assert session.scope.resource_group_name == "rg-a" and session.scope.namespace_name == "ns"
    detached = Session(None).for_scope(SUB_B)
    assert detached.cmd is None and detached.scope.subscription_id == SUB_B
