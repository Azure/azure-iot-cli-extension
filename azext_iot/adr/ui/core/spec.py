# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Resource specifications and the kind registry.

A :class:`ResourceSpec` declares everything the UI needs to know about one resource kind:
how to fetch it, how to render it, what it nests, and what can be done to it. The generic
browse screen, command-bar resolution, drill-down and action gating are all driven from
these declarations, so adding a kind is a new module plus one registration.

This module is deliberately free of any UI framework import.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Payload = Dict[str, Any]
Scope = Dict[str, Any]

# Style tokens are resolved by the presentation layer; core stays framework-free.
STYLE_OK = "ok"
STYLE_WARN = "warn"
STYLE_ERROR = "error"
STYLE_MUTED = "muted"
STYLE_ACTIVE = "active"

#: Provisioning states that mean "still settling" rather than a terminal outcome.
TRANSITIONAL_STATES = frozenset({"Accepted", "Provisioning", "Updating", "Deleting", "Creating"})
FAILED_STATES = frozenset({"Failed", "Canceled"})
_TRANSITIONAL_STATES_NORMALIZED = frozenset(
    state.casefold() for state in TRANSITIONAL_STATES
)
_FAILED_STATES_NORMALIZED = frozenset(state.casefold() for state in FAILED_STATES)


def _identity(value: Any) -> str:
    return "" if value is None else str(value)


@dataclass(frozen=True)
class Column:
    """One column of a resource table."""

    key: str
    label: str
    extract: Callable[[Payload], Any]
    width: Optional[int] = None
    wide: bool = False
    #: Optional style token for the cell, derived from the payload.
    style: Optional[Callable[[Payload], Optional[str]]] = None
    #: Sort key; defaults to the extracted value lowercased for stable text ordering.
    sort_key: Optional[Callable[[Payload], Any]] = None

    def text(self, payload: Payload) -> str:
        return _identity(self.extract(payload))

    def sort_value(self, payload: Payload) -> Any:
        if self.sort_key is not None:
            return self.sort_key(payload)
        value = self.extract(payload)
        return value.lower() if isinstance(value, str) else value


@dataclass(frozen=True)
class Guide:
    """The short orientation shown at the top of a page.

    Answers the three questions a customer asks on arriving somewhere unfamiliar: what am
    I looking at, what is the main next action, what does this actually run against Azure,
    and what will it not do. The action may name the few workflow keys that matter; the
    full shortcut inventory remains generated from bindings in the hint bar.

    Kept on the spec rather than in a screen so a new kind arrives with its own guidance
    instead of inheriting a generic sentence that explains nothing.
    """

    #: What this page shows, in one sentence.
    about: str
    #: The most useful next action on this page. Kept separate so the presentation can
    #: give it more visual weight than explanatory prose.
    action: str = ""
    #: The command or API this page runs behind the scenes, plus read/write character.
    runs: str = ""
    #: A limitation or caveat worth knowing before acting.
    note: str = ""

    def rows(self) -> List[Tuple[str, str]]:
        """Label/value pairs, omitting the parts that were not filled in."""
        return [
            (label, value)
            for label, value in (
                ("about", self.about),
                ("action", self.action),
                ("runs", self.runs),
                ("note", self.note),
            )
            if value
        ]


@dataclass(frozen=True)
class ChildRef:
    """A kind reachable by drilling into a row of the parent kind."""

    kind: str
    label: str
    key: Optional[str] = None
    #: Short customer-facing explanation used by hierarchy overviews.
    description: str = ""


@dataclass(frozen=True)
class Action:
    """A named operation offered on a selected row.

    ``invoke`` receives ``(session, scope, payload)``. Mutating actions must pass
    ``no_wait=True`` to the provider and return the resulting poller so the operations
    tray can drive it (see design doc PR1).
    """

    name: str
    label: str
    key: Optional[str] = None
    destructive: bool = False
    #: Whether the action applies to this payload; used to hide inapplicable actions.
    applies_to: Optional[Callable[[Payload], bool]] = None
    invoke: Optional[Callable[..., Any]] = None
    #: Kinds whose cached data is invalidated once the action reaches a terminal state.
    refreshes: Tuple[str, ...] = ()

    def is_applicable(self, payload: Payload) -> bool:
        return True if self.applies_to is None else bool(self.applies_to(payload))


@dataclass(frozen=True)
class ResourceSpec:
    """Declarative description of one resource kind."""

    kind: str
    title: str
    title_plural: str
    columns: Sequence[Column]
    #: Unique, stable row identity. Required: row diffing depends on it.
    row_id: Callable[[Payload], str]
    list: Optional[Callable[..., Sequence[Payload]]] = None
    get: Optional[Callable[..., Payload]] = None
    aliases: Tuple[str, ...] = ()
    #: Kind this one nests beneath, if any. Drives scoping and breadcrumbs.
    parent: Optional[str] = None
    children: Tuple[ChildRef, ...] = ()
    actions: Tuple[Action, ...] = ()
    #: Default sort as (column key, descending).
    sort: Optional[Tuple[str, bool]] = None
    #: Per-kind poll override in seconds; None uses the session default.
    refresh_interval: Optional[int] = None
    #: Scope key under which a selected row's name is passed to child kinds.
    #: Defaults to ``<kind>_name``. Declared here so the application needs no
    #: per-kind knowledge to build a child scope.
    scope_key: Optional[str] = None
    #: Extra scope a selected row contributes to its children beyond ``scope_key``
    #: (e.g. a namespace also fixes the resource group its children live in).
    scope_extra: Optional[Callable[[Payload], Dict[str, Any]]] = None
    #: Scope keys this kind cannot be listed without. Checked before any request, so a
    #: kind opened out of context explains itself instead of surfacing an SDK error.
    requires: Tuple[str, ...] = ()
    #: Orientation shown above the table. Optional, but every registered kind should have
    #: one; a page that cannot explain itself is a page the customer has to guess at.
    guide: Optional[Guide] = None
    #: Compact description of a loaded collection for a parent's hierarchy overview.
    #: Defaults to a few row names; kinds with a more useful aggregate may override it.
    summarize: Optional[Callable[[Sequence[Payload]], str]] = None

    def missing_scope(self, scope: Dict[str, Any]) -> List[str]:
        """Required scope keys that are absent or empty."""
        return [key for key in self.requires if not (scope or {}).get(key)]

    def child_scope(self, payload: Payload) -> Dict[str, Any]:
        """Scope contributed by one selected row of this kind to its children."""
        scope: Dict[str, Any] = {
            self.scope_key or f"{self.kind}_name": str(self.row_id(payload))
        }
        if self.scope_extra is not None:
            scope.update(self.scope_extra(payload) or {})
        return scope

    def column(self, key: str) -> Optional[Column]:
        for column in self.columns:
            if column.key == key:
                return column
        return None

    def visible_columns(self, show_wide: bool = False) -> List[Column]:
        return [c for c in self.columns if show_wide or not c.wide]

    def default_sort(self) -> Tuple[str, bool]:
        return self.sort if self.sort else (self.columns[0].key, False)

    def summarize_rows(self, payloads: Sequence[Payload]) -> str:
        """A compact, useful preview of a child collection."""
        rows = list(payloads)
        if self.summarize is not None:
            return self.summarize(rows)
        if not rows:
            return (
                "None in this namespace"
                if "namespace_name" in self.requires
                else "None in the current scope"
            )
        names = [str(self.row_id(payload)) for payload in rows[:3]]
        if len(rows) > 3:
            names.append(f"+{len(rows) - 3} more")
        return ", ".join(names)

    def action(self, name: str) -> Optional[Action]:
        for action in self.actions:
            if action.name == name:
                return action
        return None


class SpecError(ValueError):
    """Raised when a spec or registration is malformed."""


def validate_spec(spec: ResourceSpec) -> None:
    """Fail loudly on a malformed spec. Called on every registration."""
    if not spec.kind:
        raise SpecError("spec requires a non-empty kind")
    if not spec.columns:
        raise SpecError(f"spec '{spec.kind}' declares no columns")
    if spec.row_id is None:
        raise SpecError(f"spec '{spec.kind}' has no row_id; row diffing requires one")

    keys = [column.key for column in spec.columns]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        raise SpecError(f"spec '{spec.kind}' has duplicate column keys: {sorted(duplicates)}")

    sort_key = spec.sort[0] if spec.sort else None
    if sort_key and sort_key not in keys:
        raise SpecError(f"spec '{spec.kind}' sorts on unknown column '{sort_key}'")

    action_names = [action.name for action in spec.actions]
    repeated = {name for name in action_names if action_names.count(name) > 1}
    if repeated:
        raise SpecError(f"spec '{spec.kind}' has duplicate action names: {sorted(repeated)}")


@dataclass
class Registry:
    """The set of known resource kinds, indexed by kind and by alias."""

    _specs: Dict[str, ResourceSpec] = field(default_factory=dict)
    _aliases: Dict[str, str] = field(default_factory=dict)

    def register(self, spec: ResourceSpec) -> ResourceSpec:
        validate_spec(spec)
        if spec.kind in self._specs:
            raise SpecError(f"kind '{spec.kind}' is already registered")

        for alias in (spec.kind,) + tuple(spec.aliases):
            owner = self._aliases.get(alias)
            if owner is not None and owner != spec.kind:
                raise SpecError(f"alias '{alias}' is already bound to kind '{owner}'")
            self._aliases[alias] = spec.kind

        self._specs[spec.kind] = spec
        return spec

    def get(self, kind: str) -> ResourceSpec:
        try:
            return self._specs[kind]
        except KeyError:
            raise SpecError(f"unknown kind '{kind}'") from None

    def resolve(self, token: str) -> Optional[ResourceSpec]:
        """Resolve a command-bar token to a spec, or None if it matches nothing."""
        kind = self._aliases.get((token or "").strip().lower())
        return self._specs.get(kind) if kind else None

    def children_of(self, kind: str) -> Tuple[ChildRef, ...]:
        return self.get(kind).children

    def roots(self) -> List[ResourceSpec]:
        """Kinds that are not nested beneath another, in registration order."""
        return [spec for spec in self._specs.values() if spec.parent is None]

    def all(self) -> List[ResourceSpec]:
        return list(self._specs.values())

    def aliases(self) -> Dict[str, str]:
        return dict(self._aliases)

    def __contains__(self, kind: str) -> bool:
        return kind in self._specs

    def __len__(self) -> int:
        return len(self._specs)


def state_style(payload: Payload, *keys: str) -> Optional[str]:
    """Map a provisioning-style state field onto a style token.

    Shared by kind modules so status colouring stays consistent across every table.
    """
    lookup = keys or ("provisioningState",)
    properties = payload.get("properties") or {}
    for key in lookup:
        value = payload.get(key) or properties.get(key)
        if not value:
            continue
        normalized = str(value).casefold()
        if normalized in _FAILED_STATES_NORMALIZED:
            return STYLE_ERROR
        if normalized in _TRANSITIONAL_STATES_NORMALIZED:
            return STYLE_WARN
        if normalized == "succeeded":
            return STYLE_OK
    return None
