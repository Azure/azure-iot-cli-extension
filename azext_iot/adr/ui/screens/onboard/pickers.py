# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Resource pickers for onboarding.

Pickers exist so a customer never types an ARM identifier, which removes the entire class
of malformed-identifier errors by construction. Candidates that cannot be used are still
shown, with the reason: a customer who cannot find their hub assumes the product is
broken.

This module is deliberately free of any UI framework import.
"""

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

ELIGIBLE = "eligible"
WARNING = "warning"
INELIGIBLE = "ineligible"


@dataclass
class Candidate:
    """One selectable resource, with the verdict explaining whether it can be used."""

    name: str
    resource_id: str
    resource_group: str = ""
    location: str = ""
    identity: str = "none"
    verdict: str = ELIGIBLE
    reason: str = ""
    recommended: bool = False
    #: The payload this candidate was judged from, for rules needing more than the summary.
    raw: Optional[Dict[str, Any]] = None

    @property
    def selectable(self) -> bool:
        return self.verdict != INELIGIBLE

    def describe(self) -> str:
        label = {
            ELIGIBLE: "ready",
            WARNING: "check",
            INELIGIBLE: "blocked",
        }.get(self.verdict, self.verdict)
        if self.reason:
            return f"{label}  {self.reason}"
        return "recommended" if self.recommended else label


NO_IDENTITY = "none"


def catalog_key(step_id: str, resource_group_name: Optional[str] = None) -> str:
    """Cache/error key for one onboarding picker step."""
    if step_id == "namespace":
        return f"namespace:{resource_group_name or '-'}"
    return {"scope": "resource_group"}.get(step_id, step_id)


def _identity_of(resource: Dict[str, Any]) -> str:
    identity = resource.get("identity") or {}
    kind = identity.get("type") if isinstance(identity, dict) else None
    text = str(kind or "").strip()
    # ARM renders an absent identity as the literal "None"; normalise both spellings.
    return NO_IDENTITY if text.lower() in ("", "none") else text


def _resource_group_of(resource: Dict[str, Any]) -> str:
    group = resource.get("resourcegroup") or resource.get("resourceGroup")
    if group:
        return str(group)
    parts = str(resource.get("id") or "").split("/")
    if "resourceGroups" in parts:
        index = parts.index("resourceGroups")
        if index + 1 < len(parts):
            return parts[index + 1]
    return ""


def evaluate(resource: Dict[str, Any], namespace_location: Optional[str] = None,
             registered_hub_names: Optional[Sequence[str]] = None,
             require_identity: bool = True) -> Candidate:
    """Judge one candidate resource against the namespace it would be linked to."""
    identity = _identity_of(resource)
    location = str(resource.get("location") or "")
    candidate = Candidate(
        name=str(resource.get("name") or ""),
        resource_id=str(resource.get("id") or ""),
        resource_group=_resource_group_of(resource),
        location=location,
        identity=identity,
        raw=resource,
    )

    properties = resource.get("properties") or {}
    provisioning_state = str(
        resource.get("provisioningState")
        or properties.get("provisioningState")
        or ""
    )
    if provisioning_state.lower() in ("failed", "canceled"):
        candidate.verdict = INELIGIBLE
        candidate.reason = "provisioning failed"
        return candidate

    warnings = []
    if require_identity and identity == NO_IDENTITY:
        # Guided setup can enable a SAMI or attach a UAMI before linking.
        warnings.append("identity setup required")
    if namespace_location and location and location.lower() != namespace_location.lower():
        warnings.append("other region")

    if registered_hub_names is not None:
        # DPS records Hub host names; compare on the leading segment.
        registered = {
            str(value).split(".", maxsplit=1)[0].lower()
            for value in registered_hub_names
        }
        if candidate.name.lower() in registered:
            candidate.recommended = True
        else:
            # A Hub the DPS cannot allocate to produces a namespace that
            # looks correctly linked but silently provisions nothing.
            warnings.append("not in DPS")

    if warnings:
        candidate.verdict = WARNING
        candidate.reason = " + ".join(warnings)

    return candidate


def rank(candidates: Sequence[Candidate]) -> List[Candidate]:
    """Recommended first, then eligible, then warnings, then ineligible."""
    order = {ELIGIBLE: 0, WARNING: 1, INELIGIBLE: 2}

    def key(candidate: Candidate):
        return (0 if candidate.recommended else 1, order.get(candidate.verdict, 3), candidate.name)

    return sorted(candidates, key=key)


class ResourceCatalog:
    """Enumerates the non-ADR resources onboarding needs.

    Uses each provider's own list operation rather than a resource-graph query: the
    extension already carries these clients, so there is no new dependency and no extra
    permission to negotiate.
    """

    def __init__(self, cmd):
        self.cmd = cmd
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self.errors: Dict[str, str] = {}
        self._generation = 0
        self._request_sequence = 0
        self._requests: Dict[str, int] = {}
        self._lock = threading.RLock()

    def _listed(self, key: str, loader) -> List[Dict[str, Any]]:
        with self._lock:
            if key in self._cache:
                return list(self._cache[key])
            generation = self._generation
            self._request_sequence += 1
            request = self._request_sequence
            self._requests[key] = request
        try:
            listed = [self._as_dict(item) for item in loader()]
        except Exception as error:  # noqa: BLE001 - recorded so the UI can explain
            # An empty list and an unreadable provider need different customer actions.
            with self._lock:
                if (
                    generation != self._generation
                    or self._requests.get(key) != request
                ):
                    return []
                self.errors[key] = str(error)
                self._cache[key] = []
                self._requests.pop(key, None)
                return []
        with self._lock:
            if (
                generation != self._generation
                or self._requests.get(key) != request
            ):
                return []
            self._cache[key] = listed
            self.errors.pop(key, None)
            self._requests.pop(key, None)
            return list(listed)

    @staticmethod
    def namespace_key(resource_group_name: Optional[str]) -> str:
        return catalog_key("namespace", resource_group_name)

    def error_for(
        self,
        step_id: str,
        resource_group_name: Optional[str] = None,
    ) -> Optional[str]:
        """Return the loader error associated with an onboarding picker step."""
        key = catalog_key(step_id, resource_group_name)
        with self._lock:
            return self.errors.get(key)

    @staticmethod
    def _as_dict(item) -> Dict[str, Any]:
        if isinstance(item, dict):
            return item
        serialize = getattr(item, "as_dict", None)
        if callable(serialize):
            return serialize()
        return {
            "name": getattr(item, "name", ""),
            "id": getattr(item, "id", ""),
            "location": getattr(item, "location", ""),
            "identity": getattr(getattr(item, "identity", None), "__dict__", {}) or {},
        }

    def provisioning_services(self) -> List[Dict[str, Any]]:
        def load():
            from azext_iot._factory import iot_service_provisioning_factory

            client = iot_service_provisioning_factory(self.cmd.cli_ctx).iot_dps_resource
            return client.list_by_subscription()

        return self._listed("dps", load)

    def hubs(self) -> List[Dict[str, Any]]:
        def load():
            from azext_iot._factory import iot_hub_service_factory

            client = iot_hub_service_factory(self.cmd.cli_ctx)
            return client.iot_hub_resource.list_by_subscription()

        return self._listed("hub", load)

    def registered_hub_names(self, dps_resource: Dict[str, Any]) -> List[str]:
        """Hubs the selected DPS may allocate devices to.

        A hub outside this set produces a namespace that looks correctly linked but
        silently provisions nothing, so it is surfaced as a warning rather than hidden.
        """
        properties = (dps_resource or {}).get("properties") or {}
        return [
            str(hub.get("name") or "")
            for hub in (properties.get("iotHubs") or [])
            if isinstance(hub, dict)
        ]

    def subscriptions(self) -> List[Dict[str, Any]]:
        """Subscriptions from the CLI's cached login; enabled ones first."""

        def load():
            from azure.cli.core._profile import Profile

            subscriptions = Profile(cli_ctx=self.cmd.cli_ctx).load_cached_subscriptions()
            enabled = [s for s in subscriptions if str(s.get("state", "")) == "Enabled"]
            return [
                {
                    "name": item.get("name"),
                    "id": item.get("id"),
                    "location": "",
                    # A subscription has no managed identity; eligibility must not require one.
                    "identity": {"type": "n/a"},
                }
                for item in (enabled or subscriptions)
            ]

        return self._listed("subscription", load)

    def resource_groups(self) -> List[Dict[str, Any]]:
        def load():
            from azext_iot._factory import resource_service_factory

            client = resource_service_factory(self.cmd.cli_ctx).resource_groups
            return [
                {"name": group.name, "id": group.id, "location": group.location,
                 "identity": {"type": "n/a"}}
                for group in client.list()
            ]

        return self._listed("resource_group", load)

    def namespaces(self, session, resource_group_name=None) -> List[Dict[str, Any]]:
        """Existing Device Registry namespaces, so one can be adopted rather than created."""

        def load():
            return session.list_from(
                "namespace", "list", resource_group_name=resource_group_name
            )

        return self._listed(self.namespace_key(resource_group_name), load)

    def update_instances(self) -> List[Dict[str, Any]]:
        """Software Update instances, which the product owns and can also create."""

        def load():
            from azext_iot._factory import adr_update_instance_service_factory

            client = adr_update_instance_service_factory(self.cmd.cli_ctx)
            return client.update_instances.list_by_subscription()

        return self._listed("su", load)

    def user_assigned_identities(self) -> List[Dict[str, Any]]:
        """User-assigned identities available in the active subscription."""

        def load():
            from azure.cli.command_modules.identity._client_factory import (
                _msi_client_factory,
            )

            client = _msi_client_factory(
                self.cmd.cli_ctx
            ).user_assigned_identities
            return client.list_by_subscription()

        return self._listed("uami", load)

    def clear(self) -> None:
        with self._lock:
            self._generation += 1
            self._cache.clear()
            self.errors.clear()
            self._requests.clear()
