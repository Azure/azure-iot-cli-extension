# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Bounded readiness checks for owned ADR integration fixtures, not CLI retries.

Only exact resource GET HTTP 404 proves cleanup absence. Accepted namespace
deletes are polled, never replayed. Hub/DPS recovery is restricted to the observed
namespace-MI read-authorization failure or strictly bound linkInitiate denial
after a persisted link write. It neither adds fixture grants nor treats ARM role
visibility as effective authorization.
"""

import re
import shlex
import sys
import time
from copy import deepcopy
from urllib.parse import unquote, urlsplit

from azure.cli.core.azclierror import AzureResponseError
from azure.cli.core.commands.arm import show_exception_handler
from azure.cli.core.commands.client_factory import get_subscription_id
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot._factory import _ADR_CANARY_ARM_ENDPOINT
from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.base import ADRProvider, _ADR_LRO_TIMEOUT_SECONDS
from azext_iot.adr.providers.link_helpers import failed_link_recovery_commands
from azext_iot.adr.providers.link_recovery import LinkRecovery, _namespace_identity
from azext_iot.adr.rbac import resolve_namespace_outbound_principal
from azext_iot.tests.adr._helpers import is_resource_not_found_error
from azext_iot.tests.adr._log import LogKind, _log


LINK_READINESS_TIMEOUT = _ADR_LRO_TIMEOUT_SECONDS
HUB_LINK_READINESS_TIMEOUT = LINK_READINESS_TIMEOUT  # Existing test-helper import compatibility.
_OWNED_LINK_TYPES = {
    "hub": ("messaging", IOT_HUB_ENDPOINT_TYPE),
    "dps": ("provisioning", DPS_ENDPOINT_TYPE),
}
_CHILD_REJECTIONS = {"CannotDeleteResource", "NamespaceNotEmpty"}
_ACTIVE_STATES = {"Creating", "Updating", "InProgress", "Accepted"}


class _Deadline:
    """Charge CLI calls as well as sleeps; pytest bounds any single stuck call."""

    def __init__(self, timeout, clock, sleeper, description):
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.end = self.clock() + timeout
        self.description = description
        self.observation = "no observation"

    def check(self):
        if self.clock() >= self.end:
            raise AssertionError(f"Timed out waiting for {self.description}: {self.observation}")

    def call(self, callback, *args):
        self.check()
        result = callback(*args)
        self.check()
        return result

    def pause(self, seconds):
        self.check()
        _log(LogKind.WARN, "%s: %s; polling within deadline", self.description, self.observation)
        self.sleeper(min(seconds, self.end - self.clock()))
        self.check()


def _http_error(error):
    """Find response metadata through transparent CLI/testsdk wrappers only."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        if status is not None:
            return error, status
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return None, None


def _get_resource(scenario, command, getter=None):
    """None means an actual GET 404, never empty CLI output or an exit code."""
    ambient_context = sys.exc_info()[1:]
    try:
        result = getter() if getter is not None else scenario.cmd(command).get_output_in_json()
    except (HttpResponseError, CloudError, CLIError, SystemExit) as error:
        evidence = error
        # ARM's show handler can be called *outside* the HTTP except block.
        # Its SystemExit then inherits an unrelated cleanup assertion, not the
        # HTTP error. The real handler's traceback still owns the response.
        # Never infer absence from exit 3, text, or a similarly named wrapper.
        if (
            isinstance(error, SystemExit) and error.code == 3 and error.__cause__ is None
            and getattr(error, "status_code", None) is None and getattr(error, "response", None) is None
            and is_resource_not_found_error(error, ambient_context=ambient_context)
        ):
            trace = error.__traceback__
            while trace is not None:
                if trace.tb_frame.f_code is show_exception_handler.__code__:
                    candidate = trace.tb_frame.f_locals.get("ex")
                    if isinstance(candidate, (HttpResponseError, CloudError)):
                        evidence = candidate
                    break
                trace = trace.tb_next
        original, status = _http_error(evidence)
        response = getattr(original, "response", None)
        request = getattr(response, "request", None)
        url = getattr(request, "url", None)
        parts = shlex.split(command)
        namespace = parts[parts.index("--namespace") + 1]
        group = parts[parts.index("-g") + 1]
        path = f"/resourceGroups/{group}/providers/Microsoft.DeviceRegistry/namespaces/{namespace}"
        if parts[3] in {"job", "group"}:
            path += f"/{parts[3]}s/{parts[parts.index('-n') + 1]}"
        if (
            (not isinstance(error, SystemExit) or error.code == 3)
            and is_resource_not_found_error(evidence) and status == 404
            and getattr(response, "status_code", None) == 404
            and getattr(request, "method", None) == "GET"
            and isinstance(url, str)
            and urlsplit(url).scheme == "https"
            and urlsplit(url).netloc in {"management.azure.com", urlsplit(_ADR_CANARY_ARM_ENDPOINT).netloc}
            and unquote(urlsplit(url).path).casefold() == (
                f"/subscriptions/{get_subscription_id(scenario.cli_ctx)}{path}"
            ).casefold()
        ):
            return None
        raise
    assert isinstance(result, dict), "Resource GET returned no JSON object (not HTTP 404)"
    return result


def _child_rejection(error):
    original, status = _http_error(error)
    if status is None:
        # NamespaceProvider translates this explicit DELETE rejection. testsdk
        # can replace its implicit HTTP context with a transparent rethrow cycle.
        # Only accept the known rejection + guidance, not a code mentioned in
        # a timeout, a generic conflict, or an uncertain accepted operation.
        return isinstance(error, AzureResponseError) and re.fullmatch(
            r"\(NamespaceNotEmpty\) Namespace cannot be deleted while it contains child resources: "
            r"[^\n]+\. Delete these resources before deleting the namespace\."
            r"\nNamespace deletion does not cascade\. Delete the child resources "
            r"before retrying namespace deletion:\n[\s\S]+",
            str(error),
        ) is not None
    if status != 409 or not isinstance(original, HttpResponseError):
        return False
    code = getattr(getattr(original, "error", None), "code", None)
    if code is None:
        match = re.match(r"^\((CannotDeleteResource|NamespaceNotEmpty)\)", str(original))
        code = match[1] if match else None
    response = getattr(original, "response", None)
    request = getattr(response, "request", None)
    url = getattr(request, "url", None)
    # A rejection of an LRO GET is not evidence that DELETE was rejected.
    return (
        code in _CHILD_REJECTIONS
        and getattr(response, "status_code", None) == 409
        and getattr(request, "method", None) == "DELETE"
        and isinstance(url, str) and bool(url)
    )


def delete_test_namespace(
    scenario, namespace_name, resource_group, *, jobs=(), groups=(),
    timeout=120, interval=10, clock=None, sleeper=None, namespace_getter=None,
):
    """Require owned job/group GET 404 before sending the parent's DELETE.

    Names include children explicitly deleted earlier in the lifecycle. Empty
    lists alone cannot prove their absence. Lists are an additional guard after
    an explicit child-index rejection, never an instruction to delete strangers.
    A bound namespace SDK GET can preserve the original HTTP response when the
    CLI's exit-code wrapper loses it during exception unwinding. The same exact
    GET/URI/404 checks apply; an exit code alone never establishes absence.
    """
    scope = shlex.join(["--namespace", namespace_name, "-g", resource_group])
    budget = _Deadline(timeout, clock, sleeper, "owned namespace cleanup")
    accepted = False
    rejected = None
    while True:
        for kind, names in (("job", jobs), ("group", groups)):
            for name in names:
                shown = budget.call(_get_resource, scenario, f"iot adr ns {kind} show {scope} -n {shlex.quote(name)}")
                while shown is not None:
                    budget.observation = f"owned {kind} GET still readable"
                    budget.pause(interval)
                    shown = budget.call(
                        _get_resource, scenario, f"iot adr ns {kind} show {scope} -n {shlex.quote(name)}",
                    )
                _log(LogKind.RESULT, "Owned %s GET returned HTTP 404", kind)
        namespace = budget.call(_get_resource, scenario, f"iot adr ns show {scope}", namespace_getter)
        if namespace is None:
            return
        state = (namespace.get("properties") or {}).get("provisioningState")
        if accepted or state == "Deleting":
            accepted = True
            budget.observation = "namespace DELETE accepted; waiting for GET HTTP 404"
            budget.pause(interval)
            continue
        if rejected is not None:
            for kind in ("job", "group"):
                children = budget.call(scenario.cmd, f"iot adr ns {kind} list {scope}").get_output_in_json()
                if children != []:
                    raise rejected
        try:
            budget.call(scenario.cmd, f"iot adr ns delete {scope} -y --no-wait")
        except (HttpResponseError, AzureResponseError) as error:
            if not _child_rejection(error):
                raise
            rejected = error
            budget.observation = "namespace child-index rejection after owned child GET HTTP 404"
        else:
            accepted = True
            budget.observation = "namespace DELETE accepted; waiting for GET HTTP 404"
        budget.pause(interval)


def _link_state(endpoint):
    status = endpoint.get("provisioningStatus") or endpoint.get("status") or {}
    return endpoint.get("linkingState") or status.get("status")


def _endpoint_settings(endpoint):
    settings = {
        key: deepcopy(endpoint.get(key))
        for key in ("resourceId", "endpointType", "inboundCallerIdentity", "provisioning")
    }
    if isinstance(settings["resourceId"], str):
        settings["resourceId"] = settings["resourceId"].casefold()
    identity = settings["inboundCallerIdentity"]
    if isinstance(identity, dict) and isinstance(identity.get("userAssignedIdentity"), str):
        identity["userAssignedIdentity"] = identity["userAssignedIdentity"].casefold()
    return settings


def _read_authorization_failure(endpoint):
    status = endpoint.get("provisioningStatus") or endpoint.get("status") or {}
    error = status.get("error") or endpoint.get("error") or endpoint.get("linkingError") or {}
    target = endpoint.get("resourceId")
    # Match the observed direction and exact target, not generic 403/Failed.
    message = (
        f"The namespace's managed identity is not authorized to read the linked resource '{target}'. "
        "Grant it read access on the resource, then resubmit the request."
    )
    # LinkInitiateFailed must always use the production principal/action/scope
    # binding, never this older message-only read-authorization compatibility path.
    return error.get("code") != "LinkInitiateFailed" and error.get("message") == message


def _authorization_failure(namespace, endpoint, binding):
    """Keep the legacy read shape; share the production linkInitiate classifier."""
    properties = namespace["properties"]
    if namespace.get("error") or properties.get("error"):
        return False
    # Only the canonical structured linkingError may authorize the new retry.
    # Conflicting/alternate error envelopes must not be hidden by a matching one.
    error = endpoint.get("linkingError") or {}
    if error.get("code") != "LinkInitiateFailed":
        return _read_authorization_failure(endpoint)
    if (
        endpoint.get("error") or (endpoint.get("status") or {}).get("error")
        or (endpoint.get("provisioningStatus") or {}).get("error")
    ):
        return False
    return binding.authorized_failure(endpoint)


def link_hub_with_readiness(
    scenario, command, namespace_name, resource_group, endpoint_name, expected_endpoint,
    *, timeout=HUB_LINK_READINESS_TIMEOUT, clock=None, sleeper=None,
):
    """Compatibility wrapper for owned Hub adds."""
    return link_with_readiness(
        scenario, command, namespace_name, resource_group, endpoint_name, expected_endpoint,
        link_kind="hub", timeout=timeout, clock=clock, sleeper=sleeper,
    )


def link_dps_with_readiness(
    scenario, command, namespace_name, resource_group, endpoint_name, expected_endpoint,
    *, timeout=LINK_READINESS_TIMEOUT, clock=None, sleeper=None,
):
    """Apply the same narrow authorization recovery to owned DPS adds."""
    return link_with_readiness(
        scenario, command, namespace_name, resource_group, endpoint_name, expected_endpoint,
        link_kind="dps", timeout=timeout, clock=clock, sleeper=sleeper,
    )


def link_with_readiness(
    scenario, command, namespace_name, resource_group, endpoint_name, expected_endpoint,
    *, link_kind, timeout=LINK_READINESS_TIMEOUT, clock=None, sleeper=None,
):
    """Submit once, then recover only a persisted terminal authorization failure.

    Only owned Hub/messaging and DPS/provisioning adds are supported, never SU.
    Recovery uses the existing identity-preserving update/preflight. After an
    accepted update, stale Failed reads cannot trigger another write: observe
    progress first, or Succeeded. All CLI/read errors propagate unchanged.
    """
    assert link_kind in _OWNED_LINK_TYPES, "Readiness recovery supports only owned Hub/DPS adds"
    section, endpoint_type = _OWNED_LINK_TYPES[link_kind]
    tokens = shlex.split(command)
    if tokens and tokens[0] == "az":
        tokens = tokens[1:]
    assert tokens[:6] == ["iot", "adr", "ns", "link", link_kind, "add"], "Expected a matching owned link add"
    label = "Hub" if link_kind == "hub" else "DPS"
    budget = _Deadline(timeout, clock, sleeper, f"owned {label} link readiness")
    show = "iot adr ns show " + shlex.join(["-n", namespace_name, "-g", resource_group])
    expected = deepcopy(expected_endpoint)
    expected["endpointType"] = endpoint_type
    original = budget.call(scenario.cmd, show).get_output_in_json()
    namespace_id = original.get("id")
    expected_path = f"/resourceGroups/{resource_group}/providers/Microsoft.DeviceRegistry/namespaces/{namespace_name}"
    assert isinstance(namespace_id, str) and namespace_id.casefold().endswith(expected_path.casefold()), (
        "Namespace snapshot does not match the intended link scope"
    )
    # Use only LinkRecovery's pure classifier/snapshot, never its mutation loop:
    # this scenario deliberately exercises no-wait submission and GET readiness.
    binding = LinkRecovery(
        provider=None, namespace=original, section=section, name=endpoint_name,
        expected=expected, budget=None, verify=None,
        authorization_request={
            "link_type": link_kind, "namespace_scope": namespace_id,
            "target_scope": expected["resourceId"],
            "namespace_principal_id": resolve_namespace_outbound_principal(original),
        },
    )
    budget.call(scenario.cmd, command + " --no-wait")
    expected = _endpoint_settings(expected)
    progressed = True  # The initial add is never replayed.
    retries = 0
    retry_at = None
    while True:
        namespace = budget.call(scenario.cmd, show).get_output_in_json()
        assert _namespace_identity(namespace) == binding.namespace_identity, (
            "Namespace resource or configured outbound identity changed; recovery stopped"
        )
        properties = namespace["properties"]
        ns_state = properties.get("provisioningState")
        endpoint = (properties.get(section) or {}).get("endpoints", {}).get(endpoint_name)
        state = _link_state(endpoint) if endpoint else None
        budget.observation = f"namespace={ns_state!r}, endpoint={state!r}, recovery updates={retries}"
        detail = ADRProvider._extract_failure_detail(namespace)
        if detail:
            budget.observation += f"; {detail}"
        others = [
            other
            for other_section in ("messaging", "provisioning", "updating")
            for name, other in (properties.get(other_section) or {}).get("endpoints", {}).items()
            if (other_section, name) != (section, endpoint_name)
        ]
        if any(_link_state(other) in {"Failed", "Canceled", "Cancelled"} for other in others):
            raise AssertionError("Non-recoverable failure on another namespace endpoint")
        if endpoint:
            assert _endpoint_settings(endpoint) == expected, (
                f"{label} endpoint target, identity or provisioning settings changed"
            )
        if ns_state == "Succeeded" and state == "Succeeded":
            _log(LogKind.RESULT, "%s link namespace and endpoint both Succeeded after %d recovery updates", label, retries)
            return {"name": endpoint_name, **endpoint}
        if ns_state in _ACTIVE_STATES or state in _ACTIVE_STATES:
            progressed = True
            retry_at = None
        elif any(_link_state(other) in _ACTIVE_STATES for other in others):
            retry_at = None
        elif ns_state == "Failed" and state == "Failed" and _authorization_failure(namespace, endpoint, binding):
            if progressed:
                if retry_at is None:
                    retry_at = budget.clock() + min(10 * (retries + 1), 30)
                if budget.clock() >= retry_at:
                    recovery = failed_link_recovery_commands({
                        "id": namespace["id"],
                        "properties": {section: {"endpoints": {endpoint_name: endpoint}}},
                    })
                    assert len(recovery) == 1, f"Cannot safely recover the persisted {label} endpoint"
                    budget.call(scenario.cmd, recovery[0] + " --no-wait")
                    retries += 1
                    progressed = False
                    retry_at = None
        elif ns_state in {"Failed", "Canceled", "Cancelled"} or state in {"Failed", "Canceled", "Cancelled"}:
            raise AssertionError(f"Non-recoverable {label} link failure: {budget.observation}")
        budget.pause(10)
