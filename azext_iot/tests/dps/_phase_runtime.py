# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Process-local safeguards used only by receipt-enabled DPS integration workers."""

from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
import inspect
import json
import os
import shlex
import signal
import sys
from time import monotonic, sleep
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from azure.core.exceptions import HttpResponseError
from azure.core.pipeline.policies import RetryPolicy
from azure.core.pipeline.transport import HttpTransport, RequestsTransport
from filelock import FileLock, Timeout as LockTimeout

from azext_iot.tests.dps import _phase_receipts as receipts
from azext_iot.tests.dps import _phase

ARM_HOST = "centraluseuap.management.azure.com"
_WRITE = ContextVar("owned_dps_fixture_write", default=None)
_COMMAND = ContextVar("dps_cli_command_writes", default=None)
_FENCE = "_dps_arm_write_fence"
_READ_ACTIONS = {"listkeys", "checknameavailability", "checkprovisioningservicenameavailability"}


class ScopeError(RuntimeError):
    """Refuse an out-of-scope call or a replay before it reaches the transport."""


def require_linux():
    if sys.platform != "linux":
        raise pytest.UsageError("Isolated DPS phase orchestration requires Linux for bounded owned-process cleanup.")


@contextmanager
def owned_write(name, method):
    record = receipts._owned(name)  # pylint: disable=protected-access
    state = {"path": record["id"].lower(), "method": method, "sent": False} if record else None
    token = _WRITE.set(state)
    try:
        yield
    finally:
        _WRITE.reset(token)


def _matches(request, state):
    return state and request.method == state["method"] and urlsplit(request.url).path.lower() == state["path"]


def _is_write(request):
    return request.method in ("PUT", "PATCH", "DELETE") or (
        request.method == "POST" and urlsplit(request.url).path.lower().rsplit("/", 1)[-1] not in _READ_ACTIONS
    )


def _require_owned_path(path):
    config = receipts.settings()
    if config:
        directory, uid, subscription, _ = config
        for receipt in directory.glob("owned-*.json"):
            record = json.loads(receipt.read_text(encoding="utf-8"))
            owned = record["id"].lower()
            if (record.get("run_uid") == uid and record.get("subscription") == subscription
                    and (path.lower() == owned or path.lower().startswith(owned + "/"))):
                return
    raise ScopeError("ARM mutation requires an owned resource or child scope in this phase's receipts.")


class OwnedRetryPolicy(RetryPolicy):
    def send(self, request):
        if _is_write(request.http_request):
            _require_owned_path(urlsplit(request.http_request.url).path)
            # A new PipelineContext is created for each SDK operation. Keeping
            # the fence on that context also catches policies above RetryPolicy
            # that re-enter it. A later deliberate operation has a fresh context.
            fence = request.context.setdefault(_FENCE, {"sent": False, "receipt": uuid4().hex})
            request.context.options[_FENCE] = fence
            request.context.options.update(retry_total=0, retry_connect=0, retry_read=0, retry_status=0)
        return super().send(request)


class ScopedTransport(HttpTransport):
    def __init__(self, inner, subscription, authorization=False):
        self.inner = inner
        self.subscription = subscription
        self.authorization = authorization

    def open(self):
        self.inner.open()

    def close(self):
        self.inner.close()

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        self.inner.__exit__(*args)

    def sleep(self, duration):
        self.inner.sleep(duration)

    def send(self, request, **kwargs):
        fence = kwargs.pop(_FENCE, None)
        url = urlsplit(request.url)
        if (url.scheme != "https" or url.netloc != ARM_HOST
                or not url.path.lower().startswith(f"/subscriptions/{self.subscription}/".lower())):
            raise ScopeError("Orchestrated DPS management requests require the explicit subscription and canary ARM.")
        if request.method == "POST" and url.path.lower().endswith("/register"):
            raise ScopeError("Orchestrated DPS fixtures must not register resource providers.")
        if _is_write(request):
            _require_owned_path(url.path)
            if self.authorization and "/providers/microsoft.authorization/roleassignments/" not in url.path.lower():
                raise ScopeError("Orchestrated RBAC writes are limited to owned-scope role assignments.")
            if not fence or fence["sent"]:
                raise ScopeError("Refusing missing-boundary or repeated ARM mutation transport attempt.")
            command = _COMMAND.get()
            key = (request.method, url.path.lower())
            if command is not None:
                if key in command:
                    raise ScopeError("Refusing replay of an ARM mutation within one CLI command.")
                command.add(key)
            fence["sent"] = True
        state = _WRITE.get()
        if _matches(request, state):
            if state["sent"]:
                raise ScopeError("Refusing replay of an owned fixture mutation after its first transport attempt.")
            state["sent"] = True  # Before send, including an accepted request followed by a read timeout.
        elif state and request.method in ("PUT", "PATCH", "DELETE"):
            raise ScopeError("Owned fixture mutation does not match its exact pre-create receipt.")
        if fence:
            # Include generated role-assignment IDs without recording keys,
            # tokens, request bodies, or signed URL query parameters.
            receipts.write(f"mutation-{fence['receipt']}.json", {
                "id": url.path, "method": request.method, "transport_attempted": True,
            }, exclusive=True)
        return self.inner.send(request, **kwargs)


class _RoleAssignmentPending(Exception):
    """Native duplicate fallback has an exact principal, but no visible grant."""

    def __init__(self, principal):
        super().__init__("Duplicate role assignment is not yet visible.")
        self.principal = principal


@contextmanager
def _role_assignment_create_scope(role, scope, assignee_object_id):
    """Use native list arguments, not exception frames, for duplicate readback."""
    from azure.cli.command_modules.role import custom as role_commands
    from azext_iot.tests import helpers

    with helpers.role_assignment_create_scope(assignee_object_id):
        original = role_commands.list_role_assignments

        @wraps(original)
        def list_for_duplicate(*args, **kwargs):
            duplicate = sys.exc_info()[1]
            principal = kwargs.get("assignee_object_id")
            matching = (
                isinstance(duplicate, HttpResponseError) and duplicate.status_code == 409
                and getattr(duplicate.error, "code", None) == "RoleAssignmentExists"
                and kwargs.get("role") == role and kwargs.get("scope") == scope
                and isinstance(principal, str) and principal
                and (not assignee_object_id or principal.lower() == assignee_object_id.lower())
            )
            if matching:
                kwargs.update(fill_principal_name=False, fill_role_definition_name=False)
            assignments = original(*args, **kwargs)  # Any IndexError from this operation must propagate.
            if matching and isinstance(assignments, list) and not assignments:
                raise _RoleAssignmentPending(principal) from duplicate
            return assignments

        with patch.object(role_commands, "list_role_assignments", list_for_duplicate):
            yield


def _verify_role_assignment(role, scope, assignee, principal, command, name, record, max_tries, wait, deadline):
    from azext_iot.tests import helpers

    visibility_error = None
    for attempt in range(max_tries + 1):
        # Native CLI resolves aliases and filters exact scope/role/principal.
        # Once create/readback supplies an object ID, all later reads use it.
        visibility = {"assignee_object_id": principal} if principal else {"assignee": assignee}
        assignments = helpers.get_role_assignments(
            scope=scope, role=role, fill_role_definition_name=False, fill_principal_name=False, **visibility,
        )
        if any(
            not isinstance(value.get("principalId"), str) or not value["principalId"].strip()
            for value in assignments
        ):
            raise ScopeError("Role assignment listing returned an invalid principal.")
        confirmed = next((
            value["principalId"] for value in assignments
            if not principal or value["principalId"].lower() == principal.lower()
        ), None)
        if confirmed:
            record.update(principal_id=confirmed, verified=True)
            receipts.write(name, record)
            return
        if attempt == max_tries or (wait and monotonic() >= deadline):
            break
        if not record.get("create_attempted"):
            # Durable BEFORE invoking CLI: failures, cancellation and worker
            # death must never let another worker create a new assignment GUID.
            record["create_attempted"] = True
            receipts.write(name, record)
            try:
                with _role_assignment_create_scope(role, scope, principal):
                    result = helpers.invoke_checked(helpers.cli, command, description="Owned fixture role assignment")
            except _RoleAssignmentPending as error:
                visibility_error = error
                resolved = error.principal
            else:
                resolved = (result.as_json() or {}).get("principalId")
            if resolved:
                if not isinstance(resolved, str) or (principal and resolved.lower() != principal.lower()):
                    raise ScopeError("Role assignment create returned a different principal.")
                principal = resolved
                record["principal_id"] = principal
                receipts.write(name, record)
        sleep(min(wait, max(0, deadline - monotonic())))
    raise ScopeError("Owned role assignment was not visible before its read-only verification bound.") from visibility_error


def assign_role_assignment_once(
    role, scope, assignee=None, max_tries=10, wait=10, *, assignee_object_id=None, assignee_principal_type=None,
):
    """One phase-owned logical grant attempt across workers, then read-only confirmation."""
    from azext_iot.tests import helpers
    _require_owned_path(scope)
    if max_tries < 0 or wait < 0:
        raise ValueError("Role assignment verification bounds must be nonnegative.")
    deadline = monotonic() + max_tries * wait
    command = helpers.role_assignment_create_command(
        role, scope, assignee, assignee_object_id=assignee_object_id, assignee_principal_type=assignee_principal_type,
    )
    directory, uid, subscription, _ = receipts.settings()
    # Keep alias and object-ID interfaces distinct, even for UUID-shaped aliases.
    # Fixture workers request the same account alias (or known MI object ID).
    target = {
        "phase": _phase.get_phase(), "run_uid": uid, "subscription": subscription,
        "scope": scope.lower(), "role": role.lower(),
        "target_kind": "object_id" if assignee_object_id else "alias",
        "target": (assignee_object_id or assignee).lower(),
    }
    digest = sha256(json.dumps(target, sort_keys=True).encode("utf-8")).hexdigest()
    name = f"role-grant-{digest}.json"
    destination = directory / name
    # Separate from receipts.write's atomic-file lock. All grant readers/writers
    # hold this logical-operation lock, including read-only verification.
    lock = FileLock(str(destination) + ".grant.lock")
    try:
        lock.acquire(timeout=max(0, deadline - monotonic()))
    except LockTimeout as error:
        raise ScopeError("Owned role assignment exceeded its cross-worker verification bound.") from error
    try:
        record = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else dict(
            target, create_attempted=False, verified=False,
        )
        if any(record.get(key) != value for key, value in target.items()):
            raise ScopeError("Role assignment receipt does not match this phase's exact grant.")
        if not isinstance(record.get("create_attempted"), bool) or not isinstance(record.get("verified"), bool):
            raise ScopeError("Role assignment receipt has invalid attempt/verification state.")
        record.pop("recorded_at", None)  # Let receipts.write timestamp this transition, not the previous one.
        stored_principal = record.get("principal_id")
        if "principal_id" in record and (not isinstance(stored_principal, str) or not stored_principal.strip()):
            raise ScopeError("Role assignment receipt has an invalid principal.")
        if record["verified"] and not stored_principal:
            raise ScopeError("Role assignment receipt is missing its verified principal.")
        principal = stored_principal or assignee_object_id
        if assignee_object_id and principal.lower() != assignee_object_id.lower():
            raise ScopeError("Role assignment receipt has a different principal.")
        if record.get("verified") and principal:
            return
        _verify_role_assignment(
            role, scope, assignee, principal, command, name, record, max_tries, wait, deadline,
        )
    finally:
        lock.release()


@contextmanager
def activate(subscription, existing=()):
    """Pin only this pytest process; leave shared profiles/cloud and product defaults untouched."""
    from azure.cli.core._profile import Profile
    from azure.cli.core.profiles import ResourceType
    from azure.cli.core.profiles._shared import get_client_class
    from azure.mgmt.authorization import AuthorizationManagementClient
    from azext_iot.common.embedded_cli import EmbeddedCLI
    from azext_iot.sdk.dps.mgmt import IotDpsClient
    from azext_iot.sdk.iothub.mgmt import IotHubClient

    def check(value):
        if value and value.lower() != subscription.lower():
            raise ScopeError("An orchestrated DPS command requested a different subscription.")

    original_init = EmbeddedCLI.__init__
    original_invoke = EmbeddedCLI.invoke

    def cli_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.user_subscription = subscription
        self.az_cli.data["subscription_id"] = subscription

    def invoke(self, command, subscription=None, capture_stderr=None):
        check(subscription)
        arguments = shlex.split(command)
        if arguments[:2] in (["account", "set"], ["cloud", "set"]):
            raise ScopeError("Orchestrated tests must not change the shared active subscription or cloud.")
        for index, argument in enumerate(arguments):
            if argument in ("--subscription", "-s"):
                check(arguments[index + 1])
            elif argument.startswith("--subscription="):
                check(argument.partition("=")[2])
        token = _COMMAND.set(set())
        try:
            with patch.dict(self.az_cli.data, {"subscription_id": target}):
                return original_invoke(self, command, subscription=target, capture_stderr=capture_stderr)
        finally:
            _COMMAND.reset(token)

    def profile_method(original, parameter):
        @wraps(original)
        def call(self, *args, **kwargs):
            bound = inspect.signature(original).bind(self, *args, **kwargs)
            check(bound.arguments.get(parameter))
            bound.arguments[parameter] = subscription
            return original(*bound.args, **bound.kwargs)
        return call

    resource_client = get_client_class(ResourceType.MGMT_RESOURCE_RESOURCES)

    def sdk_init(original, authorization=False, canary=False):
        @wraps(original)
        def initialize(self, *args, **kwargs):
            check(kwargs.get("subscription_id", args[1] if len(args) > 1 else None))
            if canary:
                # Route this test client, not the shared CLI cloud/profile.
                if len(args) > 2:
                    args = (*args[:2], f"https://{ARM_HOST}", *args[3:])
                else:
                    kwargs["base_url"] = f"https://{ARM_HOST}"
            kwargs["transport"] = ScopedTransport(
                kwargs.get("transport") or RequestsTransport(), subscription, authorization=authorization,
            )
            kwargs["retry_policy"] = OwnedRetryPolicy()
            original(self, *args, **kwargs)
        # Azure CLI's is_track2 uses getfullargspec, which does not unwrap
        # functools.wraps. Preserve its real constructor/credential contract.
        initialize.__signature__ = inspect.signature(original)
        return initialize

    target = subscription
    with ExitStack() as stack:
        stack.enter_context(patch.object(EmbeddedCLI, "__init__", cli_init))
        stack.enter_context(patch.object(EmbeddedCLI, "invoke", invoke))
        for instance in existing:
            stack.enter_context(patch.object(instance, "user_subscription", subscription))
            stack.enter_context(patch.dict(instance.az_cli.data, {"subscription_id": subscription}))
        for method, parameter in (
            ("get_subscription", "subscription"), ("get_raw_token", "subscription"),
            ("get_login_credentials", "subscription_id"),
        ):
            stack.enter_context(patch.object(Profile, method, profile_method(getattr(Profile, method), parameter)))
        for client in (IotDpsClient, IotHubClient, AuthorizationManagementClient, resource_client):
            stack.enter_context(patch.object(
                client, "__init__", sdk_init(
                    client.__init__, authorization=client is AuthorizationManagementClient,
                    canary=client in (AuthorizationManagementClient, resource_client),
                ),
            ))
        yield


class WorkerStop:
    """Keep tox/controller alive; pytest.exit unwinds workers before xdist tears down execnet."""

    def __init__(self, session, directory):
        self.session = session
        self.directory = directory
        self.cleaning = False

    def stop(self, _signum=None, _frame=None):
        self.session.shouldstop = "DPS phase deadline/cancellation requested fixture cleanup"
        if not self.cleaning:
            pytest.exit(self.session.shouldstop, returncode=2)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self):
        self.cleaning = True
        try:
            yield
        finally:
            self.cleaning = False

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_sessionfinish(self):
        self.cleaning = True
        yield


def start_worker(session):
    config = receipts.settings()
    if not config or (not hasattr(session.config, "workerinput") and _phase.get_phase() != _phase.LOCAL_AUTH_TOGGLE):
        return
    require_linux()
    directory = config[0]
    plugin = WorkerStop(session, directory)
    session.config.pluginmanager.register(plugin, "dps-worker-stop")
    stop_signal = signal.Signals["SIGUSR1"]
    previous = signal.signal(stop_signal, plugin.stop)
    session.config.add_cleanup(lambda: signal.signal(stop_signal, previous))
    receipts.write(f"worker-{os.getpid()}.json", {
        "pid": os.getpid(), "parent_pid": os.getppid(), "ready": True,
    }, exclusive=True)
    if (directory / "stop-requested.json").exists():
        plugin.stop()
