# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Exercise private identity-query fixtures without collecting or executing live tests."""

from copy import deepcopy
from functools import partial
from shlex import split
from types import SimpleNamespace
from urllib.parse import urlsplit

import jmespath
import pytest
from requests import Response
from azure.cli.core.azclierror import CLIInternalError
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from knack.util import CLIError

from azext_iot.tests import helpers, iothub
from azext_iot.tests.iothub import conftest as infrastructure
from azext_iot.tests.iothub._integration_helpers import wait_for_query_ids
from azext_iot.tests.iothub.devices import test_iothub_devices_int as subject


pytest_plugins = ["pytester"]


def _arg(args, *names):
    return next((args[args.index(name) + 1] for name in names if name in args), None)


@pytest.fixture
def isolated_backend(mocker):
    mocker.patch.object(infrastructure, "_isolated_hub_pending", None)
    mocker.patch.object(infrastructure.settings.env, "azext_iot_testhub", None)
    mocker.patch.object(iothub.settings.env, "azext_iot_testhub", None)
    mocker.patch.object(infrastructure._sas_phase, "enabled", return_value=False)
    scenario = SimpleNamespace(
        entity_name="shared", entity_rg=infrastructure.RG, host_name="shared.test",
        device_host_name="shared-device.test", region=infrastructure.HUB_TEST_LOCATION,
        _generated_device_ids=[],
    )
    backend = SimpleNamespace(
        active={"shared"}, registries={"shared": {}}, commands=[], reads=[], deletes=[], peak=1,
        failure=None, scenario=scenario, stale=["device7", "device_5", "device_6", "device_7"],
    )
    scenario.cli_ctx = SimpleNamespace()
    original = dict(vars(scenario))
    backend.original = original

    def invoke(command, **_kwargs):
        args = split(command)
        backend.commands.append(args)
        name = _arg(args, "-n", "--hub-name")
        assert _arg(args, "-g", "--resource-group") == infrastructure.RG
        if args[:3] == ["iot", "hub", "show"]:
            raise CLIError(f"An IotHub '{name}' under resource group '{infrastructure.RG}' was not found.")
        elif args[:3] == ["iot", "hub", "create"]:
            assert name not in backend.active
            assert name.startswith("aziotclitest-hub-")
            assert _arg(args, "--disable-local-auth") == "true"
            assert _arg(args, "--location") == infrastructure.HUB_TEST_LOCATION
            if backend.failure == "create":
                raise CLIInternalError("Uncertain Hub create")
            backend.active.add(name)
            backend.registries[name] = {}
            backend.peak = max(backend.peak, len(backend.active))
            output = {
                "id": f"/subscriptions/unit/resourceGroups/{infrastructure.RG}/providers/Microsoft.Devices/IotHubs/{name}",
                "location": infrastructure.HUB_TEST_LOCATION,
                "properties": {"disableLocalAuth": True, "hostName": name + ".test", "deviceHostName": name + "-device.test"},
            }
        elif args[:3] == ["iot", "hub", "delete"]:
            assert name != "shared" and name in backend.active
            backend.deletes.append(name)
            if backend.failure == "delete":
                raise CLIInternalError("Uncertain Hub delete")
            if backend.failure != "absence":
                backend.active.remove(name)
        else:
            # The real shared scenario teardown lists configurations and drains
            # the authoritative registry, never the predecessor's stale query.
            assert args[:4] in (
                ["iot", "edge", "deployment", "list"], ["iot", "hub", "configuration", "list"],
            )
            assert name != "shared"
            output = []
        return SimpleNamespace(
            success=lambda: True, error_code=0, as_json=lambda: output,
        )

    mocker.patch.object(infrastructure.cli, "invoke", side_effect=invoke)
    mocker.patch.object(helpers.cli, "invoke", side_effect=invoke)

    def read_hub(*, resource_group_name, resource_name):
        assert resource_group_name == infrastructure.RG
        backend.reads.append(resource_name)
        if backend.failure == "preflight":
            raise CLIInternalError("Hub preflight failed")
        if resource_name not in backend.active and backend.failure != "collision":
            error = HttpResponseError(message="Hub not found")
            error.status_code = 404
            raise error
        return {"name": resource_name}

    client = mocker.patch.object(infrastructure, "iot_hub_service_factory").return_value.__enter__.return_value
    client.iot_hub_resource.get.side_effect = read_hub
    backend.roles = mocker.patch.object(infrastructure, "assign_iot_hub_dataplane_rbac_role")
    marker = SimpleNamespace(kwargs={"count": 1})
    backend.request = SimpleNamespace(
        instance=scenario, _pyfuncitem=SimpleNamespace(get_closest_marker=lambda _name: marker),
    )
    backend.marker = marker
    backend.providers = []

    def provider(**kwargs):
        name = kwargs["hub_name"]
        assert name != "shared"
        assert kwargs["rg"] == infrastructure.RG
        assert kwargs["auth_type_dataplane"] == "login"
        backend.providers.append(name)
        devices = mocker.Mock()
        devices.get_devices.side_effect = lambda top: list(backend.registries[name].values())[:top]

        def delete(id, if_match):
            assert if_match == "*"
            if id not in backend.registries[name]:
                response = Response()
                response.status_code = 404
                raise HttpResponseError(message="Device already absent", response=response)
            del backend.registries[name][id]

        devices.delete_identity.side_effect = delete
        return SimpleNamespace(service_sdk=SimpleNamespace(devices=devices))

    mocker.patch.object(iothub, "DeviceIdentityProvider", side_effect=provider)
    mocker.patch("azext_iot.iothub.providers.device_identity.DeviceIdentityProvider", side_effect=provider)
    return backend


def _fixture(backend):
    return infrastructure.fixture_isolated_hub.__wrapped__(backend.request)


@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
def test_private_absence_requires_exact_arm_get_404(mocker, status):
    from azext_iot.sdk.iothub.mgmt import IotHubClient
    from azext_iot.tests import _hub_ownership as ownership
    from azext_iot.tests.test_hub_ownership_transport_unit import Credential, Wire

    name = "aziotclitest-hub-" + "a" * 18
    path = (
        f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups/{infrastructure.RG}"
        f"/providers/Microsoft.Devices/IotHubs/{name}"
    )
    wire = Wire()
    wire.handle = mocker.Mock(return_value=(status, {"error": {"code": "TestError", "message": "offline"}}, {}))
    mocker.patch("requests.Session.send", side_effect=lambda request, **kwargs: wire.send(request, **kwargs))
    client = IotHubClient(Credential(), ownership.SUBSCRIPTION, base_url=ownership.ARM, retry_total=0)
    factory = mocker.patch.object(infrastructure, "iot_hub_service_factory", return_value=client)
    command = mocker.patch.object(infrastructure.cli, "invoke", side_effect=AssertionError("No CLI discovery"))
    if status == 404:
        infrastructure._require_absent_hub(name)
    elif status == 200:
        with pytest.raises(CLIInternalError, match="not confirmed absent"):
            infrastructure._require_absent_hub(name)
    else:
        with pytest.raises(HttpResponseError) as raised:
            infrastructure._require_absent_hub(name)
        assert raised.value.status_code == status
    factory.assert_called_once_with(infrastructure.cli.az_cli)
    command.assert_not_called()
    assert len(wire.calls) == 1
    assert wire.calls[0][0] == "GET"
    assert urlsplit(wire.calls[0][1]).path == path


@pytest.mark.parametrize("error", [
    CLIError("An IotHub 'private' under resource group 'rg' was not found."),
    ServiceRequestError("Transport failure"),
    HttpResponseError(message="No HTTP response"),
])
def test_private_absence_does_not_infer_404_from_other_errors(mocker, error):
    client = mocker.patch.object(infrastructure, "iot_hub_service_factory").return_value.__enter__.return_value
    client.iot_hub_resource.get.side_effect = error
    with pytest.raises(type(error)) as raised:
        infrastructure._require_absent_hub("private")
    assert raised.value is error
    client.iot_hub_resource.get.assert_called_once_with(resource_group_name=infrastructure.RG, resource_name="private")


def test_private_absence_does_not_accept_factory_404(mocker):
    error = HttpResponseError(message="Client setup failed")
    error.status_code = 404
    mocker.patch.object(infrastructure, "iot_hub_service_factory", side_effect=error)
    with pytest.raises(HttpResponseError) as raised:
        infrastructure._require_absent_hub("private")
    assert raised.value is error


def _run_identity_body(backend, mocker, extra_query_row=False):
    scenario = backend.scenario
    serial = iter(range(100))
    scenario.create_random_name = lambda prefix, length: prefix + str(next(serial))
    scenario.generate_device_names = partial(iothub.IoTLiveScenarioTest.generate_device_names, scenario)
    scenario.set_cmd_auth_type = lambda command, auth_type: helpers.set_cmd_auth_type(command, auth_type, None)
    scenario.check = lambda path, value: (path, value)
    scenario.exists = lambda path: (path, "exists")
    scenario.is_empty = lambda: []
    queries = []

    def command(text, checks=None, expect_failure=False):
        args = split(text)
        assert _arg(args, "-n", "--hub-name") == scenario.host_name
        assert _arg(args, "-g", "--resource-group") == scenario.entity_rg
        assert _arg(args, "--auth-type") == "login"
        registry = backend.registries[scenario.entity_name]
        device_id = _arg(args, "-d", "--device-id")
        if args[:3] == ["iot", "hub", "query"] or args[:4] == ["iot", "hub", "device-twin", "list"]:
            output = list(deepcopy(registry).values())
            if args[:3] == ["iot", "hub", "query"]:
                assert _arg(args, "-q") == "select * from devices"
                if extra_query_row:
                    output.append({"deviceId": "foreign"})
                if _arg(args, "--top") == "1":
                    output = output[:1]
            elif "--ee" in args:
                output = [row for row in output if row["capabilities"]["iotEdge"]]
            queries.append((args, deepcopy(checks)))
            for path, expected in checks or []:
                value = jmespath.search(path, output)
                assert bool(value) if expected == "exists" else value == expected
        elif args[3] == "create":
            registry[device_id] = {
                "deviceId": device_id, "capabilities": {"iotEdge": "--edge-enabled" in args},
                "authentication": {"symmetricKey": {"primaryKey": "before", "secondaryKey": "before"}},
            }
            output = deepcopy(registry[device_id])
        elif args[3] == "delete":
            del registry[device_id]
            output = None
        elif expect_failure:
            assert device_id not in registry
            output = None
        else:
            if args[3] == "update":
                registry[device_id]["authentication"]["symmetricKey"] = {"primaryKey": "after", "secondaryKey": "after"}
                if _arg(args, "--ee") == "false":
                    registry[device_id]["capabilities"]["iotEdge"] = False
            output = deepcopy(registry[device_id])
        return SimpleNamespace(get_output_in_json=lambda: output)

    scenario.cmd = command
    mocker.patch.object(subject, "wait_for_query_ids", side_effect=partial(wait_for_query_ids, attempts=1, wait=0))
    subject.TestIoTHubDevices.test_iothub_device_identity(scenario)
    return queries


@pytest.mark.parametrize("extra_query_row", [False, True])
def test_private_case_keeps_full_query_semantics_and_actual_owned_cleanup(isolated_backend, mocker, extra_query_row):
    backend = isolated_backend
    fixture = _fixture(backend)
    hub = next(fixture)
    assert backend.registries["shared"] == {}
    assert backend.stale == ["device7", "device_5", "device_6", "device_7"]
    assert backend.scenario.entity_name == hub["name"] != "shared"
    assert backend.scenario.device_host_name == hub["name"] + "-device.test"
    try:
        if extra_query_row:
            with pytest.raises(AssertionError, match="expected IDs.*foreign"):
                _run_identity_body(backend, mocker, extra_query_row=True)
        else:
            queries = _run_identity_body(backend, mocker)
            for edge_phase, cohort_size in enumerate((3, 6)):
                phase = queries[edge_phase * 6:(edge_phase + 1) * 6]
                assert len(phase) == 6  # readiness, default, -1, 1, twin list, edge twin list
                assert [_arg(args, "--top") for args, _ in phase[:4]] == [None, None, "-1", "1"]
                for _, checks in (phase[1], phase[2], phase[4]):
                    assert ("length([*])", cohort_size) in checks
                assert ("length([*])", 1) in phase[3][1]
        # Execute the existing unittest teardown while the private binding is
        # active. Its actual helpers delete only private IDs and confirm empty registry.
        iothub.IoTLiveScenarioTest.tearDown(backend.scenario)
        assert backend.registries[hub["name"]] == {}
    finally:
        fixture.close()
    assert backend.active == {"shared"}
    assert backend.deletes == [hub["name"]]
    assert backend.providers and set(backend.providers) == {hub["name"]}
    assert backend.scenario.entity_name == "shared"
    assert backend.scenario._generated_device_ids is backend.original["_generated_device_ids"]
    assert backend.stale == ["device7", "device_5", "device_6", "device_7"]


@pytest.mark.parametrize("failure", ["preflight", "collision", "create", "role", "delete", "absence"])
def test_private_lifecycle_never_adopts_or_replays_and_blocks_uncertain_capacity(isolated_backend, failure):
    backend = isolated_backend
    backend.failure = failure
    if failure == "role":
        backend.roles.side_effect = CLIInternalError("Role assignment failed")
    fixture = _fixture(backend)
    with pytest.raises(CLIInternalError):
        next(fixture)
        fixture.close()
    create_count = sum(args[:3] == ["iot", "hub", "create"] for args in backend.commands)
    assert create_count == (0 if failure in ("preflight", "collision") else 1)
    assert len(backend.deletes) == (1 if failure in ("role", "delete", "absence") else 0)
    assert backend.scenario.entity_name == "shared"
    if failure in ("create", "delete", "absence"):
        before = len(backend.commands)
        with pytest.raises(CLIInternalError, match="unresolved"):
            infrastructure._iot_hubs_provisioner(backend.request)
        assert len(backend.commands) == before
    else:
        assert infrastructure._isolated_hub_pending is None


def test_identity_private_lifetime_fits_existing_four_hub_reservation(isolated_backend):
    from azext_iot.tests import _hub_phase_runner, _hub_suite_manifest

    backend = isolated_backend
    fixture = _fixture(backend)
    next(fixture)
    assert backend.peak == 2  # one shared Hub plus the function-scoped private Hub
    fixture.close()
    assert backend.reads == [backend.deletes[0], backend.deletes[0]]
    assert not any(args[:3] == ["iot", "hub", "show"] for args in backend.commands)
    # Even conservatively overlapping BOTH existing state pools costs only four:
    # shared + two dataplane Hubs + the separate negative-state module's Hub.
    backend.marker.kwargs["count"] = 2
    dataplane = infrastructure.provisioned_only_iot_hubs_module.__wrapped__(backend.request)
    next(dataplane)
    backend.marker.kwargs["count"] = 1
    negative = infrastructure.provisioned_only_iot_hubs_module.__wrapped__(backend.request)
    next(negative)
    assert backend.peak == _hub_phase_runner.SLOTS["entra"] == 4
    with pytest.raises(StopIteration):
        next(negative)
    with pytest.raises(StopIteration):
        next(dataplane)
    assert backend.active == {"shared"}
    nodes = _hub_suite_manifest.nodes("HubData", "entra")
    identity = next(index for index, node in enumerate(nodes) if node.endswith("::test_iothub_device_identity"))
    assert all(index > identity for index, node in enumerate(nodes) if "/state/" in node)


def test_only_identity_uses_function_scoped_private_fixture():
    assert infrastructure.fixture_isolated_hub._pytestfixturefunction.scope == "function"
    for name, method in vars(subject.TestIoTHubDevices).items():
        if name.startswith("test_"):
            fixtures = [mark.args for mark in getattr(method, "pytestmark", []) if mark.name == "usefixtures"]
            assert fixtures == ([("fixture_isolated_hub",)] if name == "test_iothub_device_identity" else [])


@pytest.mark.parametrize("borrowed", [False, True])
def test_private_case_rejects_sas_or_borrowed_scope_before_commands(isolated_backend, mocker, borrowed):
    if borrowed:
        mocker.patch.object(infrastructure.settings.env, "azext_iot_testhub", "borrowed")
    else:
        mocker.patch.object(infrastructure._sas_phase, "enabled", return_value=True)
    with pytest.raises(CLIInternalError, match="dynamically owned Entra"):
        next(_fixture(isolated_backend))
    assert not isolated_backend.commands


@pytest.mark.parametrize("focused", [False, True])
def test_pytest_binding_spans_unittest_teardown_in_full_and_focused_runs(pytester, focused):
    # Synthetic unittest cases only: never collect the live scenario or create
    # its constructor-time shared Hub. Exercise real pytest fixture ordering.
    config = pytester.makeini("[pytest]")
    path = pytester.makepyfile("""
        import unittest
        import pytest
        from azext_iot.tests import iothub
        from azext_iot.tests.iothub import conftest as infrastructure
        from azext_iot.tests.iothub.devices.test_iothub_device_isolation_unit import isolated_backend

        @pytest.fixture
        def fixture_isolated_hub(request, isolated_backend):
            instance = request.instance
            for key, value in isolated_backend.original.items():
                setattr(instance, key, value)
            instance.backend = isolated_backend
            yield from infrastructure.fixture_isolated_hub.__wrapped__(request)
            assert instance.entity_name == 'shared'
            assert isolated_backend.active == {'shared'}
            assert len(isolated_backend.deletes) == 1

        class TestLifecycle(unittest.TestCase):
            @pytest.mark.usefixtures('fixture_isolated_hub')
            def test_private(self):
                assert self.entity_name.startswith('aziotclitest-hub-')
                self._generated_device_ids.append('owned')
                self.backend.registries[self.entity_name]['owned'] = {'deviceId': 'owned'}

            def test_ordinary(self):
                assert not hasattr(self, 'backend')

            def tearDown(self):
                if self._testMethodName == 'test_private':
                    assert self.entity_name.startswith('aziotclitest-hub-')
                    iothub.IoTLiveScenarioTest.tearDown(self)
                    assert self.backend.registries[self.entity_name] == {}
    """)
    node = str(path) + ("::TestLifecycle::test_private" if focused else "")
    result = pytester.inline_run(
        "-c", str(config), "--rootdir", str(pytester.path), "--confcutdir", str(pytester.path),
        node, "-q", "-p", "pytest_mock", "-o", "addopts=",
    )
    result.assertoutcome(passed=1 if focused else 2)
