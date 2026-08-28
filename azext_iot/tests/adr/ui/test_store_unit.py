# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Store: intervals, backoff, staleness and invalidation (step 7).

A controlled clock is used throughout so the policy is asserted exactly rather than by
sleeping.
"""

import pytest

from azext_iot.adr.ui.core.redaction import REDACTED
from azext_iot.adr.ui.core.store import MAX_BACKOFF_SEC, MIN_INTERVAL_SEC, Store, cache_key
from azext_iot.tests.adr.ui.conftest import widget_spec


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Loader:
    """Counts calls so tests can assert whether the network would have been touched."""

    def __init__(self, payloads=None, error=None):
        self.payloads = payloads if payloads is not None else [{"name": "a"}]
        self.error = error
        self.calls = 0

    def __call__(self, scope):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.payloads)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    return Store(default_interval=10, clock=clock)


@pytest.fixture
def spec():
    return widget_spec()


SCOPE = {"namespace_name": "ns", "resource_group_name": "rg"}


# -- intervals -----------------------------------------------------------------------


def test_first_fetch_calls_the_loader(store, spec):
    loader = Loader()
    assert store.fetch(spec, SCOPE, loader) == [{"name": "a"}]
    assert loader.calls == 1


def test_repeat_within_the_interval_is_served_from_cache(store, spec, clock):
    loader = Loader()
    store.fetch(spec, SCOPE, loader)
    clock.advance(5)
    store.fetch(spec, SCOPE, loader)
    assert loader.calls == 1, "a poll inside the interval must not cost a request"


def test_fetch_after_the_interval_reloads(store, spec, clock):
    loader = Loader()
    store.fetch(spec, SCOPE, loader)
    clock.advance(11)
    store.fetch(spec, SCOPE, loader)
    assert loader.calls == 2


def test_force_bypasses_the_interval(store, spec, clock):
    loader = Loader()
    store.fetch(spec, SCOPE, loader)
    clock.advance(1)
    store.fetch(spec, SCOPE, loader, force=True)
    assert loader.calls == 2


def test_interval_floor_is_enforced(clock):
    store = Store(default_interval=1, clock=clock)
    assert store.default_interval == MIN_INTERVAL_SEC


def test_per_kind_interval_override_is_used(store):
    fast = widget_spec(kind="fast", aliases=("f",), refresh_interval=5)
    slow = widget_spec(kind="slow", aliases=("s",), refresh_interval=600)
    assert store.interval_for(fast) == 5
    assert store.interval_for(slow) == 600


def test_kind_interval_below_the_floor_is_raised(store):
    assert store.interval_for(widget_spec(refresh_interval=1)) == MIN_INTERVAL_SEC


# -- scope isolation -----------------------------------------------------------------


def test_different_scopes_are_cached_separately(store, spec):
    loader = Loader()
    store.fetch(spec, {"namespace_name": "one"}, loader)
    store.fetch(spec, {"namespace_name": "two"}, loader)
    assert loader.calls == 2, "one namespace's rows must never be shown for another"


def test_cache_key_ignores_non_identifying_scope():
    left = cache_key("device", {"namespace_name": "ns", "filter": "abc"})
    right = cache_key("device", {"namespace_name": "ns", "filter": "xyz"})
    assert left == right, "display state must not fragment the cache"


# -- failure, staleness and backoff --------------------------------------------------


def test_failure_with_no_cached_data_propagates(store, spec):
    loader = Loader(error=RuntimeError("service down"))
    with pytest.raises(RuntimeError, match="service down"):
        store.fetch(spec, SCOPE, loader)


def test_first_load_failure_remains_an_error_during_backoff(store, spec):
    loader = Loader(error=RuntimeError("service down"))
    with pytest.raises(RuntimeError, match="service down"):
        store.fetch_result(spec, SCOPE, loader)
    with pytest.raises(RuntimeError, match="service down"):
        store.fetch_result(spec, SCOPE, loader)
    assert loader.calls == 1


def test_failure_after_success_returns_stale_data(store, spec, clock):
    good = Loader([{"name": "a"}])
    store.fetch(spec, SCOPE, good)
    clock.advance(20)
    bad = Loader(error=RuntimeError("service down"))
    assert store.fetch(spec, SCOPE, bad) == [{"name": "a"}], "last known data is retained"
    assert store.entry(spec.kind, SCOPE).error == "service down"


def test_fetch_result_reports_cached_refresh_failures(store, spec, clock):
    store.fetch_result(spec, SCOPE, Loader([{"name": "a"}]))
    clock.advance(20)
    result = store.fetch_result(
        spec,
        SCOPE,
        Loader(error=RuntimeError("service down")),
    )
    assert result.payloads == [{"name": "a"}]
    assert result.error == "service down"
    assert result.stale


def test_credentials_are_redacted_before_they_are_cached(store, spec):
    payload = {
        "name": "symmetric",
        "properties": {
            "primaryKey": "secret-one",
            "secondaryKey": "secret-two",
        },
    }
    result = store.fetch_result(spec, SCOPE, Loader([payload]))
    assert result.payloads[0]["properties"]["primaryKey"] == REDACTED
    assert result.payloads[0]["properties"]["secondaryKey"] == REDACTED
    assert store.entry(spec.kind, SCOPE).payloads == result.payloads


def test_backoff_grows_with_consecutive_failures(store, spec, clock):
    loader = Loader(error=RuntimeError("down"))
    for _ in range(3):
        with pytest.raises(RuntimeError):
            store.fetch(spec, SCOPE, loader)
        clock.advance(MAX_BACKOFF_SEC)
    entry = store.entry(spec.kind, SCOPE)
    assert entry.failures == 3


def test_backoff_suppresses_immediate_retries(store, spec, clock):
    loader = Loader(error=RuntimeError("down"))
    good = Loader([{"name": "a"}])
    store.fetch(spec, SCOPE, good)  # seed a successful load
    clock.advance(20)
    store.fetch(spec, SCOPE, loader)  # fails, arms backoff
    calls_before = loader.calls
    store.fetch(spec, SCOPE, loader, force=True)  # inside the backoff window
    assert loader.calls == calls_before, "backoff holds even against a forced refresh"


def test_backoff_is_capped(store):
    assert store._backoff(100) == MAX_BACKOFF_SEC


def test_success_clears_the_failure_state(store, spec, clock):
    good = Loader([{"name": "a"}])
    store.fetch(spec, SCOPE, good)
    clock.advance(20)
    store.fetch(spec, SCOPE, Loader(error=RuntimeError("down")))
    clock.advance(MAX_BACKOFF_SEC)
    store.fetch(spec, SCOPE, good, force=True)
    entry = store.entry(spec.kind, SCOPE)
    assert entry.failures == 0 and entry.error is None


def test_entry_reports_age(store, spec, clock):
    store.fetch(spec, SCOPE, Loader())
    clock.advance(30)
    assert store.entry(spec.kind, SCOPE).age(clock()) == 30


def test_entry_without_a_load_has_no_age(store, spec):
    assert store.entry(spec.kind, SCOPE).age() is None


# -- invalidation --------------------------------------------------------------------


def test_invalidate_scope_forces_the_next_fetch(store, spec, clock):
    loader = Loader()
    store.fetch(spec, SCOPE, loader)
    store.invalidate(spec.kind, SCOPE)
    store.fetch(spec, SCOPE, loader)
    assert loader.calls == 2, "a successful mutation must refresh its table immediately"


def test_invalidate_kind_clears_every_scope(store, spec):
    loader = Loader()
    store.fetch(spec, {"namespace_name": "one"}, loader)
    store.fetch(spec, {"namespace_name": "two"}, loader)
    store.invalidate(spec.kind)
    store.fetch(spec, {"namespace_name": "one"}, loader)
    assert loader.calls == 3


def test_invalidate_everything(store, spec):
    loader = Loader()
    store.fetch(spec, SCOPE, loader)
    store.invalidate()
    store.fetch(spec, SCOPE, loader)
    assert loader.calls == 2
