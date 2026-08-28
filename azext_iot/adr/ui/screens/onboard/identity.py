# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the repo root for license information.
# --------------------------------------------------------------------------------------------

"""Managed-identity choices and mutations for guided namespace linking."""

from dataclasses import dataclass
from typing import Any, Dict

from azext_iot.adr.ui.core.commands import quote

SYSTEM_ASSIGNED = "system"
USER_ASSIGNED = "user"


@dataclass(frozen=True)
class IdentityChoice:
    """The identity one resource will use for its side of a namespace link."""

    mode: str = SYSTEM_ASSIGNED
    uami_id: str = ""
    uami_name: str = ""
    principal_id: str = ""
    create_uami: bool = False
    uami_resource_group: str = ""
    uami_location: str = ""

    @property
    def is_user_assigned(self) -> bool:
        return self.mode == USER_ASSIGNED

    @property
    def label(self) -> str:
        if self.is_user_assigned:
            return f"UAMI: {self.uami_name or self.uami_id.rsplit('/', 1)[-1]}"
        return "System-assigned"


def system_choice() -> IdentityChoice:
    return IdentityChoice()


def choice_from_namespace(namespace: Dict[str, Any]) -> IdentityChoice:
    current = outbound_identity(namespace)
    if str(current.get("type") or "").replace(" ", "").casefold() != "userassigned":
        return system_choice()
    resource_id = str(current.get("userAssignedIdentity") or "")
    principal = ""
    for attached_id, details in attached_uamis(namespace).items():
        if str(attached_id).casefold() == resource_id.casefold() and isinstance(details, dict):
            principal = str(details.get("principalId") or "")
            break
    return IdentityChoice(
        mode=USER_ASSIGNED,
        uami_id=resource_id,
        uami_name=resource_id.rsplit("/", 1)[-1],
        principal_id=principal,
    )


def choice_key(kind: str, resource_id: str = "") -> str:
    """Stable context key for a namespace or selected target resource."""
    if kind == "namespace":
        return "namespace"
    return f"{kind}:{resource_id.casefold()}"


def choices(context: Dict[str, Any]) -> Dict[str, IdentityChoice]:
    return context.setdefault("identity_choices", {})


def get_choice(
    context: Dict[str, Any],
    kind: str,
    resource_id: str = "",
) -> IdentityChoice:
    return choices(context).get(choice_key(kind, resource_id), system_choice())


def has_choice(
    context: Dict[str, Any],
    kind: str,
    resource_id: str = "",
) -> bool:
    return choice_key(kind, resource_id) in choices(context)


def set_choice(
    context: Dict[str, Any],
    kind: str,
    choice: IdentityChoice,
    resource_id: str = "",
) -> None:
    choices(context)[choice_key(kind, resource_id)] = choice


def remove_choice(
    context: Dict[str, Any],
    kind: str,
    resource_id: str = "",
) -> None:
    choices(context).pop(choice_key(kind, resource_id), None)


def identity_payload(resource: Dict[str, Any]) -> Dict[str, Any]:
    identity = (resource or {}).get("identity") or {}
    return identity if isinstance(identity, dict) else {}


def has_system_identity(resource: Dict[str, Any]) -> bool:
    identity_type = str(identity_payload(resource).get("type") or "")
    return "systemassigned" in identity_type.replace(" ", "").casefold()


def attached_uamis(resource: Dict[str, Any]) -> Dict[str, Any]:
    identity = identity_payload(resource)
    attached = (
        identity.get("userAssignedIdentities")
        or identity.get("user_assigned_identities")
        or {}
    )
    return attached if isinstance(attached, dict) else {}


def has_uami(resource: Dict[str, Any], resource_id: str) -> bool:
    expected = (resource_id or "").casefold()
    return any(str(item).casefold() == expected for item in attached_uamis(resource))


def outbound_identity(namespace: Dict[str, Any]) -> Dict[str, Any]:
    identity = ((namespace or {}).get("properties") or {}).get("outboundIdentity") or {}
    return identity if isinstance(identity, dict) else {}


def outbound_matches(namespace: Dict[str, Any], choice: IdentityChoice) -> bool:
    current = outbound_identity(namespace)
    identity_type = str(current.get("type") or "").replace(" ", "").casefold()
    if choice.is_user_assigned:
        current_id = str(current.get("userAssignedIdentity") or "").casefold()
        return identity_type == "userassigned" and current_id == choice.uami_id.casefold()
    return identity_type == "systemassigned"


def principal_of(resource: Dict[str, Any], choice: IdentityChoice) -> str:
    if choice.is_user_assigned:
        if choice.principal_id:
            return choice.principal_id
        attached = attached_uamis(resource)
        for resource_id, details in attached.items():
            if str(resource_id).casefold() != choice.uami_id.casefold():
                continue
            if isinstance(details, dict):
                return str(details.get("principalId") or "")
        return ""
    return str(identity_payload(resource).get("principalId") or "")


def identity_flags(choice: IdentityChoice):
    if choice.is_user_assigned:
        return (), {"mi_user_assigned": choice.uami_id}
    return ("--mi-system-assigned",), {}


def identity_command_flags(choice: IdentityChoice) -> str:
    if choice.is_user_assigned:
        return f"--mi-user-assigned {quote(choice.uami_id)}"
    return "--mi-system-assigned"


def assignment_rows(context: Dict[str, Any]):
    """Customer-facing identity matrix for Final Plan."""
    rows = [
        (
            "Namespace -> targets",
            context.get("namespace_name") or "<namespace>",
            get_choice(context, "namespace"),
        )
    ]
    dps = context.get("selected_dps")
    request = context.get("create_dps")
    if dps is not None:
        rows.append(("DPS -> namespace", dps.name, get_choice(context, "dps", dps.resource_id)))
    elif request is not None:
        rows.append(("DPS -> namespace", request.name, request.identity))
    hubs = list(context.get("selected_hubs") or [])
    for hub in hubs:
        rows.append(("Hub -> namespace", hub.name, get_choice(context, "hub", hub.resource_id)))
    if context.get("create_hub") is not None:
        rows.append(("Hub -> namespace", context["create_hub"].name, context["create_hub"].identity))
    instances = list(context.get("selected_sus") or [])
    for instance in instances:
        rows.append(("Updates -> namespace", instance.name, get_choice(context, "su", instance.resource_id)))
    if context.get("create_su") is not None:
        rows.append(("Updates -> namespace", context["create_su"].name, context["create_su"].identity))
    return rows


def create_uami_command(choice: IdentityChoice) -> str:
    return (
        f"az identity create -n {quote(choice.uami_name)} "
        f"-g {quote(choice.uami_resource_group)} "
        f"-l {quote(choice.uami_location)}"
    )


def create_uami(session, choice: IdentityChoice):
    from azure.cli.command_modules.identity._client_factory import _msi_client_factory

    client = _msi_client_factory(session.cmd.cli_ctx).user_assigned_identities
    return client.create_or_update(
        resource_group_name=choice.uami_resource_group,
        resource_name=choice.uami_name,
        parameters={"location": choice.uami_location},
    )


def attach_identity(catalog, kind: str, resource: Dict[str, Any], choice: IdentityChoice):
    """Attach the chosen identity without removing identities already on the resource."""
    if kind == "hub":
        from azext_iot._factory import iot_hub_service_factory

        client = iot_hub_service_factory(catalog.cmd.cli_ctx).iot_hub_resource
        body = dict(resource)
        identity = _merged_identity(resource, choice)
        body["identity"] = identity
        return client.begin_create_or_update(
            resource_group_name=_resource_group(resource),
            resource_name=resource.get("name"),
            iot_hub_description=body,
            etag=resource.get("etag"),
        )
    if kind == "dps":
        from azext_iot._factory import iot_service_provisioning_factory

        client = iot_service_provisioning_factory(
            catalog.cmd.cli_ctx
        ).iot_dps_resource
        body = dict(resource)
        body["identity"] = _merged_identity(resource, choice)
        return client.begin_create_or_update(
            resource_group_name=_resource_group(resource),
            provisioning_service_name=resource.get("name"),
            iot_dps_description=body,
        )
    if kind == "su":
        from azext_iot._factory import adr_update_instance_service_factory

        client = adr_update_instance_service_factory(
            catalog.cmd.cli_ctx
        ).update_instances
        return client.begin_update(
            resource_group_name=_resource_group(resource),
            update_instance_name=resource.get("name"),
            properties={"identity": _merged_identity(resource, choice)},
        )
    raise ValueError(f"Unsupported identity attachment target '{kind}'.")


def _merged_identity(resource: Dict[str, Any], choice: IdentityChoice) -> Dict[str, Any]:
    existing_uamis = dict(attached_uamis(resource))
    if choice.is_user_assigned:
        existing_uamis.setdefault(choice.uami_id, {})
    system = has_system_identity(resource) or not choice.is_user_assigned
    if system and existing_uamis:
        identity_type = "SystemAssigned, UserAssigned"
    elif system:
        identity_type = "SystemAssigned"
    elif existing_uamis:
        identity_type = "UserAssigned"
    else:
        identity_type = "None"
    identity = {"type": identity_type}
    if existing_uamis:
        identity["userAssignedIdentities"] = existing_uamis
    return identity


def _resource_group(resource: Dict[str, Any]) -> str:
    group = resource.get("resourceGroup") or resource.get("resourcegroup")
    if group:
        return str(group)
    parts = str(resource.get("id") or "").split("/")
    for index, part in enumerate(parts):
        if part.casefold() == "resourcegroups" and index + 1 < len(parts):
            return parts[index + 1]
    return ""
