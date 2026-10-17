# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Subscription and resource group discovery for the scope picker.

Discovery is bounded and cached: subscriptions come from the local ``az login`` profile (no
network), resource groups are listed once per subscription with a hard item cap, and a failure is
recorded as an explicit denied or failed listing instead of an empty one. Nothing here changes the
CLI's default subscription; resource groups are listed with an explicit subscription id.

This module is deliberately free of any UI framework import.
"""

import re
import time
from dataclasses import dataclass, field, replace
from enum import Enum
from itertools import islice
from threading import Event, RLock
from typing import Callable, Dict, Optional, Tuple

from azext_iot.adr.ui.core.session import _http_status, translate_error

#: Resource groups listed per subscription. A larger estate is still reachable by typing a name.
GROUP_LIMIT = 1000
#: Seconds a resource group listing is reused before the picker lists again.
GROUP_TTL_SEC = 300
#: Seconds a denied or failed listing is reused, so reopening the picker does not hammer ARM.
ERROR_TTL_SEC = 30
#: Seconds a second caller waits for a listing another worker is already fetching.
SHARED_WAIT_SEC = 60

SUBSCRIPTIONS = "subscriptions"
_GROUP_NAME = re.compile(r"^[-\w._()]{1,90}$")


class ListState(Enum):
    READY = "ready"
    EMPTY = "empty"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True)
class Choice:
    """One pickable subscription or resource group."""

    id: str
    name: str
    detail: str = ""
    #: Subscriptions only: ``Enabled``, ``Disabled``, ``Warned`` and so on.
    state: str = ""
    is_default: bool = False


@dataclass(frozen=True)
class Listing:
    state: ListState
    items: Tuple[Choice, ...] = ()
    message: str = ""
    truncated: bool = False
    loaded_at: float = 0.0

    @property
    def usable(self) -> bool:
        return self.state in (ListState.READY, ListState.EMPTY)


def valid_group_name(name: str) -> bool:
    """ARM resource group naming: 1-90 of letters, digits, ``-_.()``; never ending in a period."""
    name = (name or "").strip()
    return bool(_GROUP_NAME.match(name)) and not name.endswith(".")


def group_key(subscription_id: str) -> Tuple[str, str]:
    return ("groups", str(subscription_id or "").lower())


def _classify(error: Exception, what: str) -> Listing:
    translated = translate_error(error)
    status = _http_status(error)
    text = f"{error} {getattr(translated, 'detail', '') or ''}"
    if status in (401, 403) or "AuthorizationFailed" in text or "does not have authorization" in text:
        return Listing(ListState.DENIED, message=f"Not authorized to list {what}; type a name.")
    return Listing(ListState.FAILED, message=f"Could not list {what}: {translated.message}")


@dataclass
class _Entry:
    listing: Optional[Listing] = None
    pending: Optional[Event] = field(default=None)


class ScopeCatalog:
    """Cached, de-duplicated listings keyed by ``SUBSCRIPTIONS`` or :func:`group_key`.

    ``list_subscriptions()`` returns profile entries (``id``, ``name``, ``state``, ``isDefault``);
    ``list_groups(subscription_id)`` returns an iterable of objects or dicts with ``name`` and
    ``location``. Both are called on worker threads only.
    """

    def __init__(self, list_subscriptions: Callable, list_groups: Callable,
                 clock: Callable[[], float] = time.monotonic):
        self._list_subscriptions = list_subscriptions
        self._list_groups = list_groups
        self._clock = clock
        self._lock = RLock()
        self._entries: Dict[Tuple, _Entry] = {}
        self.calls = 0

    @classmethod
    def for_cli(cls, cli_ctx) -> "ScopeCatalog":
        def subscriptions():
            from azure.cli.core._profile import Profile
            return Profile(cli_ctx=cli_ctx).load_cached_subscriptions()

        def groups(subscription_id):
            from azure.cli.core.commands.client_factory import get_mgmt_service_client
            from azure.cli.core.profiles import ResourceType
            # Explicit subscription: never the CLI default, never written back to the profile.
            client = get_mgmt_service_client(cli_ctx, ResourceType.MGMT_RESOURCE_RESOURCES,
                                             subscription_id=subscription_id)
            return client.resource_groups.list()

        return cls(subscriptions, groups)

    def peek(self, key) -> Optional[Listing]:
        """The cached listing, fresh or not, without any I/O. Safe on the UI thread."""
        with self._lock:
            entry = self._entries.get(key)
            return entry.listing if entry else None

    def is_fresh(self, key) -> bool:
        listing = self.peek(key)
        if listing is None:
            return False
        if key == SUBSCRIPTIONS and listing.usable:
            return True
        ttl = GROUP_TTL_SEC if listing.usable else ERROR_TTL_SEC
        return self._clock() - listing.loaded_at < ttl

    def fetch(self, key, force: bool = False) -> Listing:
        """Blocking: return a fresh listing, joining a fetch already in flight for ``key``."""
        with self._lock:
            entry = self._entries.setdefault(key, _Entry())
            if not force and self.is_fresh(key):
                return entry.listing
            waiter, owner = entry.pending, entry.pending is None
            if owner:
                waiter = entry.pending = Event()
        if not owner:
            waiter.wait(SHARED_WAIT_SEC)
            # The entry the owner fills, even if the key was invalidated meanwhile.
            return entry.listing or Listing(ListState.FAILED, message="Listing timed out. Try again.")
        listing = Listing(ListState.FAILED, message="Listing was interrupted. Try again.")
        try:
            listing = self._load(key)
        finally:
            with self._lock:
                # Published before waking joiners, so they never see the previous listing.
                entry.listing = listing
                entry.pending = None
                waiter.set()
        return listing

    def _load(self, key) -> Listing:
        self.calls += 1
        now = self._clock()
        if key == SUBSCRIPTIONS:
            try:
                rows = list(self._list_subscriptions() or [])
            except Exception as error:  # noqa: BLE001 - recorded as an explicit failure
                return Listing(ListState.FAILED, message=f"Could not read the az login profile: {error}",
                               loaded_at=now)
            items = sorted((self._subscription(row) for row in rows if row.get("id")),
                           key=lambda c: (c.state.casefold() != "enabled", c.name.casefold()))
            if not items:
                return Listing(ListState.EMPTY, message="No subscriptions in the az login profile. "
                               "Run az login outside radar.", loaded_at=now)
            return Listing(ListState.READY, tuple(items), loaded_at=now)
        try:
            listed = list(islice(iter(self._list_groups(key[1]) or ()), GROUP_LIMIT + 1))
        except Exception as error:  # noqa: BLE001 - recorded as denied or failed, never empty
            return replace(_classify(error, "resource groups"), loaded_at=now)
        truncated = len(listed) > GROUP_LIMIT
        items = sorted((self._group(row) for row in listed[:GROUP_LIMIT]), key=lambda c: c.name.casefold())
        if not items:
            return Listing(ListState.EMPTY, message="No resource groups in this subscription.", loaded_at=now)
        return Listing(ListState.READY, tuple(items), truncated=truncated, loaded_at=now)

    @staticmethod
    def _subscription(row) -> Choice:
        return Choice(id=str(row.get("id")), name=str(row.get("name") or row.get("id")),
                      detail=str(row.get("id")), state=str(row.get("state") or ""),
                      is_default=bool(row.get("isDefault")))

    @staticmethod
    def _group(row) -> Choice:
        get = row.get if isinstance(row, dict) else (lambda key: getattr(row, key, None))
        name = str(get("name") or "")
        return Choice(id=name, name=name, detail=str(get("location") or ""))

    def invalidate(self, key=None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)
