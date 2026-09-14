# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""The onboarding step graph for connectivity (S0 through S5).

Scope covers namespace connectivity and optional Software Updates. Certificates,
groups and jobs remain separate browsing surfaces.

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
)

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
    return bool(_endpoints(context, "updating")) and not software_updates_chosen(context)


def software_updates_chosen(context: Dict[str, Any]) -> bool:
    return bool(context.get("selected_sus")) or context.get("create_su") is not None


def reconcile_software_updates_creation(context: Dict[str, Any]) -> None:
    """A reloaded matching endpoint proves that the planned creation/link persisted.

    This also covers a local timeout after Azure accepted the link. Never discard a
    request for a different target, or infer completion solely from a resource name.
    """
    request = context.get("create_su")
    endpoints = _endpoints(context, "updating")
    if request is None or len(endpoints) != 1:
        return
    target_id = (next(iter(endpoints.values())) or {}).get("resourceId") or ""
    planned_id = request.arm_id(context.get("subscription_id") or "")
    if target_id.rstrip("/").casefold() == planned_id.rstrip("/").casefold():
        context.pop("create_su")


def namespace_location(context: Dict[str, Any]):
    """Use live namespace state when available, otherwise the planned namespace region."""
    location = _namespace(context).get("location")
    request = context.get("create_namespace")
    return location or (request.location if request is not None else None)


def onboarding_error(context: Dict[str, Any]) -> str:
    """Reject all known topology/region conflicts before creating prerequisites."""
    reason = software_updates_error(context)
    if reason:
        return reason
    location = namespace_location(context)
    if not location:
        return ""
    for kind, key in (("dps", "selected_dps"), ("hub", "selected_hubs"), ("su", "selected_sus")):
        selected = context.get(key)
        targets = ([selected] if selected is not None else []) if kind == "dps" else list(selected or [])
        request = context.get(f"create_{kind}")
        if request is not None:
            targets.append(request)
        for target in targets:
            target_location = getattr(target, "location", "") or (
                getattr(target, "raw", None) or {}
            ).get("location")
            if target_location and str(target_location).casefold() != str(location).casefold():
                return (
                    f"Cross-region linking is not supported. Namespace region is '{location}'; "
                    f"{kind.upper()} '{target.name}' region is '{target_location}'. "
                    "Choose or create targets in the namespace region."
                )
    return ""


def software_updates_error(context: Dict[str, Any]) -> str:
    """Validate existing, selected and planned instances before any work is submitted."""
    endpoints = _endpoints(context, "updating")
    selected = list(context.get("selected_sus") or [])
    creating = context.get("create_su") is not None
    if len(endpoints) > 1 or len(selected) + int(creating) > 1:
        return "Only one Software Updates instance may be linked per namespace."
    if endpoints and (selected or creating):
        existing = next(iter(endpoints.values())) or {}
        if creating or (
            (existing.get("resourceId") or "").rstrip("/").casefold()
            != selected[0].resource_id.rstrip("/").casefold()
        ):
            return (
                "This namespace already has a Software Updates instance. Only one is allowed; "
                "su update changes the existing inbound identity, not the linked target."
            )
    return ""


def _su_endpoint_name(context: Dict[str, Any]) -> str:
    return next(iter(_endpoints(context, "updating")), None) or context.get("su_endpoint_name") or "su"


def _topology(namespace):
    """Only writable link state participates; asynchronous status changes are harmless."""
    properties = (namespace or {}).get("properties") or {}
    return (
        properties.get("outboundIdentity"),
        {
            section: {
                name: {key: endpoint.get(key) for key in (
                    "endpointType", "resourceId", "inboundCallerIdentity", "provisioning"
                )}
                for name, endpoint in ((properties.get(section) or {}).get("endpoints") or {}).items()
            }
            for section in ("provisioning", "messaging", "updating")
        },
    )


def plan_preflight(context: Dict[str, Any]) -> List[PlanItem]:
    """Guard the frozen review against stale topology before identities, grants or creates."""
    from copy import deepcopy

    if has_namespace(context) and has_identity(context) and not any(
        context.get(key) for key in (
            "create_resource_group", "create_namespace", "create_dps", "create_hub", "create_su",
            "selected_dps", "selected_hubs", "selected_sus",
        )
    ):
        return []
    expected = deepcopy(_topology(_namespace(context)))

    def verify(session, ctx):
        if getattr(session, "read_only", False):
            raise AzureResponseError("Read-only session: setup is disabled.")
        reason = onboarding_error(ctx)
        if reason:
            raise AzureResponseError(reason)
        if has_namespace(ctx):
            current = session.call(session.provider("namespace").show, **_scope_of(ctx))
            reason = onboarding_error({**ctx, "namespace": current})
            if reason:
                raise AzureResponseError(reason)
            if _topology(current) != expected:
                raise AzureResponseError("Namespace links or outbound identity changed. Reload and review the plan.")
            ctx["namespace"] = current

    return [PlanItem(
        key="preflight", description="Recheck namespace topology before making changes",
        command="# Recheck current namespace links against the reviewed plan",
        phase=-1, long_running=False, invoke=verify, category="verification",
    )]


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
            "outbound_user_assigned_mi": (
                request.identity.uami_id
                if request.identity.is_user_assigned
                else None
            ),
        },
        flags=(
            ()
            if request.identity.is_user_assigned
            else ("--outbound-system-assigned-mi",)
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
        f"--outbound-user-assigned-mi {quote(choice.uami_id)}"
        if choice.is_user_assigned
        else "--outbound-system-assigned-mi"
    )
    items.append(
        PlanItem(
            key="identity",
            description=f"Configure namespace outbound identity: {choice.label}",
            # Updating outbound identity on linked namespaces invokes base RBAC.
            # Batch all displayed requirements first, including those existing links.
            phase=PHASE_PROPAGATION if any(
                _endpoints(context, section) for section in ("provisioning", "messaging", "updating")
            ) else PHASE_IDENTITY,
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
                f"--user-assigned-mi {quote(choice.uami_id)}"
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
                "--system-assigned-mi true"
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
        f"{_subscription_argument(resource_id)} "
        '--query "identity.principalId || properties.principalId" --output tsv)"'
    )


def _subscription_argument(scope: str) -> str:
    from azext_iot.adr.rbac import _scope_subscription

    subscription = _scope_subscription(scope)
    return f" --subscription {quote(subscription)}" if subscription else ""


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
        f"--scope {quote(scope)}{_subscription_argument(scope)}"
    )


def plan_software_updates(context: Dict[str, Any]) -> List[PlanItem]:
    """Optional: link an update instance so the namespace can run update jobs."""
    reason = software_updates_error(context)
    if reason:
        return [PlanItem(key="su", description="Link Software Updates", action="blocked",
                         blocked_reason=reason, phase=0, long_running=False)]
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
                                   "user_assigned_mi": (
                                       request.identity.uami_id
                                       if request.identity.is_user_assigned
                                       else None
                                   ),
                               },
                               flags=(
                                   ()
                                   if request.identity.is_user_assigned
                                   else ("--system-assigned-mi",)
                               )),
                invoke=make,
                target=request.name,
                category="resource",
            )
        )
        instances.append(_placeholder(request, context))

    updating = bool(_endpoints(context, "updating"))
    for index, instance in enumerate(instances):
        choice = (
            request.identity
            if request is not None and getattr(instance, "pending", False)
            else get_choice(context, "su", instance.resource_id)
        )
        items.extend(_plan_target_identity(context, "su", instance, choice))
        endpoint = _su_endpoint_name(context)
        link_command = render(
            "iot adr ns link su update" if updating else "iot adr ns link su add",
            scope=_scope_of(context),
            options={
                "endpoint_name": endpoint,
                "su_id": None if updating else instance.resource_id,
            },
        )

        def link(session, ctx, _su=instance, _endpoint=endpoint, _choice=choice, _updating=updating):
            provider = session.provider("link")
            return session.call(
                provider.su_update if _updating else provider.su_add,
                endpoint_name=_endpoint,
                namespace_name=ctx.get("namespace_name"),
                resource_group_name=ctx.get("resource_group_name"),
                mi_system_assigned=not _choice.is_user_assigned,
                mi_user_assigned=_choice.uami_id if _choice.is_user_assigned else None,
                no_wait=True,
                **({} if _updating else {"su_resource_id": _su.resource_id}),
            )

        items.append(
            PlanItem(
                key="su" if index == 0 else f"su-{index}",
                description=(
                    f"Update inbound identity on existing Software Updates endpoint '{endpoint}'"
                    if updating else f"Link update instance '{instance.name}' as endpoint '{endpoint}'"
                ),
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
        endpoint = _su_endpoint_name(context)
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
            if str(endpoint.get("resourceId") or "").rstrip("/").casefold() != target_id.rstrip("/").casefold():
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


def _service_principal_grant_command(
    application_id: str,
    role: str,
    scope: str,
) -> str:
    return (
        'az role assignment create --assignee-object-id '
        f'"$(az ad sp show --id {quote(application_id)} '
        f"{_subscription_argument(scope)} "
        '--query id --output tsv)" '
        "--assignee-principal-type ServicePrincipal "
        f"--role {quote(role)} --scope {quote(scope)}{_subscription_argument(scope)}"
    )


def plan_permissions(context: Dict[str, Any]) -> List[PlanItem]:
    """Display base requirements and execute them through one atomic RBAC preflight."""
    from azext_iot.adr.ui.screens.onboard.permissions import plan_link_roles

    return plan_link_roles(context)


# -- graph ---------------------------------------------------------------------------


def build_flow(context: Dict[str, Any]) -> Flow:
    """The connectivity flow: scope, namespace, identity, provisioning, messaging, grants."""
    steps = [
        Step(id="preflight", title="Validate plan", plan=plan_preflight,
             hidden=True, optional=True),
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
             after=("dps",), detect=lambda ctx: False, plan=plan_permissions,
             hidden=True, optional=True,
             blocked_reason="Choose the DPS, hubs, or update instances to link first."),
        Step(id="verification", title="Verify readiness",
             after=("dps",), detect=lambda ctx: False,
             plan=plan_final_verification, hidden=True, optional=True),
        # The commit point, named so the rail shows where changes happen.
        Step(id="review", title="Review and run", after=("namespace",),
             detect=lambda ctx: False, optional=True,
             blocked_reason="Choose or create a namespace first."),
    ]
    return Flow(steps=steps, context=context, validate=onboarding_error)
