# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.cli.testsdk.base import ExecutionResult
from azure.cli.testsdk.exceptions import CliExecutionError
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError
from knack.util import CLIError

from azext_iot.tests.adr import test_adr_certificate_authority_int as ca_scenario
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    CleanupLedger,
    is_resource_not_found_error,
    wait_for_resource_absent,
)


def _sdk_error(error):
    def invoke(*_args, **_kwargs):
        try:
            raise error
        except type(error) as caught:
            raise CliExecutionError(caught)  # pylint: disable=raise-missing-from

    cli = Mock(data={})
    cli.invoke.side_effect = invoke
    with pytest.raises(type(error)) as raised:
        ExecutionResult(cli, "iot hub show -n owned-hub -g owned-rg")
    return raised.value


def _missing_hub():
    return CLIError("An IotHub 'owned-hub' under resource group 'owned-rg' was not found.")


def test_sdk_rethrow_wrapper_allows_proven_absence_before_creation():
    error = _sdk_error(_missing_hub())
    assert isinstance(error.__context__, CliExecutionError)
    assert error.__context__.__context__ is None
    assert error.__context__.exception is error
    assert is_resource_not_found_error(error)
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=[error, Mock()])

    helper.create_owned_resource(
        "create owned hub", kind="hub", name="owned-hub", resource_group="owned-rg",
    )

    assert helper.cmd.call_count == 2
    helper.cmd.assert_called_with("create owned hub")
    assert ("hub", "owned-hub", "owned-rg") in helper._owned_resources


@pytest.mark.parametrize("location", ["error", "response", "wrapper", "cause"])
@pytest.mark.parametrize("status", [403, 502])
def test_sdk_rethrow_denials_never_create_or_record_ownership(location, status):
    error = _missing_hub()
    if location == "error":
        error.status_code = status
    elif location == "response":
        error.response = SimpleNamespace(status_code=status)
    elif location == "cause":
        error.__cause__ = HttpResponseError(message="ResourceNotFound 404")
        error.__cause__.status_code = status
    wrapped = _sdk_error(error)
    if location == "wrapper":
        wrapped.__context__.status_code = status
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=wrapped)

    with pytest.raises(CLIError):
        helper.create_owned_resource(
            "create owned hub", kind="hub", name="owned-hub", resource_group="owned-rg",
        )

    helper.cmd.assert_called_once()
    assert not getattr(helper, "_owned_resources", {})
    assert not is_resource_not_found_error(wrapped)


@pytest.mark.parametrize("error", [
    ClientAuthenticationError(message="ResourceNotFound 404"),
    ServiceRequestError(message="ResourceNotFound 404"),
    CLIError("unrelated failure mentioning 404"),
])
def test_sdk_rethrow_does_not_relabel_other_failures(error):
    assert not is_resource_not_found_error(_sdk_error(error))


def test_sdk_wrapper_structured_denial_and_nontransparent_cycles_are_rejected():
    error = _sdk_error(_missing_hub())
    error.__context__.error = {"code": "AuthorizationFailed"}
    assert not is_resource_not_found_error(error)
    error.__context__.error = None
    error.__context__.exception = CLIError("different exception")
    assert not is_resource_not_found_error(error)


def test_cleanup_dependency_failure_retains_exact_callbacks_for_explicit_retry():
    child = Mock(side_effect=[CLIError("child remains"), None])
    parent = Mock()
    independent = Mock()
    ledger = CleanupLedger()
    ledger.register("parent", parent, depends_on=("child",))
    ledger.register("child", child)
    ledger.register("independent", independent)

    assert [label for label, _ in ledger.cleanup()] == ["child", "parent"]
    parent.assert_not_called()
    assert not ledger.cleanup()
    parent.assert_called_once()
    independent.assert_called_once()
    assert child.call_count == 2


def test_cleanup_unregistered_dependency_blocks_parent():
    parent = Mock()
    ledger = CleanupLedger()
    ledger.register("parent", parent, depends_on=("unregistered child",))
    assert "unregistered child" in str(ledger.cleanup()[0][1])
    parent.assert_not_called()


def test_absence_wait_requires_actual_absence_and_does_not_retry_read_errors():
    scenario = SimpleNamespace(cmd=Mock(side_effect=[Mock(), ResourceNotFoundError("gone")]))
    wait_for_resource_absent(scenario, "show child", interval=0)
    assert scenario.cmd.call_count == 2

    scenario.cmd = Mock(return_value=Mock())
    with pytest.raises(AssertionError, match="resource is still readable"):
        wait_for_resource_absent(scenario, "show child", timeout=0)

    for status in (403, 502):
        error = HttpResponseError(message="ResourceNotFound 404")
        error.status_code = status
        scenario.cmd = Mock(side_effect=error)
        with pytest.raises(HttpResponseError):
            wait_for_resource_absent(scenario, "show child")
        scenario.cmd.assert_called_once()


class CertificateScenario:
    def __init__(self):
        self.resources = {}
        self.commands = []
        self.deleting = set()
        self.lingering_policy = False
        self.delete_error = None
        self.delete_error_removes_backend = False
        self.create_error = None
        self.race_to_absence = False

    @staticmethod
    def not_found():
        error = HttpResponseError(message="(ResourceNotFound) gone")
        error.status_code = 404
        return error

    def cmd(self, command, **kwargs):
        self.commands.append(command)
        parts = shlex.split(command)
        if parts[:5] == ["iot", "adr", "ns", "ca", "policy"]:
            kind, action = "policy", parts[5]
        elif parts[:4] == ["iot", "adr", "ns", "ca"]:
            kind, action = "ca", parts[4]
        else:
            kind, action = "namespace", parts[3]
        name = parts[parts.index("-n") + 1] if "-n" in parts else None
        key = kind, name
        if kwargs.get("expect_failure"):
            return Mock()
        if action == "create":
            properties = (
                {"certificate": {"validityPeriodInDays": 30}}
                if kind == "policy" else
                {"certificateAuthorityType": "Root" if name == "rootca" else "ICA"}
            )
            self.resources[key] = {"name": name, "properties": properties}
            if name == self.create_error:
                raise CLIError("create failed after persistence")
        elif action == "update":
            self.resources[key]["tags"] = {"env": "updated" if kind == "policy" else "int"}
        elif action == "delete":
            if name == self.delete_error:
                if self.delete_error_removes_backend:
                    self.resources.pop(key)
                raise CLIError("CannotDeleteResource: child remains")
            self.deleting.add(key)
            if self.race_to_absence:
                self.resources.pop(key)
                raise self.not_found()
        elif action == "show":
            if key in self.deleting and not (kind == "policy" and self.lingering_policy):
                self.resources.pop(key, None)
            if key not in self.resources:
                raise self.not_found()
        elif action == "list":
            return Mock(get_output_in_json=lambda: [
                value for (resource_kind, _), value in self.resources.items() if resource_kind == kind
            ])
        return Mock(get_output_in_json=lambda: self.resources.get(key))

    def run(self):
        ca_scenario.TestADRCertificateAuthorityLifecycle.test_adr_certificate_authority_lifecycle(self)

    def deletions(self):
        return [command for command in self.commands if " delete " in command]


@pytest.fixture
def certificate_scenario(monkeypatch):
    monkeypatch.setattr(ca_scenario, "generate_adr_namespace_name", lambda: "owned-namespace")
    monkeypatch.setattr(
        ca_scenario, "wait_for_resource_absent",
        lambda test, command: wait_for_resource_absent(test, command, timeout=0, interval=0),
    )
    return CertificateScenario()


@pytest.mark.parametrize("race", [False, True])
def test_ca_cleanup_waits_for_delete_and_child_absence_before_parents(certificate_scenario, race):
    scenario = certificate_scenario
    scenario.race_to_absence = race
    scenario.run()
    assert not scenario.resources
    assert [shlex.split(command)[shlex.split(command).index("-n") + 1]
            for command in scenario.deletions()] == ["leafpolicy", "issuingca", "rootca", "owned-namespace"]
    for command in scenario.deletions():
        assert "--no-wait" not in shlex.split(command)
        delete_index = scenario.commands.index(command)
        assert " show " in scenario.commands[delete_index + 1]


def test_ca_lingering_policy_blocks_all_parents_and_retains_ownership(certificate_scenario, monkeypatch):
    scenario = certificate_scenario
    scenario.lingering_policy = True
    ledger = CleanupLedger()
    monkeypatch.setattr(ca_scenario, "CleanupLedger", lambda: ledger)
    with pytest.raises(AssertionError, match="resource is still readable"):
        scenario.run()
    assert len(scenario.deletions()) == 1
    assert len(scenario.resources) == 4
    assert {action[0] for action in ledger._actions} == {"policy", "ica", "root", "namespace"}
    scenario.lingering_policy = False
    assert not ledger.cleanup()
    assert len(scenario.deletions()) == 4
    assert not scenario.resources


@pytest.mark.parametrize("backend_absent", [False, True])
def test_ca_rejected_ica_delete_preserves_root_and_namespace(certificate_scenario, backend_absent):
    scenario = certificate_scenario
    scenario.delete_error = "issuingca"
    scenario.delete_error_removes_backend = backend_absent
    with pytest.raises(CLIError, match="CannotDeleteResource"):
        scenario.run()
    assert len(scenario.deletions()) == 2
    assert ("ca", "rootca") in scenario.resources
    assert ("namespace", "owned-namespace") in scenario.resources


def test_ca_cleanup_failure_cannot_turn_lifecycle_green(certificate_scenario):
    certificate_scenario.delete_error = "owned-namespace"
    with pytest.raises(AssertionError, match="ADR cleanup failed: namespace: CannotDeleteResource"):
        certificate_scenario.run()


def test_ca_partial_create_is_owned_and_cleaned_in_dependency_order(certificate_scenario):
    certificate_scenario.create_error = "issuingca"
    with pytest.raises(CLIError, match="create failed after persistence"):
        certificate_scenario.run()
    assert len(certificate_scenario.deletions()) == 3
    assert not certificate_scenario.resources


def test_ca_preexisting_namespace_is_never_overwritten_or_deleted(certificate_scenario):
    certificate_scenario.resources[("namespace", "owned-namespace")] = {"name": "owned-namespace"}
    with pytest.raises(AssertionError, match="Refusing to overwrite"):
        certificate_scenario.run()
    assert len(certificate_scenario.commands) == 1
    assert not certificate_scenario.deletions()


@pytest.mark.parametrize("status", [403, 502])
def test_ca_failed_namespace_lookup_never_creates_or_deletes(certificate_scenario, status):
    error = HttpResponseError(message="ResourceNotFound 404")
    error.status_code = status
    certificate_scenario.cmd = Mock(side_effect=error)
    with pytest.raises(HttpResponseError):
        certificate_scenario.run()
    certificate_scenario.cmd.assert_called_once()
