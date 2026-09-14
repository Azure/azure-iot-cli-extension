# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Advisory resource-write checks. Service-role policy belongs exclusively to ADR RBAC."""

import contextlib
import io
import re
from typing import Any, Dict, List, Optional

from azext_iot.adr.ui.core import diagnostics
from azext_iot.adr.ui.core.commands import quote

_PERMISSIONS_API = "2022-04-01"


def _embedded_cli(session):
    from azext_iot.common.embedded_cli import EmbeddedCLI

    cli_ctx = getattr(getattr(session, "cmd", None), "cli_ctx", None)
    return EmbeddedCLI(cli_ctx=cli_ctx, capture_stderr=True)


@contextlib.contextmanager
def _quiet():
    """Do not let CLI warnings overwrite the alternate-screen buffer."""
    with contextlib.redirect_stderr(io.StringIO()):
        yield


def _matches(pattern: str, action: str) -> bool:
    regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return re.match(regex, action, flags=re.IGNORECASE) is not None


def permits(permissions: List[Dict[str, Any]], action: str) -> bool:
    for entry in permissions or []:
        allowed = any(_matches(p, action) for p in entry.get("actions") or [])
        denied = any(_matches(p, action) for p in entry.get("notActions") or [])
        if allowed and not denied:
            return True
    return False


def permissions_at_scope(session, scope: str, actions: List[str]) -> Optional[Dict[str, bool]]:
    """An unknown result is explicitly shown as not ready, never as permission granted."""
    if not scope:
        return None
    cli_ctx = getattr(getattr(session, "cmd", None), "cli_ctx", None)
    arm = cli_ctx.cloud.endpoints.resource_manager.rstrip("/")
    url = f"{arm}{scope}/providers/Microsoft.Authorization/permissions?api-version={_PERMISSIONS_API}"
    try:
        cli = _embedded_cli(session)
        with _quiet():
            result = cli.invoke(f"rest --method get --url {quote(url)}")
            if not result.success():
                raise RuntimeError(f"Could not read resource permissions at {scope}.")
            payload = result.as_json()
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            raise ValueError(f"Resource permissions response at {scope} has no value list.")
    except Exception as error:  # noqa: BLE001 - surfaced as an unknown preflight result
        diagnostics.exception("resource permission probe failed for %s: %s", scope, error)
        return None
    return {action: permits(payload["value"], action) for action in actions}
