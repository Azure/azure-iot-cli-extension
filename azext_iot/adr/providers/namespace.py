# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from typing import Dict, List, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from msrestazure.tools import is_valid_resource_id, parse_resource_id

from azext_iot.adr.common import (
    IdentityType,
    ManagedServiceIdentityType,
    build_mi_body,
    validate_uami_resource_id,
)
from azext_iot.adr.providers.base import ADRProvider, console
from azext_iot.adr.topology import writable_namespace_properties

logger = get_logger(__name__)


_OUTBOUND_MI_MUTEX_MSG = (
    "Specify only one outbound identity: --outbound-system-assigned-mi uses the "
    "namespace's system-assigned identity, while --outbound-user-assigned-mi "
    "<uami-resource-id> uses a user-assigned managed identity (the two options "
    "are mutually exclusive)."
)


def _normalize_resource_id(resource_id: str) -> str:
    return resource_id.rstrip("/").casefold()


def _resolve_outbound_identity(
    outbound_mi_system_assigned: Optional[bool],
    outbound_mi_user_assigned: Optional[str],
) -> Optional[dict]:
    """Return the OutboundIdentity body (or None when no flag provided)."""
    # An empty/whitespace UAMI (e.g. `--outbound-user-assigned-mi ""`) means the caller
    # did not actually supply one. Clear it first so it neither trips the SAMI/UAMI
    # mutually-exclusive check below nor reaches build_mi_body as a malformed value.
    if outbound_mi_user_assigned is not None and not outbound_mi_user_assigned.strip():
        outbound_mi_user_assigned = None
    if outbound_mi_system_assigned and outbound_mi_user_assigned:
        raise MutuallyExclusiveArgumentError(_OUTBOUND_MI_MUTEX_MSG)
    if outbound_mi_user_assigned:
        validate_uami_resource_id(outbound_mi_user_assigned)
    return build_mi_body(
        outbound_mi_system_assigned,
        outbound_mi_user_assigned,
        sami_type=IdentityType.system_assigned.value,
        uami_type=IdentityType.user_assigned.value,
    )


def _build_namespace_identity(
    existing_identity: Optional[dict] = None,
    user_assigned_identity: Optional[str] = None,
    ensure_system_assigned: bool = False,
) -> dict:
    """Build a namespace ARM identity while preserving existing UAMI assignments."""
    existing_identity = existing_identity or {}
    identity_type = existing_identity.get("type") or ""
    has_system_assigned = ensure_system_assigned or "SystemAssigned" in identity_type
    user_assigned_identities = {
        _normalize_resource_id(resource_id): resource_id
        for resource_id in (existing_identity.get("userAssignedIdentities") or {})
    }
    if user_assigned_identity:
        user_assigned_identities.setdefault(
            _normalize_resource_id(user_assigned_identity),
            user_assigned_identity,
        )

    if has_system_assigned and user_assigned_identities:
        resolved_type = ManagedServiceIdentityType.system_assigned_user_assigned.value
    elif has_system_assigned:
        resolved_type = ManagedServiceIdentityType.system_assigned.value
    elif user_assigned_identities:
        resolved_type = ManagedServiceIdentityType.user_assigned.value
    else:
        resolved_type = "None"

    identity = {"type": resolved_type}
    if user_assigned_identities:
        identity["userAssignedIdentities"] = {
            resource_id: {} for resource_id in user_assigned_identities.values()
        }
    return identity


def _build_observability(
    existing_observability: Optional[dict], enabled: bool
) -> dict:
    observability = dict(existing_observability or {})
    observability["enabled"] = enabled
    return observability


def _managed_identity_type(has_system_assigned: bool, user_identity_ids) -> str:
    if has_system_assigned and user_identity_ids:
        return ManagedServiceIdentityType.system_assigned_user_assigned.value
    if has_system_assigned:
        return ManagedServiceIdentityType.system_assigned.value
    if user_identity_ids:
        return ManagedServiceIdentityType.user_assigned.value
    return "None"


def _clean_identity_ids(identity_ids: Optional[List[str]]) -> Optional[List[str]]:
    if identity_ids is None:
        return None
    cleaned = [
        identity_id.strip()
        for identity_id in identity_ids
        if isinstance(identity_id, str) and identity_id.strip()
    ]
    if len(cleaned) != len(identity_ids):
        raise InvalidArgumentValueError(
            "User-assigned identity resource IDs must not be empty."
        )
    unique_ids = {}
    for identity_id in cleaned:
        validate_uami_resource_id(identity_id)
        unique_ids.setdefault(_normalize_resource_id(identity_id), identity_id)
    return list(unique_ids.values())


def _clean_migrate_resource_ids(resource_ids: Optional[List[str]]) -> List[str]:
    if not resource_ids:
        raise RequiredArgumentMissingError(
            "Specify at least one legacy asset resource ID with --resource-ids."
        )

    unique_ids = {}
    for resource_id in resource_ids:
        cleaned_id = resource_id.strip() if isinstance(resource_id, str) else ""
        if not cleaned_id or not is_valid_resource_id(cleaned_id):
            raise InvalidArgumentValueError(
                f"'{resource_id}' is not a valid Azure resource ID."
            )
        parsed = parse_resource_id(cleaned_id)
        if (
            (parsed.get("namespace") or "").casefold()
            != "microsoft.deviceregistry"
            or (parsed.get("type") or "").casefold() != "assets"
            or "child_name_1" in parsed
        ):
            raise InvalidArgumentValueError(
                f"'{resource_id}' is not a Microsoft.DeviceRegistry/assets "
                "resource ID."
            )
        unique_ids.setdefault(_normalize_resource_id(cleaned_id), cleaned_id)
    return list(unique_ids.values())


class NamespaceProvider(ADRProvider):
    def __init__(self, cmd):
        super(NamespaceProvider, self).__init__(cmd)

    def create(
        self,
        namespace_name: str,
        resource_group_name: str,
        location: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
        outbound_mi_system_assigned: Optional[bool] = None,
        outbound_mi_user_assigned: Optional[str] = None,
        observability_enabled: Optional[bool] = None,
        **kwargs,
    ):
        try:
            existing_namespace = self.client.namespaces.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
        except HttpResponseError as error:
            if error.status_code != 404:
                raise
            existing_namespace = None

        if not location:
            location = (existing_namespace or {}).get("location")
        if not location:
            location = self._ensure_location(
                self.cmd.cli_ctx, resource_group_name, location
            )

        namespace_resource = {"location": location}
        if tags is not None:
            namespace_resource["tags"] = tags
        elif existing_namespace is not None and "tags" in existing_namespace:
            namespace_resource["tags"] = deepcopy(existing_namespace["tags"])

        outbound_identity = _resolve_outbound_identity(
            outbound_mi_system_assigned, outbound_mi_user_assigned
        )

        existing_properties = (existing_namespace or {}).get("properties") or {}
        properties = writable_namespace_properties(existing_properties)
        if outbound_identity is not None:
            properties["outboundIdentity"] = outbound_identity
        elif outbound_mi_system_assigned is False:
            properties["outboundIdentity"] = None

        if existing_namespace is None:
            # Keep the established new-resource default while avoiding an
            # implicit SAMI change on CreateOrReplace of an existing resource.
            namespace_resource["identity"] = _build_namespace_identity(
                user_assigned_identity=(
                    outbound_identity.get("userAssignedIdentity")
                    if outbound_identity
                    else None
                ),
                ensure_system_assigned=True,
            )
        elif outbound_identity is not None:
            namespace_resource["identity"] = _build_namespace_identity(
                existing_identity=existing_namespace.get("identity"),
                user_assigned_identity=outbound_identity.get(
                    "userAssignedIdentity"
                ),
                ensure_system_assigned=bool(
                    outbound_mi_system_assigned
                ),
            )
        elif "identity" in existing_namespace:
            existing_identity = existing_namespace.get("identity")
            namespace_resource["identity"] = (
                _build_namespace_identity(existing_identity)
                if existing_identity
                else existing_identity
            )

        existing_observability = existing_properties.get("observability")
        if observability_enabled is not None:
            properties["observability"] = _build_observability(
                existing_observability, observability_enabled
            )

        if properties:
            namespace_resource["properties"] = properties

        poller = self.client.namespaces.begin_create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            resource=namespace_resource,
        )
        no_wait = kwargs.pop("no_wait", False)
        if no_wait:
            return poller
        with console.status(f"Creating namespace {namespace_name}..."):
            namespace_result = self._await_terminal(poller, **kwargs)

        # The create response may omit resourceGroup; backfill it from the request input.
        # (namespace_result can be None if the provisioningState poll times out.)
        if namespace_result and not namespace_result.get("resourceGroup"):
            namespace_result["resourceGroup"] = resource_group_name

        return namespace_result

    def show(self, namespace_name: str, resource_group_name: str):
        return self.client.namespaces.get(resource_group_name=resource_group_name, namespace_name=namespace_name)

    def list(self, resource_group_name: Optional[str] = None):
        if resource_group_name:
            result = self.client.namespaces.list_by_resource_group(resource_group_name=resource_group_name)
        else:
            result = self.client.namespaces.list_by_subscription()
        return list(result)

    def delete(self, namespace_name: str, resource_group_name: str, **kwargs):
        # The service does NOT cascade: it rejects the delete with 'NamespaceNotEmpty'
        # while any child resource remains, so children must be removed first.
        try:
            poller = self.client.namespaces.begin_delete(
                resource_group_name=resource_group_name, namespace_name=namespace_name
            )
            return self._wait(poller, f"Deleting namespace {namespace_name}...", **kwargs)
        except HttpResponseError as error:
            self._raise_if_namespace_not_empty(error, namespace_name)
            raise

    def migrate(
        self,
        namespace_name: str,
        resource_group_name: str,
        resource_ids: List[str],
        **kwargs,
    ):
        body = {
            "scope": "Resources",
            "resourceIds": _clean_migrate_resource_ids(resource_ids),
        }
        poller = self.client.namespaces.begin_migrate(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            body=body,
        )
        return self._wait(
            poller,
            f"Migrating assets into namespace {namespace_name}...",
            **kwargs,
        )

    @staticmethod
    def _raise_if_namespace_not_empty(error: HttpResponseError, namespace_name: str):
        """Translate the backend 'NamespaceNotEmpty' rejection into actionable guidance.

        Returns without raising when ``error`` is unrelated, so the caller can re-raise it
        unchanged.
        """
        if "NamespaceNotEmpty" not in str(error):
            return
        # error.message carries a multi-line 'Exception Details' block; keep only its first
        # line so the guidance below stays readable.
        summary = (error.message or str(error)).strip().splitlines()[0].strip()
        raise AzureResponseError(
            f"{summary}\nNamespace deletion does not cascade. Delete the child resources "
            f"and links in this safe order:\n"
            f"  az iot adr ns job run delete --ns {namespace_name} -g <rg> "
            f"--job-name <job> --run-name <run>\n"
            f"  az iot adr ns job delete --ns {namespace_name} -g <rg> -n <job>\n"
            f"  az iot adr ns registry-device delete --ns {namespace_name} -g <rg> -n <device>\n"
            f"  az iot adr ns group delete --ns {namespace_name} -g <rg> -n <group>\n"
            f"  az iot adr ns ca policy delete --ns {namespace_name} -g <rg> "
            f"--ca-name <ca> -n <policy>\n"
            f"  az iot adr ns ca delete --ns {namespace_name} -g <rg> -n <ca>\n"
            f"  az iot adr ns link hub delete --ns {namespace_name} -g <rg> -n <endpoint>\n"
            f"  az iot adr ns link dps delete --ns {namespace_name} -g <rg> -n <endpoint>\n"
            f"  az iot adr ns link su delete --ns {namespace_name} -g <rg> -n <endpoint>\n"
            "Warning: each link delete command permanently deletes the linked "
            "Azure Hub, DPS, or Update Instance resource; it is not a non-destructive unlink."
        )

    def update(
        self,
        namespace_name: str,
        resource_group_name: str,
        tags: Optional[Dict[str, str]] = None,
        outbound_mi_system_assigned: Optional[bool] = None,
        outbound_mi_user_assigned: Optional[str] = None,
        observability_enabled: Optional[bool] = None,
        **kwargs,
    ):
        # NamespaceUpdate body: tags at top, substantive fields nested under "properties".
        body: dict = {}
        if tags is not None:
            body["tags"] = tags

        properties = {}
        namespace = None
        if observability_enabled is not None:
            namespace = self.client.namespaces.get(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
            )
            existing_observability = (
                ((namespace or {}).get("properties") or {}).get("observability") or {}
            )
            properties["observability"] = _build_observability(
                existing_observability, observability_enabled
            )

        outbound_identity = _resolve_outbound_identity(
            outbound_mi_system_assigned, outbound_mi_user_assigned
        )
        if outbound_identity is not None:
            properties["outboundIdentity"] = outbound_identity
            if namespace is None:
                namespace = self.client.namespaces.get(
                    resource_group_name=resource_group_name,
                    namespace_name=namespace_name,
                )
            body["identity"] = _build_namespace_identity(
                existing_identity=(namespace or {}).get("identity"),
                user_assigned_identity=outbound_identity.get("userAssignedIdentity"),
                ensure_system_assigned=bool(outbound_mi_system_assigned),
            )
        elif outbound_mi_system_assigned is False:
            properties["outboundIdentity"] = None
        if properties:
            body["properties"] = properties
        if not body:
            raise RequiredArgumentMissingError(
                "Nothing to update. Provide --tags, --observability-enabled, or "
                "an outbound managed identity."
            )

        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties=body,
        )
        return self._wait(poller, f"Updating namespace {namespace_name}...", **kwargs)

    def identity_show(self, namespace_name: str, resource_group_name: str):
        namespace = self.show(namespace_name, resource_group_name)
        return (namespace or {}).get("identity")

    def identity_assign(
        self,
        namespace_name: str,
        resource_group_name: str,
        system_assigned: bool = False,
        user_assigned_identities: Optional[List[str]] = None,
        **kwargs,
    ):
        user_assigned_identities = _clean_identity_ids(user_assigned_identities)
        if not system_assigned and not user_assigned_identities:
            raise RequiredArgumentMissingError(
                "Specify --system-assigned or at least one "
                "--user-assigned-identity."
            )

        namespace = self.show(namespace_name, resource_group_name)
        existing_identity = (namespace or {}).get("identity") or {}
        existing_type = existing_identity.get("type") or ""
        has_system_assigned = system_assigned or "SystemAssigned" in existing_type
        existing_ids = {
            _normalize_resource_id(identity_id): identity_id
            for identity_id in (
                existing_identity.get("userAssignedIdentities") or {}
            )
        }
        requested_ids = {
            _normalize_resource_id(identity_id): identity_id
            for identity_id in (user_assigned_identities or [])
        }
        added_ids = set(requested_ids) - set(existing_ids)
        adds_system_identity = system_assigned and "SystemAssigned" not in existing_type
        if not added_ids and not adds_system_identity:
            raise InvalidArgumentValueError(
                "All requested managed identities are already assigned."
            )
        identity_ids = {
            **existing_ids,
            **{
                normalized_id: requested_ids[normalized_id]
                for normalized_id in added_ids
            },
        }
        identity = {
            "type": _managed_identity_type(has_system_assigned, identity_ids)
        }
        if identity_ids:
            identity["userAssignedIdentities"] = {
                identity_id: {} for identity_id in sorted(identity_ids.values())
            }

        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties={"identity": identity},
        )
        no_wait = kwargs.get("no_wait", False)
        result = self._wait(
            poller,
            f"Assigning managed identities to namespace {namespace_name}...",
            **kwargs,
        )
        if no_wait:
            return result
        return (result or {}).get("identity")

    def identity_remove(
        self,
        namespace_name: str,
        resource_group_name: str,
        system_assigned: bool = False,
        user_assigned_identities: Optional[List[str]] = None,
        **kwargs,
    ):
        user_assigned_identities = _clean_identity_ids(user_assigned_identities)
        if not system_assigned and user_assigned_identities is None:
            raise RequiredArgumentMissingError(
                "Specify --system-assigned or --user-assigned-identity."
            )

        namespace = self.show(namespace_name, resource_group_name)
        existing_identity = (namespace or {}).get("identity") or {}
        existing_type = existing_identity.get("type") or ""
        has_system_assigned = "SystemAssigned" in existing_type
        existing_ids = {
            _normalize_resource_id(identity_id): identity_id
            for identity_id in (
                existing_identity.get("userAssignedIdentities") or {}
            )
        }
        requested_ids = {
            _normalize_resource_id(identity_id): identity_id
            for identity_id in (user_assigned_identities or [])
        }
        remove_ids = (
            set(existing_ids)
            if user_assigned_identities == []
            else set(requested_ids)
        )
        if not system_assigned and not remove_ids:
            raise InvalidArgumentValueError(
                "The namespace has no user-assigned identities to remove."
            )
        missing_ids = remove_ids - set(existing_ids)
        if missing_ids:
            names = ", ".join(
                sorted(requested_ids[identity_id] for identity_id in missing_ids)
            )
            raise InvalidArgumentValueError(
                f"These user-assigned identities are not assigned: {names}."
            )
        if system_assigned and not has_system_assigned:
            raise InvalidArgumentValueError(
                "The namespace does not have a system-assigned identity."
            )

        outbound_identity = ((namespace or {}).get("properties") or {}).get(
            "outboundIdentity"
        ) or {}
        if system_assigned and outbound_identity.get("type") == "SystemAssigned":
            raise InvalidArgumentValueError(
                "The system-assigned identity is configured as the outbound "
                "identity. Change the outbound identity before removing it."
            )
        outbound_uami = outbound_identity.get("userAssignedIdentity")
        if (
            outbound_uami
            and _normalize_resource_id(outbound_uami) in remove_ids
        ):
            raise InvalidArgumentValueError(
                "A selected user-assigned identity is configured as the outbound "
                "identity. Change the outbound identity before removing it."
            )

        remaining_ids = set(existing_ids) - remove_ids
        has_system_assigned = has_system_assigned and not system_assigned
        identity = {
            "type": _managed_identity_type(has_system_assigned, remaining_ids)
        }
        if remaining_ids:
            identity["userAssignedIdentities"] = {
                **{
                    existing_ids[identity_id]: {}
                    for identity_id in sorted(remaining_ids)
                },
                **{
                    existing_ids[identity_id]: None
                    for identity_id in sorted(remove_ids)
                },
            }

        poller = self.client.namespaces.begin_update(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            properties={"identity": identity},
        )
        no_wait = kwargs.get("no_wait", False)
        result = self._wait(
            poller,
            f"Removing managed identities from namespace {namespace_name}...",
            **kwargs,
        )
        if no_wait:
            return result
        return (result or {}).get("identity")
