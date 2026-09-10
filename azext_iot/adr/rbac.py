# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Authoritative service-to-service RBAC policy for ADR namespace links."""

import base64
import binascii
from dataclasses import dataclass
import json
from time import monotonic, sleep
from typing import Dict, Iterable, Optional, Tuple

import requests
from azure.cli.core._profile import Profile
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
)

from azext_iot.common.embedded_cli import EmbeddedCLI


CONTRIBUTOR_ROLE = "Contributor"
HUB_DATA_ROLE = "IoT Hub Data Contributor"
OWNER_ROLE = "Owner"
USER_ACCESS_ADMINISTRATOR_ROLE = "User Access Administrator"
ADU_FIRST_PARTY_APP_ID = "6ee392c4-d339-4083-b04d-6b7947c6cf78"
RBAC_PROPAGATION_TIMEOUT_SECONDS = 180
RBAC_PROPAGATION_DELAYS = (2, 4, 8, 10)
GRAPH_SERVICE_PRINCIPALS_URL = (
    "https://graph.microsoft.com/v1.0/servicePrincipals"
)


@dataclass(frozen=True)
class RoleRule:
    principal: str
    role: str
    scope: str


# This is the only service-to-service role matrix. Link runtime, help, and
# tests consume it directly. User content-management roles intentionally do
# not appear here and are never granted by link commands.
LINK_ROLE_MATRIX: Dict[str, Tuple[RoleRule, ...]] = {
    "hub": (
        RoleRule("namespace", CONTRIBUTOR_ROLE, "target"),
        RoleRule("namespace", HUB_DATA_ROLE, "target"),
        RoleRule("linked", CONTRIBUTOR_ROLE, "namespace"),
    ),
    "dps": (
        RoleRule("namespace", CONTRIBUTOR_ROLE, "target"),
        RoleRule("linked", CONTRIBUTOR_ROLE, "namespace"),
    ),
    "su": (
        RoleRule("namespace", CONTRIBUTOR_ROLE, "target"),
        RoleRule("linked", CONTRIBUTOR_ROLE, "namespace"),
        RoleRule("adu_first_party", CONTRIBUTOR_ROLE, "target"),
    ),
}


def _normalized_id(resource_id: str) -> str:
    return (resource_id or "").rstrip("/").casefold()


def _scope_subscription(scope: str) -> Optional[str]:
    parts = [part for part in (scope or "").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.casefold() == "subscriptions":
            return parts[index + 1]
    return None


def _identity_type_contains(identity: dict, value: str) -> bool:
    identity_type = str((identity or {}).get("type") or "")
    return value.casefold() in {
        item.strip().casefold() for item in identity_type.split(",")
    }


def _find_user_identity(identity: dict, resource_id: str) -> Optional[dict]:
    expected = _normalized_id(resource_id)
    for attached_id, details in (
        (identity or {}).get("userAssignedIdentities") or {}
    ).items():
        if _normalized_id(attached_id) == expected:
            return details or {}
    return None


def resolve_namespace_outbound_principal(namespace: dict) -> str:
    """Resolve the configured namespace outbound MI, defaulting to its SAMI."""
    identity = (namespace or {}).get("identity") or {}
    outbound = ((namespace or {}).get("properties") or {}).get(
        "outboundIdentity"
    ) or {}
    outbound_type = str(outbound.get("type") or "SystemAssigned")

    if outbound_type.casefold() == "userassigned":
        resource_id = outbound.get("userAssignedIdentity")
        details = _find_user_identity(identity, resource_id)
        principal_id = (details or {}).get("principalId")
        if not resource_id or details is None:
            raise InvalidArgumentValueError(
                "The namespace outbound user-assigned identity is not attached "
                "to the namespace. Assign it or select another outbound identity."
            )
        if not principal_id:
            raise AzureResponseError(
                "The namespace outbound user-assigned identity has no principalId "
                "yet. Wait for identity provisioning and retry."
            )
        return principal_id

    if outbound_type.casefold() != "systemassigned":
        raise InvalidArgumentValueError(
            f"Unsupported namespace outbound identity type '{outbound_type}'."
        )
    if not _identity_type_contains(identity, "SystemAssigned"):
        raise InvalidArgumentValueError(
            "The namespace requires a system-assigned identity for outbound "
            "link calls. Assign one or configure an outbound user-assigned identity."
        )
    principal_id = identity.get("principalId")
    if not principal_id:
        raise AzureResponseError(
            "The namespace system-assigned identity has no principalId yet. "
            "Wait for identity provisioning and retry."
        )
    return principal_id


def resolve_linked_resource_principal(
    resource: dict, inbound_identity: Optional[dict], display_name: str
) -> Optional[str]:
    """Resolve an inbound identity and prove it is attached to the target."""
    if not inbound_identity:
        return None
    identity = (resource or {}).get("identity") or {}
    inbound_type = str(inbound_identity.get("type") or "")
    if inbound_type.casefold() == "systemassigned":
        if not _identity_type_contains(identity, "SystemAssigned"):
            raise InvalidArgumentValueError(
                f"The selected system-assigned identity is not enabled on "
                f"{display_name}. Assign it and retry."
            )
        principal_id = identity.get("principalId")
        if not principal_id:
            raise AzureResponseError(
                f"The {display_name} system-assigned identity has no principalId "
                "yet. Wait for identity provisioning and retry."
            )
        return principal_id
    if inbound_type.casefold() == "userassigned":
        resource_id = inbound_identity.get("userAssignedIdentity")
        details = _find_user_identity(identity, resource_id)
        if not resource_id or details is None:
            raise InvalidArgumentValueError(
                f"The selected user-assigned identity is not attached to "
                f"{display_name}. Assign it and retry."
            )
        principal_id = (details or {}).get("principalId")
        if not principal_id:
            raise AzureResponseError(
                f"The selected {display_name} user-assigned identity has no "
                "principalId yet. Wait for identity provisioning and retry."
            )
        return principal_id
    raise InvalidArgumentValueError(
        f"Unsupported inbound caller identity type '{inbound_type}'."
    )


def format_role_requirements(link_type: str) -> str:
    labels = {
        "namespace": "namespace outbound MI",
        "linked": f"{link_type.upper()} selected inbound MI",
        "adu_first_party": "ADU first-party app",
    }
    scopes = {"namespace": "namespace", "target": link_type.upper()}
    requirements = []
    for rule in LINK_ROLE_MATRIX[link_type]:
        requirement = (
            f"{labels[rule.principal]} -> {rule.role} on "
            f"{scopes[rule.scope]}"
        )
        if link_type == "hub" and rule.principal == "linked":
            requirement = (
                "when an inbound identity is selected, " + requirement
            )
        requirements.append(requirement)
    return "; ".join(requirements)


class LinkRbacManager:
    """Idempotently establish all missing assignments before link mutation."""

    def __init__(
        self,
        cli_ctx,
        cli=None,
        *,
        clock=None,
        sleeper=None,
        graph_get=None,
        propagation_timeout: int = RBAC_PROPAGATION_TIMEOUT_SECONDS,
    ):
        self._cli_ctx = cli_ctx
        self.cli = cli or EmbeddedCLI(cli_ctx=cli_ctx, capture_stderr=True)
        self._graph_get = graph_get or requests.get
        self._adu_principal_ids = {}
        self._caller_object_ids = {}
        self._clock = clock or monotonic
        self._sleep = sleeper or sleep
        self._propagation_timeout = propagation_timeout

    def _invoke_json(
        self,
        command: str,
        subscription: Optional[str] = None,
    ):
        try:
            result = self.cli.invoke(command, subscription=subscription)
            if not result.success():
                raise AzureResponseError(
                    f"Azure CLI command failed during link RBAC preflight: az {command}"
                )
            return result.as_json()
        except AzureResponseError:
            raise
        except Exception as error:
            raise AzureResponseError(
                f"Azure CLI command failed during link RBAC preflight: az {command}. "
                f"Detail: {error}"
            ) from error

    def _access_token(
        self, subscription_id: str, resource: Optional[str] = None
    ) -> str:
        # Use the same profile API as `account get-access-token`, without
        # passing its secret output through EmbeddedCLI's debug logging.
        # The subscription selects the tenant; None retains the ARM audience.
        try:
            credentials, _, _ = Profile(cli_ctx=self._cli_ctx).get_raw_token(
                subscription=subscription_id, resource=resource
            )
        except Exception as error:
            raise AzureResponseError(
                f"Could not acquire an access token for subscription "
                f"'{subscription_id}'."
            ) from error
        access_token = credentials[1]
        if not isinstance(access_token, str) or not access_token:
            raise AzureResponseError(
                f"Could not acquire an access token for subscription "
                f"'{subscription_id}'."
            )
        return access_token

    def _resolve_adu_principal(self, subscription_id: str) -> str:
        if subscription_id not in self._adu_principal_ids:
            access_token = self._access_token(
                subscription_id,
                resource=self._cli_ctx.cloud.endpoints.microsoft_graph_resource_id,
            )
            try:
                response = self._graph_get(
                    GRAPH_SERVICE_PRINCIPALS_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "$filter": f"appId eq '{ADU_FIRST_PARTY_APP_ID}'",
                        "$select": "id",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                principals = response.json().get("value") or []
            except (requests.RequestException, ValueError) as error:
                raise AzureResponseError(
                    "Could not query Microsoft Graph for the ADU first-party "
                    "service principal."
                ) from error
            self._adu_principal_ids[subscription_id] = (
                principals[0].get("id") if principals else None
            )
            if not self._adu_principal_ids[subscription_id]:
                raise AzureResponseError(
                    "Could not resolve the ADU first-party service principal. "
                    f"Resolve application ID {ADU_FIRST_PARTY_APP_ID} and grant "
                    "it Contributor on the Update Instance."
                )
        return self._adu_principal_ids[subscription_id]

    def _assignment_exists(
        self, principal_id: str, role: str, scope: str
    ) -> bool:
        assignments = self._invoke_json(
            "role assignment list "
            f"--assignee-object-id '{principal_id}' "
            f"--role '{role}' --scope '{scope}' "
            "--include-inherited --fill-principal-name false",
            subscription=_scope_subscription(scope),
        )
        return bool(assignments)

    def _current_assignee_object_id(self, subscription_id: str) -> str:
        if subscription_id in self._caller_object_ids:
            return self._caller_object_ids[subscription_id]
        access_token = self._access_token(subscription_id)
        try:
            payload = str(access_token).split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(
                base64.urlsafe_b64decode(payload).decode("utf-8")
            )
            object_id = claims.get("oid") if isinstance(claims, dict) else None
        except (
            binascii.Error,
            IndexError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ):
            object_id = None
        if not object_id:
            raise AzureResponseError(
                "Could not resolve the signed-in principal object ID from the "
                "Azure access token for automatic RBAC. "
                "Create the listed role assignments manually and retry."
            )
        self._caller_object_ids[subscription_id] = object_id
        return object_id

    def _caller_can_assign(self, assignee_object_id: str, scope: str) -> bool:
        for role in (OWNER_ROLE, USER_ACCESS_ADMINISTRATOR_ROLE):
            assignments = self._invoke_json(
                "role assignment list "
                f"--assignee-object-id '{assignee_object_id}' "
                f"--role '{role}' --scope '{scope}' "
                "--include-inherited --include-groups "
                "--fill-principal-name false",
                subscription=_scope_subscription(scope),
            )
            if assignments:
                return True
        return False

    def _wait_for_assignments(
        self, assignments: Iterable[Tuple[str, str, str]]
    ) -> None:
        """Wait until newly-created assignments are visible to ARM reads."""
        pending = list(dict.fromkeys(assignments))
        if not pending:
            return

        deadline = self._clock() + self._propagation_timeout
        delay_index = 0
        while pending:
            still_pending = []
            for principal_id, role, scope in pending:
                try:
                    if self._assignment_exists(principal_id, role, scope):
                        continue
                except AzureResponseError:
                    # Role-assignment reads can be transiently throttled while
                    # the write is propagating. Keep the assignment pending.
                    pass
                still_pending.append((principal_id, role, scope))
            pending = still_pending
            if not pending:
                return

            remaining = deadline - self._clock()
            if remaining <= 0:
                break
            delay = RBAC_PROPAGATION_DELAYS[
                min(delay_index, len(RBAC_PROPAGATION_DELAYS) - 1)
            ]
            delay_index += 1
            self._sleep(min(delay, remaining))

        commands = self._manual_commands(pending)
        raise AzureResponseError(
            "Timed out waiting for newly-created link role assignments to "
            "become visible. No namespace mutation was submitted. The "
            "assignments may already exist; retrying the link command is safe. "
            "If propagation is still incomplete, verify these assignments:\n"
            f"{commands}"
        )

    @staticmethod
    def _manual_commands(
        missing: Iterable[Tuple[str, str, str]]
    ) -> str:
        commands = []
        for principal_id, role, scope in missing:
            subscription = _scope_subscription(scope)
            subscription_arg = (
                f" --subscription '{subscription}'" if subscription else ""
            )
            commands.append(
                "az role assignment create "
                f"--assignee-object-id '{principal_id}' "
                "--assignee-principal-type ServicePrincipal "
                f"--role '{role}' --scope '{scope}'{subscription_arg}"
            )
        return "\n".join(commands)

    def ensure(
        self,
        link_type: str,
        namespace_scope: str,
        target_scope: str,
        namespace_principal_id: str,
        linked_principal_id: Optional[str],
    ) -> None:
        self.ensure_many(
            [
                {
                    "link_type": link_type,
                    "namespace_scope": namespace_scope,
                    "target_scope": target_scope,
                    "namespace_principal_id": namespace_principal_id,
                    "linked_principal_id": linked_principal_id,
                }
            ]
        )

    def ensure_many(self, requests: Iterable[dict]) -> None:
        """Authorize a complete atomic link plan before creating any assignment."""
        missing = []
        for request in requests:
            link_type = request["link_type"]
            if link_type not in LINK_ROLE_MATRIX:
                raise InvalidArgumentValueError(
                    f"Unsupported link type '{link_type}' for RBAC preflight."
                )
            principals = {
                "namespace": request["namespace_principal_id"],
                "linked": request.get("linked_principal_id"),
            }
            scopes = {
                "namespace": request["namespace_scope"],
                "target": request["target_scope"],
            }
            for rule in LINK_ROLE_MATRIX[link_type]:
                principal_id = (
                    self._resolve_adu_principal(
                        _scope_subscription(scopes["target"])
                    )
                    if rule.principal == "adu_first_party"
                    else principals.get(rule.principal)
                )
                # Hub inbound identity is optional. There is no principal to grant
                # in that direction when the endpoint omits it.
                if not principal_id:
                    continue
                scope = scopes[rule.scope]
                assignment = (principal_id, rule.role, scope)
                if (
                    assignment not in missing
                    and not self._assignment_exists(
                        principal_id, rule.role, scope
                    )
                ):
                    missing.append(assignment)

        if not missing:
            return

        unauthorized_scopes = []
        for scope in dict.fromkeys(item[2] for item in missing):
            subscription_id = _scope_subscription(scope)
            assignee_object_id = self._current_assignee_object_id(
                subscription_id
            )
            if not self._caller_can_assign(assignee_object_id, scope):
                unauthorized_scopes.append(scope)
        commands = self._manual_commands(missing)
        if unauthorized_scopes:
            scopes_text = ", ".join(unauthorized_scopes)
            raise AzureResponseError(
                "Missing link role assignments, and the signed-in principal is "
                "not an inherited Owner or User Access Administrator at every "
                f"required scope ({scopes_text}). No link mutation was submitted. "
                "Run these exact remediation commands as an authorized principal:\n"
                f"{commands}"
            )

        created = []
        for index, (principal_id, role, scope) in enumerate(missing):
            try:
                self._invoke_json(
                    "role assignment create "
                    f"--assignee-object-id '{principal_id}' "
                    "--assignee-principal-type ServicePrincipal "
                    f"--role '{role}' --scope '{scope}'",
                    subscription=_scope_subscription(scope),
                )
                created.append((principal_id, role, scope))
            except AzureResponseError as error:
                # Another actor may have created the same assignment after the
                # initial read. Treat that race as success rather than issuing
                # a duplicate or blocking an otherwise idempotent link retry.
                try:
                    assignment_now_exists = self._assignment_exists(
                        principal_id, role, scope
                    )
                except AzureResponseError:
                    assignment_now_exists = False
                if assignment_now_exists:
                    continue
                remaining = self._manual_commands(missing[index:])
                raise AzureResponseError(
                    "Automatic link RBAC setup failed before namespace mutation. "
                    "Complete these exact remediation commands, allow RBAC to "
                    f"propagate, and retry:\n{remaining}\nDetail: {error}"
                ) from error
        self._wait_for_assignments(created)
