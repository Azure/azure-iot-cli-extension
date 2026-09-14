# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Reviewed service-role requirements, executed by the authoritative ADR preflight."""

from copy import deepcopy

from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE, SU_ENDPOINT_TYPE
from azext_iot.adr.rbac import ADU_FIRST_PARTY_APP_ID, LINK_ROLE_MATRIX, _normalized_id, _scope_subscription
from azext_iot.adr.topology import endpoint_is_type
from azext_iot.adr.ui.core.commands import quote
from azext_iot.adr.ui.screens.onboard.flow import PlanItem
from azext_iot.adr.ui.screens.onboard.identity import (
    IdentityChoice, USER_ASSIGNED, get_choice, principal_of,
)
from azext_iot.adr.ui.screens.onboard.pickers import Candidate
from azext_iot.adr.ui.screens.onboard.steps import (
    PHASE_GRANT, _endpoints, _namespace, _scope_of, _topology,
    _service_principal_grant_command, grant_command, has_identity,
    has_namespace, link_choice, link_needs_work, link_targets, namespace_arm_id, onboarding_error,
)


def role_targets(context):
    """Only links that will run, including existing links affected by outbound MI changes."""
    resolved = [
        (kind, target, link_choice(context, kind, target))
        for kind in ("dps", "hub", "su") for target in link_targets(context, kind)
        if link_needs_work(context, kind, target)
    ]
    seen = {(kind, _normalized_id(target.resource_id)) for kind, target, _choice in resolved}
    if has_namespace(context) and not has_identity(context):
        types = {"dps": DPS_ENDPOINT_TYPE, "hub": IOT_HUB_ENDPOINT_TYPE, "su": SU_ENDPOINT_TYPE}
        for kind, section in (("dps", "provisioning"), ("hub", "messaging"), ("su", "updating")):
            for endpoint in _endpoints(context, section).values():
                if not endpoint_is_type(endpoint, types[kind]):
                    continue
                resource_id = endpoint.get("resourceId") or ""
                if (kind, _normalized_id(resource_id)) in seen:
                    continue
                inbound = endpoint.get("inboundCallerIdentity")
                choice = None
                if inbound:
                    choice = IdentityChoice(
                        mode=USER_ASSIGNED if str(inbound.get("type")).casefold() == "userassigned" else "system",
                        uami_id=inbound.get("userAssignedIdentity") or "",
                    )
                resolved.append((kind, Candidate(
                    name=resource_id.rsplit("/", 1)[-1], resource_id=resource_id,
                ), choice))
    return resolved


def ensure_link_roles(session, context, targets, namespace_choice, *, reviewed_namespace_principal=None):
    """Queue base target/identity validation for every displayed link, then ensure_many."""
    from azext_iot.adr.providers import link as base_link

    if getattr(session, "read_only", False):
        raise AzureResponseError("Read-only session: role setup is disabled.")
    reason = onboarding_error(context)
    if reason:
        raise AzureResponseError(reason)
    provider = session.provider("link")
    namespace = deepcopy(session.call(session.provider("namespace").show, **_scope_of(context)))
    reason = onboarding_error({**context, "namespace": namespace})
    if reason:
        raise AzureResponseError(reason)
    if has_namespace(context):
        previous = _topology(_namespace(context))
        current = _topology(namespace)
        if current[1] != previous[1] or (has_identity(context) and current[0] != previous[0]):
            raise AzureResponseError("Namespace links or outbound identity changed. Reload and review before granting roles.")
    manager = provider._rbac_manager()  # pylint: disable=protected-access
    # Match base namespace.update: project the desired UAMI before attaching it.
    # New identities are created in an earlier phase. No secret token crosses EmbeddedCLI.
    identity = namespace.setdefault("identity", {})
    outbound = {"type": "SystemAssigned"}
    if namespace_choice.is_user_assigned:
        resource_id = namespace_choice.uami_id
        details = manager._invoke_json(  # pylint: disable=protected-access
            f"identity show --ids {quote(resource_id)}",
            subscription=_scope_subscription(resource_id),
        )
        identity.setdefault("userAssignedIdentities", {})[resource_id] = details
        outbound = {"type": "UserAssigned", "userAssignedIdentity": resource_id}
    namespace.setdefault("properties", {})["outboundIdentity"] = outbound
    requests = []
    # Initial topology preflight refreshes context["namespace"]. The reviewed principal
    # must be an independent snapshot, not a comparison against that refreshed payload.
    # An explicitly empty snapshot is valid for a namespace/identity not yet created.
    expected_namespace_principal = (
        reviewed_namespace_principal if reviewed_namespace_principal is not None
        else principal_of(_namespace(context), namespace_choice)
    )
    for kind, target, choice in targets:
        inbound = None
        if choice is not None:
            inbound = {"type": "SystemAssigned"}
            if choice.is_user_assigned:
                inbound = {"type": "UserAssigned", "userAssignedIdentity": choice.uami_id}
        parser = getattr(base_link, f"_parse_{kind}_resource_id")
        strategy = getattr(base_link, f"_{kind.upper()}_TARGET")
        session.call(
            provider._preflight_link,  # pylint: disable=protected-access
            link_type=kind, namespace=namespace, target_resource_id=target.resource_id,
            inbound_identity=inbound, parsed=parser(target.resource_id), strategy=strategy,
            rbac_requests=requests,
        )
        expected_linked_principal = principal_of(getattr(target, "raw", None) or {}, choice) if choice else ""
        request = requests[-1]
        for expected, actual in (
            (expected_namespace_principal, request["namespace_principal_id"]),
            (expected_linked_principal, request["linked_principal_id"]),
        ):
            if expected and str(expected).casefold() != str(actual or "").casefold():
                raise AzureResponseError(
                    "A reviewed managed-identity principal changed. Reload and review before granting roles."
                )
    session.call(manager.ensure_many, requests)


def plan_link_roles(context):
    """Requirements are not promised new grants: inherited assignments may satisfy them."""
    reason = onboarding_error(context)
    if reason:
        return [PlanItem(key="permissions", description="Role preflight", action="blocked",
                         blocked_reason=reason, long_running=False)]
    namespace_scope = namespace_arm_id(context)
    request = context.get("create_namespace")
    namespace_choice = request.identity if request is not None else get_choice(context, "namespace")
    namespace_principal = principal_of(_namespace(context), namespace_choice)
    namespace_source = namespace_choice.uami_id if namespace_choice.is_user_assigned else namespace_scope
    targets = role_targets(context)
    items = []
    seen = set()
    for kind, target, choice in targets:
        for rule in LINK_ROLE_MATRIX[kind]:
            if rule.principal == "linked" and choice is None:
                continue
            scope = namespace_scope if rule.scope == "namespace" else target.resource_id
            if rule.principal == "adu_first_party":
                key = f"grant-adu-fpa-{target.name}"
                description = f"Azure Device Update first-party service '{rule.role}' on {kind} '{target.name}'"
                command = _service_principal_grant_command(ADU_FIRST_PARTY_APP_ID, rule.role, scope)
            else:
                if rule.principal == "namespace":
                    principal, source = namespace_principal, namespace_source
                    key = f"grant-ns-to-{kind}-{target.name}-{rule.role}"
                    description = f"namespace identity '{rule.role}' on {kind} '{target.name}'"
                else:
                    principal = principal_of(getattr(target, "raw", None) or {}, choice)
                    source = choice.uami_id if choice.is_user_assigned else target.resource_id
                    key = f"grant-{kind}-to-ns-{target.name}"
                    description = f"{kind} '{target.name}' identity '{rule.role}' on the namespace"
                command = grant_command(principal, rule.role, scope, principal_source=source)
            if command in seen:
                continue
            seen.add(command)
            items.append(PlanItem(
                key=key, description=f"Require {description}", command=command,
                action="required", phase=PHASE_GRANT, long_running=False,
                target=scope, category="role",
            ))
    if targets:
        def ensure(session, ctx, _targets=tuple(deepcopy(targets)), _choice=namespace_choice,
                   _reviewed_principal=namespace_principal):
            return ensure_link_roles(
                session, ctx, _targets, _choice, reviewed_namespace_principal=_reviewed_principal,
            )

        items.append(PlanItem(
            key="grant-preflight",
            description="Check inherited grants; authorize all missing roles and wait for visibility",
            command="# Base link preflight: only missing roles require Owner/User Access Administrator",
            phase=PHASE_GRANT, long_running=False, invoke=ensure,
            target="Azure RBAC", category="role",
        ))
    return items
