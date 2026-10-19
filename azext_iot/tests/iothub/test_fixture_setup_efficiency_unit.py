# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import CLIInternalError

from azext_iot.tests import _hub_ownership as ownership
from azext_iot.tests.iothub import conftest as fixtures
from azext_iot.tests.iothub import _integration_helpers as helpers


@pytest.mark.parametrize("existing", [(), ("first",), ("first", "second")])
@pytest.mark.parametrize("wait", [120, 180])
def test_batch_grants_keep_one_full_window_after_the_last_new_grant(mocker, existing, wait):
    granted = set(existing)
    events = []
    assignments = [
        {"role": "role", "scope": "scope", "assignee": name} for name in ("first", "second")
    ]
    mocker.patch.object(
        helpers, "get_role_assignments",
        side_effect=lambda **_: [{"principalId": name} for name in granted],
    )

    def assign(**kwargs):
        events.append(("grant", kwargs["assignee"]))
        granted.add(kwargs["assignee"])

    mocker.patch.object(helpers, "assign_role_assignment", side_effect=assign)
    mocker.patch.object(helpers, "sleep", side_effect=lambda seconds: events.append(("wait", seconds)))
    helpers.assign_roles_with_propagation(assignments=assignments, max_tries=3, wait=wait)
    expected = [("grant", name) for name in ("first", "second") if name not in existing]
    assert events == expected + ([("wait", wait)] if expected else [])


@pytest.mark.parametrize("failed", ["first", "second"])
@pytest.mark.parametrize("failure_kind", ["raise", "invisible"])
def test_failed_batch_grant_does_not_wait_or_claim_readiness(mocker, failed, failure_kind):
    granted = set()
    mocker.patch.object(
        helpers, "get_role_assignments",
        side_effect=lambda **_: [{"principalId": name} for name in granted],
    )

    def assign(**kwargs):
        if kwargs["assignee"] == failed:
            if failure_kind == "raise":
                raise CLIInternalError("Grant rejected")
            return
        granted.add(kwargs["assignee"])

    create = mocker.patch.object(helpers, "assign_role_assignment", side_effect=assign)
    sleep = mocker.patch.object(helpers, "sleep")
    with pytest.raises(CLIInternalError):
        helpers.assign_roles_with_propagation(
            assignments=[{"role": "role", "scope": "scope", "assignee": name} for name in ("first", "second")],
            max_tries=3, wait=120,
        )
    assert create.call_count == (1 if failed == "first" else 2)
    sleep.assert_not_called()


def test_state_grants_read_the_caller_once_and_batch_both_hubs(mocker):
    invoke = mocker.patch.object(fixtures.cli, "invoke")
    invoke.return_value.as_json.return_value = {"user": {"name": "caller"}}
    assign = mocker.patch.object(fixtures, "assign_roles_with_propagation")
    fixtures.assign_iot_hub_dataplane_rbac_role([{"hub": {"id": name}} for name in ("source", "destination")])
    invoke.assert_called_once_with("account show", capture_stderr=True)
    assign.assert_called_once_with(
        assignments=[
            {"role": fixtures.USER_ROLE, "scope": name, "assignee": "caller"}
            for name in ("source", "destination")
        ],
        max_tries=fixtures.MAX_RBAC_ASSIGNMENT_TRIES, wait=120,
    )


@pytest.fixture
def phase(mocker, tmp_path):
    mocker.patch.object(fixtures, "RG", ownership.GROUP)
    mocker.patch.object(fixtures, "ENTITY_RG", ownership.GROUP)
    events = []
    clock = [0]
    states = {}
    resources = {}
    arm = SimpleNamespace(deadline=None)
    observer = ownership.Observer(tmp_path / "ownership.json", "run", "regular-state-workflow", arm)
    observer.data["installed"] = True
    mocker.patch.object(fixtures, "_regular_phase_observer", return_value=observer)
    mocker.patch.object(fixtures, "monotonic", side_effect=lambda: clock[0])
    mocker.patch.object(ownership, "time", SimpleNamespace(
        monotonic=lambda: clock[0],
        sleep=lambda seconds: (events.append(("sleep", seconds)), clock.__setitem__(0, clock[0] + seconds)),
    ))

    def add(name, pending=False):
        resource_id = (
            f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups/{fixtures.RG}"
            f"/providers/Microsoft.Devices/IotHubs/{name}"
        ).casefold()
        resources[resource_id] = {
            "id": resource_id, "name": name, "location": fixtures.HUB_TEST_LOCATION,
            "tags": {ownership.OWNER_TAG: "run"},
            "properties": {"state": "Active", "provisioningState": "Succeeded", "disableLocalAuth": True},
        }
        observer.data["resources"][resource_id] = {
            "id": resource_id, "apiVersion": "version", "before": 404, "ownerTag": "run",
            "attempted": True, "resolved": not pending, "uncertain": pending,
            "mutations": [{"method": "PUT", "id": resource_id, "status": 202 if pending else 200}],
        }
        observer.save()
        return resource_id

    def read(method, resource_id, api):
        assert method == "GET"
        events.append(("read", resource_id))
        state = states.get(resource_id, [])
        value = state.pop(0) if state else "Succeeded"
        if value == "404":
            return 404, None
        resource = resources[resource_id]
        return 200, dict(resource, properties=dict(resource["properties"], provisioningState=value))

    arm.request = read

    def create(command):
        name = command.split()[command.split().index("-n") + 1]
        events.append(("create", name))
        add(name, pending="--no-wait" in command)
        return Mock()

    invoke = mocker.patch.object(fixtures, "_invoke_fixture", side_effect=create)
    return SimpleNamespace(
        observer=observer, events=events, states=states, resources=resources, clock=clock, add=add, invoke=invoke,
    )


@pytest.mark.parametrize("exists", [False, True])
def test_shared_fixture_creates_once_or_borrows_the_exact_owned_hub(phase, exists):
    if exists:
        phase.add(fixtures.ENTITY_NAME)
    first = fixtures.provisioned_shared_iot_hub.__wrapped__(Mock())
    second = fixtures.provisioned_shared_iot_hub.__wrapped__(Mock())
    assert first == second
    assert first["name"] == fixtures.ENTITY_NAME
    assert phase.invoke.call_count == (0 if exists else 1)
    assert all(event[1] == fixtures._dynamic_hub_id() for event in phase.events if event[0] == "read")


def test_shared_fixture_does_not_adopt_a_changed_owner(phase):
    resource_id = phase.add(fixtures.ENTITY_NAME)
    phase.resources[resource_id]["tags"][ownership.OWNER_TAG] = "foreign"
    with pytest.raises(ownership.OwnershipError):
        fixtures.provisioned_shared_iot_hub.__wrapped__(Mock())
    phase.invoke.assert_not_called()


@pytest.mark.parametrize("damage", ["missing", "uncertain", "location", "local-auth"])
def test_shared_fixture_rejects_unready_or_noncompliant_owned_hubs(phase, damage):
    resource_id = phase.add(fixtures.ENTITY_NAME)
    if damage == "missing":
        phase.states[resource_id] = ["404"]
    elif damage == "uncertain":
        record = phase.observer.data["resources"][resource_id]
        record["uncertain"] = True
        record["mutations"][0]["status"] = 504
    elif damage == "location":
        phase.resources[resource_id]["location"] = "wrong-region"
    else:
        phase.resources[resource_id]["properties"]["disableLocalAuth"] = False
    with pytest.raises((ownership.OwnershipError, AssertionError)):
        fixtures.provisioned_shared_iot_hub.__wrapped__(Mock())
    phase.invoke.assert_not_called()


def test_unmanaged_fixture_preserves_its_existing_private_module_pool(mocker):
    mocker.patch.object(fixtures, "_regular_phase_observer", return_value=None)
    request = Mock()
    request.getfixturevalue.return_value = [{"name": "private"}]
    assert fixtures.provisioned_shared_iot_hub.__wrapped__(request) == {"name": "private"}
    request.getfixturevalue.assert_called_once_with("provisioned_only_iot_hubs_module")


def pool_request(**settings):
    markers = {
        "hub_infrastructure": SimpleNamespace(kwargs={"count": 2, **settings}),
        "timeout": SimpleNamespace(args=(2700,), kwargs={}),
    }
    return SimpleNamespace(_pyfuncitem=SimpleNamespace(get_closest_marker=markers.get))


@pytest.mark.parametrize("with_dependencies", [False, True])
def test_pool_submits_both_creates_before_any_readiness_wait(phase, mocker, with_dependencies):
    names = ["aziotclitest-hub-" + letter * 18 for letter in ("a", "b")]
    mocker.patch.object(fixtures, "generate_hub_id", side_effect=names)
    request = pool_request(
        sys_identity=with_dependencies, user_identity=with_dependencies, storage=with_dependencies,
        desired_tags="test=pool" if with_dependencies else None,
    )
    hubs = fixtures._iot_hubs_provisioner(
        request, provisioned_user_identity={"id": "/unit/identity"},
        provisioned_storage={"connectionString": "unit-storage"},
    )
    assert phase.events[:2] == [("create", name) for name in names]
    assert all(call.args[0].endswith(" --no-wait") for call in phase.invoke.call_args_list)
    for call in phase.invoke.call_args_list:
        for option in ("--system-assigned-mi", "--user-assigned-mi /unit/identity", "--fcs unit-storage", "--tags test=pool"):
            assert (option in call.args[0]) == with_dependencies
    assert [hub["name"] for hub in hubs] == names
    assert all(hub["hub"]["properties"]["state"] == "Active" for hub in hubs)
    assert all(not record["uncertain"] for record in phase.observer.data["resources"].values())


def test_partial_pool_setup_keeps_owned_records_without_replaying_any_create(phase, mocker):
    names = ["aziotclitest-hub-" + letter * 18 for letter in ("a", "b")]
    mocker.patch.object(fixtures, "generate_hub_id", side_effect=names)
    create = phase.invoke.side_effect

    def fail_second(command):
        result = create(command)
        if phase.invoke.call_count == 2:
            record = list(phase.observer.data["resources"].values())[-1]
            record["mutations"][0]["status"] = 504
            phase.observer.save()
            raise CLIInternalError("Uncertain second create")
        return result

    phase.invoke.side_effect = fail_second
    with pytest.raises(CLIInternalError, match="Uncertain second create"):
        fixtures._iot_hubs_provisioner(pool_request())
    assert phase.events == [("create", name) for name in names]
    assert len(phase.observer.data["resources"]) == 2
    assert all(record["uncertain"] for record in phase.observer.data["resources"].values())


@pytest.mark.parametrize("pending", [["404", "Updating"], ["Updating"]])
def test_pool_wait_is_get_only_and_keeps_the_poll_interval(phase, pending):
    name = "aziotclitest-hub-" + "a" * 18
    resource_id = phase.add(name, pending=True)
    phase.states[resource_id] = list(pending)
    hubs = [{"name": name, "rg": fixtures.RG}]
    fixtures._wait_for_owned_hubs(phase.observer, hubs, 100)
    assert [event for event in phase.events if event[0] == "sleep"] == [("sleep", 15)] * len(pending)
    phase.invoke.assert_not_called()
    assert hubs[0]["hub"]["id"] == resource_id


@pytest.mark.parametrize("failure", ["Failed", "timeout", "foreign", "uncertain-write"])
def test_pool_never_yields_unproven_resources_or_replays_creates(phase, failure):
    name = "aziotclitest-hub-" + "a" * 18
    resource_id = phase.add(name, pending=True)
    if failure == "foreign":
        phase.resources[resource_id]["tags"][ownership.OWNER_TAG] = "foreign"
    elif failure == "uncertain-write":
        phase.observer.data["resources"][resource_id]["mutations"][0]["status"] = 504
    else:
        phase.states[resource_id] = ["Updating"] * 10 if failure == "timeout" else ["Failed"]
    hubs = [{"name": name, "rg": fixtures.RG}]
    with pytest.raises(ownership.OwnershipError):
        fixtures._wait_for_owned_hubs(phase.observer, hubs, 20)
    assert "hub" not in hubs[0]
    phase.invoke.assert_not_called()
