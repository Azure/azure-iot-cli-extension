# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command-specific wait conditions for Azure Device Registry resources."""

from dataclasses import dataclass
from time import sleep
from typing import Callable, Optional

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError as CLIResourceNotFoundError,
)
from azure.cli.core.commands.arm import verify_property
from azure.cli.core.commands.progress import IndeterminateProgressBar
from azure.cli.core.util import todict
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError
from msrest.exceptions import ClientException

from azext_iot.adr.common import (
    DPS_ENDPOINT_TYPE,
    IOT_HUB_ENDPOINT_TYPE,
    SU_ENDPOINT_TYPE,
)
from azext_iot.adr.topology import endpoint_is_type, get_endpoints

DEFAULT_WAIT_TIMEOUT = 3600
DEFAULT_WAIT_INTERVAL = 30


@dataclass(frozen=True)
class WaitEvaluation:
    """Result of evaluating a command-specific default wait condition."""

    complete: bool
    failure: Optional[str] = None
    observation: Optional[str] = None


def _property(resource, name):
    body = todict(resource)
    return (body.get("properties") or {}).get(name)


def provisioning_succeeded(resource) -> WaitEvaluation:
    """Wait for an ARM resource's provisioning state to succeed."""
    state = _property(resource, "provisioningState")
    normalized = str(state or "").casefold()
    if normalized in {"failed", "canceled"}:
        return WaitEvaluation(
            False,
            f"The resource reached terminal provisioningState '{state}'.",
            f"provisioningState={state!r}",
        )
    return WaitEvaluation(
        normalized == "succeeded",
        observation=f"provisioningState={state!r}",
    )


def resource_exists(_resource) -> WaitEvaluation:
    """A successful GET is the terminal condition for materialized resources."""
    return WaitEvaluation(True, observation="resource exists")


def group_membership_ready(resource) -> WaitEvaluation:
    """Wait for a group membership refresh to finish."""
    state = _property(resource, "membershipState")
    normalized = str(state or "").casefold()
    if normalized == "failedtoresolvemembers":
        return WaitEvaluation(
            False,
            "The group membership refresh failed "
            "(membershipState='FailedToResolveMembers').",
            f"membershipState={state!r}",
        )
    return WaitEvaluation(
        normalized == "ready",
        observation=f"membershipState={state!r}",
    )


def job_run_succeeded(resource) -> WaitEvaluation:
    """Wait for a job run to complete successfully."""
    state = _property(resource, "status")
    normalized = str(state or "").casefold()
    if normalized in {"failed", "canceled", "timedout"}:
        return WaitEvaluation(
            False,
            f"The job run reached terminal status '{state}' instead of 'Succeeded'.",
            f"status={state!r}",
        )
    return WaitEvaluation(
        normalized == "succeeded",
        observation=f"status={state!r}",
    )


def _link_state(endpoint):
    provisioning_status = endpoint.get("provisioningStatus") or {}
    return endpoint.get("linkingState") or (
        provisioning_status.get("status")
        if isinstance(provisioning_status, dict)
        else None
    )


def _link_failure(label: str, endpoint: dict, state) -> str:
    error = endpoint.get("linkingError") or endpoint.get("error") or {}
    if not isinstance(error, dict):
        error = {}
    message = error.get("message")
    result = f"{label} reached terminal linkingState '{state}'."
    if message:
        result += f" {message}"
    return result


def link_succeeded(resource, label: Optional[str] = None) -> WaitEvaluation:
    """Wait for one projected namespace endpoint to link successfully."""
    endpoint = todict(resource)
    state = _link_state(endpoint)
    normalized = str(state or "").casefold()
    label = label or f"Link '{endpoint.get('name') or '<unknown>'}'"
    if normalized == "failed":
        return WaitEvaluation(
            False,
            _link_failure(label, endpoint, state),
            f"linkingState={state!r}",
        )
    return WaitEvaluation(
        normalized == "succeeded",
        observation=f"linkingState={state!r}",
    )


_LINK_SECTIONS = (
    ("hub", "messaging", IOT_HUB_ENDPOINT_TYPE),
    ("dps", "provisioning", DPS_ENDPOINT_TYPE),
    ("su", "updating", SU_ENDPOINT_TYPE),
)


def namespace_links_succeeded(
    resource,
    *,
    hub_endpoint_name: Optional[str] = None,
    dps_endpoint_name: Optional[str] = None,
    su_endpoint_name: Optional[str] = None,
) -> WaitEvaluation:
    """Evaluate explicitly scoped links, or every known link when no name is given."""
    namespace = todict(resource)
    requested = {
        "hub": hub_endpoint_name,
        "dps": dps_endpoint_name,
        "su": su_endpoint_name,
    }
    explicitly_scoped = any(requested.values())
    selected = []
    missing = []

    for kind, section, endpoint_type in _LINK_SECTIONS:
        endpoints = get_endpoints(namespace, section)
        endpoint_name = requested[kind]
        if endpoint_name:
            endpoint = endpoints.get(endpoint_name)
            label = f"{kind.upper()} link '{endpoint_name}'"
            if endpoint is None:
                missing.append(label)
                continue
            if not endpoint_is_type(endpoint, endpoint_type):
                actual_type = (
                    endpoint.get("endpointType")
                    if isinstance(endpoint, dict)
                    else None
                )
                return WaitEvaluation(
                    False,
                    f"{label} exists but has endpointType "
                    f"'{actual_type}', not '{endpoint_type}'.",
                )
            selected.append((label, endpoint))
        elif not explicitly_scoped:
            selected.extend(
                (f"{kind.upper()} link '{name}'", endpoint)
                for name, endpoint in endpoints.items()
                if endpoint_is_type(endpoint, endpoint_type)
            )

    if missing:
        return WaitEvaluation(
            False,
            observation="not materialized: " + ", ".join(missing),
        )
    if not selected:
        return WaitEvaluation(False, observation="no namespace links found")

    pending = []
    for label, endpoint in selected:
        state = _link_state(endpoint)
        evaluation = link_succeeded(endpoint, label=label)
        if evaluation.failure:
            return WaitEvaluation(
                False,
                evaluation.failure,
                f"{label} linkingState={state!r}",
            )
        if not evaluation.complete:
            pending.append(f"{label}={state or 'unknown'}")
    return WaitEvaluation(
        not pending,
        observation=", ".join(pending) if pending else "all selected links succeeded",
    )


def _get_provisioning_state(resource):
    body = todict(resource)
    state = body.get("provisioning_state", body.get("provisioningState"))
    if state:
        return state
    properties = body.get("properties") or {}
    state = properties.get(
        "provisioning_state", properties.get("provisioningState")
    )
    if state:
        return state
    additional = properties.get(
        "additional_properties", properties.get("additionalProperties", {})
    )
    return additional.get(
        "provisioning_state", additional.get("provisioningState")
    )


def _explicit_condition(
    resource,
    *,
    created: bool,
    updated: bool,
    exists: bool,
    custom: Optional[str],
) -> bool:
    if exists:
        return True
    state = _get_provisioning_state(resource)
    if str(state or "").casefold() == "failed":
        raise AzureResponseError("The operation failed.")
    return bool(
        ((created or updated) and str(state or "").casefold() == "succeeded")
        or (custom and verify_property(resource, custom))
    )


def _is_not_found(error: Exception) -> bool:
    return isinstance(error, CLIResourceNotFoundError) or getattr(
        error, "status_code", None
    ) == 404


def wait_for_resource(
    cli_ctx,
    getter: Callable[[], object],
    default_condition: Callable[[object], WaitEvaluation],
    *,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
    created: bool = False,
    updated: bool = False,
    deleted: bool = False,
    exists: bool = False,
    custom: Optional[str] = None,
    sleeper: Callable[[float], None] = sleep,
):
    """Poll a getter using Azure CLI wait flags or a command-specific default."""
    if timeout <= 0:
        raise InvalidArgumentValueError("--timeout must be greater than zero.")
    if interval <= 0:
        raise InvalidArgumentValueError("--interval must be greater than zero.")

    explicit = any((created, updated, deleted, exists, custom))
    progress = IndeterminateProgressBar(cli_ctx, message="Waiting")
    progress.begin()
    last_observation = None
    try:
        for _ in range(0, timeout, interval):
            try:
                progress.update_progress()
                resource = getter()
                if explicit:
                    if _explicit_condition(
                        resource,
                        created=created,
                        updated=updated,
                        exists=exists,
                        custom=custom,
                    ):
                        progress.end()
                        return None
                else:
                    evaluation = default_condition(resource)
                    last_observation = evaluation.observation
                    if evaluation.failure:
                        raise AzureResponseError(evaluation.failure)
                    if evaluation.complete:
                        progress.end()
                        return None
            except (
                ClientException,
                HttpResponseError,
                CLIResourceNotFoundError,
            ) as error:
                if not _is_not_found(error):
                    raise
                if deleted:
                    progress.end()
                    return None
                if explicit and updated and not any((created, exists, custom)):
                    raise
                last_observation = "resource not found"
            sleeper(interval)
    except Exception:
        progress.stop()
        raise

    progress.end()
    suffix = f" Last observation: {last_observation}." if last_observation else ""
    raise CLIError(f"Wait operation timed out after {timeout} seconds.{suffix}")
