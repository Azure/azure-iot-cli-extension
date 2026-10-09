# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from contextlib import ExitStack
from copy import deepcopy
from shlex import split
from types import SimpleNamespace
from unittest import TestCase

import pytest
from azure.cli.core.azclierror import BadRequestError, CLIInternalError, ForbiddenError, UnauthorizedError
from azure.core.exceptions import ServiceRequestError, ServiceResponseError

from azext_iot.tests.iothub.core import test_iothub_storage_int as subject


REJECTED_MESSAGE = (
    "ErrorCode:BlobContainerValidationError;Error: 400 ErrorCode: BlobContainerValidationError\r\n"
    "Message: Unauthorized to write to output blob container.\r\n"
    "Timestamp: offline\r\nPublic Message: Unauthorized to write to output blob container."
)


def rejected_submission():
    return BadRequestError({"Message": REJECTED_MESSAGE, "ExceptionMessage": "https://storage.test/?sig=unit-secret"})


@pytest.fixture
def clock(mocker):
    state = SimpleNamespace(now=0)

    def sleep(seconds):
        state.now += seconds

    mocker.patch.object(subject, "monotonic", side_effect=lambda: state.now)
    mocker.patch.object(subject, "sleep", side_effect=sleep)
    return state


@pytest.fixture(autouse=True)
def no_network(mocker, monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "False")
    mocker.patch("requests.sessions.Session.send", side_effect=AssertionError("Offline storage regression attempted HTTP."))
    mocker.patch.object(subject.Profile, "get_raw_token", side_effect=AssertionError("Offline test requested a token."))


@pytest.fixture
def storage_scenario(mocker):
    scenario = object.__new__(subject.TestIoTStorage)
    TestCase.__init__(scenario, "test_system_identity_storage")
    scenario.entity_name = "owned-hub"
    scenario.entity_rg = "owned-rg"
    scenario.live_storage_id = "/subscriptions/unit/resourceGroups/owned-rg/providers/Microsoft.Storage/storageAccounts/owned"
    scenario.live_storage_uri = "https://owned.blob.test/devices?sig=unit-secret"
    scenario.user = {"type": "servicePrincipal"}
    scenario.managed_identity = None
    user_id = "/subscriptions/unit/resourceGroups/owned-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/owned"
    borrowed_id = user_id + "-borrowed"
    state = SimpleNamespace(
        identity={"type": None, "userAssignedIdentities": {borrowed_id: {"principalId": "borrowed-principal"}}},
        roles=[], events=[], role_reads=0, invisible_reads=0, failure=None, cleanup_failure=False,
        user_id=user_id, borrowed_id=borrowed_id, jobs={}, create_failure=False,
    )
    scenario.get_managed_identity = mocker.Mock(return_value={"id": user_id, "principalId": "user-principal"})
    scenario.check_for_running_import_export = mocker.Mock()
    scenario.wait_till_job_completion = mocker.Mock()
    scenario.check = mocker.Mock(side_effect=lambda path, value: (path, value))
    scenario.exists = mocker.Mock(side_effect=lambda path: ("exists", path))

    def invoke(command, **kwargs):
        args = split(command)
        operation = " ".join(args[:4])
        result = {}
        if args[:3] == ["role", "assignment", "list"]:
            state.role_reads += 1
            assert args[args.index("--scope") + 1] == scenario.live_storage_id
            assert args[args.index("--role") + 1] == subject.STORAGE_ROLE
            assert args[args.index("--fill-role-definition-name") + 1] == "false"
            result = [] if state.role_reads <= state.invisible_reads else deepcopy(state.roles)
        elif args[:3] == ["role", "assignment", "create"]:
            state.events.append("role.create")
            if state.create_failure:
                raise ServiceRequestError("Uncertain role create")
            assignee_flag = "--assignee" if "--assignee" in args else "--assignee-object-id"
            result = {
                "principalId": args[args.index(assignee_flag) + 1],
                "id": scenario.live_storage_id + "/providers/Microsoft.Authorization/roleAssignments/" + args[-1],
            }
            state.roles.append(result)
        elif operation == "iot hub identity show":
            result = deepcopy(state.identity)
        elif operation == "iot hub identity assign":
            state.events.append("identity.assign")
            if "--system" in args:
                state.identity.update(type="SystemAssigned,UserAssigned", principalId="system-principal")
            else:
                state.identity["userAssignedIdentities"][user_id] = {"principalId": "user-principal"}
            result = deepcopy(state.identity)
        elif operation == "iot hub identity remove":
            state.events.append("identity.remove")
            if "--system" in args:
                state.identity.pop("principalId", None)
                state.identity["type"] = "UserAssigned"
            else:
                assert args[args.index("--user") + 1] == user_id
                del state.identity["userAssignedIdentities"][user_id]
        elif operation in ("iot hub device-identity export", "iot hub device-identity import"):
            operation = args[3]
            if kwargs.get("expect_failure"):
                assert args[args.index("--identity") + 1] == "fake_managed_identity"
                state.events.append("negative")
            else:
                state.events.append(operation)
                if state.failure and state.failure[0] == operation:
                    raise state.failure[1]
                result = {"jobId": operation + "-job"}
        elif operation == "iot hub job show":
            result = state.jobs[args[-1]]
        else:
            raise AssertionError(f"Unexpected offline command shape: {args[:4]}")
        return SimpleNamespace(get_output_in_json=lambda: deepcopy(result))

    def delete_owned(command, name):
        args = split(command)
        if args[:3] == ["role", "assignment", "delete"]:
            state.events.append("role.delete")
            assert args == ["role", "assignment", "delete", "--ids", name]
            assert name.startswith(scenario.live_storage_id + "/providers/Microsoft.Authorization/roleAssignments/")
            if state.cleanup_failure:
                raise CLIInternalError("Role cleanup failed")
            state.roles[:] = [role for role in state.roles if role["id"] != name]
        else:
            state.events.append("uami.delete")
            if state.cleanup_failure:
                raise CLIInternalError("Identity cleanup failed")

    scenario.cmd = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject, "_delete_fixture_resource", side_effect=delete_owned)
    mocker.patch.object(subject, "sleep")
    mocker.patch.object(subject, "uuid4", return_value="11111111-2222-3333-4444-555555555555")
    return scenario, state


@pytest.mark.parametrize("kind", ["system", "user"])
@pytest.mark.parametrize("identity_present", [False, True])
@pytest.mark.parametrize("role_present", [False, True])
@pytest.mark.parametrize("failed_operation", [None, "export", "import"])
def test_managed_storage_preserves_borrowed_state_and_cleans_owned_state_without_replay(
    storage_scenario, kind, identity_present, role_present, failed_operation
):
    scenario, state = storage_scenario
    principal = kind + "-principal"
    if identity_present:
        if kind == "system":
            state.identity.update(type="SystemAssigned,UserAssigned", principalId=principal)
        else:
            state.identity["userAssignedIdentities"][state.user_id.upper() + "/"] = {"principalId": principal}
    if role_present:
        state.roles.append({"principalId": principal, "id": "borrowed-role"})
    original_identity = deepcopy(state.identity)
    error = BadRequestError("BlobContainerValidationError: Unauthorized to write to output blob container")
    state.failure = (failed_operation, error) if failed_operation else None

    run = getattr(subject.TestIoTStorage, f"test_{kind}_identity_storage")
    if failed_operation:
        with pytest.raises(BadRequestError) as raised:
            run(scenario)
        assert raised.value is error
    else:
        run(scenario)
    assert state.events.count("export") == 1
    assert state.events.count("import") == (0 if failed_operation == "export" else 1)
    assert state.events.count("negative") == (0 if failed_operation else 1)
    assert state.events.count("identity.assign") == (not identity_present)
    assert state.events.count("identity.remove") == (not identity_present)
    assert state.events.count("role.create") == (not role_present)
    assert state.events.count("role.delete") == (not role_present)
    assert state.roles == ([{"principalId": principal, "id": "borrowed-role"}] if role_present else [])
    assert state.borrowed_id in state.identity["userAssignedIdentities"]
    if identity_present:
        assert state.identity == original_identity
    if not identity_present and not role_present:
        assert state.events.index("role.delete") < state.events.index("identity.remove")
    expected_jobs = [] if failed_operation == "export" else ["export-job"]
    if not failed_operation:
        expected_jobs.append("import-job")
    assert [call.args[0] for call in scenario.wait_till_job_completion.call_args_list] == expected_jobs
    for call in scenario.cmd.call_args_list:
        if "device-identity" not in call.args[0] or call.kwargs.get("expect_failure"):
            continue
        args = split(call.args[0])
        assert args[args.index("--identity") + 1] == ("[system]" if kind == "system" else state.user_id)
        checks = call.kwargs["checks"]
        assert ("storageAuthenticationType", "identityBased") in checks
        assert ("outputBlobContainerUri", scenario.live_storage_uri) in checks
        assert ("failureReason", None) in checks
        assert ("type", args[3]) in checks and ("exists", "jobId") in checks
        if args[3] == "export":
            assert ("excludeKeysInExport", False) in checks
        else:
            assert ("inputBlobContainerUri", scenario.live_storage_uri) in checks


@pytest.mark.parametrize("error_type", [ForbiddenError, UnauthorizedError, ServiceRequestError, ServiceResponseError])
def test_service_or_transport_failure_is_not_retried(storage_scenario, error_type):
    scenario, state = storage_scenario
    error = error_type("Original service failure")
    state.failure = ("export", error)
    with pytest.raises(error_type) as raised:
        scenario.test_system_identity_storage()
    assert raised.value is error
    assert state.events == ["identity.assign", "role.create", "export", "role.delete", "identity.remove"]


@pytest.mark.parametrize("kind", ["system", "user"])
def test_role_cleanup_failure_still_removes_owned_attachment(storage_scenario, kind):
    scenario, state = storage_scenario
    state.cleanup_failure = True
    with pytest.raises(CLIInternalError, match="Role cleanup failed"):
        getattr(scenario, f"test_{kind}_identity_storage")()
    assert state.events[-2:] == ["role.delete", "identity.remove"]
    assert state.borrowed_id in state.identity["userAssignedIdentities"]


@pytest.mark.parametrize("user_type,assignee_flag", [("user", "--assignee"), ("servicePrincipal", "--assignee-object-id")])
@pytest.mark.parametrize("visible", [False, True])
def test_role_visibility_is_bounded_without_a_blind_settle(
    mocker, storage_scenario, user_type, assignee_flag, visible
):
    scenario, state = storage_scenario
    scenario.user["type"] = user_type
    state.invisible_reads = 3 if visible else 100
    mocker.patch.object(subject, "MAX_RBAC_ASSIGNMENT_TRIES", 3)
    if visible:
        with ExitStack() as cleanup:
            scenario.assign_storage_role_if_needed("principal", cleanup)
            assert len(state.roles) == 1
        assert subject.sleep.call_args_list == [mocker.call(10)] * 2
    else:
        with pytest.raises(CLIInternalError, match="not visible after 3 reads"):
            with ExitStack() as cleanup:
                scenario.assign_storage_role_if_needed("principal", cleanup)
        assert subject.sleep.call_args_list == [mocker.call(10)] * 2
    assert state.role_reads == 4
    assert state.events == ["role.create", "role.delete"]
    assert not state.roles
    create = next(call.args[0] for call in scenario.cmd.call_args_list if call.args[0].startswith("role assignment create"))
    assert assignee_flag in split(create)
    assert "--name 11111111-2222-3333-4444-555555555555" in create


@pytest.mark.parametrize("response", [None, {}, (), [None], [{}], [{"principalId": 1}], [{"principalId": ""}]])
def test_invalid_role_list_is_not_treated_as_absence(storage_scenario, response):
    scenario, state = storage_scenario
    scenario.cmd.side_effect = None
    scenario.cmd.return_value.get_output_in_json.return_value = response
    with pytest.raises(CLIInternalError, match="valid principal list"):
        with ExitStack() as cleanup:
            scenario.assign_storage_role_if_needed("principal", cleanup)
    assert not state.events


def test_uncertain_role_create_is_not_replayed_and_cleanup_uses_requested_id(storage_scenario):
    scenario, state = storage_scenario
    state.create_failure = True
    with pytest.raises(ServiceRequestError, match="Uncertain role create"):
        scenario.test_system_identity_storage()
    assert state.events == ["identity.assign", "role.create", "role.delete", "identity.remove"]
    assert state.role_reads == 1


def test_role_list_service_error_propagates_before_create(storage_scenario):
    scenario, state = storage_scenario
    scenario.cmd.side_effect = ForbiddenError("Role list denied")
    with pytest.raises(ForbiddenError, match="Role list denied"):
        with ExitStack() as cleanup:
            scenario.assign_storage_role_if_needed("principal", cleanup)
    assert not state.events


def test_unrelated_storage_grants_survive_owned_cleanup(storage_scenario):
    scenario, state = storage_scenario
    borrowed = {"principalId": "another-principal", "id": "borrowed-role"}
    state.roles.append(borrowed)
    scenario.test_system_identity_storage()
    assert state.roles == [borrowed]


def test_failed_job_poll_does_not_replay_export_or_bypass_cleanup(storage_scenario):
    scenario, state = storage_scenario
    scenario.wait_till_job_completion.side_effect = CLIInternalError("Job failed")
    with pytest.raises(CLIInternalError, match="Job failed"):
        scenario.test_system_identity_storage()
    assert state.events == ["identity.assign", "role.create", "export", "role.delete", "identity.remove"]


def test_unsupported_caller_type_does_not_create_a_role(storage_scenario):
    scenario, state = storage_scenario
    scenario.user["type"] = "unsupported"
    with pytest.raises(subject.CLIError, match="not supported"):
        scenario.test_system_identity_storage()
    assert state.events == ["identity.assign", "identity.remove"]


def test_created_uami_is_owned_before_the_existing_settle(storage_scenario):
    scenario, state = storage_scenario
    created = {"id": state.user_id, "principalId": "user-principal"}
    scenario.cmd.side_effect = None
    scenario.cmd.return_value.get_output_in_json.return_value = created
    subject.sleep.side_effect = RuntimeError("Interrupted settle")
    with pytest.raises(RuntimeError, match="Interrupted settle"):
        subject.TestIoTStorage.get_managed_identity(scenario)
    assert scenario.managed_identity is not None
    assert scenario.managed_identity == created


def test_uami_teardown_failure_does_not_bypass_base_cleanup(mocker, storage_scenario):
    scenario, state = storage_scenario
    scenario.managed_identity = {"id": state.user_id}
    state.cleanup_failure = True
    base_cleanup = mocker.patch.object(subject.IoTLiveScenarioTest, "tearDown")
    with pytest.raises(CLIInternalError, match="Identity cleanup failed"):
        scenario.tearDown()
    base_cleanup.assert_called_once()


def test_failed_job_diagnostics_do_not_dump_storage_credentials(storage_scenario, capsys):
    scenario, state = storage_scenario
    state.jobs["job-id"] = {"status": "failed", "outputBlobContainerUri": scenario.live_storage_uri}
    with pytest.raises(CLIInternalError, match="status is failed"):
        subject.TestIoTStorage.wait_till_job_completion(scenario, "job-id")
    output = capsys.readouterr().out
    assert "unit-secret" not in output and scenario.live_storage_uri not in output
    event = json.loads(output)
    assert event["jobId"] == "job-id" and event["jobStatus"] == "failed"
    assert event["hub"] == "owned-hub" and event["storageScope"] == scenario.live_storage_id
    assert event["time"].endswith("+00:00")


@pytest.mark.parametrize("payload", [
    "BlobContainerValidationError: Unauthorized to write to output blob container.",
    {}, {"Message": None}, {"Message": 400},
    {"Message": REJECTED_MESSAGE, "jobId": "possibly-accepted"},
    {"Message": REJECTED_MESSAGE.replace("400", "503")},
    {"Message": REJECTED_MESSAGE.replace("BlobContainerValidationError", "OtherError")},
    {"Message": REJECTED_MESSAGE.replace("write to output", "read from input")},
    {"Message": REJECTED_MESSAGE.replace("Unauthorized", "Forbidden")},
])
def test_readiness_requires_exact_structured_rejected_submission(storage_scenario, payload):
    scenario, state = storage_scenario
    error = BadRequestError(payload)
    state.failure = ("export", error)
    with pytest.raises(BadRequestError) as raised:
        scenario.test_system_identity_storage()
    assert raised.value is error
    assert state.events == ["identity.assign", "role.create", "export", "role.delete", "identity.remove"]


@pytest.mark.parametrize("kind", ["system", "user"])
@pytest.mark.parametrize("operation", ["export", "import"])
def test_rejected_storage_submission_probes_readiness_then_runs_each_job_once(
    storage_scenario, clock, kind, operation, capsys
):
    scenario, state = storage_scenario
    invoke = scenario.cmd.side_effect
    rejected = []

    def submit(command, **kwargs):
        if command.startswith(f"iot hub device-identity {operation}") and not kwargs.get("expect_failure"):
            clock.now += 2  # time spent in the RPC is part of the readiness budget
            if len(rejected) < 2:
                rejected.append(command)
                raise rejected_submission()
        return invoke(command, **kwargs)

    scenario.cmd.side_effect = submit
    getattr(scenario, f"test_{kind}_identity_storage")()
    assert len(rejected) == 2
    assert clock.now == 26
    assert state.events.count("export") == state.events.count("import") == state.events.count("negative") == 1
    assert [call.args[0] for call in scenario.wait_till_job_completion.call_args_list] == ["export-job", "import-job"]
    assert state.events[-2:] == ["role.delete", "identity.remove"] and not state.roles
    output = capsys.readouterr().out
    assert "unit-secret" not in output and scenario.live_storage_uri not in output
    events = [json.loads(line) for line in output.splitlines()]
    pending = [event for event in events if event["storageEvent"].endswith(".storage.pending")]
    assert [event["attempt"] for event in pending] == [1, 2]
    assert all(event["principalId"] == kind + "-principal" for event in pending)


@pytest.mark.parametrize("rpc_seconds,attempts,sleeps", [(8, 1, []), (6, 1, [1]), (1, 3, [2, 2])])
def test_readiness_timeout_includes_rpc_time_and_surfaces_permanent_rejection(
    mocker, storage_scenario, clock, rpc_seconds, attempts, sleeps, capsys
):
    scenario, state = storage_scenario
    invoke = scenario.cmd.side_effect
    rejected = []
    mocker.patch.object(subject, "IDENTITY_READINESS_TIMEOUT", 7)
    mocker.patch.object(subject, "SETUP_SLEEP_INTERVAL", 2)

    def submit(command, **kwargs):
        if command.startswith("iot hub device-identity export"):
            rejected.append(command)
            clock.now += rpc_seconds
            raise rejected_submission()
        return invoke(command, **kwargs)

    scenario.cmd.side_effect = submit
    with pytest.raises(CLIInternalError, match="submission deadline") as raised:
        scenario.test_system_identity_storage()
    assert raised.value.__suppress_context__
    assert "unit-secret" not in str(raised.value) and "unit-secret" not in capsys.readouterr().out
    assert len(rejected) == attempts
    assert [call.args[0] for call in subject.sleep.call_args_list] == sleeps
    assert not state.roles and state.events[-2:] == ["role.delete", "identity.remove"]
    scenario.wait_till_job_completion.assert_not_called()
    assert "import" not in state.events and "negative" not in state.events


@pytest.mark.parametrize("failure", ["parse", "missing-id", "check", "job"])
def test_accepted_or_uncertain_job_is_never_resubmitted(mocker, storage_scenario, clock, failure):
    scenario, state = storage_scenario
    result = SimpleNamespace(get_output_in_json=mocker.Mock(return_value={}))
    if failure == "parse":
        result.get_output_in_json.side_effect = rejected_submission()
    if failure == "check":
        scenario.cmd.side_effect = AssertionError("Job checks failed after acceptance")
    else:
        scenario.cmd.side_effect = None
        scenario.cmd.return_value = result
    if failure == "job":
        result.get_output_in_json.return_value = {"jobId": "accepted-job"}
        scenario.wait_till_job_completion.side_effect = rejected_submission()
    error = {"parse": BadRequestError, "missing-id": KeyError, "check": AssertionError, "job": BadRequestError}[failure]
    with pytest.raises(error):
        job_id = scenario._submit_identity_job("job submission", [], "principal", "export")
        scenario.wait_till_job_completion(job_id)
    scenario.cmd.assert_called_once()
    subject.sleep.assert_not_called()
    assert not state.events


def test_slow_accepted_submission_is_not_replayed_at_deadline(storage_scenario, clock):
    scenario, _ = storage_scenario

    def submit(*_args, **_kwargs):
        clock.now += subject.IDENTITY_READINESS_TIMEOUT + 1
        return SimpleNamespace(get_output_in_json=lambda: {"jobId": "accepted-job"})

    scenario.cmd.side_effect = submit
    assert scenario._submit_identity_job("submission", [], "principal", "export") == "accepted-job"
    scenario.cmd.assert_called_once()
    subject.sleep.assert_not_called()
