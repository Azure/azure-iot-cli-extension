# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Polling cache.

ARM has no watch primitive, so freshness is achieved by polling. This module owns the
policy: how often a kind may be refetched, how long to back off after a failure, and how
to describe data that is stale rather than absent.

It runs on worker threads, so the small amount of shared state is guarded by a lock.
This module is deliberately free of any UI framework import.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from azext_iot.adr.ui.core.redaction import redact

#: Floor on how often any kind may be refetched, mirroring the CLI-side floor.
MIN_INTERVAL_SEC = 5
#: Backoff ceiling: a persistently failing collection is retried at most this rarely.
MAX_BACKOFF_SEC = 120
BACKOFF_FACTOR = 2

#: Scope keys that identify a collection. Anything else (filters, display state) must not
#: fragment the cache.
_IDENTITY_KEYS = (
    "subscription_id",
    "resource_group_name",
    "namespace_name",
    "registry_device_name",
    "certificate_authority_name",
    "job_name",
    "group_name",
)


def cache_key(kind: str, scope: Dict[str, Any]) -> Tuple:
    return (kind,) + tuple((key, scope.get(key)) for key in _IDENTITY_KEYS)


@dataclass
class Entry:
    """Cached payloads for one collection, plus everything needed to describe them."""

    payloads: List[Any] = field(default_factory=list)
    loaded_at: Optional[float] = None
    error: Optional[str] = None
    failures: int = 0
    next_attempt_at: float = 0.0

    @property
    def has_loaded(self) -> bool:
        return self.loaded_at is not None

    def age(self, now: Optional[float] = None) -> Optional[float]:
        if self.loaded_at is None:
            return None
        return (now if now is not None else time.monotonic()) - self.loaded_at


@dataclass(frozen=True)
class FetchResult:
    """One cache read, including whether its payloads survived a failed refresh."""

    payloads: List[Any]
    error: Optional[str] = None
    loaded_at: Optional[float] = None

    @property
    def stale(self) -> bool:
        return self.error is not None and self.loaded_at is not None

    def __iter__(self):
        return iter(self.payloads)


class Store:
    """Caches collections and decides when they may be refetched."""

    def __init__(self, default_interval: int = MIN_INTERVAL_SEC, clock: Callable[[], float] = time.monotonic):
        self.default_interval = max(int(default_interval), MIN_INTERVAL_SEC)
        self._clock = clock
        self._entries: Dict[Tuple, Entry] = {}
        self._lock = threading.RLock()

    # -- policy ------------------------------------------------------------

    def interval_for(self, spec) -> int:
        override = getattr(spec, "refresh_interval", None)
        return max(int(override or self.default_interval), MIN_INTERVAL_SEC)

    def _should_fetch(self, entry: Entry, interval: int, force: bool) -> bool:
        now = self._clock()
        if force:
            # A manual refresh still respects backoff, so a failing service cannot be
            # hammered by holding down the refresh key.
            return now >= entry.next_attempt_at
        if not entry.has_loaded:
            return now >= entry.next_attempt_at
        return now - entry.loaded_at >= interval

    # -- access ------------------------------------------------------------

    def entry(self, kind: str, scope: Dict[str, Any]) -> Entry:
        with self._lock:
            return self._entries.setdefault(cache_key(kind, scope), Entry())

    def fetch(self, spec, scope: Dict[str, Any], loader: Callable[[Dict[str, Any]], List[Any]],
              force: bool = False) -> List[Any]:
        """Return payloads for ``spec``, refetching only when policy allows.

        Blocking: always called from a worker thread. Raises whatever ``loader`` raises
        when there is no cached data to fall back on; otherwise it records the failure and
        returns the last known payloads so the screen can show stale data.
        """
        return self.fetch_result(spec, scope, loader, force=force).payloads

    def fetch_result(
        self,
        spec,
        scope: Dict[str, Any],
        loader: Callable[[Dict[str, Any]], List[Any]],
        force: bool = False,
    ) -> FetchResult:
        """Return cached payloads together with refresh failure and freshness metadata."""
        key = cache_key(spec.kind, scope)
        with self._lock:
            entry = self._entries.setdefault(key, Entry())
            interval = self.interval_for(spec)
            should = self._should_fetch(entry, interval, force)

        if not should:
            with self._lock:
                if entry.error and not entry.has_loaded:
                    raise RuntimeError(entry.error)
                return FetchResult(list(entry.payloads), entry.error, entry.loaded_at)

        try:
            payloads = list(redact(list(loader(scope))))
        except Exception as error:  # noqa: BLE001 - recorded, then re-raised if fatal
            with self._lock:
                entry.failures += 1
                entry.error = str(error)
                entry.next_attempt_at = self._clock() + self._backoff(entry.failures)
                if not entry.has_loaded:
                    raise
                return FetchResult(list(entry.payloads), entry.error, entry.loaded_at)

        with self._lock:
            entry.payloads = payloads
            entry.loaded_at = self._clock()
            entry.error = None
            entry.failures = 0
            entry.next_attempt_at = 0.0
            return FetchResult(list(payloads), loaded_at=entry.loaded_at)

    @staticmethod
    def _backoff(failures: int) -> float:
        return min(MIN_INTERVAL_SEC * (BACKOFF_FACTOR ** max(failures - 1, 0)), MAX_BACKOFF_SEC)

    # -- invalidation ------------------------------------------------------

    def invalidate(self, kind: Optional[str] = None, scope: Optional[Dict[str, Any]] = None) -> None:
        """Force the next fetch for a collection, a whole kind, or everything.

        Called after a successful mutation so the affected tables refresh immediately
        instead of waiting out their interval.
        """
        with self._lock:
            if kind is None:
                self._entries.clear()
                return
            if scope is not None:
                self._entries.pop(cache_key(kind, scope), None)
                return
            for key in [k for k in self._entries if k[0] == kind]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
