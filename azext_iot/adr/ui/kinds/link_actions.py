# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Explicit release link operations; recovery never replays an add."""

from azext_iot.adr.ui.core.actions import Field, NAME
from azext_iot.adr.ui.core.commands import render
from azext_iot.adr.ui.core.session import SessionError
from azext_iot.adr.ui.core.spec import Action

TYPES = {
    "hub": "Microsoft.Devices/IotHubs",
    "dps": "Microsoft.Devices/provisioningServices",
    "su": "Microsoft.DeviceUpdate/updateInstances",
}


def status(payload):
    return (payload.get("provisioningStatus") or {}).get("status") or payload.get("linkingState")


def _action(kind, method):
    creating = method == "add"
    writing = method != "wait"
    destructive = method == "remove"

    def applies(payload):
        return payload.get("endpointType", "").casefold() == TYPES[kind].casefold() and (
            method not in ("wait", "update") or status(payload) == ("Accepted" if method == "wait" else "Failed")
        )

    def arguments(scope, payload):
        args = {key: scope[key] for key in ("namespace_name", "resource_group_name")}
        values = payload.get("_inputs", {})
        args["endpoint_name"] = values["name"] if creating else payload["name"]
        if creating:
            args[f"{kind}_resource_id"] = values["target"]
            args["mi_system_assigned"] = True
        return args

    def preview(scope, payload):
        args = arguments(scope, payload)
        options = {}
        if creating:
            options[f"--{kind}-id"] = payload["_inputs"]["target"]
        flags = ("--yes",) if destructive else ("--system-assigned-mi",) if creating else ()
        return render(f"iot adr ns link {kind} {method}",
                      scope=dict(args, subscription_id=scope["subscription_id"]), options=options, flags=flags)

    def note(scope, payload):
        from azext_iot.adr.rbac import LINK_ROLE_MATRIX

        if method not in ("add", "update"):
            return ("Remove only the endpoint; the target and service role assignments remain."
                    if destructive else "Wait for endpoint success. GET only; does not resend the link.")
        target = payload["_inputs"]["target"] if creating else payload.get("resourceId", "unknown target")
        namespace = (f"/subscriptions/{scope['subscription_id']}/resourceGroups/{scope['resource_group_name']}"
                     f"/providers/Microsoft.DeviceRegistry/namespaces/{scope['namespace_name']}")
        roles = "\n".join(
            f"ROLE {rule.principal} identity: {rule.role} on {target if rule.scope == 'target' else namespace}"
            for rule in LINK_ROLE_MATRIX[kind]
        )
        return (
            f"{roles}\nMay create missing grants; requires roleAssignments/write at these scopes. "
            "Permission/grant state is not yet verified. Release preflight checks it before link submission. "
            "A failed preflight can leave completed role grants. No rollback or automatic replay."
        )

    def invoke(session, scope, payload):
        if writing and session.read_only:
            raise SessionError("Read-only session: writes are disabled.")
        if scope.get("subscription_id") != session.scope.subscription_id:
            raise SessionError("Subscription changed. Review again.")
        args = arguments(scope, payload)
        provider = session.provider("link")
        current = session.list_from("link", "list_all", namespace_name=args["namespace_name"],
                                    resource_group_name=args["resource_group_name"])
        match = next((row for row in current if row["name"] == args["endpoint_name"]
                      and row["endpointType"].casefold() == TYPES[kind].casefold()), None)
        if creating and match is not None:
            raise SessionError("Link already exists. Wait for Accepted links; update Failed links. Add was not sent.")
        if not creating and (not match or not applies(match) or match.get("resourceId") != payload.get("resourceId")):
            raise SessionError("Link changed or is not applicable. Refresh and review again.")
        if method == "wait":
            from azext_iot.adr import commands_wait
            return session.call(getattr(commands_wait, f"adr_link_{kind}_wait"),
                                session.cmd, provider.client, **args, timeout=300, interval=5)
        if not destructive:
            args["no_wait"] = True
        return session.call(getattr(provider, f"{kind}_{method}"), **args)

    return Action(
        name=f"{kind}_{method}", label=f"{kind.upper()} {method}",
        destructive=destructive, mutation=writing, collection=creating, applies_to=applies,
        fields=(NAME, Field("target", "", "Existing target ARM resource ID")) if creating else (),
        invoke=invoke, preview=preview, review_note=note, refreshes=("link", "namespace"),
        note=("May write service ROLE grants; details appear on Review." if method in ("add", "update")
              else "Remove endpoint only; retain target and roles." if destructive else "GET only; does not resend."),
        unavailable=f"Requires a {kind.upper()} link"
        + (" in Accepted state." if method == "wait" else " in Failed state." if method == "update" else "."),
    )


def build_actions():
    return tuple(_action(kind, method) for kind in TYPES for method in ("add", "wait", "update", "remove"))
