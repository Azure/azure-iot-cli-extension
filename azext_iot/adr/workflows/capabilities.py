# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Azure-managed CMS planning. No certificate material crosses the service adapter."""

import shlex

from azure.cli.core.azclierror import ArgumentUsageError

from azext_iot.adr.workflows.models import (
    PlanItem, STATE_BLOCKED, STATE_PLANNED, STATE_SATISFIED, STATE_SUCCEEDED,
)


def cms_name(request, kind):
    return {
        "root": request.cms.root_name,
        "intermediate": request.cms.intermediate_name,
        "policy": request.cms.policy_name,
    }[kind]


def cms_conflict(request, kind, metadata):
    properties = metadata.get("properties") or {}
    if properties.get("provisioningState") != "Succeeded":
        return "Provisioning is failed, unknown or in progress; inspect the resource, wait for Succeeded, then rerun."
    if kind == "policy":
        validity = (properties.get("certificate") or {}).get("validityPeriodInDays")
        if validity != request.cms.validity_days:
            return "Existing policy validity differs from cms.validityDays; select another policy name or matching validity."
        return ""
    expected = "Root" if kind == "root" else "ICA"
    if properties.get("certificateAuthorityType") != expected:
        return f"Existing certificate authority must have type {expected}; choose a different name."
    issuer = properties.get("issuer") or {}
    if kind == "root":
        if issuer:
            return "Existing root has an unexpected issuer; setup will not replace or convert it."
        return ""
    root_id = (
        f"/subscriptions/{request.subscription_id}/resourceGroups/{request.resource_group_name}"
        f"/providers/Microsoft.DeviceRegistry/namespaces/{request.namespace_name}"
        f"/certificateAuthorities/{request.cms.root_name}"
    )
    if issuer.get("issuerType") != "Microsoft":
        return "Existing ICA is not Azure-managed (Microsoft issuer); setup never converts external PKI."
    if str(issuer.get("certificateAuthorityResourceId") or "").casefold() != root_id.casefold():
        return "Existing ICA issuer does not match cms.rootName; select matching names."
    # Microsoft-managed responses can omit external activation's status field.
    if issuer.get("status") not in (None, "Active"):
        return "ICA issuer is not Active; inspect its status and wait before rerunning. Setup does not rotate or activate CAs."
    return ""


def cms_command(request, kind):
    quote = shlex.quote
    scope = f"--ns {quote(request.namespace_name)} -g {quote(request.resource_group_name)}"
    if kind == "policy":
        return (
            f"az iot adr ns ca policy create -n {quote(request.cms.policy_name)} {scope} "
            f"--ca-name {quote(request.cms.intermediate_name)} --validity-days {request.cms.validity_days}"
        )
    command = f"az iot adr ns ca create -n {quote(cms_name(request, kind))} {scope}"
    return command + (
        " --type Root" if kind == "root" else
        f" --type ICA --issuer-type Microsoft --issuer-ca-name {quote(request.cms.root_name)}"
    )


def plan_cms(request, namespace, run, services):
    if not request.cms:
        return []
    items = []
    for kind in ("root", "intermediate", "policy"):
        metadata = run(
            f"Read CMS {kind}", services.show_cms, request, kind, workflow_scope="cms",
        ) if namespace else None
        conflict = cms_conflict(request, kind, metadata) if metadata is not None else ""
        items.append(PlanItem(
            f"cms-{kind}", "reuse" if metadata is not None else "create", cms_name(request, kind),
            STATE_BLOCKED if conflict else STATE_SATISFIED if metadata is not None else STATE_PLANNED,
            conflict or "Azure-managed CMS; caller ARM permissions are required. No service-role grants are added.",
            command=cms_command(request, kind) if metadata is None else "",
            dependencies=("namespace",) if kind == "root" else (
                "cms-root" if kind == "intermediate" else "cms-intermediate",
            ),
            details={
                "workflowScope": "cms",
                **({"validityDays": request.cms.validity_days} if kind == "policy" else
                   {"type": "Root" if kind == "root" else "ICA"}),
            },
        ))
    return items


def apply_cms(request, run, services, items):
    if not request.cms:
        return
    # Re-read the entire chain on retries before creating anything.
    plan = plan_cms(request, True, run, services)
    conflicts = [item.message for item in plan if item.state == STATE_BLOCKED]
    if conflicts:
        raise ArgumentUsageError("CMS setup is blocked: " + "; ".join(conflicts))
    for kind in ("root", "intermediate", "policy"):
        metadata = run(f"Read CMS {kind}", services.show_cms, request, kind, workflow_scope="cms")
        created = metadata is None
        if created:
            run(
                f"Create CMS {kind}", services.create_cms, request, kind,
                workflow_scope="cms", mutation=True,
            )
            metadata = run(
                f"Verify CMS {kind}", services.show_cms, request, kind, workflow_scope="cms",
            )
        conflict = cms_conflict(request, kind, metadata or {})
        if conflict:
            raise ArgumentUsageError(f"CMS {kind}: {conflict}")
        items.append(PlanItem(
            f"cms-{kind}", "create" if created else "reuse", cms_name(request, kind),
            STATE_SUCCEEDED if created else STATE_SATISFIED,
        ))
