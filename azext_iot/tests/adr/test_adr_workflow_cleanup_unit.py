# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline coverage of workflow integration resource ownership and failures."""

import shlex
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError

from azext_iot.tests.adr import test_adr_namespace_workflow_int as scenarios
from azext_iot.tests.adr._helpers import ADRFullInfraHelper


CASES = [
    ("test_namespace_setup_check_and_resume", ("namespace",)),
    ("test_namespace_setup_links_dps", ("namespace", "dps")),
    ("test_namespace_setup_links_hub_after_dps", ("namespace", "dps", "hub")),
    ("test_namespace_setup_links_software_updates", ("namespace", "su")),
]
RESOURCE_CASES = [(method, kind) for method, kinds in CASES for kind in kinds]
NAMES = {"namespace": "ns", "dps": "dps", "hub": "hub", "su": "testsuabcdefgh"}


class _Scenario(ADRFullInfraHelper):
    def __init__(self):
        self.resources = set()
        self._owned_resources = {}
        self.commands = []
        self.deleted = []
        self.fail_create = None
        self.fail_delete = None
        self.primary_error = RuntimeError("setup failed after creating resource")
        self.cleanup_error = RuntimeError("standalone deletion failed")

    def get_subscription_id(self):
        return "sub"

    def cmd(self, command):
        self.commands.append(command)
        args = shlex.split(command)
        payload = {
            "state": "Succeeded",
            "summary": {"NotConfigured": 3},
            "items": [{"id": "namespace", "state": "Satisfied"}],
        }
        if "--plan-only" in args:
            payload.update(state="Planned", items=[{
                "id": "namespace", "state": "Planned",
                "details": {"tags": {"env": "integration", "owner": "adr-workflow"}},
            }])
        elif args[:4] == ["iot", "adr", "ns", "link"]:
            assert args[5] == "show", command
            payload = {"linkingState": "Succeeded"}
        elif args[:4] == ["iot", "adr", "ns", "check"]:
            pass
        else:
            kind = next(
                kind for kind, prefix in reversed(list(self._RESOURCE_COMMANDS.items()))
                if command.startswith(f"{prefix} ")
            )
            action = args[len(shlex.split(self._RESOURCE_COMMANDS[kind]))]
            if action == "setup":
                kind = "su" if "--software-updates" in args else "namespace"
            resource = (kind, NAMES[kind], scenarios.TEST_RG)
            if action == "show":
                if kind not in self.resources:
                    raise ResourceNotFoundError("ResourceNotFound")
            elif action in {"create", "setup"}:
                # Includes partially failed creates: ownership must already exist.
                assert resource in self._owned_resources, command
                self.resources.add(kind)
                if kind == self.fail_create:
                    raise self.primary_error
                payload["id"] = f"/subscriptions/sub/resourceGroups/rg/providers/test/{kind}"
            elif action == "delete":
                assert resource in self._owned_resources, command
                self.deleted.append(kind)
                if kind == self.fail_delete:
                    raise self.cleanup_error
                self.resources.remove(kind)
            else:
                raise AssertionError(f"Unexpected command: {command}")
        return SimpleNamespace(get_output_in_json=lambda: payload)


@pytest.fixture
def scenario(monkeypatch):
    monkeypatch.setattr(scenarios, "generate_adr_namespace_name", lambda: NAMES["namespace"])
    monkeypatch.setattr(scenarios, "generate_dps_name", lambda: NAMES["dps"])
    monkeypatch.setattr(scenarios, "generate_hub_name", lambda: NAMES["hub"])
    monkeypatch.setattr(scenarios, "generate_generic_id", lambda: "abcdefgh")
    return _Scenario()


def _run(scenario, method):
    getattr(scenarios.TestADRNamespaceWorkflow, method)(scenario)


@pytest.mark.parametrize("method,kinds", CASES)
def test_workflow_scenarios_delete_owned_namespace_before_standalone_targets(scenario, method, kinds):
    _run(scenario, method)
    assert scenario.deleted == list(kinds)
    assert not scenario.resources
    assert not scenario._owned_resources


@pytest.mark.parametrize("method,kind", RESOURCE_CASES)
def test_workflow_scenarios_clean_partial_creation_without_masking_failure(scenario, method, kind):
    scenario.fail_create = kind
    with pytest.raises(RuntimeError) as raised:
        _run(scenario, method)
    assert raised.value is scenario.primary_error
    assert kind in scenario.deleted
    assert not scenario.resources
    assert not scenario._owned_resources


@pytest.mark.parametrize("method,kind", RESOURCE_CASES)
def test_workflow_scenarios_never_claim_or_delete_existing_fixtures(scenario, method, kind):
    scenario.resources.add(kind)
    with pytest.raises(AssertionError, match="Refusing to overwrite"):
        _run(scenario, method)
    assert kind not in scenario.deleted
    assert scenario.resources == {kind}
    assert not scenario._owned_resources


def test_workflow_scenario_reports_cleanup_only_failure_and_continues(scenario):
    scenario.fail_delete = "namespace"
    with pytest.raises(AssertionError, match="standalone deletion failed"):
        _run(scenario, "test_namespace_setup_links_software_updates")
    assert scenario.deleted == ["namespace", "su"]
    assert scenario.resources == {"namespace"}


def test_workflow_scenario_preserves_primary_failure_when_cleanup_also_fails(scenario):
    scenario.fail_create = "su"
    scenario.fail_delete = "namespace"
    with pytest.raises(RuntimeError) as raised:
        _run(scenario, "test_namespace_setup_links_software_updates")
    assert raised.value is scenario.primary_error
    assert scenario.deleted == ["namespace", "su"]
    assert scenario.resources == {"namespace"}


def test_plan_only_workflow_scenario_never_claims_resources(scenario):
    _run(scenario, "test_namespace_setup_tagged_plan_is_read_only")
    assert len(scenario.commands) == 1
    assert not scenario.resources
    assert not scenario._owned_resources
    assert not scenario.deleted
