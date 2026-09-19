# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Focused registry lifecycle, readiness, subscription and ownership contracts."""

import json
import shlex
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError, RequiredArgumentMissingError
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr import _readiness as readiness
from azext_iot.tests.adr import test_adr_registry_device_int as scenarios
from azext_iot.tests.adr.conftest import _spec_adr_client


@pytest.mark.parametrize("expect_failure", [False, True])
def test_live_scenario_keeps_shared_wrapper_and_readiness_budget(expect_failure, mocker):
    scenario_class = scenarios.TestADRRegistryDeviceLifecycle
    assert issubclass(scenario_class, ADRLiveScenarioTest)
    methods = [method for name, method in vars(scenario_class).items() if name.startswith("test_")]
    assert len(methods) == 1
    timeout = [mark for mark in methods[0].pytestmark if mark.name == "timeout"]
    assert len(timeout) == 1 and timeout[0].args == (2100,) and timeout[0].kwargs == {"func_only": False}
    delegate = mocker.patch.object(ADRLiveScenarioTest, "cmd")
    scenario = scenario_class(methods[0].__name__)
    checks = [Mock()]
    assert scenario.cmd("iot adr ns list", checks=checks, expect_failure=expect_failure) is delegate.return_value
    delegate.assert_called_once_with(
        f"iot adr ns list --subscription {scenarios.TEST_SUBSCRIPTION}", checks=checks, expect_failure=expect_failure,
    )
    error = HttpResponseError("Do not conceal errors from the ADR wrapper.")
    delegate.side_effect = error
    with pytest.raises(HttpResponseError) as caught:
        scenario.cmd("iot adr ns list")
    assert caught.value is error


class _LifecycleBackend:
    """Small orchestration double, not a substitute for the real SDK wire tests."""

    def __init__(self, scenario, collision=None, primary_failure=False):
        self.scenario = scenario
        self.resources = {}
        self.commands = []
        self.collision = collision
        self.primary_failure = primary_failure
        self.sdk_calls = []
        self.update_states = []
        self.wait_observations = []
        self.attribute_list_lag = 2
        self.attribute_list_reads = []

    @staticmethod
    def resource_id(group, namespace, name=None, device=None):
        resource_id = (
            f"/subscriptions/{scenarios.TEST_SUBSCRIPTION}/resourceGroups/{scenarios.TEST_RG}"
            f"/providers/Microsoft.DeviceRegistry/namespaces/{namespace}"
        )
        if group == "device":
            resource_id += f"/registryDevices/{name}"
        elif group == "attribute":
            resource_id += f"/registryDevices/{device}/attributes/{name}"
        return resource_id

    def sdk_get(self, group, **scope):
        self.sdk_calls.append((group, scope))
        assert scope["resource_group_name"] == scenarios.TEST_RG
        resource_id = self.resource_id(
            group, scope["namespace_name"],
            scope.get("attribute_name") if group == "attribute" else scope.get("registry_device_name"),
            scope.get("registry_device_name"),
        )
        if self.collision == group:
            return {"id": resource_id, "name": "foreign"}
        if group not in self.resources:
            raise _sdk_error(resource_id)
        resource = deepcopy(self.resources[group])
        assert resource["id"].casefold() == resource_id.casefold()
        return resource

    def cmd(self, command):
        # Exercise the real testsdk brace formatting; malformed JSON examples
        # otherwise pass tests that replace cmd with a permissive Mock.
        tokens = shlex.split(self.scenario._apply_kwargs(command))
        self.commands.append(tokens)
        group = "namespace"
        offset = 3
        if tokens[:4] == ["iot", "adr", "ns", "registry-device"]:
            group = "device"
            offset = 4
            if tokens[offset] in ("auth", "attribute", "capability"):
                group = tokens[offset]
                offset += 1
        verb = tokens[offset]
        args = tokens[offset + 1:]
        name = args[args.index("-n") + 1] if "-n" in args else None
        if self.collision == group and verb == "show":
            return Mock(get_output_in_json=lambda: {"name": "foreign"})
        resource = self.resources.get(group)
        if self.primary_failure and group == "device" and verb == "show" and "--external-device-id" in args:
            raise AssertionError("primary lifecycle failure")
        if verb == "wait":
            if group == "device" and resource and ("--custom" in args or "--updated" in args):
                properties = resource["properties"]
                self.wait_observations.append((args, deepcopy(properties)))
                if "--custom" in args:
                    assert args[args.index("--custom") + 1] == "properties.enablementState=='Disabled'"
                    assert properties["enablementState"] == "Disabled"
                    # The desired field is visible before the PATCH is terminal.
                    # Custom-condition success must not advance provisioning.
                else:
                    properties["provisioningState"] = "Succeeded"
            return Mock(get_output_in_json=lambda: None)
        if verb in ("show", "show-keys", "revoke-certs"):
            if resource is None or (name and name.startswith("missing-")):
                # Real CLI show can discard the SDK response and exit with 3.
                # Ownership/cleanup probes must not use this lossy channel.
                raise SystemExit(3)
            output = deepcopy(resource)
            if "--external-device-id" in args:
                output["id"] = output["id"].casefold()
        elif verb == "list":
            output = [deepcopy(resource)] if resource else []
            if group == "attribute":
                assert resource is not None, "The attribute must already be GET-visible."
                if self.attribute_list_lag:
                    self.attribute_list_lag -= 1
                    output = []
                self.attribute_list_reads.append(deepcopy(output))
            for listed in output:
                listed["id"] = listed["id"].lower()
        elif verb in ("create", "update"):
            if group == "device" and verb == "update" and "--enablement-state" not in args:
                raise RequiredArgumentMissingError("Nothing to update")
            if group == "device" and verb == "update":
                state = resource["properties"]["provisioningState"]
                self.update_states.append(state)
                if state != "Succeeded":
                    error = HttpResponseError("ResourceProvisioningInProgress")
                    error.status_code = 409
                    raise error
            properties = dict(resource["properties"]) if resource else {}
            if group == "attribute":
                properties = json.loads(args[args.index("--properties") + 1]) if "--properties" in args else {}
                if properties.get("reportedBy", "User") != "User":
                    raise InvalidArgumentValueError("service-owned")
                properties["reportedBy"] = "User"
            else:
                properties["provisioningState"] = (
                    "Accepted" if group == "device" and verb == "update" and "--no-wait" in args else "Succeeded"
                )
            for flag, field in (
                ("--external-device-id", "externalDeviceId"), ("--enablement-state", "enablementState"),
                ("--manufacturer", "manufacturer"), ("--model", "model"),
                ("--hardware-revision", "hardwareRevision"), ("--software-revision", "softwareRevision"),
            ):
                if flag in args:
                    properties[field] = args[args.index(flag) + 1]
            if group == "device" and verb == "create":
                properties["enablementState"] = "Enabled"
            namespace = args[args.index("--ns") + 1] if "--ns" in args else name
            device = args[args.index("--rdn") + 1] if "--rdn" in args else None
            output = {
                "id": self.resource_id(group, namespace, name, device), "name": name, "properties": properties,
            }
            if resource and "tags" in resource:
                output["tags"] = deepcopy(resource["tags"])
            if "--tags" in args:
                key, value = args[args.index("--tags") + 1].split("=", 1)
                output["tags"] = {key: value}
            self.resources[group] = output
        else:
            assert verb == "delete", command
            self.resources.pop(group, None)
            output = None
        return Mock(get_output_in_json=lambda: deepcopy(output))


@pytest.mark.parametrize("collision", [None, "device", "attribute"])
def test_lifecycle_cleanup_keeps_collision_quarantine_and_testsdk_json(mocker, collision):
    mocker.patch("azext_iot.tests.adr._readiness.time.sleep")
    scenario = scenarios.TestADRRegistryDeviceLifecycle("test_registry_device_lifecycle")
    scenario.kwargs = {}
    scenario.cli_ctx = Mock()
    backend = _LifecycleBackend(scenario, collision)
    mocker.patch.object(ADRLiveScenarioTest, "cmd", side_effect=lambda command, **_kwargs: backend.cmd(command))
    client = _spec_adr_client()
    for group, operations in (
        ("namespace", client.namespaces), ("device", client.registry_devices), ("attribute", client.registry_device_attributes),
    ):
        operations.get.side_effect = lambda group=group, **scope: backend.sdk_get(group, **scope)
    mocker.patch.object(scenarios, "adr_service_factory", return_value=client)
    if collision is not None:
        with pytest.raises(AssertionError, match="Expected HTTP 404"):
            scenario.test_registry_device_lifecycle()
        assert not any("delete" in command for command in backend.commands)
        assert "namespace" in backend.resources
    else:
        scenario.test_registry_device_lifecycle()
        assert not backend.resources
        commands = [" ".join(tokens) for tokens in backend.commands]
        assert sum("registry-device attribute delete" in command for command in commands) == 1
        assert sum("registry-device delete" in command for command in commands) == 1
        assert sum("iot adr ns delete" in command for command in commands) == 1
        assert backend.update_states == ["Succeeded", "Succeeded"]
        assert len(backend.wait_observations) == 3
        custom, terminal, final = backend.wait_observations
        assert "--custom" in custom[0] and "--updated" in terminal[0] and "--updated" in final[0]
        for _, properties in (custom, terminal):
            assert properties["enablementState"] == "Disabled"
            assert properties["provisioningState"] == "Accepted"
        assert final[1]["enablementState"] == "Enabled"
        assert backend.attribute_list_reads[:2] == [[], []]
        assert len(backend.attribute_list_reads) == 3 and len(backend.attribute_list_reads[-1]) == 1
        # One initial PUT, one intentional replace, one rejected negative PUT;
        # delayed LIST visibility must never introduce an additional mutation.
        assert sum("registry-device attribute create" in command for command in commands) == 3
    scenario.doCleanups()
    assert all(tokens[-2:] == ["--subscription", scenarios.TEST_SUBSCRIPTION] for tokens in backend.commands)
    client.close.assert_called_once()


def test_lifecycle_backend_requires_terminal_wait_after_early_custom_success():
    scenario = scenarios.TestADRRegistryDeviceLifecycle("test_registry_device_lifecycle")
    scenario.kwargs = {}
    backend = _LifecycleBackend(scenario)
    args = "--ns owned -g rg -n device"
    backend.cmd(f"{scenarios.PREFIX} create {args} --external-device-id owned")
    backend.cmd(f"{scenarios.PREFIX} update {args} --enablement-state Disabled --no-wait")
    backend.cmd(f'{scenarios.PREFIX} wait {args} --custom "properties.enablementState==\'Disabled\'"')
    observed = backend.cmd(f"{scenarios.PREFIX} show {args}").get_output_in_json()
    assert observed["properties"]["enablementState"] == "Disabled"
    assert observed["properties"]["provisioningState"] == "Accepted"
    with pytest.raises(HttpResponseError, match="ResourceProvisioningInProgress") as raised:
        backend.cmd(f"{scenarios.PREFIX} update {args} --enablement-state Enabled")
    assert raised.value.status_code == 409
    assert backend.resources["device"]["properties"]["enablementState"] == "Disabled"
    backend.cmd(f"{scenarios.PREFIX} wait {args} --updated")
    backend.cmd(f"{scenarios.PREFIX} update {args} --enablement-state Enabled")
    assert backend.resources["device"]["properties"]["provisioningState"] == "Succeeded"


@pytest.fixture
def attribute_listing_case(mocker):
    """Exercise the exact inline live wait, including its cleanup on failure."""
    mocker.patch("azext_iot.tests.adr._readiness.time.sleep")
    scenario = scenarios.TestADRRegistryDeviceLifecycle("test_registry_device_lifecycle")
    scenario.kwargs = {}
    scenario.cli_ctx = Mock()
    backend = _LifecycleBackend(scenario)
    read = Mock()

    def command(text):
        if text.startswith(f"{scenarios.PREFIX} attribute list "):
            backend.commands.append(shlex.split(text))
            return read()
        return backend.cmd(text)

    scenario.cmd = command
    client = _spec_adr_client()
    for group, operations in (
        ("namespace", client.namespaces), ("device", client.registry_devices), ("attribute", client.registry_device_attributes),
    ):
        operations.get.side_effect = lambda group=group, **scope: backend.sdk_get(group, **scope)
    mocker.patch.object(scenarios, "adr_service_factory", return_value=client)
    elapsed, pauses = [0], []
    real_wait = scenarios.wait_for_condition

    def pause(seconds):
        pauses.append(seconds)
        elapsed[0] += seconds

    def wait(fetch, condition, **kwargs):
        if kwargs["description"] == "owned registry-device attribute list visibility":
            assert kwargs["timeout"] == 120 and kwargs["interval"] == 5
            return real_wait(fetch, condition, **kwargs, clock=lambda: elapsed[0], sleeper=pause)
        return real_wait(fetch, condition, **kwargs)

    mocker.patch.object(scenarios, "wait_for_condition", side_effect=wait)
    yield scenario, backend, read, elapsed, pauses
    scenario.doCleanups()
    client.close.assert_called_once()


def test_attribute_listing_wait_preserves_exact_membership_and_only_polls_reads(attribute_listing_case):
    scenario, backend, read, elapsed, pauses = attribute_listing_case
    pages = []

    def listing():
        attribute_id = backend.resources["attribute"]["id"]
        foreign = {"id": attribute_id + "-foreign"}
        page = [[], [foreign], [foreign, {"id": attribute_id.lower()}]][read.call_count - 1]
        pages.append(page)
        return Mock(get_output_in_json=Mock(return_value=page))

    read.side_effect = listing
    scenario.test_registry_device_lifecycle()
    assert read.call_count == 3 and pages[0] == [] and len(pages[-1]) == 2
    assert pauses == [5, 5] and elapsed[0] == 10
    assert sum(" attribute create " in " ".join(command) for command in backend.commands) == 3
    assert not backend.resources


@pytest.mark.parametrize("page", [[], [{"id": "/foreign/attributes/owned"}]])
def test_attribute_listing_wait_stops_at_120_seconds_without_mutation(attribute_listing_case, page):
    scenario, backend, read, elapsed, pauses = attribute_listing_case
    read.return_value = Mock(get_output_in_json=Mock(return_value=page))
    with pytest.raises(AssertionError, match="Timed out waiting for owned registry-device attribute list visibility"):
        scenario.test_registry_device_lifecycle()
    assert elapsed[0] == 120 and pauses == [5] * 24 and read.call_count == 25
    assert sum(" attribute create " in " ".join(command) for command in backend.commands) == 1
    assert not backend.resources


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_attribute_listing_wait_propagates_first_sdk_error_without_retry(attribute_listing_case, status):
    scenario, backend, read, elapsed, pauses = attribute_listing_case
    error = HttpResponseError("attribute LIST failed")
    error.status_code = status
    read.side_effect = error
    with pytest.raises(HttpResponseError) as raised:
        scenario.test_registry_device_lifecycle()
    assert raised.value is error
    read.assert_called_once()
    assert elapsed[0] == 0 and not pauses and not backend.resources


@pytest.mark.parametrize("error", [SystemExit(3), ValueError("invalid JSON")])
def test_attribute_listing_wait_preserves_cli_and_decode_failures(attribute_listing_case, error):
    scenario, backend, read, elapsed, pauses = attribute_listing_case
    read.return_value = Mock(get_output_in_json=Mock(side_effect=error))
    with pytest.raises(type(error)) as raised:
        scenario.test_registry_device_lifecycle()
    assert raised.value is error
    read.assert_called_once()
    assert elapsed[0] == 0 and not pauses and not backend.resources


def _sdk_error(resource_id, status=404, *, method="GET", host=None):
    error = ResourceNotFoundError("owned target absent") if status == 404 else HttpResponseError("read failed")
    error.status_code = status
    error.response = SimpleNamespace(
        status_code=status,
        request=SimpleNamespace(method=method, url=(host or scenarios.TEST_ARM_ENDPOINT) + resource_id),
    )
    return error


def test_cleanup_uses_sdk_404_while_unwinding_primary_error(mocker):
    mocker.patch("azext_iot.tests.adr._readiness.time.sleep")
    scenario = scenarios.TestADRRegistryDeviceLifecycle("test_registry_device_lifecycle")
    scenario.kwargs = {}
    scenario.cli_ctx = Mock()
    backend = _LifecycleBackend(scenario, primary_failure=True)
    scenario.cmd = backend.cmd
    client = _spec_adr_client()
    for group, operations in (
        ("namespace", client.namespaces), ("device", client.registry_devices), ("attribute", client.registry_device_attributes),
    ):
        operations.get.side_effect = lambda group=group, **scope: backend.sdk_get(group, **scope)
    factory = mocker.patch.object(scenarios, "adr_service_factory", return_value=client)
    with pytest.raises(AssertionError, match="primary lifecycle failure"):
        scenario.test_registry_device_lifecycle()
    factory.assert_called_once_with(scenario.cli_ctx, subscription_id=scenarios.TEST_SUBSCRIPTION)
    assert not backend.resources
    commands = [" ".join(tokens) for tokens in backend.commands]
    assert sum("registry-device delete" in command for command in commands) == 1
    assert sum("iot adr ns delete" in command for command in commands) == 1
    assert "show" not in " ".join(commands[commands.index(next(c for c in commands if "registry-device delete" in c)):])
    scenario.doCleanups()
    client.close.assert_called_once()


OWNED_ID = (
    f"/subscriptions/{scenarios.TEST_SUBSCRIPTION}/resourceGroups/{scenarios.TEST_RG}"
    "/providers/Microsoft.DeviceRegistry/namespaces/owned/registryDevices/device"
)


@pytest.mark.parametrize("error", [
    SystemExit(3), _sdk_error(OWNED_ID, 403), _sdk_error(OWNED_ID, 500),
    _sdk_error(OWNED_ID + "-foreign"), _sdk_error(OWNED_ID, method="DELETE"),
    _sdk_error(OWNED_ID, host="https://foreign.invalid"),
    ResourceNotFoundError("unstructured not-found"),
])
def test_owned_cleanup_does_not_accept_exit_codes_or_unrelated_responses(error):
    test = Mock()
    getter = Mock(side_effect=error)
    with pytest.raises(type(error)) as raised:
        scenarios._remove_owned(test, scenarios.PREFIX, "--ns owned -g rg -n device", getter, OWNED_ID)
    assert raised.value is error
    test.cmd.assert_not_called()


@pytest.mark.parametrize("resource", [None, {}, {"id": OWNED_ID + "-foreign"}])
def test_owned_cleanup_rejects_malformed_or_foreign_success(resource):
    test = Mock()
    with pytest.raises(AssertionError):
        scenarios._remove_owned(test, scenarios.PREFIX, "--ns owned -g rg -n device", lambda: resource, OWNED_ID)
    test.cmd.assert_not_called()


def test_owned_cleanup_rejects_conflicting_authorization_code():
    error = _sdk_error(OWNED_ID)
    error.error = SimpleNamespace(code="AuthorizationFailed")
    test = Mock()
    with pytest.raises(HttpResponseError) as raised:
        scenarios._remove_owned(test, scenarios.PREFIX, "--ns owned -g rg -n device", Mock(side_effect=error), OWNED_ID)
    assert raised.value is error
    test.cmd.assert_not_called()


def test_owned_cleanup_waits_for_exact_404_without_replaying_delete(mocker):
    mocker.patch("azext_iot.tests.adr._helpers.time.sleep")
    getter = Mock(side_effect=[{"id": OWNED_ID.lower()}, {"id": OWNED_ID}, _sdk_error(OWNED_ID)])
    test = Mock()
    scenarios._remove_owned(test, scenarios.PREFIX, "--ns owned -g rg -n device", getter, OWNED_ID)
    test.cmd.assert_called_once_with(f"{scenarios.PREFIX} delete --ns owned -g rg -n device --yes")
    assert getter.call_count == 3


def test_owned_cleanup_of_absent_resource_never_submits_delete():
    getter = Mock(side_effect=_sdk_error(OWNED_ID))
    test = Mock()
    scenarios._remove_owned(test, scenarios.PREFIX, "--ns owned -g rg -n device", getter, OWNED_ID)
    test.cmd.assert_not_called()
    assert getter.call_count == 2


def test_namespace_bound_get_does_not_relax_existing_scope_checks():
    namespace_id = OWNED_ID.rsplit("/registryDevices/", 1)[0]
    command = f"iot adr ns show --namespace owned -g {scenarios.TEST_RG}"
    scenario = Mock()
    getter = Mock(side_effect=_sdk_error(namespace_id))
    assert readiness._get_resource(scenario, command, getter) is None
    scenario.cmd.assert_not_called()
    for error in (SystemExit(3), _sdk_error(namespace_id + "-foreign"), _sdk_error(namespace_id, 403)):
        getter.side_effect = error
        with pytest.raises(type(error)):
            readiness._get_resource(scenario, command, getter)
