# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import monotonic, sleep
from typing import Any, Dict, FrozenSet, Mapping, NoReturn, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    CLIInternalError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from rich.console import Console

from azext_iot._factory import adr_service_factory
from azext_iot.common.arm import adapt_modeless_lro_poller
from azext_iot.adr.providers.link_helpers import failed_link_recovery_commands
from azext_iot.constants import LRO_POLL_WAIT_SEC
from azext_iot.common.utility import process_json_arg

__all__ = ["ADRProvider", "console", "parse_json_object"]

logger = get_logger(__name__)

# Shared Rich console for all ADR providers. Declared once here (instead of a
# module-level `Console()` in every provider) so spinners/print styling stay consistent.
console = Console()


def parse_json_object(
    value: Any,
    argument_name: str,
    *,
    allowed_keys: Optional[FrozenSet[str]] = None,
    required_keys: FrozenSet[str] = frozenset(),
) -> Dict[str, Any]:
    """Parse an inline JSON object or JSON file and validate its top-level keys."""
    if isinstance(value, str):
        # ADR command help historically showed both ordinary paths and
        # Azure-CLI-style @path inputs. Keep the common JSON parser unchanged
        # and normalize exactly one optional marker at this boundary.
        if value.startswith("@"):
            value = value[1:]
        try:
            value = process_json_arg(value, argument_name)
        except CLIInternalError as error:
            raise InvalidArgumentValueError(
                f"{argument_name} must be a valid JSON object or a path to a JSON file."
            ) from error
    if not isinstance(value, dict):
        raise InvalidArgumentValueError(
            f"{argument_name} must be a JSON object or a path to a JSON file."
        )

    if allowed_keys is not None:
        unsupported = set(value) - allowed_keys
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise InvalidArgumentValueError(
                f"{argument_name} contains unsupported properties: {names}."
            )

    missing = sorted(
        key for key in required_keys if key not in value or value[key] is None
    )
    if missing:
        names = ", ".join(missing)
        raise RequiredArgumentMissingError(
            f"{argument_name} must contain the following properties: {names}."
        )
    return value


_ADR_LRO_TIMEOUT_SECONDS = 10 * 60
_ADR_LRO_MAX_DELAY_SECONDS = 30


_PROVISIONING_FAILURES = ("Failed", "Canceled")


class ADRResourceStateError(AzureResponseError):
    """A structured terminal resource failure, distinct from transport/CLI errors."""

    def __init__(self, message, body):
        super().__init__(message)
        self.body = body


def _retry_after_seconds(response, fallback: float) -> float:
    """Return a positive integer Retry-After, case-insensitively."""
    value = None
    headers = getattr(response, "headers", None) or {}
    items = headers.items() if isinstance(headers, Mapping) else ()
    for key, candidate in items:
        if str(key).casefold() == "retry-after":
            value = candidate
            break
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if parsed <= 0:
        parsed = max(0, fallback)
    return min(parsed, _ADR_LRO_MAX_DELAY_SECONDS)


class ADRProvider(object):
    def __init__(self, cmd, client=None):
        self.cmd = cmd
        self.client = (
            client
            if client is not None
            else adr_service_factory(cmd.cli_ctx)
        )

    def _wait(self, poller, status_message: str, **kwargs):
        """Block on a long-running-operation poller, honoring ``--no-wait``.

        This captures the epilogue shared by nearly every mutating ADR command:
        pop ``no_wait`` from kwargs and return the poller immediately when set,
        otherwise show ``status_message`` in a spinner while waiting for the
        operation to reach a terminal state. Remaining kwargs are forwarded to
        ``_await_terminal`` (e.g. polling interval overrides).
        """
        no_wait = kwargs.pop("no_wait", False)
        if no_wait:
            return adapt_modeless_lro_poller(poller)
        with console.status(status_message):
            return self._await_terminal(poller, **kwargs)

    def _await_terminal(self, poller, **kwargs):
        """Wait for an ADR long-running operation to reach a terminal state.

        Single choke point used both by ``_wait`` and by the few commands that drive
        their poller directly. ADR LROs now use the SDK's poller, with this wrapper
        preserving the CLI's bounded wait budget. The SDK treats an inline 200 as
        complete, so a terminal failed ``provisioningState`` is raised here.
        """
        failure_target = kwargs.pop("failure_target", None)
        poller = adapt_modeless_lro_poller(poller)
        result = self._bounded_poller_result(poller, **kwargs)
        properties = result.get("properties") if isinstance(result, dict) else None
        state = properties.get("provisioningState") if isinstance(properties, dict) else None
        if state in _PROVISIONING_FAILURES:
            response = self._poller_initial_http_response(poller)
            raise ADRResourceStateError(
                self._format_failure(state, result, response, "operation response", target=failure_target), result,
            )
        return result

    @staticmethod
    def _bounded_poller_result(
        poller,
        *,
        deadline_guard=None,
        sleeper=sleep,
        wait_sec=LRO_POLL_WAIT_SEC,
        timeout_sec=_ADR_LRO_TIMEOUT_SECONDS,
        clock=monotonic,
        **_,
    ):
        # Azure Core result(timeout=...) may return None while unfinished.
        # Do not interpret that as completion or bypass the real polling method.
        # A caller-owned deadline_guard (e.g. --timeout on link commands) replaces the default budget.
        deadline = clock() + max(0, timeout_sec)

        def remaining():
            if deadline_guard:
                return deadline_guard()
            local_remaining = deadline - clock()
            if local_remaining <= 0:
                raise AzureResponseError(
                    f"Timed out waiting for the operation to complete after {timeout_sec} seconds."
                )
            return local_remaining

        remaining()
        while not poller.done():
            sleeper(min(wait_sec, remaining()))
            remaining()
        result = poller.result()
        remaining()
        return result

    @staticmethod
    def _poller_initial_response(poller):
        method = getattr(poller, "_polling_method", None)
        if method is None and hasattr(poller, "polling_method"):
            try:
                method = poller.polling_method()
            except Exception:  # noqa: BLE001
                method = None
        return getattr(method, "_initial_response", None)

    @classmethod
    def _poller_initial_http_response(cls, poller):
        initial = cls._poller_initial_response(poller)
        return getattr(initial, "http_response", None)

    @staticmethod
    def _extract_failure_detail(body, target=None):
        """Best-effort human-readable reason from a Failed resource body.

        Scans the endpoint collections (provisioning / messaging) for an
        entry that carries its own status/error (this is where a failed link records
        *why* it failed), then falls back to a resource-level error object. A
        ``(section, name)`` target limits the scan to the endpoint being mutated, so
        another endpoint's older failure is never reported for it. Returns "" when
        nothing useful is present.
        """
        if not isinstance(body, dict):
            return ""
        props = body.get("properties") or {}
        for group in (target[0],) if target else ("provisioning", "messaging"):
            endpoints = ((props.get(group) or {}).get("endpoints")) or {}
            if not isinstance(endpoints, dict):
                continue
            for name, endpoint in endpoints.items():
                if not isinstance(endpoint, dict) or (target and name != target[1]):
                    continue
                status = endpoint.get("provisioningStatus") or endpoint.get("status") or {}
                if not isinstance(status, dict):
                    status = {}
                error = (
                    status.get("error")
                    or endpoint.get("error")
                    or endpoint.get("linkingError")
                    or {}
                )
                if not isinstance(error, dict):
                    error = {}
                message = ADRProvider._error_text(error)
                ep_state = status.get("status") or endpoint.get("linkingState")
                if message:
                    return f"endpoint '{name}': {message}"
                if ep_state and str(ep_state).lower() == "failed":
                    return f"endpoint '{name}' is in a 'Failed' state"
        for error in (props.get("error"), body.get("error")):
            detail = ADRProvider._error_text(error)
            if detail:
                return detail
        return ""

    @staticmethod
    def _error_text(error):
        if not isinstance(error, dict):
            return ""
        return ": ".join(
            value.strip() for key in ("code", "message")
            if isinstance(value := error.get(key), str) and value.strip()
        )

    def _format_failure(self, state, body, response, source="resource-status response", target=None):
        """Preserve observed errors and label correlation by the response source."""
        message = f"The operation did not succeed (provisioningState='{state}')."
        detail = self._extract_failure_detail(body, target)
        if detail:
            message += f" {detail}" if detail.endswith((".", "!", "?")) else f" {detail}."
        else:
            message += f" The {source} did not include a detailed error."
        resource_id = body.get("id") if isinstance(body, dict) else None
        if isinstance(resource_id, str) and resource_id:
            message += f" Resource: {resource_id}."
        if detail and "not authorized" in detail.lower():
            message += (
                " Verify access for the identity and resource named in the service error. "
                "Role assignments visible in ARM may not yet be effective at the linked service. "
                "If the failed endpoint is still present, use link update, not link add, "
                "preserving its existing identity and endpoint settings. "
                "Update reruns RBAC preflight; it does not require deleting the linked resource."
            )
            commands = failed_link_recovery_commands(body)
            if commands:
                message += (
                    "\nAfter verifying access and allowing any recent assignments to propagate, "
                    "retry the persisted failed link(s):\n"
                    + "\n".join(commands)
                    + "\n"
                )
        headers = getattr(response, "headers", None)
        corr = headers.get("x-ms-correlation-request-id") if headers is not None else None
        if corr:
            message += f" Correlation ID from the {source}: {corr}."
        message += " Check Azure Activity Log for this resource around the operation time."
        return message

    def _raise_if_parent_not_found(self, error: Exception, message: str) -> NoReturn:
        """Translate a backend "ParentResourceNotFound" 404 into a friendly error.

        ARM returns an opaque 404 when a parent in the resource path (e.g. the
        certificate authority behind a certificate policy) does not exist. Callers
        pass a resource-specific ``message`` so the user gets actionable guidance.
        Any other error is re-raised unchanged.
        """
        if (
            isinstance(error, HttpResponseError)
            and error.status_code == 404
            and "ParentResourceNotFound" in str(error)
        ):
            raise ResourceNotFoundError(message)
        raise error

    def _resolve_location(
        self, namespace_name: str, resource_group_name: str, location: Optional[str] = None
    ):
        """Resolve a child resource location from its parent Device Registry namespace.

        Namespace child resources must be co-located with their parent, so
        default to the namespace's location when the caller does not specify
        one explicitly.
        """
        if location:
            return location
        namespace = self.client.namespaces.get(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )
        location = namespace.get("location")
        if not location:
            raise AzureResponseError(
                "Error attempting to determine location from parent Namespace: "
                "Namespace does not contain a location property."
            )
        return location

    def _ensure_location(self, cli_ctx, resource_group_name: str, location: Optional[str] = None):
        """Resolve a location, falling back to the resource group's location.

        Unlike ``_resolve_location`` (which reads the parent namespace), this is used when there
        is no parent resource yet — e.g. creating the namespace itself — so the resource group's
        location is the sensible default.
        """
        if location:
            return location

        # Get resource group location as fallback
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        from azure.mgmt.resource import ResourceManagementClient

        resource_client = get_mgmt_service_client(cli_ctx, ResourceManagementClient)
        rg = resource_client.resource_groups.get(resource_group_name)
        return rg.location
