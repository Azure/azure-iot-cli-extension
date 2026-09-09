# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared helpers for ADR integration tests that require Azure infrastructure."""

import re
import sys
import time
from typing import Callable, Dict, Optional, TypeVar

from azext_iot.tests.adr._log import (  # noqa: F401 - re-exported for back-compat
    LogKind,
    _fmt_duration,
    _log,
    timed_step,
)
from azext_iot.tests.adr.conftest import RoleAssignmentHelper, TEST_LOCATION


ROLE_PROPAGATION_DELAY = 30
RESOURCE_POLL_INTERVAL = 10
RESOURCE_MAX_POLLS = 30
RESOURCE_POLL_TIMEOUT = RESOURCE_POLL_INTERVAL * RESOURCE_MAX_POLLS
MATERIALIZATION_POLL_INTERVAL = 10
MATERIALIZATION_POLL_TIMEOUT = 120
RESOURCE_RETRYABLE_STATUS_CODES = {
    404,
    408,
    409,
    429,
    500,
    502,
    503,
    504,
}
RESOURCE_RETRYABLE_ERROR = re.compile(
    r"ResourceNotFound|ParentResourceNotFound|"
    r"RequestTimeout|TooManyRequests|Conflict|"
    r"InternalServerError|BadGateway|ServiceUnavailable|GatewayTimeout|"
    r"\b(408|409|429|500|502|503|504)\b",
    re.IGNORECASE,
)
RESOURCE_NOT_FOUND_ERROR = re.compile(
    r"ResourceNotFound|ParentResourceNotFound|could not be found|\b404\b",
    re.IGNORECASE,
)
T = TypeVar("T")


class CleanupLedger:
    """Run registered cleanup callbacks in reverse dependency order."""

    def __init__(self):
        self._actions = []

    def __enter__(self):
        return self

    def register(self, label: str, cleanup: Callable[[], None]) -> None:
        self._actions.append((label, cleanup))

    def dismiss(self, label: str) -> None:
        self._actions = [
            action for action in self._actions if action[0] != label
        ]

    def cleanup(self) -> list:
        failures = []
        while self._actions:
            label, cleanup = self._actions.pop()
            try:
                cleanup()
            except Exception as error:  # noqa: BLE001 - report all cleanup errors
                failures.append((label, error))
                _log(LogKind.WARN, "Cleanup failed for %s: %s", label, error)
            else:
                _log(LogKind.RESULT, "Cleanup completed for %s", label)
        return failures

    def __exit__(self, exception_type, _exception, _traceback):
        failures = self.cleanup()
        if failures and exception_type is None:
            detail = ", ".join(
                f"{label}: {error}" for label, error in failures
            )
            raise AssertionError(f"ADR cleanup failed: {detail}")
        return False


def is_retryable_resource_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(
            getattr(error, "response", None), "status_code", None
        )
    return (
        status_code in RESOURCE_RETRYABLE_STATUS_CODES
        or RESOURCE_RETRYABLE_ERROR.search(str(error)) is not None
    )


def is_resource_not_found_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        status_code = getattr(
            getattr(error, "response", None), "status_code", None
        )
    return (
        status_code == 404
        or RESOURCE_NOT_FOUND_ERROR.search(str(error)) is not None
    )


def wait_for_condition(
    fetch: Callable[[], T],
    is_success: Callable[[T], bool],
    *,
    description: str,
    is_terminal_failure: Optional[Callable[[T], bool]] = None,
    timeout: Optional[float] = RESOURCE_POLL_TIMEOUT,
    interval: float = RESOURCE_POLL_INTERVAL,
    max_attempts: Optional[int] = None,
    describe: Optional[Callable[[T], str]] = None,
    is_retryable_error: Callable[[Exception], bool] = is_retryable_resource_error,
    clock: Optional[Callable[[], float]] = None,
    sleeper: Optional[Callable[[float], None]] = None,
) -> T:
    """Poll a bounded condition and report its final sanitized observation."""
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    deadline = None if timeout is None else clock() + timeout
    attempts = 0
    last_value = None
    last_error = None

    while True:
        attempts += 1
        try:
            value = fetch()
        except Exception as error:  # noqa: BLE001 - retryability is explicit
            if not is_retryable_error(error):
                raise
            last_error = error
        else:
            last_value = value
            last_error = None
            if is_success(value):
                return value
            if is_terminal_failure and is_terminal_failure(value):
                detail = describe(value) if describe else type(value).__name__
                raise AssertionError(
                    f"{description} reached a terminal failure after "
                    f"{attempts} attempt(s) ({detail})."
                )

        attempts_exhausted = (
            max_attempts is not None and attempts >= max_attempts
        )
        time_exhausted = deadline is not None and clock() >= deadline
        if attempts_exhausted or time_exhausted:
            if last_error is not None:
                detail = f"last error: {last_error}"
            elif last_value is not None:
                observation = (
                    describe(last_value)
                    if describe
                    else type(last_value).__name__
                )
                detail = f"last observation: {observation}"
            else:
                detail = "no observation"
            raise AssertionError(
                f"Timed out waiting for {description} after {attempts} "
                f"attempt(s) ({detail})."
            )

        sleep_for = interval
        if deadline is not None:
            sleep_for = min(interval, max(0, deadline - clock()))
        sleeper(sleep_for)


def wait_for_resource_succeeded(
    test,
    show_command: str,
    *,
    max_polls: int = RESOURCE_MAX_POLLS,
    poll_interval: int = RESOURCE_POLL_INTERVAL,
) -> dict:
    """Poll an ADR resource until provisioning succeeds or fails."""
    def fetch():
        return test.cmd(show_command).get_output_in_json()

    def state(resource):
        return (resource.get("properties") or {}).get("provisioningState")

    return wait_for_condition(
        fetch,
        lambda resource: state(resource) == "Succeeded",
        description="resource provisioningState 'Succeeded'",
        is_terminal_failure=lambda resource: state(resource)
        in {"Failed", "Canceled", "Cancelled"},
        timeout=None,
        interval=poll_interval,
        max_attempts=max_polls,
        describe=lambda resource: f"provisioningState={state(resource)!r}",
    )


def wait_for_materialized_resources(
    test,
    list_command: str,
    *,
    description: str,
    timeout: float = MATERIALIZATION_POLL_TIMEOUT,
    interval: float = MATERIALIZATION_POLL_INTERVAL,
) -> list:
    """Wait for a backend-materialized child collection to become non-empty."""
    return wait_for_condition(
        lambda: test.cmd(list_command).get_output_in_json(),
        bool,
        description=description,
        timeout=timeout,
        interval=interval,
        describe=lambda resources: f"materialized count={len(resources or [])}",
    )


class ADRFullInfraHelper(RoleAssignmentHelper):
    """Setup and teardown for tests linking an ADR namespace to an IoT Hub."""

    def setup_full_infra(
        self,
        resource_group: str,
        namespace_name: str,
        hub_name: str,
        identity_name: str,
        assign_setup_roles: bool = True,
    ) -> Dict[str, str]:
        """Create UAMI, ADR namespace, and a standalone IoT Hub."""
        with timed_step("Setup 1/5 > Create UAMI"):
            uami_cmd = (
                f"identity create -n {identity_name} -g {resource_group} "
                f"--location {TEST_LOCATION}"
            )
            _log(LogKind.CMD, "az %s", uami_cmd)
            identity = self.cmd(uami_cmd).get_output_in_json()
            identity_resource_id = identity["id"]
            identity_principal_id = identity["principalId"]
            _log(LogKind.RESULT, "principalId=%s", identity_principal_id)

            _log(LogKind.CMD, "az account show")
            subscription_id = self.cmd("account show").get_output_in_json()["id"]
            _log(LogKind.RESULT, "subscription=%s", subscription_id)

        if assign_setup_roles:
            with timed_step("Setup 2/5 > RBAC: Hub RP Contributor"):
                self.assign_hub_rp_contributor_role(
                    subscription_id, resource_group
                )

        with timed_step("Setup 3/5 > Create ADR Namespace"):
            ns_cmd = (
                f"iot adr ns create -n {namespace_name} -g {resource_group} "
                f"--location {TEST_LOCATION} "
                f"--outbound-user-assigned-mi {identity_resource_id}"
            )
            _log(LogKind.CMD, "az %s", ns_cmd)
            namespace = self.cmd(ns_cmd).get_output_in_json()
            adr_resource_id = namespace["id"]
            assert namespace["properties"]["provisioningState"] == "Succeeded"
            _log(
                LogKind.RESULT,
                "id=%s, identity=%s",
                adr_resource_id,
                namespace.get("identity", {}).get("type"),
            )

        if assign_setup_roles:
            with timed_step("Setup 4/5 > RBAC: ADR Roles for UAMI"):
                self.assign_adr_roles_to_identity(
                    identity_principal_id, adr_resource_id
                )

        with timed_step(
            "Setup 5/5 > Create Standard IoT Hub (may take 3-5 min)"
        ):
            hub_cmd = (
                f"iot hub create -n {hub_name} -g {resource_group} "
                f"--sku S1 --location {TEST_LOCATION} "
                f"--user-assigned-mi {identity_resource_id} "
                "--disable-local-auth true"
            )
            _log(LogKind.CMD, "az %s", hub_cmd)
            _log(
                LogKind.WARN,
                "Hub provisioning in progress - this is the slowest step ...",
            )
            hub = self.cmd(hub_cmd).get_output_in_json()
            assert hub["properties"]["state"] == "Active"
            _log(LogKind.RESULT, "Hub state=Active")

            hub_show_cmd = (
                f"iot hub show -n {hub_name} -g {resource_group}"
            )
            _log(LogKind.CMD, "az %s", hub_show_cmd)
            self.cmd(hub_show_cmd).get_output_in_json()
            _log(
                LogKind.RESULT,
                "Standard Hub created independently; namespace links are added "
                "only through az iot adr ns link.",
            )

        _log(
            LogKind.WARN,
            "Waiting %ds for role/hub propagation ...",
            ROLE_PROPAGATION_DELAY,
        )
        time.sleep(ROLE_PROPAGATION_DELAY)

        return {
            "subscription_id": subscription_id,
            "identity_resource_id": identity_resource_id,
            "identity_principal_id": identity_principal_id,
            "adr_resource_id": adr_resource_id,
            "hub_name": hub_name,
        }

    def cleanup_namespace(
        self, namespace_name: str, resource_group: str
    ) -> None:
        """Delete just the ADR namespace."""
        with timed_step("Cleanup > Delete Namespace"):
            cleanup_cmd = (
                f"iot adr ns delete -n {namespace_name} "
                f"-g {resource_group} -y"
            )
            _log(LogKind.CMD, "az %s", cleanup_cmd)
            try:
                self.cmd(cleanup_cmd)
                _log(LogKind.RESULT, "ok")
            except Exception as error:  # noqa: BLE001 - cleanup is best-effort
                _log(LogKind.WARN, "Cleanup failed: %s", error)

    def cleanup_full_infra(
        self,
        resource_group: str,
        hub_name: Optional[str] = None,
        namespace_name: Optional[str] = None,
        identity_name: Optional[str] = None,
        dps_name: Optional[str] = None,
        linked_endpoints: Optional[list] = None,
    ) -> None:
        """Clean up linked endpoints before their namespace and identities."""
        _log(LogKind.STEP, "Cleanup > Delete All Infrastructure")
        cleanup_start = time.monotonic()
        active_error = sys.exc_info()[1]
        failures = []

        if namespace_name:
            for kind, endpoint_name in linked_endpoints or []:
                try:
                    listed = self.cmd(
                        f"iot adr ns link {kind} list "
                        f"--ns {namespace_name} -g {resource_group}"
                    ).get_output_in_json()
                except Exception as error:  # noqa: BLE001 - inspect all cleanup paths
                    if not is_resource_not_found_error(error):
                        failures.append(
                            (f"{kind} link list {endpoint_name}", error)
                        )
                    continue
                if endpoint_name not in {
                    endpoint.get("name") for endpoint in listed or []
                }:
                    continue
                command = (
                    f"iot adr ns link {kind} delete -n {endpoint_name} "
                    f"--ns {namespace_name} -g {resource_group} --yes"
                )
                _log(LogKind.CMD, "az %s", command)
                try:
                    self.cmd(command)
                    _log(
                        LogKind.RESULT,
                        "%s link and target deleted",
                        kind.upper(),
                    )
                except Exception as error:  # noqa: BLE001
                    failures.append((f"{kind} link {endpoint_name}", error))
                    _log(
                        LogKind.WARN,
                        "%s link cleanup failed: %s",
                        kind.upper(),
                        error,
                    )

        resources = [
            (
                "DPS",
                f"iot dps show --name {dps_name} -g {resource_group}"
                if dps_name
                else None,
                f"iot dps delete --name {dps_name} -g {resource_group}"
                if dps_name
                else None,
            ),
            (
                "IoT Hub",
                f"iot hub show -n {hub_name} -g {resource_group}"
                if hub_name
                else None,
                f"iot hub delete -n {hub_name} -g {resource_group}"
                if hub_name
                else None,
            ),
            (
                "ADR namespace",
                f"iot adr ns show -n {namespace_name} -g {resource_group}"
                if namespace_name
                else None,
                f"iot adr ns delete -n {namespace_name} "
                f"-g {resource_group} -y"
                if namespace_name
                else None,
            ),
            (
                "UAMI",
                f"identity show -n {identity_name} -g {resource_group}"
                if identity_name
                else None,
                f"identity delete -n {identity_name} -g {resource_group}"
                if identity_name
                else None,
            ),
        ]
        for label, show_command, command in resources:
            if command:
                try:
                    self.cmd(show_command)
                except Exception as error:  # noqa: BLE001 - inspect all cleanup paths
                    if is_resource_not_found_error(error):
                        _log(LogKind.RESULT, "%s already absent", label)
                    else:
                        failures.append((f"{label} lookup", error))
                        _log(
                            LogKind.WARN,
                            "%s cleanup lookup failed: %s",
                            label,
                            error,
                        )
                    continue
                _log(LogKind.CMD, "az %s", command)
                try:
                    self.cmd(command)
                    _log(LogKind.RESULT, "%s deleted", label)
                except Exception as error:  # noqa: BLE001
                    failures.append((label, error))
                    _log(LogKind.WARN, "%s cleanup failed: %s", label, error)
        _log(
            "_time",
            "(%s)",
            _fmt_duration(time.monotonic() - cleanup_start),
        )
        if failures and active_error is None:
            detail = ", ".join(
                f"{label}: {error}" for label, error in failures
            )
            raise AssertionError(
                f"ADR cleanup failed: {detail}"
            ) from failures[0][1]
