# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Shared helpers for ADR integration tests that require Azure infrastructure."""

import json
import re
import shlex
import sys
import time
from typing import Callable, Dict, Optional, TypeVar

from azure.cli.core.azclierror import ResourceNotFoundError as CLIResourceNotFoundError
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError as SDKResourceNotFoundError,
    ServiceRequestError,
    ServiceResponseError,
)
from knack.util import CLIError
from msrestazure.azure_exceptions import CloudError

from azext_iot.tests.adr._log import (  # noqa: F401 - re-exported for back-compat
    LogKind,
    _fmt_duration,
    _log,
    timed_step,
)
from azext_iot.tests.adr.conftest import RoleAssignmentHelper, TEST_LOCATION
from azext_iot.tests.settings import HUB_TEST_LOCATION


ROLE_PROPAGATION_DELAY = 30
RESOURCE_POLL_INTERVAL = 10
RESOURCE_MAX_POLLS = 30
RESOURCE_POLL_TIMEOUT = RESOURCE_POLL_INTERVAL * RESOURCE_MAX_POLLS
SU_PROVISIONING_MAX_POLLS = 360
SU_PROVISIONING_POLL_INTERVAL = 10
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
    r"(?:\((?:ResourceNotFound|ParentResourceNotFound|ResourceGroupNotFound)\)|"
    r"(?:ResourceNotFound|ParentResourceNotFound|ResourceGroupNotFound)(?=[:\s]))[^\n]*(?:\n.*)?|"
    r"An IotHub '[^']+' under resource group '[^']+' was not found\.",
    re.IGNORECASE | re.DOTALL,
)
RESOURCE_NOT_FOUND_CODES = {"resourcenotfound", "parentresourcenotfound", "resourcegroupnotfound", "notfound"}
HUB_NOT_FOUND_RESPONSE = re.compile(r"Not Found\((.*)\)", re.DOTALL)
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
    statuses = []
    codes = []
    seen = set()
    current = error
    while True:
        if id(current) in seen:
            return False
        if isinstance(current, (ClientAuthenticationError, ServiceRequestError, ServiceResponseError)):
            return False
        seen.add(id(current))
        response_statuses = []
        for status in (
            getattr(current, "status_code", None),
            getattr(getattr(current, "response", None), "status_code", None),
        ):
            if status is not None:
                statuses.append(status)
                response_statuses.append(status)
        if isinstance(current, CLIError):
            match = HUB_NOT_FOUND_RESPONSE.fullmatch(str(current))
            if match:
                try:
                    detail = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return False
                if not isinstance(detail, dict) or "httpStatusCode" not in detail or "code" not in detail:
                    return False
                statuses.append(detail["httpStatusCode"])
                response_statuses.append(detail["httpStatusCode"])
                codes.append(detail["code"])
        if not isinstance(current, SystemExit):
            for detail in (current, getattr(current, "error", None)):
                code = detail.get("code") if isinstance(detail, dict) else getattr(detail, "code", None)
                if code not in (None, ""):
                    codes.append(code)
        cause = current.__cause__
        # A fresh HTTP response during cleanup can have an unrelated primary
        # failure as its implicit context. Only unwrap status-less wrappers.
        if cause is None and not response_statuses and not current.__suppress_context__:
            cause = current.__context__
        if cause is None:
            break
        current = cause

    # Any contradictory status/code wins over not-found-looking message text,
    # including evidence preserved beneath a CLI wrapper.
    if any(status != 404 for status in statuses):
        return False
    for code in codes:
        if isinstance(code, str) and code.casefold() in RESOURCE_NOT_FOUND_CODES:
            continue
        # Hub ARM returns numeric IH404002; require its accompanying HTTP 404.
        if statuses and isinstance(code, (int, str)) and str(code) == "404002":
            continue
        return False
    if statuses or codes:
        return True
    if isinstance(current, (CLIResourceNotFoundError, SDKResourceNotFoundError)):
        return True
    if isinstance(current, SystemExit):
        return current.code == 3
    return isinstance(current, CLIError) and RESOURCE_NOT_FOUND_ERROR.fullmatch(str(current)) is not None


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


def wait_for_listed_resource(
    test,
    list_command: str,
    resource_name: str,
    *,
    timeout: float = MATERIALIZATION_POLL_TIMEOUT,
    interval: float = MATERIALIZATION_POLL_INTERVAL,
) -> list:
    """Wait for a newly-created resource to become visible in collection reads."""
    return wait_for_condition(
        lambda: test.cmd(list_command).get_output_in_json(),
        lambda resources: any(resource.get("name") == resource_name for resource in resources),
        description=f"resource '{resource_name}' in '{list_command}'",
        timeout=timeout,
        interval=interval,
        describe=lambda resources: f"listed count={len(resources)}; expected resource absent",
    )


class ADRFullInfraHelper(RoleAssignmentHelper):
    """Setup and teardown for tests linking an ADR namespace to an IoT Hub."""

    _RESOURCE_COMMANDS = {
        "namespace": "iot adr ns",
        "dps": "iot dps",
        "hub": "iot hub",
        "su": "iot adr ns su instance",
        "identity": "identity",
    }

    def create_owned_resource(self, command, *, kind, name, resource_group):
        """Require absence and record the attempt before creating a resource."""
        if kind not in self._RESOURCE_COMMANDS:
            raise ValueError(f"Unsupported test-owned resource kind: {kind}")
        if not self._resource_is_absent(kind, name, resource_group):
            raise AssertionError(f"Refusing to overwrite existing {kind} '{name}' in '{resource_group}'.")
        if not hasattr(self, "_owned_resources"):
            self._owned_resources = {}
        self._owned_resources[(kind, name, resource_group)] = None
        return self.cmd(command)

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
            identity = self.create_owned_resource(
                uami_cmd, kind="identity", name=identity_name, resource_group=resource_group,
            ).get_output_in_json()
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
            namespace = self.create_owned_resource(
                ns_cmd, kind="namespace", name=namespace_name, resource_group=resource_group,
            ).get_output_in_json()
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
                f"--sku S1 --location {HUB_TEST_LOCATION} "
                f"--user-assigned-mi {identity_resource_id} "
                "--disable-local-auth true"
            )
            _log(LogKind.CMD, "az %s", hub_cmd)
            _log(
                LogKind.WARN,
                "Hub provisioning in progress - this is the slowest step ...",
            )
            hub = self.create_owned_resource(
                hub_cmd, kind="hub", name=hub_name, resource_group=resource_group,
            ).get_output_in_json()
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
        """Clean up the caller's test namespace without masking its failure."""
        self._cleanup_owned_resources([("namespace", namespace_name, resource_group)])

    def _resource_is_absent(self, kind, name, resource_group):
        command = self._RESOURCE_COMMANDS[kind]
        arguments = f"-n {shlex.quote(name)} -g {shlex.quote(resource_group)}"
        try:
            self.cmd(f"{command} show {arguments}")
        except SystemExit as error:
            if error.code == 3 and is_resource_not_found_error(error):
                return True
            raise AssertionError(f"{kind} lookup exited with code {error.code}") from error
        except (HttpResponseError, CloudError, CLIError) as error:
            if not is_resource_not_found_error(error):
                raise
            return True
        return False

    def _delete_owned_resource(self, kind, name, resource_group):
        if self._resource_is_absent(kind, name, resource_group):
            return
        command = self._RESOURCE_COMMANDS[kind]
        arguments = f"-n {shlex.quote(name)} -g {shlex.quote(resource_group)}"
        confirmation = " --yes" if kind in {"namespace", "su"} else ""
        try:
            self.cmd(f"{command} delete {arguments}{confirmation}")
        except SystemExit as error:
            if error.code == 3 and is_resource_not_found_error(error):
                return
            raise AssertionError(f"{kind} delete exited with code {error.code}") from error
        except (HttpResponseError, CloudError, CLIError) as error:
            if not is_resource_not_found_error(error):
                raise

    def cleanup_full_infra(self):
        """Delete recorded namespaces before targets, and identities last.

        Links are namespace properties, not ownership records. Never discover
        targets from endpoints or delete a supplied external fixture.
        """
        resources = getattr(self, "_owned_resources", {})
        self._cleanup_owned_resources(resources)

    def _cleanup_owned_resource(self, resource):
        self._delete_owned_resource(*resource)
        self._owned_resources.pop(resource, None)

    def _cleanup_owned_resources(self, resources):
        if not hasattr(self, "_owned_resources"):
            self._owned_resources = {}
        order = {kind: index for index, kind in enumerate(self._RESOURCE_COMMANDS)}
        ledger = CleanupLedger()
        for kind, name, group in sorted(resources, key=lambda item: order[item[0]], reverse=True):
            resource = (kind, name, group)
            self._owned_resources.setdefault(resource, None)
            ledger.register(
                f"{kind} {name}",
                lambda resource=resource: self._cleanup_owned_resource(resource),
            )
        failures = ledger.cleanup()
        if failures and sys.exc_info()[0] is None:
            detail = ", ".join(f"{label}: {error}" for label, error in failures)
            raise AssertionError(f"ADR cleanup failed: {detail}") from failures[0][1]
