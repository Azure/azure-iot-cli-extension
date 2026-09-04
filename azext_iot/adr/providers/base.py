# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from collections.abc import Mapping
from time import monotonic, sleep
from typing import Any, Callable, Dict, FrozenSet, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    CLIInternalError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError
from azure.core.rest import HttpRequest
from knack.log import get_logger
from rich.console import Console

from azext_iot._factory import adr_service_factory
from azext_iot.constants import LRO_POLL_WAIT_SEC
from azext_iot.common.utility import process_json_arg, wait_for_terminal_state

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


# ---------------------------------------------------------------------------
# TEMPORARY WORKAROUND — the Device Registry service is under active development.
#
# ADR mutations are long-running operations (LROs). The status URL the service
# returns (via the ``Azure-AsyncOperation`` header) points at the DIRECT
# resource-provider host (``control-plane.prod.<region>.iotadr.net``), NOT at
# ARM. That host currently requires an ARM PoP (proof-of-possession) token that
# neither the Azure SDK poller nor a plain bearer client sends, so polling the
# async-operation URL returns HTTP 500 "ARM PoP token authentication failed"
# even though the mutation itself succeeds (HTTP 202). Per the Device Registry
# team this async-status implementation is incomplete/temporary; until it is
# fixed we poll a mutation's resource ``provisioningState`` or a POST action's
# Location URL instead. Resource polling matches the Device Registry team's
# reference tool, which avoids the broken Azure-AsyncOperation URL.
#
# TO REVERT once the backend is fixed: set POLL_PROVISIONING_STATE_WORKAROUND to
# ``False`` (or delete this block, the workaround branch in ``_await_terminal``
# and ``_poll_provisioning_state``). No command call sites need to change.
# ---------------------------------------------------------------------------
POLL_PROVISIONING_STATE_WORKAROUND = True

# Terminal ARM ``provisioningState`` values.
_PROVISIONING_SUCCEEDED = "Succeeded"
_PROVISIONING_FAILURES = ("Failed", "Canceled")

# PUT/PATCH/DELETE LROs address the resource itself, so their initial request
# URL can be GET-polled for ``provisioningState``. POST actions are polled
# through their Location header to avoid the broken Azure-AsyncOperation host.
_RESOURCE_MUTATION_METHODS = ("PUT", "PATCH", "DELETE")
_ACTION_METHOD = "POST"
_ADR_LRO_TIMEOUT_SECONDS = 10 * 60
_ADR_LRO_MAX_DELAY_SECONDS = 30


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


def _poll_with_deadline(
    request: Callable,
    inspect_response: Callable,
    timeout_message: Callable[[], str],
    *,
    initial_response=None,
    wait_sec: float = LRO_POLL_WAIT_SEC,
    timeout_sec: float = _ADR_LRO_TIMEOUT_SECONDS,
    clock: Callable = monotonic,
    sleeper: Callable = sleep,
):
    """Poll until an inspector reports completion or the deadline expires."""
    deadline = clock() + max(0, timeout_sec)
    previous_response = initial_response
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        delay = _retry_after_seconds(previous_response, wait_sec)
        if delay:
            sleeper(min(delay, remaining))
            if deadline - clock() <= 0:
                break

        response = request()
        complete, value = inspect_response(response)
        if complete:
            return value
        previous_response = response

    raise AzureResponseError(timeout_message())


class ADRProvider(object):
    def __init__(self, cmd):
        self.cmd = cmd
        self.client = adr_service_factory(cmd.cli_ctx)

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
            return poller
        with console.status(status_message):
            return self._await_terminal(poller, **kwargs)

    def _await_terminal(self, poller, **kwargs):
        """Wait for an ADR long-running operation to reach a terminal state.

        Single choke point used both by ``_wait`` and by the few commands that
        drive their poller directly. While the temporary workaround is enabled we
        poll the resource's ``provisioningState`` (see the module note above);
        otherwise we defer to the shared SDK helper.
        """
        if POLL_PROVISIONING_STATE_WORKAROUND:
            return self._poll_provisioning_state(poller, **kwargs)
        return wait_for_terminal_state(poller, **kwargs)

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
    def _poller_initial_request(cls, poller):
        """Best-effort ``(url, method)`` of the request wrapped by a poller."""
        initial = cls._poller_initial_response(poller)
        request = getattr(initial, "http_request", None)
        if request is None:
            request = getattr(getattr(initial, "http_response", None), "request", None)
        if request is None:
            return None, None
        return getattr(request, "url", None), (getattr(request, "method", "") or "").upper()

    @classmethod
    def _poller_location(cls, poller):
        response = cls._poller_initial_http_response(poller)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        return headers.get("Location") or headers.get("location")

    @classmethod
    def _poller_initial_http_response(cls, poller):
        initial = cls._poller_initial_response(poller)
        return getattr(initial, "http_response", None)

    @classmethod
    def _poller_is_async(cls, poller):
        response = cls._poller_initial_http_response(poller)
        if response is None:
            return False
        headers = getattr(response, "headers", None) or {}
        return response.status_code == 202 or bool(
            headers.get("Azure-AsyncOperation")
            or headers.get("azure-asyncoperation")
            or headers.get("Location")
            or headers.get("location")
        )

    @staticmethod
    def _extract_failure_detail(body):
        """Best-effort human-readable reason from a Failed resource body.

        Scans the endpoint collections (provisioning / messaging / updating) for an
        entry that carries its own status/error (this is where a failed link records
        *why* it failed), then falls back to a resource-level error object. Returns
        "" when nothing useful is present.
        """
        if not isinstance(body, dict):
            return ""
        props = body.get("properties") or {}
        for group in ("provisioning", "messaging", "updating"):
            endpoints = ((props.get(group) or {}).get("endpoints")) or {}
            if not isinstance(endpoints, dict):
                continue
            for name, endpoint in endpoints.items():
                if not isinstance(endpoint, dict):
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
                message = error.get("message")
                ep_state = status.get("status") or endpoint.get("linkingState")
                if message:
                    return f"endpoint '{name}': {message}"
                if ep_state and str(ep_state).lower() == "failed":
                    return f"endpoint '{name}' is in a 'Failed' state"
        error = props.get("error") or body.get("error") or {}
        if isinstance(error, dict) and error.get("message"):
            code = error.get("code")
            return f"{code}: {error['message']}" if code else error["message"]
        return ""

    def _format_failure(self, state, body, response):
        """Build an actionable error message for a terminal Failed/Canceled LRO.

        Surfaces the backend's endpoint-level reason (when present) plus the GET's
        correlation id, instead of just the bare provisioningState, so the failure
        is diagnosable without hunting through the activity log.
        """
        message = f"The operation did not succeed (provisioningState='{state}')."
        detail = self._extract_failure_detail(body)
        if detail:
            message += f" {detail}" if detail.endswith((".", "!", "?")) else f" {detail}."
        if detail and "not authorized" in detail.lower():
            # Role names and directions are defined only in adr.rbac. Keep this
            # fallback generic so it cannot drift from automatic add preflight.
            message += (
                " The service-to-service link roles are incomplete. Rerun the "
                "corresponding link add command to perform automatic RBAC "
                "preflight, or use the exact remediation commands it prints."
            )
        headers = getattr(response, "headers", None)
        corr = headers.get("x-ms-correlation-request-id") if headers is not None else None
        if corr:
            message += f" Correlation id: {corr}."
        else:
            message += " Inspect the service activity log using the operation's correlation id."
        return message

    def _poll_provisioning_state(
        self,
        poller,
        wait_sec: int = LRO_POLL_WAIT_SEC,
        timeout_sec: int = _ADR_LRO_TIMEOUT_SECONDS,
        clock=None,
        sleeper=None,
        **_,
    ):
        """TEMPORARY: resolve an LRO by polling the resource's ``provisioningState``.

        See the module-level workaround note. Steps:

        * If the poller already completed inline (e.g. a create/PUT that returns
          the resource with a terminal ``provisioningState``), return its result
          directly - no async-operation/PoP hop needed.
        * Otherwise recover the resource URL from the poller and GET it until
          ``provisioningState`` is terminal: ``Succeeded`` (or a resource that
          exposes no ``provisioningState``) returns the body; ``Failed`` /
          ``Canceled`` raises ``AzureResponseError``.

        For a DELETE a 404 means the resource is gone (success). Other resource
        404 responses are retried. POST actions use the authenticated SDK
        pipeline to poll the Location URL.
        """
        url, method = self._poller_initial_request(poller)
        initial_response = self._poller_initial_http_response(poller)
        if method == _ACTION_METHOD:
            if initial_response is not None and not self._poller_is_async(poller):
                return poller.result()
            return self._poll_location(
                poller,
                wait_sec=wait_sec,
                timeout_sec=timeout_sec,
                clock=clock,
                sleeper=sleeper,
            )
        if url and method in _RESOURCE_MUTATION_METHODS:
            if initial_response is not None and not self._poller_is_async(poller):
                return poller.result()
        else:
            if poller.done():
                return poller.result()
            return wait_for_terminal_state(poller, wait_sec=wait_sec)

        is_delete = method == "DELETE"
        last_body = None

        def inspect_response(response):
            nonlocal last_body
            code = response.status_code
            if code == 404:
                if is_delete:
                    return True, None  # resource removed -> delete complete
                return False, None  # not readable yet -> retry
            if 200 <= code < 300:
                last_body = response.json()
                state = (last_body.get("properties") or {}).get("provisioningState")
                if state == _PROVISIONING_SUCCEEDED or state is None:
                    return True, last_body
                if state in _PROVISIONING_FAILURES:
                    raise AzureResponseError(self._format_failure(state, last_body, response))
                return False, None
            if code in (408, 429) or code >= 500:
                return False, None
            if 400 <= code < 500:
                response.raise_for_status()
            return False, None

        def timeout_message():
            state = ((last_body or {}).get("properties") or {}).get(
                "provisioningState"
            )
            return (
                "Timed out waiting for the operation to complete"
                + (f" (last provisioningState='{state}')." if state else ".")
            )

        return _poll_with_deadline(
            lambda: self.client.send_request(HttpRequest("GET", url)),
            inspect_response,
            timeout_message,
            initial_response=initial_response,
            wait_sec=wait_sec,
            timeout_sec=timeout_sec,
            clock=clock or monotonic,
            sleeper=sleeper or sleep,
        )

    def _poll_location(
        self,
        poller,
        wait_sec: int,
        timeout_sec: int = _ADR_LRO_TIMEOUT_SECONDS,
        clock=None,
        sleeper=None,
    ):
        location = self._poller_location(poller)
        if not location:
            raise AzureResponseError(
                "The service returned an asynchronous POST operation without a Location header."
            )

        last_status = None

        def inspect_response(response):
            nonlocal last_status
            code = response.status_code
            if code == 404:
                return False, None
            if 200 <= code < 300:
                body = None
                if code != 204:
                    try:
                        body = response.json()
                    except ValueError:
                        body = None
                properties = (body or {}).get("properties") or {}
                last_status = (body or {}).get("status") or properties.get(
                    "provisioningState"
                )
                if last_status in _PROVISIONING_FAILURES:
                    raise AzureResponseError(
                        self._format_failure(last_status, body or {}, response)
                    )
                if code != 202 and (
                    last_status == _PROVISIONING_SUCCEEDED or last_status is None
                ):
                    return True, body
                return False, None
            if code in (408, 429) or code >= 500:
                return False, None
            if 400 <= code < 500:
                response.raise_for_status()
            return False, None

        def timeout_message():
            return (
                "Timed out waiting for the POST operation to complete"
                + (
                    f" (last status='{last_status}')."
                    if last_status
                    else "."
                )
            )

        return _poll_with_deadline(
            lambda: self.client.send_request(HttpRequest("GET", location)),
            inspect_response,
            timeout_message,
            initial_response=self._poller_initial_http_response(poller),
            wait_sec=wait_sec,
            timeout_sec=timeout_sec,
            clock=clock or monotonic,
            sleeper=sleeper or sleep,
        )

    def _raise_if_parent_not_found(self, error: Exception, message: str):
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
