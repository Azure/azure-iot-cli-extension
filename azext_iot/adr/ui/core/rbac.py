# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Role assignments: can we make them, and making them.

Linking a namespace to a DPS or a Hub needs grants in both directions. Handing those to
the customer as commands to paste is a poor deal when the CLI is already signed in as
someone who may well be allowed to make them - so radr asks first, and only falls back to
printing commands when the answer is no.

The probe is the authoritative one: ARM reports the caller's effective actions at a scope,
so the answer accounts for inherited assignments, PIM activations and deny-assignment
style ``notActions`` without radr having to guess from role names.

Free of any UI framework import, like everything else under ``core``.
"""

import contextlib
import io
import re
from typing import Any, Dict, List, Optional

from azext_iot.adr.ui.core import diagnostics
from azext_iot.adr.ui.core.commands import quote

#: The action a caller needs to create a role assignment. Held by Owner and by
#: User Access Administrator, and by nothing else built in.
ROLE_WRITE_ACTION = "Microsoft.Authorization/roleAssignments/write"

_PERMISSIONS_API = "2022-04-01"
_ARM = "https://management.azure.com"

#: What ARM says when the grant already exists. Re-running setup must not fail on this.
_ALREADY_EXISTS = "roleassignmentexists"
#: What ARM says when the caller may not grant. Distinct from a transient failure: no
#: amount of retrying helps, the customer has to escalate.
_DENIED_MARKERS = ("authorizationfailed", "does not have authorization to perform action")


class GrantDenied(Exception):
    """The signed-in account may not create this role assignment."""


def _embedded_cli(session):
    """An EmbeddedCLI bound to the session's CLI context.

    ``capture_stderr`` matters here rather than being a nicety: an uncaptured az error
    prints straight through the alternate screen buffer and corrupts the UI.
    """
    from azext_iot.common.embedded_cli import EmbeddedCLI

    cli_ctx = getattr(getattr(session, "cmd", None), "cli_ctx", None)
    return EmbeddedCLI(cli_ctx=cli_ctx, capture_stderr=True)


@contextlib.contextmanager
def _quiet():
    """Keep az's own warnings off the screen.

    EmbeddedCLI captures stdout, but knack logs warnings to stderr, and Textual does not
    redirect stderr - anything written there lands on top of the running interface.
    """
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def _matches(pattern: str, action: str) -> bool:
    """ARM action globbing: ``*`` spans anything, including slashes."""
    regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return re.match(regex, action, flags=re.IGNORECASE) is not None


def permits(permissions: List[Dict[str, Any]], action: str = ROLE_WRITE_ACTION) -> bool:
    """Whether the caller's effective permissions allow ``action``.

    A ``notActions`` match removes the action granted by the same entry, so each entry is
    judged on its own before the results are combined - which is how ARM evaluates them.
    """
    for entry in permissions or []:
        allowed = any(_matches(p, action) for p in (entry.get("actions") or []))
        if not allowed:
            continue
        denied = any(_matches(p, action) for p in (entry.get("notActions") or []))
        if not denied:
            return True
    return False


def can_grant_roles(session, scope: str) -> Optional[bool]:
    """Ask ARM whether this caller can create role assignments at ``scope``.

    Returns None when the question could not be answered - the caller should then treat
    grants as manual rather than promising something radr may not be able to deliver.
    """
    if not scope:
        return None
    url = f"{_ARM}{scope}/providers/Microsoft.Authorization/permissions?api-version={_PERMISSIONS_API}"
    try:
        cli = _embedded_cli(session)
        with _quiet():
            cli.invoke(f"rest --method get --url {quote(url)}")
        payload = cli.as_json()
    except Exception as error:  # noqa: BLE001 - an unanswered probe is not a failure
        diagnostics.exception("role permission probe failed for %s: %s", scope, error)
        return None
    verdict = permits(payload.get("value") if isinstance(payload, dict) else None)
    diagnostics.log("role permission probe at %s: can_grant=%s", scope, verdict)
    return verdict


def permissions_at_scope(
    session,
    scope: str,
    actions: List[str],
) -> Optional[Dict[str, bool]]:
    """Resolve several effective ARM actions with one permissions request."""
    if not scope:
        return None
    url = f"{_ARM}{scope}/providers/Microsoft.Authorization/permissions?api-version={_PERMISSIONS_API}"
    try:
        cli = _embedded_cli(session)
        with _quiet():
            cli.invoke(f"rest --method get --url {quote(url)}")
        payload = cli.as_json()
    except Exception as error:  # noqa: BLE001 - caller presents an unknown result
        diagnostics.exception("permission probe failed for %s: %s", scope, error)
        return None
    entries = payload.get("value") if isinstance(payload, dict) else None
    result = {action: permits(entries or [], action) for action in actions}
    diagnostics.log("permission probe at %s: %s", scope, result)
    return result


def resolve_principal(session, resource_id: str) -> Optional[str]:
    """The system-assigned principal id of a resource, read at run time.

    Needed because a resource created earlier in the same plan has no principal id when
    the plan is built - only after it exists. ``az resource show --ids`` picks a workable
    api-version for us, which keeps this free of a per-provider version table.
    """
    if not resource_id:
        return None
    try:
        cli = _embedded_cli(session)
        with _quiet():
            cli.invoke(
                f"resource show --ids {quote(resource_id)} "
                "--query \"identity.principalId || properties.principalId\""
            )
        principal = cli.as_json()
    except Exception as error:  # noqa: BLE001 - reported by the caller as a blocked grant
        diagnostics.exception("could not read identity of %s: %s", resource_id, error)
        return None
    return principal if isinstance(principal, str) and principal else None


def resolve_service_principal(session, application_id: str) -> Optional[str]:
    """Resolve a tenant-local service-principal object id from its application id."""
    if not application_id:
        return None
    try:
        cli = _embedded_cli(session)
        with _quiet():
            cli.invoke(
                f"ad sp show --id {quote(application_id)} --query id"
            )
        principal = cli.as_json()
    except Exception as error:  # noqa: BLE001 - caller reports the blocked grant
        diagnostics.exception(
            "could not resolve service principal %s: %s",
            application_id,
            error,
        )
        return None
    return principal if isinstance(principal, str) and principal else None


def grant_role(session, principal_id: str, role: str, scope: str) -> bool:
    """Create one role assignment, tolerating the one that already exists.

    Returns True when the assignment was created, False when it was already there.
    Raises :class:`GrantDenied` when the caller lacks the right, and the underlying error
    for anything else.
    """
    if not principal_id or not scope:
        raise ValueError("a role grant needs both a principal id and a scope")

    command = (
        f"role assignment create --assignee-object-id {quote(principal_id)} "
        f"--assignee-principal-type ServicePrincipal --role {quote(role)} "
        f"--scope {quote(scope)}"
    )
    try:
        cli = _embedded_cli(session)
        with _quiet():
            cli.invoke(command)
    except Exception as error:  # noqa: BLE001 - classified below and re-raised
        text = str(error).lower()
        if _ALREADY_EXISTS in text:
            diagnostics.log("grant '%s' on %s: already exists", role, scope)
            return False
        if any(marker in text for marker in _DENIED_MARKERS):
            raise GrantDenied(
                f"not allowed to grant '{role}' on {scope.rsplit('/', 1)[-1]}; "
                "this needs Owner or User Access Administrator"
            ) from error
        raise
    diagnostics.log("granted '%s' on %s", role, scope)
    return True
