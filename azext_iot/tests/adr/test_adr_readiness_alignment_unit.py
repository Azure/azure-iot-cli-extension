# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for legacy no-wait readiness using production permission binding."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.providers.link_helpers import failed_link_recovery_commands
from azext_iot.adr.providers.link_recovery import LinkRecovery
from azext_iot.tests.adr import _readiness as readiness
from azext_iot.tests.adr.test_adr_readiness_unit import Clock, DPS_ID, LINKS, NS_ID, UAMI_ID, _expected, _output


# Observed Hub envelope in run 35353501504. The subscription/RG remain offline
# fixtures; the denied object ID is deliberately distinct from the client ID.
DENIED = "968b143a-9db1-4647-8d0e-d4e20aa511cc"
CLIENT = "3794e83c-342b-4713-ace2-0c42bd4c2c7e"
OTHER = "11111111-1111-4111-8111-111111111111"


class Scenario:
    def __init__(self, kind="hub", outbound="user"):
        self.kind = kind
        self.section, self.endpoint_type, self.name = LINKS[kind]
        self.expected = _expected(kind)
        if kind == "hub":
            self.expected["resourceId"] = self.expected["resourceId"].rsplit("/", 1)[0] + "/testhubeeda074c"
        self.expected["inboundCallerIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        self.original = {
            "id": NS_ID,
            "identity": {"type": "SystemAssigned", "principalId": DENIED},
            "properties": {"provisioningState": "Succeeded"},
        }
        if outbound == "user":
            self.original["identity"] = {
                "type": "SystemAssigned, UserAssigned", "principalId": OTHER,
                "userAssignedIdentities": {UAMI_ID: {"principalId": DENIED}},
            }
            self.original["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
        if kind == "hub":
            self.original["properties"]["provisioning"] = {"endpoints": {"dps": {
                "resourceId": DPS_ID, "endpointType": LINKS["dps"][1], "linkingState": "Succeeded",
                "inboundCallerIdentity": {"type": "SystemAssigned"},
            }}}
        self.error = self.denial()
        self.states = ["Failed", "Failed", "Succeeded"]
        self.last_state = "Failed"
        self.transform = lambda value: value
        self.clock = Clock()
        self.writes = []
        self.write_times = []
        self.write_error = None
        self.initial_read_cost = 0
        self.cmd = Mock(side_effect=self.command)

    def denial(self, *, principal=DENIED, action=None, target=None):
        service = {"hub": "Hub", "dps": "DPS"}[self.kind]
        return {
            "code": "LinkInitiateFailed",
            "message": (
                f"The namespace's managed identity is not authorized to link the {service} resource. "
                "Grant it access on the resource, then resubmit the request. "
                f"({service} resource reported: [AuthorizationFailed] The client '{CLIENT}' "
                f"with object id '{principal}' does not have authorization to perform action "
                f"'{action or self.endpoint_type + '/linkInitiate/action'}' "
                f"over scope '{target or self.expected['resourceId']}' or the scope is invalid. "
                "If access was recently granted, please refresh your credentials.)"
            ),
        }

    def body(self, state):
        body = deepcopy(self.original)
        body["properties"]["provisioningState"] = "Updating" if state == "InProgress" else state
        endpoint = dict(deepcopy(self.expected), endpointType=self.endpoint_type, linkingState=state)
        if state == "Failed":
            endpoint["linkingError"] = deepcopy(self.error)
        body["properties"][self.section] = {"endpoints": {self.name: endpoint}}
        return self.transform(body)

    def command(self, text):
        if text == "iot adr ns show -n ns -g rg":
            if not self.writes:
                self.clock.now += self.initial_read_cost
                return _output(deepcopy(self.original))
            if self.states:
                self.last_state = self.states.pop(0)
            return _output(self.body(self.last_state))
        assert " role " not in text
        assert text.endswith(" --no-wait")
        assert f" link {self.kind} " in text
        assert " add " in text or " update " in text
        if " update " in text and self.write_error:
            raise self.write_error
        self.writes.append(text)
        self.write_times.append(self.clock.now)
        return _output(None)

    def run(self, **kwargs):
        command = (
            f"iot adr ns link {self.kind} add --ns ns -g rg -n {self.name} "
            f"--{self.kind}-id {self.expected['resourceId']} --user-assigned-mi {UAMI_ID}"
        )
        return readiness.link_with_readiness(
            self, command, "ns", "rg", self.name, self.expected, link_kind=self.kind,
            clock=self.clock, sleeper=self.clock.sleep, **kwargs,
        )


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("outbound", ["system", "user"])
def test_observed_denial_recovers_only_exact_original_outbound_identity(mocker, kind, outbound):
    scenario = Scenario(kind, outbound)
    classifier = mocker.spy(LinkRecovery, "authorized_failure")
    run = mocker.patch.object(LinkRecovery, "run", side_effect=AssertionError("Do not replace no-wait coverage"))
    snapshot = deepcopy(scenario.original)
    expected_update = failed_link_recovery_commands(scenario.body("Failed"))[0] + " --no-wait"
    result = scenario.run()
    assert result["linkingState"] == "Succeeded"
    assert all(result[key] == value for key, value in scenario.expected.items())
    assert scenario.cmd.call_args_list[0].args == ("iot adr ns show -n ns -g rg",)
    assert len(scenario.writes) == 2 and scenario.writes[1] == expected_update
    assert scenario.writes[0].endswith(" --no-wait")
    assert scenario.clock.now == 20 and scenario.original == snapshot
    assert classifier.call_count == 2
    run.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("mutation", [
    "principal", "client-is-principal", "action", "target", "target-child", "kind",
    "invalid-request", "old-read-message", "additional-detail", "other-error", "namespace-error",
    "properties-error", "alternate-envelope", "conflicting-legacy-envelope", "suffix",
])
def test_unbound_and_invalid_denials_fail_without_recovery(kind, mutation):
    scenario = Scenario(kind)
    if mutation == "principal":
        scenario.error = scenario.denial(principal=OTHER)  # SAMI is not the selected outbound UAMI.
    elif mutation == "client-is-principal":
        scenario.error = scenario.denial(principal=CLIENT)
        scenario.error["message"] = scenario.error["message"].replace(f"client '{CLIENT}'", f"client '{DENIED}'")
    elif mutation == "action":
        scenario.error = scenario.denial(action=scenario.endpoint_type + "/read")
    elif mutation in {"target", "target-child"}:
        scenario.error = scenario.denial(target=scenario.expected["resourceId"] + (
            "/child" if mutation == "target-child" else "-other"
        ))
    elif mutation == "kind":
        service, other = ("Hub", "DPS") if kind == "hub" else ("DPS", "Hub")
        scenario.error["message"] = scenario.error["message"].replace(service, other)
    elif mutation == "invalid-request":
        scenario.error["message"] = (
            "The DPS resource rejected the link request as invalid. "
            "Verify the endpoint configuration, then resubmit the request."
        )
    elif mutation == "old-read-message":
        scenario.error["message"] = (
            f"The namespace's managed identity is not authorized to read the linked resource "
            f"'{scenario.expected['resourceId']}'. Grant it read access on the resource, then resubmit the request."
        )
    elif mutation == "additional-detail":
        scenario.error["details"] = [{"code": "OtherError"}]
    elif mutation == "suffix":
        scenario.error["message"] += " Another error."
    else:
        def transform(body):
            endpoint = body["properties"][scenario.section]["endpoints"][scenario.name]
            if mutation == "other-error":
                endpoint["error"] = {"code": "OtherError"}
            elif mutation == "conflicting-legacy-envelope":
                endpoint["error"] = {"message": (
                    f"The namespace's managed identity is not authorized to read the linked resource "
                    f"'{scenario.expected['resourceId']}'. Grant it read access on the resource, "
                    "then resubmit the request."
                )}
            elif mutation == "namespace-error":
                body["error"] = {"code": "OtherError"}
            elif mutation == "properties-error":
                body["properties"]["error"] = {"code": "OtherError"}
            else:
                endpoint["status"] = {"status": "Failed", "error": endpoint.pop("linkingError")}
            return body
        scenario.transform = transform
    with pytest.raises(AssertionError, match="Non-recoverable"):
        scenario.run()
    assert len(scenario.writes) == 1 and not scenario.clock.sleeps


@pytest.mark.parametrize("mutation", ["namespace-id", "outbound", "principal", "target", "inbound", "settings"])
@pytest.mark.parametrize("after_update", [False, True])
def test_identity_target_or_setting_drift_never_authorizes_another_write(mutation, after_update):
    scenario = Scenario()

    def transform(body):
        if after_update and len(scenario.writes) < 2:
            return body
        endpoint = body["properties"][scenario.section]["endpoints"][scenario.name]
        if mutation == "namespace-id":
            body["id"] += "-other"
        elif mutation == "outbound":
            body["properties"]["outboundIdentity"] = {"type": "SystemAssigned"}
        elif mutation == "principal":
            body["identity"]["userAssignedIdentities"][UAMI_ID]["principalId"] = OTHER
        elif mutation == "target":
            endpoint["resourceId"] += "-other"
        elif mutation == "inbound":
            endpoint["inboundCallerIdentity"] = {"type": "SystemAssigned"}
        else:
            endpoint["provisioning"]["allocationWeight"] += 1
        return body

    scenario.transform = transform
    with pytest.raises(AssertionError, match="changed"):
        scenario.run()
    assert len(scenario.writes) == (2 if after_update else 1)


def test_initial_snapshot_cost_is_charged_before_add():
    scenario = Scenario()
    scenario.initial_read_cost = readiness.LINK_READINESS_TIMEOUT
    with pytest.raises(AssertionError, match="Timed out"):
        scenario.run()
    assert not scenario.writes and scenario.cmd.call_count == 1


@pytest.mark.parametrize("missing", ["principal", "scope"])
def test_unbound_original_snapshot_cannot_start_a_mutation(missing):
    scenario = Scenario(outbound="system")
    if missing == "principal":
        scenario.original["identity"].pop("principalId")
        error, message = AzureResponseError, "principalId"
    else:
        scenario.original["id"] += "-other"
        error, message = AssertionError, "intended link scope"
    with pytest.raises(error, match=message):
        scenario.run()
    assert not scenario.writes and scenario.cmd.call_count == 1


def test_stale_failure_does_not_replay_accepted_recovery_or_extend_deadline():
    scenario = Scenario()
    scenario.states = ["Failed", "Failed"]
    with pytest.raises(AssertionError, match="recovery updates=1"):
        scenario.run(timeout=65)
    assert scenario.clock.now == 65 and len(scenario.writes) == 2
    assert max(scenario.clock.sleeps) == 10


def test_progress_allows_bounded_recovery_but_never_suppresses_persistent_failure():
    scenario = Scenario()
    scenario.states = (["InProgress"] + ["Failed"] * 4) * 30
    with pytest.raises(AssertionError, match="Timed out"):
        scenario.run(timeout=240)
    assert scenario.clock.now == 240
    assert scenario.write_times == [0, 20, 80, 140, 190]
    assert sum(" add " in command for command in scenario.writes) == 1


def test_accepted_recovery_can_finish_after_four_minutes_without_replay():
    scenario = Scenario()
    scenario.states = ["Failed", "Failed"] + ["InProgress"] * 30 + ["Succeeded"]
    scenario.run()
    assert 240 < scenario.clock.now < readiness.LINK_READINESS_TIMEOUT == 600
    assert len(scenario.writes) == 2
    assert " add " in scenario.writes[0] and " update " in scenario.writes[1]


def test_accepted_recovery_still_stops_at_native_default_deadline():
    scenario = Scenario()
    scenario.states = ["Failed", "Failed"] + ["InProgress"] * 70
    with pytest.raises(AssertionError, match="Timed out"):
        scenario.run()
    assert scenario.clock.now == readiness.LINK_READINESS_TIMEOUT == 600
    assert len(scenario.writes) == 2


def test_update_preflight_failure_is_not_swallowed_or_bypassed():
    scenario = Scenario()
    scenario.write_error = AzureResponseError("Required service role cannot be verified")
    with pytest.raises(AzureResponseError) as caught:
        scenario.run()
    assert caught.value is scenario.write_error and len(scenario.writes) == 1
