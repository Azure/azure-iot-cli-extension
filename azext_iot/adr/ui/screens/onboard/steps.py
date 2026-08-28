# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""The onboarding step graph for connectivity (S0 through S5).

Scope is deliberately limited to reaching minimum viability: a namespace that can
provision and communicate with devices. Certificates, software updates, the first device
and the first group are later steps that plug into this same engine.

Ordering here is not a UI preference. Each rule mirrors one the service enforces:
a DPS endpoint must exist before a messaging endpoint is accepted, at most one
DPS endpoint may be linked, and both the namespace and each linked resource must
present an identity.

This module is deliberately free of any UI framework import.
"""

from typing import Any, Dict, List

from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.ui.core.commands import quote, render
from azext_iot.adr.ui.screens.onboard.create import (
    create_dps,
    create_hub,
    create_namespace,
    create_update_instance,
)
from azext_iot.adr.ui.screens.onboard.flow import Flow, PlanItem, Step
from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice,
    attach_identity,
    choice_key,
    create_uami,
    create_uami_command,
    get_choice,
    has_system_identity,
    has_uami,
    identity_command_flags,
    outbound_matches,
    principal_of as identity_principal_of,
)

#: Roles the linking saga needs, in both directions.
NAMESPACE_TO_RESOURCE_ROLES = {
    "hub": ("Contributor", "IoT Hub Data Contributor"),
    "dps": ("Contributor",),
    "su": ("Contributor",),
}
RESOURCE_TO_NAMESPACE_ROLE = "Contributor"
ADU_FIRST_PARTY_APP_ID = "6ee392c4-d339-4083-b04d-6b7947c6cf78"
#: Role assignments are not effective immediately; linking too soon fails for a reason
#: that looks like a backend bug. The e2e waits the same amount.
ROLE_PROPAGATION_WAIT_SEC = 60

#: Execution phases. Grants must precede the links that depend on them.
PHASE_PREREQUISITE = 10
PHASE_SCOPE = 5
PHASE_IDENTITY = 15
PHASE_GRANT = 20
PHASE_PROPAGATION = 30
PHASE_LINK = 40
PHASE_VERIFY = 50


# -- detection ----------------------------------------------------------------------


def _namespace(context: Dict[str, Any]) -> Dict[str, Any]:
    return context.get("namespace") or {}


def _endpoints(context: Dict[str, Any], section: str) -> Dict[str, Any]:
    properties = _namespace(context).get("properties") or {}
    group = properties.get(section) or {}
    return group.get("endpoints") or {}


def has_subscription(context: Dict[str, Any]) -> bool:
    return bool(context.get("subscription_id"))


def has_scope(context: Dict[str, Any]) -> bool:
    return bool(
        context.get("resource_group_name")
        and context.get("create_resource_group") is None
    )


def scope_planned(context: Dict[str, Any]) -> bool:
    return bool(context.get("resource_group_name")) or context.get("create_resource_group") is not None


def has_namespace(context: Dict[str, Any]) -> bool:
    return bool(_namespace(context))


def software_updates_linked(context: Dict[str, Any]) -> bool:
    return bool(_endpoints(context, "updating"))


def software_updates_chosen(context: Dict[str, Any]) -> bool:
    return bool(context.get("selected_sus")) or context.get("create_su") is not None


def has_identity(context: Dict[str, Any]) -> bool:
    return outbound_matches(
        _namespace(context),
        get_choice(context, "namespace"),
    )


def has_provisioning(context: Dict[str, Any]) -> bool:
    return bool(_endpoints(context, "provisioning"))


def has_messaging(context: Dict[str, Any]) -> bool:
    return bool(_endpoints(context, "messaging"))


# -- "will the plan satisfy this?" ---------------------------------------------------


def namespace_planned(context: Dict[str, Any]) -> bool:
    return bool(context.get("namespace_name")) or context.get("create_namespace") is not None


def identity_planned(context: Dict[str, Any]) -> bool:
    # An identity can always be assigned once the namespace exists or is planned.
    return namespace_planned(context)


def provisioning_planned(context: Dict[str, Any]) -> bool:
    return context.get("selected_dps") is not None or context.get("create_dps") is not None


def messaging_planned(context: Dict[str, Any]) -> bool:
    return bool(context.get("selected_hubs")) or context.get("create_hub") is not None


def permissions_confirmed(context: Dict[str, Any]) -> bool:
    """Role assignments are advisory until the open security question is settled.

    The flow reports what is required and lets the operator confirm it is done, rather
    than silently granting rights on the customer's behalf.
    """
    return bool(context.get("permissions_confirmed"))


# -- plan contributions --------------------------------------------------------------


class _PendingResource:
    """Stands in for a resource the plan will create.

    Its ARM id is deterministic, so the link command can be written now. Its principal id
    is not known until it exists, which is why its reverse grant is reported separately.
    """

    def __init__(self, request, subscription_id: str):
        self.name = request.name
        self.resource_id = request.arm_id(subscription_id or "<subscription>")
        self.raw = {}
        self.pending = True


def _placeholder(request, context: Dict[str, Any]) -> "_PendingResource":
    return _PendingResource(request, context.get("subscription_id") or "")


def _scope_of(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "namespace_name": context.get("namespace_name"),
        "resource_group_name": context.get("resource_group_name"),
    }


def plan_resource_group(context: Dict[str, Any]) -> List[PlanItem]:
    request = context.get("create_resource_group")
    if request is None:
        return [
            PlanItem(key="scope", description="Choose a resource group", action="blocked",
                     blocked_reason="no resource group chosen yet", phase=0,
                     long_running=False)
        ]

    def make(session, _ctx, _request=request):
        from azext_iot._factory import resource_service_factory

        client = resource_service_factory(session.cmd.cli_ctx).resource_groups
        return client.create_or_update(_request.name, {"location": _request.location})

    return [
        PlanItem(
            key="resource-group",
            description=f"Create resource group '{request.name}' in {request.location}",
            phase=PHASE_SCOPE,
            command=render(
                "group create",
                name=request.name,
                options={"location": request.location},
            ),
            long_running=False,
            invoke=make,
        )
    ]


def plan_namespace(context: Dict[str, Any]) -> List[PlanItem]:
    request = context.get("create_namespace")
    if request is None:
        return [
            PlanItem(
                key="namespace",
                description="Select an existing namespace, or create a new one",
                action="blocked",
                blocked_reason="no namespace selected yet",
                phase=0,
                long_running=False,
            )
        ]

    def make(session, _ctx, _request=request):
        return create_namespace(session, _request)

    command = render(
        "iot adr ns create",
        name=request.name,
        scope={"resource_group_name": request.resource_group_name},
        options={
            "location": request.location,
            "outbound_mi_user_assigned": (
                request.identity.uami_id
                if request.identity.is_user_assigned
                else None
            ),
        },
        flags=(
            ()
            if request.identity.is_user_assigned
            else ("--outbound-mi-system-assigned",)
        ),
    )
    if request.tags:
        tag_args = " ".join(
            quote(f"{key}={value}") for key, value in request.tags.items()
        )
        command += f" --tags {tag_args}"

    return [
        PlanItem(
            key="namespace",
            description=f"Create namespace '{request.name}' in {request.location}",
            phase=PHASE_PREREQUISITE,
            command=command,
            invoke=make,
            target=request.name,
            category="resource",
        )
    ]


def _configure_outbound_identity(session, context: Dict[str, Any]):
    choice = get_choice(context, "namespace")
    return session.call(
        session.provider("namespace").update,
        namespace_name=context.get("namespace_name"),
        resource_group_name=context.get("resource_group_name"),
        outbound_mi_system_assigned=not choice.is_user_assigned,
        outbound_mi_user_assigned=choice.uami_id if choice.is_user_assigned else None,
        no_wait=True,
    )


def plan_identity(context: Dict[str, Any]) -> List[PlanItem]:
    items = []
    name = context.get("namespace_name") or "<namespace>"
    if context.get("create_namespace") is not None:
        # `ns create` always assigns a system-assigned identity, so assigning one again
        # fails with "All requested managed identities are already assigned."
        items.append(
            PlanItem(
                key="identity",
                description="Namespace identity - assigned as part of creating the namespace",
                action="exists",
                phase=0,
                long_running=False,
                target=name,
                category="identity",
            )
        )
        return items
    choice = get_choice(context, "namespace")
    flag = (
        f"--outbound-mi-user-assigned {quote(choice.uami_id)}"
        if choice.is_user_assigned
        else "--outbound-mi-system-assigned"
    )
    items.append(
        PlanItem(
            key="identity",
            description=f"Configure namespace outbound identity: {choice.label}",
            phase=PHASE_IDENTITY,
            command=(
                f"az iot adr ns update -n {quote(name)} "
                f"-g {quote(context.get('resource_group_name') or '')} {flag}"
            ),
            depends_on=("namespace",),
            invoke=_configure_outbound_identity,
            target=name,
            category="identity",
        )
    )
    return items


def _all_identity_choices(context: Dict[str, Any]) -> List[IdentityChoice]:
    selected = list((context.get("identity_choices") or {}).values())
    for key in ("create_namespace", "create_dps", "create_hub", "create_su"):
        request = context.get(key)
        if request is not None:
            selected.append(request.identity)
    return selected


def _plan_uami_creations(context: Dict[str, Any]) -> List[PlanItem]:
    items = []
    seen = set()
    for choice in _all_identity_choices(context):
        if not choice.is_user_assigned or not choice.create_uami:
            continue
        normalized = choice.uami_id.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)

        def make(session, _ctx, _choice=choice):
            return session.call(create_uami, session, _choice)

        items.append(
            PlanItem(
                key=f"uami-create-{choice.uami_name}",
                description=f"Create user-assigned identity '{choice.uami_name}'",
                phase=PHASE_PREREQUISITE - 1,
                command=create_uami_command(choice),
                invoke=make,
                verify=_uami_verifier(choice),
                target=choice.uami_name,
                category="identity",
            )
        )
    return items


def plan_uamis(context: Dict[str, Any]) -> List[PlanItem]:
    return _plan_uami_creations(context)


def _uami_verifier(choice: IdentityChoice):
    def verify(session, _context, notify=None):
        import time

        from azure.cli.command_modules.identity._client_factory import (
            _msi_client_factory,
        )

        client = _msi_client_factory(
            session.cmd.cli_ctx
        ).user_assigned_identities
        for _ in range(30):
            identity = client.get(
                resource_group_name=choice.uami_resource_group,
                resource_name=choice.uami_name,
            )
            payload = (
                identity.as_dict()
                if hasattr(identity, "as_dict")
                else identity
            )
            principal = (
                payload.get("principal_id")
                or payload.get("principalId")
                if isinstance(payload, dict)
                else getattr(identity, "principal_id", None)
            )
            if principal:
                if notify is not None:
                    notify(f"principalId: {principal}")
                return identity
            if notify is not None:
                notify("Waiting for principalId")
            time.sleep(2)
        raise AzureResponseError(
            f"Timed out waiting for UAMI '{choice.uami_name}' principalId."
        )

    return verify


def _plan_target_identity(
    context: Dict[str, Any],
    kind: str,
    target,
    choice: IdentityChoice,
) -> List[PlanItem]:
    """Plan SAMI enablement or UAMI attachment for one selected target."""
    if getattr(target, "pending", False):
        return []
    raw = dict(getattr(target, "raw", None) or {})
    raw.setdefault("name", target.name)
    raw.setdefault("id", target.resource_id)
    raw.setdefault("resourceGroup", getattr(target, "resource_group", ""))
    ready = (
        has_uami(raw, choice.uami_id)
        if choice.is_user_assigned
        else has_system_identity(raw)
    )
    if ready:
        return []

    def attach(_session, ctx, _kind=kind, _raw=raw, _choice=choice):
        return _session.call(
            attach_identity,
            ctx["_catalog"],
            _kind,
            _raw,
            _choice,
        )

    if choice.is_user_assigned:
        description = f"Attach {choice.label} to {kind} '{target.name}'"
        if kind == "hub":
            command = (
                f"az iot hub identity assign -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} "
                f"--user-assigned {quote(choice.uami_id)}"
            )
        elif kind == "dps":
            command = (
                f"az iot dps update -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} "
                f"--mi-user-assigned {quote(choice.uami_id)}"
            )
        else:
            command = (
                f"az iot adr ns su instance update -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} "
                f"--mi-user-assigned {quote(choice.uami_id)}"
            )
    else:
        description = f"Enable system-assigned identity on {kind} '{target.name}'"
        if kind == "hub":
            command = (
                f"az iot hub identity assign -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} --system-assigned"
            )
        elif kind == "dps":
            command = (
                f"az iot dps update -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} "
                "--mi-system-assigned true"
            )
        else:
            command = (
                f"az iot adr ns su instance update -n {quote(target.name)} "
                f"-g {quote(raw.get('resourceGroup') or '')} "
                "--mi-system-assigned true"
            )
    return [
        PlanItem(
            key=f"identity-{choice_key(kind, target.resource_id)}",
            description=description,
            phase=PHASE_IDENTITY,
            command=command,
            invoke=attach,
            target=target.name,
            category="identity",
        )
    ]


def plan_provisioning(context: Dict[str, Any]) -> List[PlanItem]:
    dps = context.get("selected_dps")
    request = context.get("create_dps")
    items: List[PlanItem] = []

    if dps is None and request is None:
        return [
            PlanItem(key="dps", description="Select or create a DPS",
                     action="blocked", blocked_reason="no DPS chosen yet",
                     phase=0, long_running=False)
        ]

    if request is not None:
        def make(session, ctx, _request=request):
            return create_dps(ctx["_catalog"], _request)

        items.append(
            PlanItem(
                key="dps-create",
                description=(
                    f"Create DPS '{request.name}' in {request.location} "
                    f"with {request.capacity} S1 unit(s)"
                ),
                phase=PHASE_PREREQUISITE,
                command=render(
                    "iot dps create",
                    name=request.name,
                    scope={"resource_group_name": request.resource_group_name},
                    options={
                        "location": request.location,
                        "sku": request.sku or "S1",
                        "unit": request.capacity,
                        "mi_user_assigned": (
                            request.identity.uami_id
                            if request.identity.is_user_assigned
                            else None
                        ),
                    },
                    flags=(
                        ()
                        if request.identity.is_user_assigned
                        else ("--mi-system-assigned",)
                    ),
                ),
                invoke=make,
                target=request.name,
                category="resource",
            )
        )
        dps = _placeholder(request, context)
        choice = request.identity
    else:
        choice = get_choice(context, "dps", dps.resource_id)

    items.extend(_plan_target_identity(context, "dps", dps, choice))

    endpoint = context.get("dps_endpoint_name") or "dps"
    link_command = render(
        "iot adr ns link dps add",
        scope=_scope_of(context),
        options={"endpoint_name": endpoint, "dps_id": dps.resource_id},
    )

    def link(session, ctx, _dps=dps, _endpoint=endpoint, _choice=choice):
        return session.call(
            session.provider("link").dps_add,
            endpoint_name=_endpoint,
            namespace_name=ctx.get("namespace_name"),
            resource_group_name=ctx.get("resource_group_name"),
            dps_resource_id=_dps.resource_id,
            mi_system_assigned=not _choice.is_user_assigned,
            mi_user_assigned=_choice.uami_id if _choice.is_user_assigned else None,
            no_wait=True,
        )

    items.append(
        PlanItem(
            key="dps",
            description=f"Link DPS '{dps.name}' as endpoint '{endpoint}'",
            phase=PHASE_LINK,
            command=(
                f"{link_command} "
                f"{identity_command_flags(choice)}"
            ),
            depends_on=("identity",),
            invoke=link,
            verify=_endpoint_verifier("provisioning", endpoint),
            target=endpoint,
            category="link",
        )
    )
    return items


def plan_messaging(context: Dict[str, Any]) -> List[PlanItem]:
    hubs = list(context.get("selected_hubs") or [])
    request = context.get("create_hub")
    items: List[PlanItem] = []

    if not hubs and request is None:
        return [
            PlanItem(key="hub", description="Select or create an IoT Hub", action="blocked",
                     blocked_reason="no hub chosen yet", phase=0, long_running=False)
        ]

    if request is not None:
        def make(session, ctx, _request=request):
            return create_hub(ctx["_catalog"], _request)

        items.append(
            PlanItem(
                key="hub-create",
                description=(
                    f"Create IoT Hub '{request.name}' in {request.location} "
                    f"with {request.capacity} {request.sku or 'S1'} unit(s)"
                ),
                phase=PHASE_PREREQUISITE,
                command=render(
                    "iot hub create",
                    name=request.name,
                    scope={"resource_group_name": request.resource_group_name},
                    options={
                        "location": request.location,
                        "sku": request.sku or "S1",
                        "unit": request.capacity,
                        "mi_user_assigned": (
                            request.identity.uami_id
                            if request.identity.is_user_assigned
                            else None
                        ),
                    },
                    flags=(
                        ()
                        if request.identity.is_user_assigned
                        else ("--mi-system-assigned",)
                    ),
                ),
                invoke=make,
                target=request.name,
                category="resource",
            )
        )
        hubs.append(_placeholder(request, context))
    for index, hub in enumerate(hubs):
        choice = (
            request.identity
            if request is not None and getattr(hub, "pending", False)
            else get_choice(context, "hub", hub.resource_id)
        )
        items.extend(_plan_target_identity(context, "hub", hub, choice))
        endpoint = hub.name if len(hubs) > 1 else (context.get("hub_endpoint_name") or hub.name)
        link_command = render(
            "iot adr ns link hub add",
            scope=_scope_of(context),
            options={"endpoint_name": endpoint, "hub_id": hub.resource_id},
        )

        def link(session, ctx, _hub=hub, _endpoint=endpoint, _choice=choice):
            return session.call(
                session.provider("link").hub_add,
                endpoint_name=_endpoint,
                namespace_name=ctx.get("namespace_name"),
                resource_group_name=ctx.get("resource_group_name"),
                hub_resource_id=_hub.resource_id,
                mi_system_assigned=not _choice.is_user_assigned,
                mi_user_assigned=_choice.uami_id if _choice.is_user_assigned else None,
                no_wait=True,
            )

        items.append(
            PlanItem(
                key=f"hub-{index}",
                description=f"Link IoT Hub '{hub.name}' as endpoint '{endpoint}'",
                phase=PHASE_LINK,
                command=(
                    f"{link_command} "
                    f"{identity_command_flags(choice)}"
                ),
                # The service rejects a messaging endpoint before a provisioning one exists.
                depends_on=("dps",),
                invoke=link,
                verify=_endpoint_verifier("messaging", endpoint),
                target=endpoint,
                category="link",
            )
        )
    return items


def principal_of(payload: Dict[str, Any]) -> str:
    """SystemAssigned principal id of a resource, or empty when it has none."""
    identity = (payload or {}).get("identity") or {}
    return str(identity.get("principalId") or "") if isinstance(identity, dict) else ""


def namespace_arm_id(context: Dict[str, Any]) -> str:
    return (
        f"/subscriptions/{context.get('subscription_id') or '<subscription>'}"
        f"/resourceGroups/{context.get('resource_group_name') or '<resource-group>'}"
        f"/providers/Microsoft.DeviceRegistry/namespaces/"
        f"{context.get('namespace_name') or '<namespace>'}"
    )


def _principal_lookup(resource_id: str) -> str:
    """A shell expression that resolves a newly created resource's principal id."""
    if not resource_id:
        raise ValueError("a principal lookup needs a resource id")
    return (
        '"$(az resource show '
        f"--ids {quote(resource_id)} "
        '--query "identity.principalId || properties.principalId" --output tsv)"'
    )


def grant_command(
    principal: str,
    role: str,
    scope: str,
    principal_source: str = "",
) -> str:
    """A role grant addressed by object id.

    Matches the form the e2e uses: an object id needs no directory lookup, and the
    principal type must be given explicitly for a managed identity.
    """
    assignee = quote(principal) if principal else _principal_lookup(principal_source)
    return (
        f"az role assignment create --assignee-object-id {assignee} "
        f"--assignee-principal-type ServicePrincipal --role {quote(role)} "
        f"--scope {quote(scope)}"
    )


def plan_software_updates(context: Dict[str, Any]) -> List[PlanItem]:
    """Optional: link an update instance so the namespace can run update jobs."""
    instances = list(context.get("selected_sus") or [])
    request = context.get("create_su")
    if not instances and request is None:
        return []

    items: List[PlanItem] = []
    if request is not None:
        def make(session, _ctx, _request=request):
            return create_update_instance(session, _request)

        items.append(
            PlanItem(
                key="su-create",
                description=f"Create update instance '{request.name}' in {request.location}",
                phase=PHASE_PREREQUISITE,
                command=render("iot adr ns su instance create", name=request.name,
                               scope={"resource_group_name": request.resource_group_name},
                               options={
                                   "location": request.location,
                                   "mi_user_assigned": (
                                       request.identity.uami_id
                                       if request.identity.is_user_assigned
                                       else None
                                   ),
                               },
                               flags=(
                                   ()
                                   if request.identity.is_user_assigned
                                   else ("--mi-system-assigned",)
                               )),
                invoke=make,
                target=request.name,
                category="resource",
            )
        )
        instances.append(_placeholder(request, context))

    # Updating endpoints are a map on the namespace, so several may be linked. One chosen
    # instance keeps the configured endpoint name; several must be named apart.
    for index, instance in enumerate(instances):
        choice = (
            request.identity
            if request is not None and getattr(instance, "pending", False)
            else get_choice(context, "su", instance.resource_id)
        )
        items.extend(_plan_target_identity(context, "su", instance, choice))
        endpoint = (
            instance.name if len(instances) > 1
            else (context.get("su_endpoint_name") or "su")
        )
        link_command = render(
            "iot adr ns link su add",
            scope=_scope_of(context),
            options={
                "endpoint_name": endpoint,
                "su_id": instance.resource_id,
            },
        )

        def link(session, ctx, _su=instance, _endpoint=endpoint, _choice=choice):
            return session.call(
                session.provider("link").su_add,
                endpoint_name=_endpoint,
                namespace_name=ctx.get("namespace_name"),
                resource_group_name=ctx.get("resource_group_name"),
                su_resource_id=_su.resource_id,
                mi_system_assigned=not _choice.is_user_assigned,
                mi_user_assigned=_choice.uami_id if _choice.is_user_assigned else None,
                no_wait=True,
            )

        items.append(
            PlanItem(
                key="su" if index == 0 else f"su-{index}",
                description=f"Link update instance '{instance.name}' as endpoint '{endpoint}'",
                phase=PHASE_LINK,
                command=(
                    f"{link_command} "
                    f"{identity_command_flags(choice)}"
                ),
                depends_on=("dps",),
                invoke=link,
                verify=_endpoint_verifier("updating", endpoint, require_service_address=True),
                target=endpoint,
                category="link",
            )
        )
    return items


def _endpoint_verifier(
    section: str,
    endpoint_name: str,
    require_service_address: bool = False,
):
    """Wait for one namespace endpoint's asynchronous linking saga."""

    def verify(session, context, notify=None):
        import time

        attempts = int(context.get("_link_poll_attempts", 120))
        interval = float(context.get("_link_poll_interval", 5))
        last_state = ""
        for _ in range(attempts):
            namespace = session.call(
                session.provider("namespace").show,
                namespace_name=context.get("namespace_name"),
                resource_group_name=context.get("resource_group_name"),
            )
            endpoint = (
                (((namespace or {}).get("properties") or {}).get(section) or {})
                .get("endpoints", {})
                .get(endpoint_name)
            ) or {}
            status = endpoint.get("provisioningStatus") or {}
            state = str(
                endpoint.get("linkingState")
                or (status.get("status") if isinstance(status, dict) else "")
                or ""
            )
            last_state = state or "not visible"
            if notify is not None:
                notify(f"linkingState: {last_state}")
            if state.casefold() == "succeeded":
                if require_service_address and not endpoint.get("serviceAddress"):
                    if notify is not None:
                        notify("linkingState: Succeeded; waiting for serviceAddress")
                else:
                    return endpoint
            if state.casefold() in ("failed", "canceled"):
                error = endpoint.get("linkingError") or endpoint.get("error") or {}
                detail = error.get("message") if isinstance(error, dict) else str(error)
                raise AzureResponseError(
                    f"Endpoint '{endpoint_name}' linking failed"
                    + (f": {detail}" if detail else ".")
                )
            time.sleep(interval)
        raise AzureResponseError(
            f"Timed out waiting for endpoint '{endpoint_name}' linkingState "
            f"(last state: {last_state})."
        )

    return verify


def plan_final_verification(context: Dict[str, Any]) -> List[PlanItem]:
    expected = []
    dps = context.get("selected_dps")
    dps_request = context.get("create_dps")
    if dps is not None or dps_request is not None:
        target = dps.resource_id if dps is not None else dps_request.arm_id(
            context.get("subscription_id") or ""
        )
        expected.append(("provisioning", context.get("dps_endpoint_name") or "dps", target))
    hubs = list(context.get("selected_hubs") or [])
    if context.get("create_hub") is not None:
        hubs.append(_placeholder(context["create_hub"], context))
    for hub in hubs:
        endpoint = hub.name if len(hubs) > 1 else (
            context.get("hub_endpoint_name") or hub.name
        )
        expected.append(("messaging", endpoint, hub.resource_id))
    instances = list(context.get("selected_sus") or [])
    if context.get("create_su") is not None:
        instances.append(_placeholder(context["create_su"], context))
    for instance in instances:
        endpoint = instance.name if len(instances) > 1 else (
            context.get("su_endpoint_name") or "su"
        )
        expected.append(("updating", endpoint, instance.resource_id))
    if not expected:
        return []

    def verify(session, ctx, notify=None, _expected=tuple(expected)):
        namespace = session.call(
            session.provider("namespace").show,
            namespace_name=ctx.get("namespace_name"),
            resource_group_name=ctx.get("resource_group_name"),
        )
        namespace_request = ctx.get("create_namespace")
        namespace_choice = (
            namespace_request.identity
            if namespace_request is not None
            else get_choice(ctx, "namespace")
        )
        if not outbound_matches(namespace, namespace_choice):
            raise AzureResponseError(
                "Final verification found an unexpected namespace outbound identity."
            )
        properties = (namespace or {}).get("properties") or {}
        for section, endpoint_name, target_id in _expected:
            endpoint = (
                ((properties.get(section) or {}).get("endpoints") or {})
                .get(endpoint_name)
            ) or {}
            if str(endpoint.get("resourceId") or "").casefold() != target_id.casefold():
                raise AzureResponseError(
                    f"Final verification could not match endpoint '{endpoint_name}' "
                    f"to target '{target_id}'."
                )
            if str(endpoint.get("linkingState") or "").casefold() != "succeeded":
                raise AzureResponseError(
                    f"Final verification found endpoint '{endpoint_name}' in "
                    f"linkingState '{endpoint.get('linkingState') or 'unknown'}'."
                )
        if notify is not None:
            notify(f"{len(_expected)} endpoint(s) ready")
        return namespace

    return [
        PlanItem(
            key="verify-readiness",
            description="Verify namespace identity and endpoint readiness",
            phase=PHASE_VERIFY,
            command=(
                f"az iot adr ns show -n {quote(context.get('namespace_name') or '')} "
                f"-g {quote(context.get('resource_group_name') or '')}"
            ),
            invoke=lambda _session, _context: None,
            verify=verify,
            target=context.get("namespace_name") or "namespace",
            category="verify",
        )
    ]


def _grant_invoker(principal: str, principal_source: str, role: str, scope: str):
    """Bind one grant so the plan can run it like any other operation.

    ``principal`` may be empty when the resource holding the identity is created by an
    earlier item of this same plan; ``principal_source`` is then read at run time, by
    which point the resource exists.
    """
    def invoke(session, _context):
        from azext_iot.adr.ui.core.rbac import grant_role, resolve_principal

        assignee = principal or resolve_principal(session, principal_source)
        if not assignee:
            raise RuntimeError(
                f"could not read a system-assigned identity for "
                f"{(principal_source or '').rsplit('/', 1)[-1] or 'the resource'}, "
                f"so '{role}' could not be granted"
            )
        created = grant_role(session, assignee, role, scope)
        if created:
            # Only a newly created assignment has to propagate; see the wait below.
            _context["_granted_any"] = True
        return None
    return invoke


def _service_principal_grant_invoker(
    application_id: str,
    role: str,
    scope: str,
):
    def invoke(session, context):
        from azext_iot.adr.ui.core.rbac import (
            grant_role,
            resolve_service_principal,
        )

        principal = resolve_service_principal(session, application_id)
        if not principal:
            raise RuntimeError(
                "could not resolve the Azure Device Update service principal "
                f"for application id {application_id}"
            )
        created = grant_role(session, principal, role, scope)
        if created:
            context["_granted_any"] = True
        return None

    return invoke


def _service_principal_grant_command(
    application_id: str,
    role: str,
    scope: str,
) -> str:
    return (
        'az role assignment create --assignee-object-id '
        f'"$(az ad sp show --id {quote(application_id)} '
        '--query id --output tsv)" '
        "--assignee-principal-type ServicePrincipal "
        f"--role {quote(role)} --scope {quote(scope)}"
    )


def _wait_for_propagation(_session, context):
    """Role assignments are not effective the instant they are created.

    Skipped when every grant already existed - re-running setup should not idle for a
    minute waiting for propagation that happened long ago.
    """
    import time

    if not context.get("_granted_any"):
        return None
    time.sleep(ROLE_PROPAGATION_WAIT_SEC)
    return None


def plan_permissions(context: Dict[str, Any]) -> List[PlanItem]:
    """Emit the grants the linking saga needs, in both directions, ready to run.

    Both principal ids are already known - the namespace payload and each candidate carry
    their own identity - so the commands are emitted complete rather than as placeholders
    a customer would have to fill in by hand.

    Whether radr runs them itself turns on ``can_grant_roles`` in the context, which is
    ARM's own answer about this caller at this scope. When ARM says no, the grants stay in
    the plan as commands to hand to someone with Owner or User Access Administrator -
    the customer still sees exactly what has to happen, and why radr stopped short.
    """
    namespace_scope = namespace_arm_id(context)
    namespace_request = context.get("create_namespace")
    namespace_choice = (
        namespace_request.identity
        if namespace_request is not None
        else get_choice(context, "namespace")
    )
    namespace_principal = identity_principal_of(
        context.get("namespace") or {},
        namespace_choice,
    )
    namespace_principal_source = (
        namespace_choice.uami_id
        if namespace_choice.is_user_assigned
        else namespace_scope
    )
    #: None means "not probed / could not tell", which is treated as no.
    may_grant = context.get("can_grant_roles") is True

    items: List[PlanItem] = []
    targets = []
    # Resources being created need the same grants as existing ones; their principal id
    # is simply not known yet, which the reverse grant reports explicitly.
    if context.get("selected_dps") is not None:
        targets.append(("dps", context["selected_dps"]))
    elif context.get("create_dps") is not None:
        targets.append(("dps", _placeholder(context["create_dps"], context)))
    for hub in context.get("selected_hubs") or []:
        targets.append(("hub", hub))
    if context.get("create_hub") is not None:
        targets.append(("hub", _placeholder(context["create_hub"], context)))
    for instance in context.get("selected_sus") or []:
        targets.append(("su", instance))
    if context.get("create_su") is not None:
        targets.append(("su", _placeholder(context["create_su"], context)))

    for kind, target in targets:
        request = context.get(
            {"dps": "create_dps", "hub": "create_hub", "su": "create_su"}[kind]
        )
        target_choice = (
            request.identity
            if request is not None and getattr(target, "pending", False)
            else get_choice(context, kind, target.resource_id)
        )
        target_principal = identity_principal_of(
            getattr(target, "raw", None) or {},
            target_choice,
        )
        target_principal_source = (
            target_choice.uami_id
            if target_choice.is_user_assigned
            else target.resource_id
        )
        target_pending = bool(getattr(target, "pending", False))
        namespace_pending = context.get("create_namespace") is not None

        # Forward: the namespace identity acts on the linked resource.
        for role in NAMESPACE_TO_RESOURCE_ROLES[kind]:
            item = PlanItem(
                key=f"grant-ns-to-{kind}-{target.name}-{role}",
                description=f"Grant the namespace identity '{role}' on {kind} '{target.name}'",
                action="manual",
                phase=PHASE_GRANT,
                long_running=False,
                target=target.name,
                category="role",
            )
            if namespace_principal or namespace_pending or namespace_principal_source:
                item.command = grant_command(
                    namespace_principal,
                    role,
                    target.resource_id,
                    principal_source=namespace_principal_source,
                )
                if may_grant:
                    item.action = "create"
                    # An empty principal is resolved when the item runs, by which point an
                    # earlier item in this same plan has created the namespace.
                    item.invoke = _grant_invoker(
                        namespace_principal,
                        namespace_principal_source,
                        role,
                        target.resource_id,
                    )
                elif not namespace_principal:
                    item.blocked_reason = (
                        "run this after the namespace is created, using its principal id"
                    )
            else:
                item.action = "blocked"
                item.blocked_reason = (
                    "the namespace has no system-assigned identity yet; assign one first"
                )
            items.append(item)

        # Reverse: the linked resource's identity acts on the namespace.
        reverse = PlanItem(
            key=f"grant-{kind}-to-ns-{target.name}",
            description=(
                f"Grant {kind} '{target.name}' identity "
                f"'{RESOURCE_TO_NAMESPACE_ROLE}' on the namespace"
            ),
            action="manual",
            phase=PHASE_GRANT,
            long_running=False,
            target=target.name,
            category="role",
        )
        if target_principal or target_pending or target_principal_source:
            reverse.command = grant_command(
                target_principal,
                RESOURCE_TO_NAMESPACE_ROLE,
                namespace_scope,
                principal_source=target_principal_source,
            )
            if may_grant:
                reverse.action = "create"
                reverse.invoke = _grant_invoker(
                    target_principal, target_principal_source,
                    RESOURCE_TO_NAMESPACE_ROLE, namespace_scope,
                )
            elif not target_principal:
                reverse.blocked_reason = (
                    f"run this after {target.name} is created, using its principal id"
                )
        else:
            reverse.action = "blocked"
            reverse.blocked_reason = (
                f"{target.name} exposes no system-assigned identity, so the reverse grant "
                "cannot be made; recreate it with an identity"
            )
        items.append(reverse)

        if kind == "su":
            consented = context.get("adu_fpa_confirmed") is True
            fpa = PlanItem(
                key=f"grant-adu-fpa-{target.name}",
                description=(
                    f"Grant the Azure Device Update service 'Contributor' on "
                    f"update instance '{target.name}'"
                ),
                action=(
                    "blocked"
                    if not consented
                    else ("create" if may_grant else "manual")
                ),
                blocked_reason=(
                    "explicit approval is required for the Azure Device Update "
                    "first-party service grant"
                    if not consented
                    else ""
                ),
                phase=PHASE_GRANT,
                long_running=False,
                command=_service_principal_grant_command(
                    ADU_FIRST_PARTY_APP_ID,
                    "Contributor",
                    target.resource_id,
                ),
                target=target.name,
                category="role",
            )
            if consented and may_grant:
                fpa.invoke = _service_principal_grant_invoker(
                    ADU_FIRST_PARTY_APP_ID,
                    "Contributor",
                    target.resource_id,
                )
            items.append(fpa)

    deduplicated = []
    seen_grants = set()
    for item in items:
        if item.command and item.command.startswith("az role assignment create"):
            if item.command in seen_grants:
                continue
            seen_grants.add(item.command)
        deduplicated.append(item)
    items = deduplicated

    if items:
        items.append(
            PlanItem(
                key="grant-propagation",
                description=(
                    f"Wait about {ROLE_PROPAGATION_WAIT_SEC}s for role propagation before linking"
                ),
                action="create" if may_grant else "manual",
                phase=PHASE_PROPAGATION,
                long_running=False,
                command=f"sleep {ROLE_PROPAGATION_WAIT_SEC}",
                invoke=_wait_for_propagation if may_grant else None,
                target="Azure RBAC",
                category="wait",
            )
        )
    return items


# -- graph ---------------------------------------------------------------------------


def build_flow(context: Dict[str, Any]) -> Flow:
    """The connectivity flow: scope, namespace, identity, provisioning, messaging, grants."""
    steps = [
        Step(id="subscription", title="Subscription", detect=has_subscription),
        Step(id="scope", title="Resource group", after=("subscription",), detect=has_scope,
             planned=scope_planned, plan=plan_resource_group,
             blocked_reason="Choose a subscription first."),
        Step(id="uami", title="User-assigned identities", after=("scope",),
             detect=lambda ctx: False, plan=plan_uamis, hidden=True, optional=True),
        Step(id="namespace", title="Namespace", after=("scope",), detect=has_namespace,
             planned=namespace_planned, plan=plan_namespace),
        # Never a decision: `ns create` always assigns one, and adopting a namespace
        # without one simply adds an assign to the plan.
        Step(
            id="identity",
            title="Namespace identity",
            after=("namespace",),
            detect=has_identity,
            planned=identity_planned,
            plan=plan_identity,
            hidden=True,
            blocked_reason=(
                "Choose a namespace first. radr will enable its managed identity "
                "automatically when setup runs."
            ),
        ),
        Step(
            id="dps",
            title="Link DPS",
            after=("identity",),
            detect=has_provisioning,
            planned=provisioning_planned,
            plan=plan_provisioning,
            blocked_reason=(
                "The namespace needs a managed identity so Azure can authorize access "
                "to DPS and IoT Hub. radr adds it automatically when setup runs."
            ),
        ),
        Step(
            id="hub",
            title="Link Hub",
            after=("dps",),
            detect=has_messaging,
            planned=messaging_planned,
            plan=plan_messaging,
            blocked_reason=(
                "Choose a DPS first. Azure requires the DPS link before any IoT Hub link."
            ),
        ),
        Step(id="su", title="Link Software Updates", after=("dps",),
             detect=software_updates_linked, planned=software_updates_chosen,
             plan=plan_software_updates, optional=True,
             blocked_reason="Choose a DPS first."),
        Step(id="permissions", title="Grant role assignments",
             after=("dps",), detect=permissions_confirmed, plan=plan_permissions,
             hidden=True,
             blocked_reason="Choose the DPS, hubs, or update instances to link first."),
        Step(id="verification", title="Verify readiness",
             after=("dps",), detect=lambda ctx: False,
             plan=plan_final_verification, hidden=True, optional=True),
        # The commit point, named so the rail shows where changes happen.
        Step(id="review", title="Review and run", after=("namespace",),
             detect=lambda ctx: False, optional=True,
             blocked_reason="Choose or create a namespace first."),
    ]
    return Flow(steps=steps, context=context)
