# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline regression coverage for job integration-test orchestration."""

from io import StringIO
import shlex
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core import MainCommandsLoader
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, ResourceNotFoundError
from azure.cli.core.mock import DummyCli
from azure.core.exceptions import HttpResponseError, ResourceExistsError
from knack.util import CLIError

from azext_iot import IoTExtCommandsLoader
from azext_iot.adr import (
    commands_group, commands_job, commands_job_run, commands_namespace, commands_su, commands_wait,
)
from azext_iot.adr.providers.wait import wait_for_resource
from azext_iot.tests.adr import test_adr_job_run_int as runs
from azext_iot.tests.adr import test_adr_job_int as jobs
from azext_iot.tests.adr._helpers import CleanupLedger


SCOPE = "--ns namespace -g rg --jn job --rn run"
NAMESPACE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/"
    "providers/Microsoft.DeviceRegistry/namespaces/namespace"
)
TARGET_ID = NAMESPACE_ID + "/groups/group"
INSTANCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/"
    "providers/Microsoft.DeviceUpdate/updateInstances/instance"
)


def _run(status, provisioning="Succeeded", error=None):
    return {
        "name": "run",
        "properties": {"status": status, "provisioningState": provisioning, "error": error},
    }


class _OfflineJobLoader(MainCommandsLoader):
    def load_command_table(self, args):
        loader = IoTExtCommandsLoader(self.cli_ctx)
        self.command_table = {
            name: command for name, command in loader.load_command_table(args).items()
            if name.startswith("iot adr ns")
        }
        self.cmd_to_loader_map = {name: [loader] for name in self.command_table}
        return self.command_table


class _CliScenario:
    """Use the real extension parser/handlers with isolated config and providers."""

    def __init__(self):
        self.cli = DummyCli(commands_loader_cls=_OfflineJobLoader)
        self.commands = []

    def cmd(self, command, expect_failure=False):
        self.commands.append(command)
        code = self.cli.invoke(shlex.split(command), out_file=StringIO())
        if expect_failure:
            assert code != 0, command
        elif code:
            raise self.cli.result.error
        return SimpleNamespace(get_output_in_json=lambda: self.cli.result.result)


@pytest.fixture
def cli_scenario(mocker, monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_CORE_COLLECT_TELEMETRY", "false")
    network = mocker.patch(
        "requests.sessions.Session.request",
        side_effect=AssertionError("offline scenario attempted network I/O"),
    )
    mocker.patch("azure.cli.core._profile.Profile.get_subscription", return_value={
        "id": "00000000-0000-0000-0000-000000000000", "name": "offline",
        "environmentName": "AzureCloud",
    })
    mocker.patch("azure.cli.core._profile.Profile.get_login_credentials", return_value=(
        Mock(), "00000000-0000-0000-0000-000000000000", "offline-tenant",
    ))
    provider = mocker.patch.object(commands_job_run, "JobRunProvider").return_value
    mocker.patch.object(commands_wait, "JobRunProvider", return_value=provider)
    mocker.patch.object(commands_job, "JobRunProvider", return_value=provider)
    mocker.patch("azext_iot.adr.providers.wait.IndeterminateProgressBar")
    # Keep the real wait evaluator/timeout budget without sleeping offline.
    mocker.patch.object(commands_wait, "wait_for_resource", side_effect=lambda *args, **kwargs: (
        wait_for_resource(*args, **kwargs, sleeper=lambda _: None)
    ))
    scenario = _CliScenario()
    yield scenario, provider
    network.assert_not_called()


@pytest.fixture
def resources(mocker):
    namespace = mocker.patch.object(commands_namespace, "NamespaceProvider").return_value
    group = mocker.patch.object(commands_group, "GroupProvider").return_value
    job = mocker.patch.object(commands_job, "JobProvider").return_value
    mocker.patch.object(commands_wait, "JobProvider", return_value=job)
    instance = mocker.patch.object(commands_su, "UpdateInstanceProvider").return_value
    update = mocker.patch.object(commands_su, "SoftwareUpdateProvider").return_value
    namespace.show.return_value = {
        "id": NAMESPACE_ID,
        "properties": {
            "provisioningState": "Succeeded",
            "updating": {"endpoints": {"su": {
                "endpointType": runs.SU_ENDPOINT_TYPE,
                "linkingState": "Succeeded", "resourceId": INSTANCE_ID,
                "serviceAddress": "instance.api.adu.microsoft.com",
            }}},
        },
    }
    job.show.return_value = {
        "name": "job", "properties": {
            "provisioningState": "Succeeded", "jobType": "SoftwareUpdate",
            "description": "Integration rollout",
            "target": {"resourceId": TARGET_ID},
            "definition": {
                "schedulingType": "Continuous",
                "updateResourceId": "updates/providers/Contoso/names/gateway-firmware/versions/1.2.3",
            },
        },
    }
    instance.show.return_value = {"id": INSTANCE_ID, "properties": {"provisioningState": "Succeeded"}}
    update.show_update.return_value = {
        "updateId": {"provider": "Contoso", "name": "gateway-firmware", "version": "1.2.3"},
    }
    group.show.return_value = {"properties": {"membershipState": "Ready"}}
    for provider in (namespace, group, job):
        provider.create.return_value = {}
        provider.delete.return_value = None
    return SimpleNamespace(namespace=namespace, group=group, job=job, instance=instance, update=update)


@pytest.fixture
def namespace_cleanup_clock(mocker):
    now = [0]
    wait = runs.wait_for_condition

    def sleep(delay):
        now[0] += delay

    mocker.patch.object(runs, "wait_for_condition", side_effect=lambda *args, **kwargs: wait(
        *args, **kwargs, clock=lambda: now[0], sleeper=sleep,
    ))
    return now


def _namespace_delete_error(code="CannotDeleteResource"):
    error = ResourceExistsError(message=f"{code}: nested resource index")
    error.status_code = 409
    error.error = SimpleNamespace(code=code, message=str(error), target=None, details=[])
    return error


def test_namespace_cleanup_retries_only_verified_empty_child_index(
    cli_scenario, resources, namespace_cleanup_clock,
):
    scenario, provider = cli_scenario
    resources.namespace.delete.side_effect = [_namespace_delete_error(), None]
    resources.job.list.return_value = []
    resources.group.list.return_value = []

    runs._delete_test_namespace(scenario, "namespace", "rg")

    assert resources.namespace.delete.call_count == 2
    resources.job.list.assert_called_once()
    resources.group.list.assert_called_once()
    assert namespace_cleanup_clock == [10]
    provider.cancel.assert_not_called()
    resources.job.delete.assert_not_called()
    resources.group.delete.assert_not_called()


@pytest.mark.parametrize("child_kind", ["job", "group"])
def test_namespace_cleanup_does_not_retry_with_remaining_children(cli_scenario, resources, child_kind):
    scenario, _ = cli_scenario
    error = _namespace_delete_error()
    resources.namespace.delete.side_effect = error
    resources.job.list.return_value = []
    resources.group.list.return_value = []
    getattr(resources, child_kind).list.return_value = [{"name": "remaining-child"}]

    with pytest.raises(HttpResponseError) as raised:
        runs._delete_test_namespace(scenario, "namespace", "rg")
    assert raised.value is error
    resources.namespace.delete.assert_called_once()


@pytest.mark.parametrize("code", ["Conflict", "AuthorizationFailed", "ResourceNotFound"])
def test_namespace_cleanup_does_not_retry_other_errors(cli_scenario, resources, code):
    scenario, _ = cli_scenario
    error = _namespace_delete_error(code)
    resources.namespace.delete.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        runs._delete_test_namespace(scenario, "namespace", "rg")
    assert raised.value is error
    resources.namespace.delete.assert_called_once()
    resources.job.list.assert_not_called()
    resources.group.list.assert_not_called()


def test_namespace_cleanup_stale_index_has_bounded_deadline(cli_scenario, resources, namespace_cleanup_clock):
    scenario, _ = cli_scenario
    resources.namespace.delete.side_effect = _namespace_delete_error()
    resources.job.list.return_value = []
    resources.group.list.return_value = []

    with pytest.raises(AssertionError, match="CannotDeleteResource despite empty job/group lists"):
        runs._delete_test_namespace(scenario, "namespace", "rg")
    assert namespace_cleanup_clock == [120]
    assert resources.namespace.delete.call_count == 13


def test_namespace_cleanup_child_lookup_error_is_not_ignored(cli_scenario, resources):
    scenario, _ = cli_scenario
    resources.namespace.delete.side_effect = _namespace_delete_error()
    resources.job.list.side_effect = AzureResponseError("child lookup denied")

    with pytest.raises(AzureResponseError, match="child lookup denied"):
        runs._delete_test_namespace(scenario, "namespace", "rg")
    resources.namespace.delete.assert_called_once()
    resources.group.list.assert_not_called()


def test_active_cancel_polls_execution_not_arm_provisioning(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.side_effect = [
        _run("Active"), _run("Active"), _run("Canceled"), _run("Canceled"),
    ]
    provider.cancel.return_value = None

    runs._cancel_active_run(scenario, SCOPE)

    assert provider.show.call_count == 4
    provider.cancel.assert_called_once_with(
        job_name="job", run_name="run", namespace_name="namespace",
        resource_group_name="rg", no_wait=True,
    )
    assert "--timeout 120 --interval 10" in scenario.commands[2]


@pytest.mark.parametrize("status", ["Scheduled", "Succeeded", "Failed", "TimedOut", "Canceled", None, "Unknown"])
def test_cancel_rejects_non_active_runs(cli_scenario, status):
    scenario, provider = cli_scenario
    provider.show.return_value = _run(status)
    with pytest.raises(AssertionError):
        runs._cancel_active_run(scenario, SCOPE)
    provider.cancel.assert_not_called()


@pytest.mark.parametrize("provisioning,error", [
    ("Creating", None), ("Failed", None), ("Succeeded", {"code": "AduEndpointNotLinked"}),
])
def test_cancel_requires_healthy_active_resource(cli_scenario, provisioning, error):
    scenario, provider = cli_scenario
    provider.show.return_value = _run("Active", provisioning, error)
    with pytest.raises(AssertionError):
        runs._cancel_active_run(scenario, SCOPE)
    provider.cancel.assert_not_called()


@pytest.mark.parametrize("status", ["Succeeded", "Failed", "TimedOut"])
def test_cancel_http_success_does_not_prove_canceled(cli_scenario, status):
    scenario, provider = cli_scenario
    provider.show.side_effect = [_run("Active"), _run(status), _run(status)]
    provider.cancel.return_value = None
    with pytest.raises(AssertionError, match=status):
        runs._cancel_active_run(scenario, SCOPE)
    provider.cancel.assert_called_once()


def test_cancel_racing_conflict_is_not_retried(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.return_value = _run("Active")
    # begin_cancel maps HTTP 409 to ResourceExistsError in the generated SDK.
    error = ResourceExistsError(message="Conflict: concurrent modification")
    error.status_code = 409
    provider.cancel.side_effect = error
    with pytest.raises(HttpResponseError, match="Conflict") as raised:
        runs._cancel_active_run(scenario, SCOPE)
    assert raised.value is error
    provider.cancel.assert_called_once()
    assert len(scenario.commands) == 2


def test_cancel_deadline_does_not_accept_still_active(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.return_value = _run("Active")
    provider.cancel.return_value = None
    with pytest.raises(CLIError, match="timed out after 120 seconds"):
        runs._cancel_active_run(scenario, SCOPE)
    provider.cancel.assert_called_once()
    assert provider.show.call_count == 13


def test_cancel_final_show_must_still_be_canceled(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.side_effect = [_run("Active"), _run("Canceled"), _run("Failed")]
    with pytest.raises(AssertionError, match="Failed"):
        runs._cancel_active_run(scenario, SCOPE)


@pytest.mark.parametrize("status", ["Scheduled", "Succeeded", "Failed", "TimedOut", "Canceled"])
def test_cleanup_deletes_only_scheduled_or_terminal_without_cancel(cli_scenario, status):
    scenario, provider = cli_scenario
    provider.show.return_value = _run(status)
    provider.delete.return_value = None
    runs._delete_test_run(scenario, SCOPE)
    provider.cancel.assert_not_called()
    provider.delete.assert_called_once()


def test_cleanup_waits_for_failed_execution_without_cancel(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.side_effect = [_run("Active"), _run("Failed"), _run("Failed")]
    provider.delete.return_value = None
    runs._delete_test_run(scenario, SCOPE)
    assert provider.show.call_count == 3
    provider.cancel.assert_not_called()
    provider.delete.assert_called_once()


def test_cleanup_does_not_delete_still_active_run(cli_scenario):
    scenario, provider = cli_scenario
    provider.show.return_value = _run("Active")
    with pytest.raises(CLIError, match="timed out"):
        runs._delete_test_run(scenario, SCOPE)
    provider.delete.assert_not_called()
    provider.cancel.assert_not_called()


@pytest.mark.parametrize("original_failure", [False, True])
def test_cleanup_callbacks_are_independent_and_preserve_failure(cli_scenario, original_failure):
    scenario, provider = cli_scenario
    provider.show.return_value = _run("Failed")
    provider.delete.side_effect = AzureResponseError("run deletion failed")
    job_cleanup, group_cleanup, namespace_cleanup = Mock(), Mock(), Mock()
    message = "original assertion" if original_failure else "ADR cleanup failed"
    with pytest.raises(AssertionError, match=message):
        with CleanupLedger() as cleanup:
            cleanup.register("namespace", namespace_cleanup)
            cleanup.register("group", group_cleanup)
            cleanup.register("job", job_cleanup)
            cleanup.register("run", lambda: runs._delete_test_run(scenario, SCOPE))
            if original_failure:
                raise AssertionError("original assertion")
    for callback in (job_cleanup, group_cleanup, namespace_cleanup):
        callback.assert_called_once()
    provider.cancel.assert_not_called()


def test_preprovisioned_positive_checks_prerequisites_and_final_canceled(cli_scenario, resources, monkeypatch):
    scenario, provider = cli_scenario
    monkeypatch.setattr(runs, "_PREPROVISIONED_RUN", dict(zip(
        runs._PREPROVISIONED_RUN_ENV_VARS, ("rg", "namespace", "job", "run", TARGET_ID),
    )))
    provider.show.return_value = _run("Active")
    provider.summary.return_value = {"total": 1}
    provider.results.return_value = []

    def cancel(**_kwargs):
        provider.show.return_value = _run("Canceled")
    provider.cancel.side_effect = cancel

    runs.TestADRJobRunSurface.test_adr_preprovisioned_job_run_positive(scenario)

    resources.instance.show.assert_called_once()
    resources.update.show_update.assert_called_once_with(
        namespace_name="namespace", resource_group_name="rg",
        update_provider="Contoso", update_name="gateway-firmware", update_version="1.2.3",
    )
    provider.cancel.assert_called_once()
    provider.delete.assert_not_called()
    assert scenario.commands[-1].startswith("iot adr ns job run show ")


def test_preprovisioned_empty_target_does_not_cancel(cli_scenario, resources, monkeypatch):
    scenario, provider = cli_scenario
    monkeypatch.setattr(runs, "_PREPROVISIONED_RUN", dict(zip(
        runs._PREPROVISIONED_RUN_ENV_VARS, ("rg", "namespace", "job", "run", TARGET_ID),
    )))
    provider.show.return_value = _run("Active")
    provider.summary.return_value = {"total": 0}
    with pytest.raises(AssertionError, match="actual test targets"):
        runs.TestADRJobRunSurface.test_adr_preprovisioned_job_run_positive(scenario)
    resources.update.show_update.assert_called_once()
    provider.cancel.assert_not_called()


@pytest.mark.parametrize("missing", [
    "namespace", "link", "link_state", "service_address", "instance",
    "update", "target", "group", "onboarding",
])
def test_preflight_blocks_unready_or_wrong_fixture(cli_scenario, resources, missing):
    scenario, provider = cli_scenario
    namespace = resources.namespace.show.return_value["properties"]
    link = namespace["updating"]["endpoints"]["su"]
    if missing == "namespace":
        namespace["provisioningState"] = "Creating"
    elif missing == "link":
        namespace["updating"]["endpoints"] = {}
    elif missing == "link_state":
        link["linkingState"] = "Failed"
    elif missing == "service_address":
        link["serviceAddress"] = ""
    elif missing == "instance":
        resources.instance.show.return_value["properties"]["provisioningState"] = "Creating"
    elif missing == "update":
        resources.update.show_update.side_effect = ResourceNotFoundError("update not imported")
    elif missing == "target":
        resources.job.show.return_value["properties"]["target"]["resourceId"] = TARGET_ID + "-other"
    elif missing == "group":
        resources.group.show.return_value["properties"]["membershipState"] = "Resolving"
    elif missing == "onboarding":
        resources.job.show.return_value["properties"]["jobType"] = "OnboardingUpdate"
    with pytest.raises((AssertionError, ResourceNotFoundError)):
        runs._assert_software_update_fixture_ready(
            scenario, "--namespace namespace -g rg", "job", TARGET_ID,
        )
    provider.cancel.assert_not_called()
    provider.delete.assert_not_called()


def test_missing_adu_smoke_never_cancels_owned_failed_runs(cli_scenario, resources, monkeypatch):
    scenario, provider = cli_scenario
    monkeypatch.setattr(runs, "_generate_job_name", lambda: "job")
    monkeypatch.setattr(runs, "_generate_group_name", lambda: "group")
    monkeypatch.setattr(runs, "generate_adr_namespace_name", lambda: "namespace")
    resources.namespace.show.return_value["properties"]["updating"] = {}
    owned = {}

    def create(**kwargs):
        name = kwargs["run_name"] or "run-generated"
        value = _run("Failed", error={"code": "AduEndpointNotLinked"})
        value["name"] = name
        owned[name] = value
        return value

    def show(*args, **kwargs):
        name = kwargs["run_name"] if kwargs else args[1]
        if name not in owned:
            raise ResourceNotFoundError("run not found")
        return owned[name]

    def delete(**kwargs):
        owned.pop(kwargs["run_name"])

    def list_runs(**kwargs):
        if (kwargs.get("job_name") or "").startswith("does-not-exist"):
            raise ResourceNotFoundError("job not found")
        return list(owned.values())

    def results(**kwargs):
        show(**kwargs)
        return []

    provider.create.side_effect = create
    provider.show.side_effect = show
    provider.delete.side_effect = delete
    provider.list.side_effect = list_runs
    provider.summary.return_value = {"total": 0}
    provider.results.side_effect = results
    provider.cancel.side_effect = ResourceNotFoundError("run not found")

    runs.TestADRJobRunSurface.test_adr_job_run_surface_smoke(scenario)

    assert not owned
    assert provider.create.call_count == 2
    assert provider.delete.call_count == 2
    provider.cancel.assert_called_once()
    assert provider.cancel.call_args.kwargs["run_name"].startswith("does-not-exist")
    resources.job.delete.assert_called_once()
    resources.group.delete.assert_called_once()
    resources.namespace.delete.assert_called_once()


@pytest.mark.parametrize("onboarding", [False, True])
def test_lightweight_lifecycles_schedule_in_future_without_cancel(cli_scenario, resources, monkeypatch, onboarding):
    scenario, provider = cli_scenario
    monkeypatch.setattr(jobs, "_generate_job_name", lambda: "job")
    monkeypatch.setattr(jobs, "_generate_group_name", lambda: "group")
    monkeypatch.setattr(jobs, "generate_adr_namespace_name", lambda: "namespace")
    body = deepcopy(resources.job.show.return_value)
    if onboarding:
        body["properties"]["jobType"] = "OnboardingUpdate"
        body["properties"].pop("target")
    resources.job.create.return_value = body
    resources.job.show.side_effect = [body] if onboarding else [body, ResourceNotFoundError("job deleted")]
    # Job wait has its own provider reference but shares this mock.
    if not onboarding:
        resources.job.show.side_effect = [body, body, ResourceNotFoundError("job deleted")]
    resources.job.list.return_value = [body]

    def update(**kwargs):
        if kwargs["tags"] is None:
            raise ArgumentUsageError("Nothing to update")
        return {"tags": kwargs["tags"]}
    resources.job.update.side_effect = update
    if onboarding:
        resources.job.show.side_effect = [body, body]
    scheduled = {}

    def create_run(**kwargs):
        assert kwargs["scheduled_time"]
        scheduled.update(_run("Scheduled"))
        scheduled["name"] = kwargs["run_name"] or "run-generated"
        scheduled["properties"]["scheduledTime"] = kwargs["scheduled_time"]
        return scheduled
    provider.create.side_effect = create_run
    provider.show.return_value = scheduled
    provider.delete.return_value = None
    provider.summary.return_value = {"total": 0}

    test = (
        jobs.TestADRJobLifecycle.test_adr_onboarding_update_job_lifecycle
        if onboarding else jobs.TestADRJobLifecycle.test_adr_job_lifecycle
    )
    test(scenario)

    provider.create.assert_called_once()
    provider.delete.assert_called_once()
    provider.cancel.assert_not_called()
    assert not any("link su" in command for command in scenario.commands)
    resources.job.delete.assert_called_once()
    resources.namespace.delete.assert_called_once()
