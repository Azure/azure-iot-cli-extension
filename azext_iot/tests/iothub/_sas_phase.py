# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Opt-in, serial ownership boundary for the Hub local-auth and preview cases."""

import json
import logging
import os
import re
import threading
import signal
import sys
import traceback
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from azure.cli.core.azclierror import AzCLIError
from azure.core.exceptions import HttpResponseError
from msrestazure.azure_exceptions import CloudError

from azext_iot.tests._dps_phase_runner import Redactor
from azext_iot.tests.iothub._integration_helpers import is_not_found


ENV = "azext_iot_hub_auth_phase"
UID = uuid4().hex
ROOT = "azext_iot/tests/iothub/"
MESSAGING = ROOT + "core/test_iot_messaging_int.py::TestIoTHubMessaging::"
NODES = (
    ROOT + "core/test_iothub_storage_int.py::TestIoTStorage::test_device_upload_file",
    MESSAGING + "test_device_messaging",
    MESSAGING + "test_pyamqp_device_messaging",
    MESSAGING + "test_hub_monitor_events",
    MESSAGING + "test_hub_monitor_feedback",
    ROOT + "messaging/test_iothub_c2d_messages_int.py::TestIoTHubC2DMessages::test_iothub_c2d_messages_http",
    ROOT + "devices/test_hub_preview_int.py::TestHubPreview::test_identity_roundtrip",
    ROOT + "devices/test_hub_preview_int.py::TestHubPreview::test_responding_digital_twin",
)
AUTH_TYPES = ("key", "login", "cstring")
PINS = ("azext_iot_testhub", "azext_iot_teststorageaccount", "azext_iot_teststoragecontainer")
ACTIVE = None


class HubSasError(RuntimeError):
    """A phase prerequisite or owned operation failed."""


class HubSasCleanupTimeout(BaseException):
    """Escape SDK/CLI and per-resource error handlers at the hard deadline."""


def enabled():
    phase = os.getenv(ENV, "regular")
    if phase not in ("regular", "local-auth"):
        raise pytest.UsageError(f"{ENV} must be regular or local-auth.")
    return phase == "local-auth"


def require_runtime():
    if ACTIVE is None:
        raise HubSasError("HubSAS must use its validated eight-node pytest entry point.")
    return ACTIVE


def sanitize(text, redactor=None):
    # Reuse the existing integration stream filter, including multiline private keys.
    redactor = redactor or Redactor()
    text = "".join(redactor.line(line) for line in str(text).splitlines(keepends=True))
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL omitted]", text)
    return re.sub(r"(?i)\bBearer\s+[^\s\"'<>]+", "Bearer ***", text)


def validate_selection(config):
    if tuple(arg.removeprefix("./") for arg in config.args) != NODES:
        raise pytest.UsageError("HubSAS requires exactly its eight node arguments, with upload first.")
    if (
        config.getoption("numprocesses", default=None) not in (None, 0)
        or config.getoption("keyword", default="")
        or config.getoption("markexpr", default="")
        or config.getoption("deselect", default=[])
        or config.getoption("capture", default="fd") != "fd"
        or config.getoption("showlocals", default=False)
        or config.getoption("log_cli_level", default=None)
        or config.getini("log_cli")
    ):
        raise pytest.UsageError("HubSAS requires serial, unfiltered, captured execution without locals/live logging.")
    if any(os.getenv(pin) for pin in PINS):
        raise pytest.UsageError("HubSAS cannot borrow externally pinned resources.")
    if config.getoption("reruns", default=0):
        raise pytest.UsageError("HubSAS does not permit scenario reruns.")


def require_posix_timers():
    alarm = getattr(signal, "SIGALRM", None)
    timer = getattr(signal, "ITIMER_REAL", None)
    get_timer = getattr(signal, "getitimer", None)
    set_timer = getattr(signal, "setitimer", None)
    if (
        sys.platform not in ("linux", "darwin") or alarm is None or timer is None
        or not callable(get_timer) or not callable(set_timer)
        or threading.current_thread() is not threading.main_thread()
    ):
        raise pytest.UsageError("HubSAS requires Linux or macOS with POSIX interval timers on the main thread.")
    return alarm, timer, get_timer, set_timer


@contextmanager
def cleanup_timeout(timeout=690):
    alarm, timer, get_timer, set_timer = require_posix_timers()

    def expired(_signum, _frame):
        raise HubSasCleanupTimeout("HubSAS final cleanup exceeded its hard deadline.")

    previous_timer = get_timer(timer)
    previous = signal.signal(alarm, expired)
    start = monotonic()
    try:
        # One shared worker drain plus resource cleanup; never extend an outer deadline.
        set_timer(timer, min(timeout, previous_timer[0] or timeout))
        yield
    finally:
        signal.signal(alarm, previous)
        remaining = max(0.0001, previous_timer[0] - (monotonic() - start)) if previous_timer[0] else 0
        set_timer(timer, remaining, previous_timer[1])


class BackgroundTasks:
    """Retain workers, surface their failures, and bound their combined cleanup."""

    def __init__(self):
        self.tasks = []

    def start(self, *, method, args, max_runs, return_handle=True, interval=2):
        stop = threading.Event()
        errors = []

        def run():
            try:
                for _ in range(max_runs):
                    if stop.wait(interval):
                        return
                    method(**args)
            except BaseException as error:  # A worker failure must reach the owning test.
                errors.append(type(error).__name__ + ": " + sanitize(str(error)))

        thread = threading.Thread(target=run, daemon=True)
        self.tasks.append((stop, thread, errors))
        thread.start()
        return (stop, thread) if return_handle else stop

    def finish(self, timeout=90):
        deadline = monotonic() + timeout
        for stop, _, _ in self.tasks:
            stop.set()
        for _, thread, _ in self.tasks:
            thread.join(max(0, deadline - monotonic()))
        if any(thread.is_alive() for _, thread, _ in self.tasks):
            raise HubSasError("A background device task did not stop; owned resources must not be deleted yet.")
        errors = [error for _, _, failures in self.tasks for error in failures]
        self.tasks.clear()
        if errors:
            raise HubSasError("Background device task failed: " + ", ".join(errors))


class HubSasPhase:
    def __init__(self, config, hub, storage, group, location):
        self.config = config
        self.hub, self.storage, self.group, self.location = hub, storage, group, location
        self.subscription = os.getenv("azext_iot_hubsas_subscription", "").strip()
        if not self.subscription or location != "centraluseuap":
            raise pytest.UsageError("HubSAS requires an explicit subscription and centraluseuap.")
        prefix = f"/subscriptions/{self.subscription}/resourceGroups/{group}/providers/"
        self.ids = {
            "hub": prefix + "Microsoft.Devices/IotHubs/" + hub,
            "storage": prefix + "Microsoft.Storage/storageAccounts/" + storage,
        }
        self.ids["container"] = self.ids["storage"] + "/blobServices/default/containers/devices"
        self.ids["role"] = self.ids["hub"] + "/providers/Microsoft.Authorization/roleAssignments/" + str(uuid4())
        self.allowed = {value.casefold() for value in self.ids.values()}
        self.allowed.update(
            (self.ids["hub"] + "/eventHubEndpoints/events/ConsumerGroups/" + name).casefold()
            for name in ("test1", "test2", "test3", "test4")
        )
        self.sent, self.statuses, self.absent, self.passed = set(), {}, set(), set()
        self.deleting = set()
        self.bad_report = False
        self.started = False
        self.target = None
        self.tasks = BackgroundTasks()
        self.path = Path(os.getenv("azext_iot_hubsas_receipt", "test-result/hub-sas.json"))
        if self.path.exists():
            raise pytest.UsageError("HubSAS will not overwrite a previous ownership receipt.")
        self.original_send = None
        self.original_factory = None
        self.original_get_subscription = None
        self.scoped_contexts = []
        self.cli = None
        self.hub_client = None
        self.arm_clients = {}
        self.cleanup_deadline = None
        self.cleanup_failures = {}
        self.device_ids = []
        self.write_receipt()

    def write_receipt(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "phase": "local-auth", "runUid": UID, "ids": self.ids,
            "mutations": sorted(self.sent), "statuses": self.statuses,
            "absent": sorted(self.absent), "passed": sorted(self.passed),
            "consumerGroupIds": sorted(self.allowed - {value.casefold() for value in self.ids.values()}),
            "deviceIds": self.device_ids,
            "cleanupFailures": self.cleanup_failures,
        }, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def install(self):
        import requests
        from azure.cli.core._profile import Profile
        from urllib3.util.retry import Retry

        self.original_send = requests.Session.send
        self.original_factory = logging.getLogRecordFactory()
        owner = self
        redactor, log_lock = Redactor(), threading.Lock()

        self.original_get_subscription = Profile.get_subscription

        def get_subscription(profile, subscription=None):
            # IoTOAuth requests subscription=None; scope only our CLI contexts,
            # without editing the shared profile's persisted default account.
            subscription = subscription or profile.cli_ctx.data.get("_hub_sas_subscription")
            return owner.original_get_subscription(profile, subscription)

        def records(*args, **kwargs):
            record = owner.original_factory(*args, **kwargs)
            with log_lock:
                record.msg, record.args = sanitize(record.getMessage(), redactor), ()
                if record.exc_info:
                    record.exc_text = sanitize("".join(traceback.format_exception(*record.exc_info)), redactor)
                    record.exc_info = None
                elif record.exc_text:
                    record.exc_text = sanitize(record.exc_text, redactor)
                if record.stack_info:
                    record.stack_info = sanitize(record.stack_info, redactor)
            return record

        def send(session, request, **kwargs):
            remaining = None if owner.cleanup_deadline is None else owner.cleanup_deadline - monotonic()
            if remaining is not None:
                if remaining <= 0:
                    raise HubSasError("HubSAS cleanup deadline exhausted.")
                kwargs["timeout"] = min(30, remaining)
            parsed = urlsplit(request.url)
            path = parsed.path.rstrip("/").casefold()
            arm = parsed.hostname in ("management.azure.com", "centraluseuap.management.azure.com")
            container = parsed.hostname == owner.storage + ".blob.core.windows.net" and parsed.path == "/devices"
            if arm and request.method == "POST":
                key_read = path.endswith("/listkeys") and any(
                    path.startswith(owner.ids[kind].casefold() + "/") for kind in ("hub", "storage")
                )
                name_read = path.endswith("/checknameavailability") and json.loads(request.body).get("name") in (
                    owner.hub, owner.storage,
                )
                if not (key_read or name_read):
                    raise HubSasError("An unplanned ARM action, including provider registration, is not permitted.")
            mutation = request.method in ("PUT", "PATCH", "DELETE") and (arm or container)
            key = None
            if mutation:
                if arm and path not in owner.allowed:
                    raise HubSasError("ARM mutation is outside the exact HubSAS ownership manifest.")
                if request.method == "PUT" and path == owner.ids["role"].casefold():
                    role = json.loads(request.body).get("properties", {}).get("roleDefinitionId", "")
                    if not role.casefold().endswith("/4fc6c259-987e-4a07-842e-c321cc9d413f"):
                        raise HubSasError("Only the planned Hub data-role grant is permitted.")
                if request.method == "PUT" and path in (
                    owner.ids["hub"].casefold(), owner.ids["storage"].casefold(),
                ):
                    body = json.loads(request.body)
                    if body.get("location") != owner.location or body.get("tags", {}).get("runUid") != UID:
                        raise HubSasError("Resource creation does not match the phase location/ownership.")
                    if path == owner.ids["hub"].casefold() and (
                        body.get("properties", {}).get("disableLocalAuth") is not False
                        or body.get("sku", {}).get("name") != "S1"
                    ):
                        raise HubSasError("HubSAS requires exactly an S1 Hub with disableLocalAuth=false.")
                key = request.method + " " + (path if arm else owner.ids["container"].casefold())
                if key in owner.sent:
                    raise HubSasError("Repeated/uncertain HubSAS mutation transport attempt blocked.")
                owner.sent.add(key)
                owner.write_receipt()
                session.get_adapter(request.url).max_retries = Retry(total=0, redirect=0)
            response = owner.original_send(session, request, **kwargs)
            if key:
                owner.statuses[key] = response.status_code
                owner.write_receipt()
            return response

        logging.setLogRecordFactory(records)
        requests.Session.send = send
        Profile.get_subscription = get_subscription

    def restore(self):
        if self.original_send is not None:
            import requests
            requests.Session.send = self.original_send
            logging.setLogRecordFactory(self.original_factory)
        if self.original_get_subscription is not None:
            from azure.cli.core._profile import Profile
            Profile.get_subscription = self.original_get_subscription
        for context, previous in self.scoped_contexts:
            for key, (present, value) in previous.items():
                if present:
                    context.data[key] = value
                else:
                    context.data.pop(key, None)
        self.scoped_contexts.clear()

    def scope_context(self, cli_ctx):
        if not any(context is cli_ctx for context, _ in self.scoped_contexts):
            self.scoped_contexts.append((cli_ctx, {
                key: (key in cli_ctx.data, cli_ctx.data.get(key))
                for key in ("subscription_id", "_hub_sas_subscription")
            }))
        cli_ctx.data["subscription_id"] = self.subscription
        cli_ctx.data["_hub_sas_subscription"] = self.subscription
        return cli_ctx

    def get_cli(self):
        from azext_iot.common.embedded_cli import EmbeddedCLI
        if self.cli is None:
            self.cli = EmbeddedCLI()
        self.scope_context(self.cli.az_cli)
        self.cli.user_subscription = self.subscription
        return self.cli

    def hub_operations(self):
        if self.hub_client is None:
            from azext_iot._factory import iot_hub_service_factory
            self.hub_client = iot_hub_service_factory(
                self.get_cli().az_cli, subscription_id=self.subscription,
            )
        return self.hub_client.iot_hub_resource

    def arm_client(self, resource_type):
        from azure.cli.core.commands.client_factory import get_mgmt_service_client
        if resource_type not in self.arm_clients:
            self.arm_clients[resource_type] = get_mgmt_service_client(
                self.get_cli().az_cli, resource_type, subscription_id=self.subscription,
            )
        return self.arm_clients[resource_type]

    @contextmanager
    def scoped_cleanup_cli(self):
        from azext_iot.tests import helpers
        previous = helpers.cli
        helpers.cli = self.get_cli()
        try:
            yield
        finally:
            helpers.cli = previous

    def cleanup_devices(self):
        from azext_iot.tests.helpers import clean_up_iothub_device_config
        with self.scoped_cleanup_cli():
            clean_up_iothub_device_config(hub_name=self.hub, rg=self.group)

    def command(self, command, *, expect_json=True):
        result = self.get_cli().invoke(command, subscription=self.subscription, capture_stderr=True)
        if not result.success():
            error = result.get_error()
            if error:
                raise error
            raise HubSasError(f"HubSAS command failed with exit code {result.error_code}.")
        return result.as_json() if expect_json else None

    def read(self, kind):
        from azure.cli.core.profiles import ResourceType
        # Keep native ARM wire names (including properties/provisioningState)
        # across both legacy and TypeSpec-generated Storage/Authorization models.
        options = {"cls": lambda response, _model, _headers: json.loads(response.http_response.text())}
        if kind == "hub":
            operation = self.hub_operations().get
            options = {"resource_group_name": self.group, "resource_name": self.hub}
        elif kind in ("storage", "container"):
            client = self.arm_client(ResourceType.MGMT_STORAGE)
            options.update(resource_group_name=self.group, account_name=self.storage)
            if kind == "storage":
                operation = client.storage_accounts.get_properties
            else:
                operation = client.blob_containers.get
                options["container_name"] = "devices"
        elif kind == "role":
            operation = self.arm_client(ResourceType.MGMT_AUTHORIZATION).role_assignments.get_by_id
            options["role_assignment_id"] = self.ids["role"]
        else:
            raise HubSasError(f"Unknown owned resource kind: {kind}")
        native_response = None

        def observe_response(response):
            nonlocal native_response
            native_response = response.http_response

        options["raw_response_hook"] = observe_response
        # Factories and eager credential acquisition remain outside this catch.
        # CLI show wrappers may turn a native 404 into SystemExit, not an ARM error.
        try:
            return operation(**options)
        except HttpResponseError as error:
            # Lazy token acquisition can also raise HTTP404 during pipeline.run.
            # Only the response from this resource GET proves absence.
            if error.status_code == 404 and error.response is not None and error.response is native_response:
                return None
            raise

    def provision(self, scenario):
        if self.config.getoption("collectonly") or os.getenv("AZURE_TEST_RUN_LIVE", "").casefold() != "true":
            raise HubSasError("HubSAS collection/offline execution must not provision resources.")
        if self.target is not None:
            return self.target
        if self.started:
            raise HubSasError("The first HubSAS setup failed; resource creation will not be replayed.")
        self.started = True
        if scenario._testMethodName != "test_device_upload_file":  # pylint: disable=protected-access
            raise HubSasError("File-upload setup must create the cohort first.")
        if any(self.read(kind) is not None for kind in self.ids):
            raise HubSasError("A planned HubSAS ID already exists; refusing adoption or cleanup.")
        self.command(
            f"storage account create -n {self.storage} -g {self.group} --location {self.location} "
            f"--allow-shared-key-access true --tags runUid={UID} authPhase=local-auth"
        )
        from azext_iot.tests.helpers import create_storage_account
        scenario.storage_account_name, scenario.storage_container = self.storage, "devices"
        scenario.storage_cstring = create_storage_account(
            scenario.cmd, self.storage, "devices", self.group, self.hub, create_account=False,
        )
        scenario._create_hub()  # pylint: disable=protected-access
        target = self.read("hub")
        if not target or target["properties"].get("disableLocalAuth") is not False:
            raise HubSasError("HubSAS creation did not return the required local-auth setting.")
        account = self.command("account show")
        name = account["user"]["name"]
        if not name:
            raise HubSasError("A caller principal is required for the owned Hub data role.")
        self.command(
            f'role assignment create --assignee "{name}" --role "IoT Hub Data Contributor" '
            f'--scope "{self.ids["hub"]}" --name {self.ids["role"].rsplit("/", 1)[1]}'
        )
        for _ in range(10):
            sleep(10)
            if self.read("role") is not None:
                sleep(120)
                self.target = target
                return target
        raise HubSasError("The owned Hub data role was not visible after ten reads.")

    def cleanup(self, timeout=600):
        self.tasks.finish()
        if not self.sent:
            return
        deadline = monotonic() + timeout
        self.cleanup_deadline = deadline
        pending = ["role", "hub", "storage", "container"]
        errors = {}
        while pending and monotonic() < deadline:
            # A missing, possibly accepted Hub create must not consume the
            # Storage cleanup budget. Submit eligible deletes before polling.
            for kind in pending[:]:
                try:
                    if self.cleanup_one(kind, deadline):
                        pending.remove(kind)
                except Exception as error:  # Finish other owned cleanup, then propagate every failure.
                    errors[kind] = error
                    pending.remove(kind)
            if pending and monotonic() < deadline:
                sleep(min(5, deadline - monotonic()))
        for kind in pending:
            errors[kind] = HubSasError(f"Owned {kind} cleanup was not confirmed within the cleanup budget.")
        self.cleanup_failures = {
            kind: type(error).__name__ + ": " + sanitize(str(error)) for kind, error in errors.items()
        }
        self.write_receipt()
        if len(errors) == 1:
            raise next(iter(errors.values()))
        if errors:
            raise HubSasError("Owned cleanup failures: " + json.dumps(self.cleanup_failures)) from next(iter(errors.values()))

    def cleanup_one(self, kind, deadline):
        resource_id = self.ids[kind].casefold()
        delete_key = "DELETE " + resource_id
        create_key = "PUT " + resource_id
        commands = {
            "role": f'role assignment delete --ids "{self.ids["role"]}"',
            "storage": f"storage account delete -n {self.storage} -g {self.group} -y",
        }
        if monotonic() >= deadline:
            raise HubSasError(f"Owned {kind} cleanup was not confirmed within the cleanup budget.")
        resource = self.read(kind)
        if resource is None:
            status = self.statuses.get(create_key)
            uncertain = (
                create_key in self.sent and delete_key not in self.sent
                and resource_id not in self.deleting
                and (status is None or status < 400 or status in (408, 429) or status >= 500)
                and not (kind == "container" and "storage" in self.absent)
                and not (kind == "role" and "hub" in self.absent)
            )
            if not uncertain:
                self.absent.add(kind)
                self.write_receipt()
                return True
        elif kind != "container":
            if resource.get("id", "").casefold() != resource_id or (
                kind in ("hub", "storage") and resource.get("tags", {}).get("runUid") != UID
            ):
                raise HubSasError("Cleanup resource ownership does not match this cohort.")
            properties = resource.get("properties", {})
            deleting = any(
                str(properties.get(field, "")).casefold() == "deleting"
                for field in ("state", "provisioningState")
            )
            if deleting:
                self.deleting.add(resource_id)
            if not deleting and delete_key not in self.sent:
                operations = self.hub_operations() if kind == "hub" else None
                try:
                    if kind == "hub":
                        # Both generated branch SDKs explicitly support polling=False.
                        # Resource GETs below observe completion; never resubmit DELETE.
                        operations.begin_delete(
                            resource_group_name=self.group, resource_name=self.hub, polling=False, retry_total=0,
                        )
                    else:
                        # Successful DELETE commands can have no output. GETs
                        # below, not a response body, prove resource absence.
                        self.command(commands[kind], expect_json=False)
                except (AzCLIError, HttpResponseError, CloudError) as error:
                    if not is_not_found(error):
                        raise
        return False

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items):
        if tuple(item.nodeid for item in items) != NODES:
            raise pytest.UsageError("HubSAS collection changed the exact required node order.")

    def pytest_collection_finish(self, session):
        self.pytest_collection_modifyitems(session.items)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self):
        outcome = yield
        report = outcome.get_result()
        if report.failed or report.skipped:
            self.bad_report = True
        if report.longrepr is not None:
            report.longrepr = sanitize(report.longreprtext)
        report.sections = [(name, sanitize(content)) for name, content in report.sections]
        report.user_properties = [(name, sanitize(value)) for name, value in report.user_properties]
        if report.when == "call" and report.passed:
            self.passed.add(report.nodeid)
            self.write_receipt()

    def pytest_sessionfinish(self, session):
        if self.config.getoption("collectonly"):
            return
        with cleanup_timeout():
            try:
                self.cleanup()
            except (Exception, HubSasCleanupTimeout) as error:  # Sanitize failures only at the owning session boundary.
                session.exitstatus = pytest.ExitCode.TESTS_FAILED
                reporter = self.config.pluginmanager.getplugin("terminalreporter")
                if reporter:
                    reporter.write_line(
                        "HubSAS cleanup failed: " + sanitize("".join(traceback.format_exception(error))), red=True,
                    )
        self.check_results(session)

    def check_results(self, session):
        required = {"PUT " + resource_id.casefold() for resource_id in self.ids.values()}
        if (
            self.bad_report or self.passed != set(NODES) or self.absent != set(self.ids)
            or not required.issubset(self.sent)
        ):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_unconfigure(self):
        self.restore()
