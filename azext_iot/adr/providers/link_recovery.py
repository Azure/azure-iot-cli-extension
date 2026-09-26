# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Bounded, identity-preserving recovery of confirmed link authorization failures."""

from copy import deepcopy
import re
from time import monotonic, sleep

from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError
from azure.core.exceptions import HttpResponseError
from knack.log import get_logger
from knack.util import CLIError

from azext_iot.adr.providers.base import ADRResourceStateError, _ADR_LRO_TIMEOUT_SECONDS
from azext_iot.adr.providers.wait import DEFAULT_WAIT_INTERVAL
from azext_iot.adr.topology import endpoint_update_body

logger = get_logger(__name__)
AUTHORIZATION_DELAYS = (30, 60, 120)
ACTIVE_STATES = {"Accepted", "Creating", "Updating", "InProgress", "Running"}
TERMINAL_FAILURES = {"Failed", "Canceled", "Cancelled"}
_GUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
_LINK_INITIATE_AUTHORIZATION = re.compile(
    r"The namespace's managed identity is not authorized to link the (?P<service>Hub|DPS) resource\. "
    r"Grant it access on the resource, then resubmit the request\. "
    r"\((?P=service) resource reported: \[AuthorizationFailed\] "
    rf"The client '{_GUID}' with object id '(?P<principal>{_GUID})' "
    r"does not have authorization to perform action '(?P<action>[^'\r\n]+)' "
    r"over scope '(?P<scope>[^'\r\n]+)' or the scope is invalid\. "
    r"If access was recently granted, please refresh your credentials\.\)"
)
_LINK_INITIATE_ACTIONS = {
    "hub": ("Hub", "Microsoft.Devices/IotHubs/linkInitiate/action"),
    "dps": ("DPS", "Microsoft.Devices/provisioningServices/linkInitiate/action"),
}


def validate_options(timeout, interval):
    if timeout <= 0:
        raise InvalidArgumentValueError("--timeout must be greater than zero.")
    if interval <= 0:
        raise InvalidArgumentValueError("--interval must be greater than zero.")


class LinkDeadline:
    """One mutation budget, also shared by both stages of combined link add."""

    def __init__(self, timeout=_ADR_LRO_TIMEOUT_SECONDS, interval=DEFAULT_WAIT_INTERVAL, *, clock=None, sleeper=None):
        validate_options(timeout, interval)
        self.timeout, self.interval = timeout, interval
        self.clock, self.sleeper = clock or monotonic, sleeper or sleep
        self.deadline = self.clock() + timeout
        self.observation = ""

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise AzureResponseError(
                f"Linking timed out after {self.timeout} seconds. {self.observation} "
                "Inspect the persisted endpoint with link show; use link update with its existing "
                "identity/settings after verifying access, not link add. No rollback was attempted."
            )
        return remaining

    def call(self, operation, *args, **kwargs):
        self.remaining()
        result = operation(*args, **kwargs)
        self.remaining()  # Reject late success; an in-flight RPC cannot be interrupted.
        return result

    def pause(self, delay):
        self.sleeper(min(delay, self.remaining()))
        self.remaining()


def _normalized(value):
    """Normalize only ARM IDs and identity/type casing, never endpoint settings."""
    result = deepcopy(value)
    for key in ("resourceId", "endpointType", "userAssignedIdentity", "type", "id"):
        if isinstance(result.get(key), str):
            result[key] = result[key].casefold()
    if isinstance(result.get("inboundCallerIdentity"), dict):
        result["inboundCallerIdentity"] = _normalized(result["inboundCallerIdentity"])
    return result


def _namespace_identity(namespace):
    outbound = (namespace.get("properties") or {}).get("outboundIdentity")
    if outbound is not None and not isinstance(outbound, dict):
        raise AzureResponseError("Malformed namespace outboundIdentity.")
    outbound = deepcopy(outbound or {})
    outbound["type"] = outbound.get("type") or "SystemAssigned"
    return {
        "id": str(namespace.get("id") or "").casefold(),
        "identity": deepcopy(namespace.get("identity")),
        "outboundIdentity": _normalized(outbound),
    }


def _known_http_authorization(error):
    # Do not infer authorization from error text, generic OperationFailed,
    # 401/403, or an unrelated transport failure plus a stale Failed endpoint.
    return (
        error.status_code in (None, 400)
        and not getattr(error, "adr_resource_read_failure", False)
        and getattr(error.error, "code", None) == "AdrMiNotAuthorized"
    )


class LinkRecovery:
    """One endpoint UPDATE loop; never invokes public add or replaces collections."""

    def __init__(self, provider, namespace, section, name, expected, budget, verify, *, authorization_request=None):
        self.provider, self.section, self.name = provider, section, name
        self.kind = {"provisioning": "dps", "messaging": "hub", "updating": "su"}[section]
        self.expected = _normalized(endpoint_update_body(expected))
        self.namespace_identity = _namespace_identity(namespace)
        self.authorization_request = deepcopy(authorization_request)
        self.snapshot = None
        previous = ((namespace.get("properties") or {}).get(section) or {}).get("endpoints", {}).get(name)
        self.previous = _normalized(endpoint_update_body(previous)) if isinstance(previous, dict) else None
        self.pending = False
        self.budget, self.verify = budget, verify
        self.progressed = True

    def inspect(self, namespace):
        if not isinstance(namespace, dict) or not isinstance(namespace.get("properties"), dict):
            raise AzureResponseError("Malformed namespace response during link recovery.")
        if _namespace_identity(namespace) != self.namespace_identity:
            raise AzureResponseError("Namespace resource or configured outbound identity changed; recovery stopped.")
        properties = namespace["properties"]
        group = properties.get(self.section)
        if group is not None and not isinstance(group, dict):
            raise AzureResponseError("Malformed namespace endpoint collection during link recovery.")
        endpoints = (group or {}).get("endpoints", {})
        if not isinstance(endpoints, dict):
            raise AzureResponseError("Malformed namespace endpoint collection during link recovery.")
        endpoint = endpoints.get(self.name)
        ns_state = properties.get("provisioningState")
        if not isinstance(ns_state, str) or ns_state not in ACTIVE_STATES | TERMINAL_FAILURES | {"Succeeded"}:
            raise AzureResponseError(f"Malformed namespace provisioningState: {ns_state!r}.")
        if endpoint is None:
            return ns_state, None
        if not isinstance(endpoint, dict):
            raise AzureResponseError("Malformed link endpoint response.")
        state = endpoint.get("linkingState")
        if not isinstance(state, str) or state not in ACTIVE_STATES | TERMINAL_FAILURES | {"Succeeded"}:
            raise AzureResponseError(f"Malformed endpoint linkingState: {state!r}.")
        if endpoint.get("linkingError") is not None and not isinstance(endpoint["linkingError"], dict):
            raise AzureResponseError("Malformed endpoint linkingError.")
        if (
            isinstance(endpoint.get("linkingError"), dict)
            and endpoint["linkingError"].get("message") is not None
            and not isinstance(endpoint["linkingError"]["message"], str)
        ):
            raise AzureResponseError("Malformed endpoint linkingError message.")
        if state == "Succeeded" and endpoint.get("linkingError"):
            raise AzureResponseError("Endpoint reports Succeeded with a linkingError; recovery stopped.")
        actual = _normalized(endpoint_update_body(endpoint))
        # The RP can fill omitted Hub provisioning defaults on the first read.
        # Requested values must match; then freeze every writable setting.
        expected = deepcopy(self.expected)
        actual_settings = actual.get("provisioning", {})
        expected_settings = expected.pop("provisioning", {})
        comparison = {key: value for key, value in actual.items() if key != "provisioning"}
        if (
            comparison != expected
            or not isinstance(actual_settings, dict)
            or any(actual_settings.get(key) != value for key, value in expected_settings.items())
            or (self.snapshot is not None and actual != self.snapshot)
        ):
            changed = sorted(
                key for key in set(actual) | set(self.expected)
                if actual.get(key) != self.expected.get(key)
            )
            frozen_changed = sorted(
                key for key in set(actual) | set(self.snapshot or {})
                if self.snapshot is not None and actual.get(key) != self.snapshot.get(key)
            )
            # A pending UPDATE may still expose the exact pre-write projection.
            # Never freeze it, accept it as success, or recover its stale failure.
            # No mixed projection, target/type change, post-convergence regression,
            # or old view after operation completion is eligible.
            if (
                self.pending and ns_state in ACTIVE_STATES and self.snapshot is None
                and actual == self.previous
                and all(actual.get(key) == self.expected.get(key) for key in ("resourceId", "endpointType"))
            ):
                logger.info("Pending link update still exposes the pre-update fields: %s.", ", ".join(changed))
                return ns_state, None
            raise AzureResponseError(
                "Link target, type, inbound identity or settings changed; recovery stopped. "
                f"Requested-field differences: {', '.join(changed) or 'none'}; "
                f"frozen-field differences: {', '.join(frozen_changed) or 'none'}."
            )
        self.snapshot = actual
        if ns_state in ACTIVE_STATES or state in ACTIVE_STATES:
            self.progressed = True
        return ns_state, endpoint

    def observe_lro(self, namespace):
        # Resource polling is the canary workaround, not an async-status-host
        # call. Observing progress here prevents stale Failed reads from
        # repeatedly resubmitting an already accepted recovery PATCH.
        self.inspect(namespace)

    def authorized_failure(self, endpoint):
        error = endpoint.get("linkingError")
        if endpoint.get("linkingState") != "Failed" or not isinstance(error, dict):
            return False
        if error.get("code") == "AdrMiNotAuthorized":
            return True
        return self._bound_link_initiate_authorization(error)

    def _bound_link_initiate_authorization(self, error):
        """Recognize only the observed service envelope, bound to original preflight.

        LinkInitiateFailed also covers invalid requests. Its code alone, a 403,
        or authorization-looking text cannot authorize a recovery PATCH. The
        denied object ID (not the application's client ID), exact target and
        exact linkInitiate action must all match the original RBAC request.
        Recovery still re-preflights and verifies grants twice before writing.
        """
        request = self.authorization_request
        if (
            self.kind not in _LINK_INITIATE_ACTIONS
            or error.get("code") != "LinkInitiateFailed"
            or set(error) - {"code", "message"}
            or not isinstance(error.get("message"), str)
            or not isinstance(request, dict)
            or request.get("link_type") != self.kind
        ):
            return False
        principal = request.get("namespace_principal_id")
        target = request.get("target_scope")
        namespace = request.get("namespace_scope")
        if (
            not isinstance(principal, str) or not re.fullmatch(_GUID, principal)
            or not isinstance(target, str) or target.casefold() != self.expected["resourceId"]
            or not isinstance(namespace, str) or namespace.casefold() != self.namespace_identity["id"]
        ):
            return False
        match = _LINK_INITIATE_AUTHORIZATION.fullmatch(error["message"])
        service, action = _LINK_INITIATE_ACTIONS[self.kind]
        return bool(
            match and match["service"] == service
            and match["principal"].casefold() == principal.casefold()
            and match["action"].casefold() == action.casefold()
            and match["scope"].casefold() == target.casefold()
        )

    def run(self, *, submit, get, status_message, no_wait=False, **kwargs):
        original_error = None
        retries = 0
        body = deepcopy(self.expected)
        # Keep caller spelling and full writable settings in the actual PATCH.
        body = deepcopy(kwargs.pop("endpoint_body", body))
        pending_submission = True
        try:
            while True:
                if pending_submission:
                    pending_submission = False
                    try:
                        poller = self.budget.call(submit, body)
                        if no_wait:
                            return poller
                        self.pending = True
                        try:
                            self.budget.call(
                                self.provider._wait, poller, status_message,
                                **{**kwargs, "timeout_sec": self.budget.remaining(), "wait_sec": self.budget.interval,
                                   "clock": self.budget.clock, "sleeper": self.budget.pause,
                                   "deadline_guard": self.budget.remaining, "resource_observer": self.observe_lro},
                            )
                        finally:
                            self.pending = False
                    except ADRResourceStateError as error:
                        logger.warning("Link '%s' service failure: %s", self.name, error)
                        if no_wait:
                            raise
                        _, failed = self.inspect(error.body)
                        if not failed or not self.authorized_failure(failed):
                            raise
                        original_error = error
                        self.budget.observation = str(error)
                    except HttpResponseError as error:
                        if no_wait or not _known_http_authorization(error):
                            raise
                        # This is an authoritative rejection of the latest
                        # mutation, not a stale Failed resource GET. No accepted
                        # operation needs to show InProgress before retrying.
                        self.progressed = True
                        original_error = error
                        self.budget.observation = str(error)
                        logger.warning("Link '%s' service failure: %s", self.name, error)
                # Even an LRO Succeeded is not evidence of endpoint readiness.
                try:
                    namespace = self.budget.call(get)
                except (CLIError, HttpResponseError) as error:
                    if original_error:
                        raise error from original_error
                    raise
                ns_state, endpoint = self.inspect(namespace)
                state = endpoint.get("linkingState") if endpoint else None
                self.budget.observation = (
                    f"endpoint '{self.name}': namespace={ns_state}, linkingState={state}; "
                    f"{self.provider._extract_failure_detail(namespace)}"
                )
                if ns_state == "Succeeded" and state == "Succeeded":
                    if original_error:
                        # A failing operation followed by an unrelated/stale
                        # success must not erase the service failure.
                        raise original_error
                    return namespace
                failure = ns_state in TERMINAL_FAILURES or state in TERMINAL_FAILURES
                if failure:
                    if not endpoint or not self.authorized_failure(endpoint) or ns_state not in {"Succeeded", "Failed"}:
                        if original_error:
                            raise original_error
                        raise ADRResourceStateError(
                            self.provider._format_failure(ns_state, namespace, None), namespace,
                        )
                    if self.progressed:
                        for error in (namespace.get("error"), namespace["properties"].get("error"), endpoint.get("error")):
                            if error:
                                raise ADRResourceStateError(
                                    "An additional service error prevents authorization recovery: "
                                    f"{self.provider._error_text(error)}", namespace,
                                )
                        for section in ("provisioning", "messaging", "updating"):
                            group = namespace["properties"].get(section, {})
                            if group is None:
                                group = {}
                            if not isinstance(group, dict):
                                raise AzureResponseError("Malformed namespace endpoint collection during recovery.")
                            others = group.get("endpoints", {})
                            if others is None:
                                others = {}
                            if not isinstance(others, dict):
                                raise AzureResponseError("Malformed namespace endpoint collection during recovery.")
                            for name, other in others.items():
                                if (section, name) == (self.section, self.name):
                                    continue
                                if not isinstance(other, dict) or other.get("linkingState") in ACTIVE_STATES | TERMINAL_FAILURES:
                                    raise AzureResponseError("Another namespace endpoint is active or failed; recovery stopped.")
                        logger.warning(
                            "%s. Rechecking required service-role assignments before bounded propagation recovery.",
                            self.budget.observation,
                        )
                        failed_snapshot = deepcopy(namespace)
                        original_error = original_error or ADRResourceStateError(
                            self.provider._format_failure(ns_state, namespace, None), namespace,
                        )
                        try:
                            self.budget.call(self.verify, namespace, self.budget)
                            self.budget.pause(AUTHORIZATION_DELAYS[min(retries, len(AUTHORIZATION_DELAYS) - 1)])
                            # A target principal or grant can change during the
                            # delay without changing the persisted endpoint.
                            self.budget.call(self.verify, namespace, self.budget)
                            current = self.budget.call(get)
                            self.inspect(current)
                        except (CLIError, HttpResponseError) as error:
                            raise error from original_error
                        # Includes state/error and other endpoints: never overwrite
                        # a change observed during preflight or propagation delay.
                        if current != failed_snapshot:
                            raise AzureResponseError("Namespace changed during link recovery; no retry PATCH submitted.")
                        body = endpoint_update_body(endpoint)
                        self.progressed = False
                        original_error = None
                        retries += 1
                        pending_submission = True
                        continue
                self.budget.pause(self.budget.interval)
        except (CLIError, HttpResponseError):
            logger.warning(
                "Link '%s' did not complete. Inspect its current state/error with 'iot adr ns link %s show'. "
                "For a persisted Failed endpoint, verify access and use 'iot adr ns link %s update' with its existing "
                "identity and settings, not link add. No rollback was attempted.", self.name, self.kind, self.kind,
            )
            raise
