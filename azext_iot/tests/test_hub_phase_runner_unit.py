# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline controller/ownership regressions; no constructors, credentials or live ARM."""

from pathlib import Path
import subprocess
import sys
import time
import json
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest

from azext_iot.tests import _hub_ownership as ownership
from azext_iot.tests import _hub_phase_runner as runner
from azext_iot.tests import _hub_suite_plugin as plugin
from azext_iot.tests import _dps_phase_runner as dps_runner

PREFIX = f"/subscriptions/{ownership.SUBSCRIPTION}/resourceGroups/{ownership.GROUP}/providers/"


def record(resource_id, run_id="uid"):
    return {
        "id": resource_id, "apiVersion": "test-version", "before": 404, "attempted": True,
        "resolved": True, "uncertain": False, "ownerTag": run_id,
        "mutations": [{"method": "PUT", "id": resource_id, "status": 200}],
    }


class Reader:
    deadline = None

    def __init__(self, count=0):
        self.count = count
        self.calls = []

    def inventory(self):
        # Includes foreign ADU/DPS-owned Hubs without any DPS-service inventory API.
        return [PREFIX + "Microsoft.Devices/IotHubs/foreign-" + str(i) for i in range(self.count)]

    def request(self, method, resource_id, api):
        self.calls.append((method, resource_id, api))
        return 404, None


def execute_factory(damage=None, handlers=None):
    calls = []

    def execute(command, env, log_path, runtime, cleanup, cancelled):
        phase, suite = env["AZEXT_IOT_HUB_PHASE"], env["AZEXT_IOT_HUB_SUITE"]
        calls.append(phase)
        assert command[0] == sys.executable and command[1:3] == ["-m", "pytest"]
        assert "tox" not in command and "--timeout=900" in command
        assert env["PYTHONPATH"] == "inherited-dependencies"
        assert runtime == dict(runner.BUDGETS[suite])[phase] and cleanup == runner.CLEANUP
        expected = list(runner.selection()["nodes"](suite, phase))
        receipt = plugin.PhaseReceipt(
            suite, phase, expected, Path(env["AZEXT_IOT_HUB_RECEIPT"]), env["AZEXT_IOT_HUB_RUN_ID"],
        )
        receipt.data.update(
            collected=expected[:],
            reports={node: {stage: ["passed"] for stage in ("setup", "call", "teardown")} for node in expected},
            finished=True, exitstatus=0, errors=[],
        )
        if phase != "sas" and damage in ("skip", "failure"):
            receipt.data["reports"][expected[0]]["call"] = [damage]
        if phase != "sas" and damage == "duplicate":
            receipt.data["collected"].append(expected[0])
        receipt.write()
        path = Path(env["AZEXT_IOT_HUB_OWNERSHIP"])
        if phase == "sas":
            hub = PREFIX + "Microsoft.Devices/IotHubs/test-hubsas-sas-owner"
            storage = PREFIX + "Microsoft.Storage/storageAccounts/hubsassas-owner"
            ids = {"hub": hub, "storage": storage,
                   "role": hub + "/providers/Microsoft.Authorization/roleAssignments/role",
                   "container": storage + "/blobServices/default/containers/devices"}
            mutations = ["PUT " + value.casefold() for value in ids.values()]
            data = {"phase": "local-auth", "runUid": "sas-owner", "ids": ids, "mutations": mutations,
                    "statuses": dict.fromkeys(mutations, 200), "absent": list(ids), "passed": expected,
                    "cleanupFailures": {}, "consumerGroupIds": [
                        (hub + "/eventHubEndpoints/events/ConsumerGroups/" + name).casefold()
                        for name in ("test1", "test2", "test3", "test4")
                    ], "deviceIds": []}
        else:
            resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + phase).casefold()
            data = {"schemaVersion": 1, "installed": True, "phase": phase, "runId": env["AZEXT_IOT_HUB_RUN_ID"],
                    "resources": {resource_id: record(resource_id, env["AZEXT_IOT_HUB_RUN_ID"])}, "violations": []}
            if damage == "cleanup":
                data["resources"][resource_id]["uncertain"] = True
            if damage == "cancel":
                handlers[runner.signal.SIGTERM](None, None)
        ownership.write(path, data)
        if phase != "sas" and damage == "missing":
            Path(env["AZEXT_IOT_HUB_RECEIPT"]).unlink()
        return {"exit_code": 1 if damage == "exit" and phase != "sas" else 0,
                "timed_out": damage == "timeout", "interrupted": damage == "cancel",
                "cleanup_deadline": time.monotonic() + 30}

    return execute, calls


def run(tmp_path, suite="HubData", damage=None, reader=None):
    handlers = {}
    execute, calls = execute_factory(damage, handlers)
    # This helper uses only fake execution/ARM; never install real OS handlers.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(dps_runner, "require_linux", lambda: None)
        patch.setattr(runner.signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler))
        result = runner.run(suite, ownership.SUBSCRIPTION, ownership.GROUP, ownership.REGION, tmp_path / "phases",
                            arm=reader or Reader(), execute=execute, base={"PYTHONPATH": "inherited-dependencies"})
    return result, calls


@pytest.mark.parametrize("suite", ["HubControl", "HubData"])
def test_controller_success_and_stdlib_only_gate(tmp_path, suite):
    result, calls = run(tmp_path, suite=suite)
    assert result == 0
    assert calls == [phase for phase, _ in runner.BUDGETS[suite]]
    script = (
        "import runpy,sys\n"
        "def guard(name, *args):\n"
        "    if name.startswith(('azure', 'pytest', 'azext_iot')): raise AssertionError(name)\n"
        "import builtins\noriginal=builtins.__import__\n"
        "def checked(name,*args,**kwargs):\n    guard(name)\n    return original(name,*args,**kwargs)\n"
        "builtins.__import__=checked\n"
        "gate=runpy.run_path(sys.argv[1])['evaluate_hub_phases']\n"
        "assert gate(sys.argv[2]) == {'passed': True, 'errors': []}\n"
    )
    completed = subprocess.run([sys.executable, "-I", "-c", script, runner.__file__, str(tmp_path / "phases")],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("damage", ["skip", "failure", "missing", "duplicate", "cancel", "cleanup", "exit", "timeout"])
def test_controller_fail_closed(tmp_path, damage):
    result, calls = run(tmp_path, damage=damage)
    assert result == 1
    assert not runner.evaluate_hub_phases(tmp_path / "phases")["passed"]
    assert calls == (["entra"] if damage in ("cancel", "cleanup", "timeout") else ["entra", "sas"])


@pytest.mark.parametrize("damage", ["phase", "duplicate", "ownership", "absent", "status", "sas-pass", "sas-uncertain"])
def test_gate_revalidates_evidence_not_summary_exit(tmp_path, damage):
    assert run(tmp_path)[0] == 0
    output = tmp_path / "phases"
    path = output / "hub-phases.json"
    if damage in ("phase", "duplicate"):
        data = runner.read_json(path)
        data["phases"] = data["phases"][:1] if damage == "phase" else data["phases"] * 2
    elif damage in ("ownership", "absent", "status"):
        path = output / "entra" / ("ownership.json" if damage == "ownership" else "cleanup.json")
        data = runner.read_json(path)
        if damage == "ownership":
            next(iter(data["resources"].values()))["before"] = 200
        elif damage == "absent":
            data["absentIds"] = []
        else:
            data["complete"] = False
    else:
        path = output / "sas/ownership.json"
        data = runner.read_json(path)
        if damage == "sas-pass":
            data["passed"] = data["passed"][:-1]
        else:
            del data["statuses"][data["mutations"][0]]
    ownership.write(path, data)
    assert not runner.evaluate_hub_phases(output)["passed"]


@pytest.mark.parametrize("key", [
    "azext_iot_testhub", "azext_iot_teststorageaccount", "azext_iot_ep_rg", "AZURE_IOT_AUTH_TYPE",
    "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "AZEXT_IOT_HUB_RUN_ID", "azext_iot_hub_auth_phase",
])
def test_ambient_overrides_rejected(tmp_path, key):
    with pytest.raises(ValueError, match="override"):
        runner.environment({key: "foreign"}, "HubData", "entra", tmp_path, "uid",
                           ownership.SUBSCRIPTION, ownership.GROUP)


def test_auth_environments_are_independent(tmp_path):
    base = {"PYTHONPATH": "existing", "AZURE_CONFIG_DIR": "/existing/never-copied"}
    regular = runner.environment(base, "HubData", "entra", tmp_path, "one", ownership.SUBSCRIPTION, ownership.GROUP)
    sas = runner.environment(base, "HubData", "sas", tmp_path, "two", ownership.SUBSCRIPTION, ownership.GROUP)
    assert regular["azext_iot_hub_auth_phase"] == "regular"
    assert sas["azext_iot_hub_auth_phase"] == "local-auth"
    assert regular["AZURE_IOT_AUTH_TYPE"] == sas["AZURE_IOT_AUTH_TYPE"] == "login"
    assert base == {"PYTHONPATH": "existing", "AZURE_CONFIG_DIR": "/existing/never-copied"}


def test_coverage_is_cumulative_and_junit_omits_diagnostics(tmp_path):
    command = runner.command("HubData", "entra")
    assert "--cov=azext_iot" in command and "--cov-append" in command
    assert "--junitxml" not in " ".join(command)
    node = runner.selection()["nodes"]("HubData", "entra")[0]
    path = tmp_path / "junit.xml"
    runner.write_junit(
        {"phase": "entra", "reports": {node: {"call": ["failed"]}}, "diagnostic": "sensitive-output"},
        [node], path,
    )
    assert "sensitive-output" not in path.read_text(encoding="utf-8")
    assert list(ET.parse(path).getroot().iter("testcase"))[0].find("error") is not None


def test_gate_requires_sanitized_junit_for_every_phase(tmp_path):
    assert run(tmp_path)[0] == 0
    (tmp_path / "phases/sas/junit.xml").unlink()
    assert not runner.evaluate_hub_phases(tmp_path / "phases")["passed"]


def test_unsupported_platform_rejects_before_output_credentials_or_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    reader = Mock()
    with pytest.raises(RuntimeError, match="Linux"):
        runner.run("HubData", ownership.SUBSCRIPTION, ownership.GROUP, ownership.REGION, tmp_path / "no",
                   arm=reader, base={})
    assert not reader.mock_calls and not (tmp_path / "no").exists()


def test_capacity_includes_foreign_hubs_and_prospective_separate_fixtures(tmp_path):
    result, calls = run(tmp_path, reader=Reader(count=48))
    assert result == 1 and not calls
    assert runner.SLOTS["entra"] >= 3


def test_observer_precreate_evidence_and_no_uncertain_replay(tmp_path):
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "entra", Reader())
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    root = observer.prepare("PUT", resource_id, "api", {"properties": {"disableLocalAuth": True}})
    receipt = runner.read_json(tmp_path / "owner.json")
    assert receipt["resources"][root]["before"] == 404
    assert receipt["resources"][root]["mutations"][0]["status"] is None
    with pytest.raises(ownership.OwnershipError, match="Uncertain"):
        observer.prepare("PUT", resource_id, "api", {})
    assert len(observer.data["resources"][root]["mutations"]) == 1


@pytest.mark.parametrize("kind", ["foreign", "local-auth", "outside", "unplanned"])
def test_observer_does_not_own_or_delete_foreign_resources(tmp_path, kind):
    reader = Reader()
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "entra", reader)
    resource_id = PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32
    body = {"properties": {"disableLocalAuth": True}}
    method = "PUT"
    if kind == "foreign":
        reader.request = Mock(return_value=(200, {"id": resource_id}))
    elif kind == "local-auth":
        body["properties"]["disableLocalAuth"] = False
    elif kind == "outside":
        resource_id = resource_id.replace(ownership.GROUP, "foreign-group")
    else:
        method = "DELETE"
    with pytest.raises(ownership.OwnershipError):
        observer.prepare(method, resource_id, "api", body)
    assert not observer.data["resources"]


def test_parent_cleanup_durable_intent_multiple_roots_and_no_sweep(tmp_path):
    ids = sorted((PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + str(i)).casefold() for i in range(2))
    evidence = {"schemaVersion": 1, "installed": True, "runId": "uid", "phase": "entra",
                "resources": {key: record(key) for key in ids}, "violations": []}
    path = tmp_path / "owner.json"
    deleted = []
    reader = Reader()

    def request(method, resource_id, api):
        assert resource_id in ids
        if method == "DELETE":
            persisted = runner.read_json(path)["resources"][resource_id]
            assert persisted["uncertain"] and persisted["mutations"][-1]["status"] is None
            deleted.append(resource_id)
            return 202, None
        return (404, None) if resource_id in deleted else (
            200, {"id": resource_id, "tags": {ownership.OWNER_TAG: "uid"}})

    reader.request = request
    result = runner.cleanup_regular(reader, evidence, "uid", "entra", time.monotonic() + 30, path)
    assert result["complete"] and result["absentIds"] == ids and deleted == ids
    evidence["resources"][ids[0]]["uncertain"] = True
    reader.request = Mock(side_effect=AssertionError("Uncertain cleanup must not make any ARM request"))
    assert not runner.cleanup_regular(reader, evidence, "uid", "entra", time.monotonic() + 30, path)["complete"]


def test_process_scope_explicit_tokens_endpoint_and_restore(monkeypatch):
    import requests
    from azure.cli.core._profile import Profile
    token = Mock(return_value=("never-persist", None, None))
    subscription = Mock(return_value={"id": ownership.SUBSCRIPTION})
    send = Mock(return_value="response")
    monkeypatch.setattr(Profile, "get_raw_token", token)
    monkeypatch.setattr(Profile, "get_subscription", subscription)
    monkeypatch.setattr(requests.Session, "send", send)
    scope = ownership.ProcessScope()
    scope.install()
    try:
        Profile.get_raw_token(object(), resource=ownership.AUDIENCE)
        assert token.call_args.kwargs["subscription"] == ownership.SUBSCRIPTION
        assert token.call_args.kwargs["resource"] == ownership.AUDIENCE
        Profile.get_raw_token(object(), scopes=["https://management.core.windows.net/.default"])
        assert token.call_args.kwargs["scopes"] == [ownership.AUDIENCE + ".default"]
        Profile.get_raw_token(object(), resource="https://iothubs.azure.net")
        assert token.call_args.kwargs["resource"] == "https://iothubs.azure.net"
        request = requests.Request("GET", "https://management.azure.com" + PREFIX).prepare()
        assert requests.Session().send(request) == "response"
        assert request.url.startswith(ownership.ARM)
        assert send.call_args.kwargs["allow_redirects"] is False
        with pytest.raises(ownership.OwnershipError):
            Profile.get_raw_token(object(), subscription="foreign")
    finally:
        scope.restore()
    assert Profile.get_raw_token is token and Profile.get_subscription is subscription
    assert requests.Session.send is send


def test_parent_refuses_replaced_foreign_resource(tmp_path):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-replaced").casefold()
    data = {"schemaVersion": 1, "installed": True, "runId": "uid", "phase": "entra", "violations": [],
            "resources": {resource_id: record(resource_id)}}
    reader = Reader()
    reader.request = Mock(return_value=(200, {"id": resource_id, "tags": {ownership.OWNER_TAG: "foreign"}}))
    result = runner.cleanup_regular(reader, data, "uid", "entra", time.monotonic() + 30, tmp_path / "owner.json")
    assert not result["complete"] and result["errors"]
    assert reader.request.call_count == 1 and reader.request.call_args.args[0] == "GET"


def test_ownership_plugin_installs_before_integration_imports(monkeypatch, tmp_path):
    monkeypatch.setattr(dps_runner, "require_linux", lambda: None)
    monkeypatch.setenv("AZEXT_IOT_HUB_SUITE", "HubData")
    monkeypatch.setenv("AZEXT_IOT_HUB_PHASE", "entra")
    monkeypatch.setenv("AZEXT_IOT_HUB_RUN_ID", "uid")
    monkeypatch.setenv("AZEXT_IOT_HUB_RECEIPT", str(tmp_path / "pytest.json"))
    monkeypatch.setenv("AZEXT_IOT_HUB_OWNERSHIP", str(tmp_path / "owner.json"))
    monkeypatch.setenv("azext_iot_hub_auth_phase", "regular")
    monkeypatch.setattr(plugin, "validate_args", Mock())
    observer, scope = Mock(), Mock()
    monkeypatch.setattr(ownership, "Observer", Mock(return_value=observer))
    monkeypatch.setattr(ownership, "ProcessScope", Mock(return_value=scope))
    monkeypatch.setattr(ownership, "Arm", Mock())
    config = Mock()
    plugin.pytest_load_initial_conftests(config, None, [])
    scope.install.assert_called_once()
    observer.install.assert_called_once()
    assert config.add_cleanup.call_count == 2


def test_observer_transport_tags_conditional_create_and_uncertain_no_replay(tmp_path, monkeypatch):
    import json
    import requests
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "b" * 32).casefold()
    sends = []

    def send(_session, request, **kwargs):
        sends.append(request)
        assert runner.read_json(tmp_path / "owner.json")["resources"][resource_id]["uncertain"]
        assert request.headers["If-None-Match"] == "*"
        assert json.loads(request.body)["tags"][ownership.OWNER_TAG] == "uid"
        assert request.url.startswith(ownership.ARM) and kwargs["allow_redirects"] is False
        raise TimeoutError("Unknown server acceptance")

    monkeypatch.setattr(requests.Session, "send", send)
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "entra", Reader())
    observer.install()
    try:
        for index in range(2):
            request = requests.Request(
                "PUT", "https://management.azure.com" + resource_id + "?api-version=test",
                json={"location": ownership.REGION, "properties": {"disableLocalAuth": True}},
            ).prepare()
            with pytest.raises(TimeoutError if index == 0 else ownership.OwnershipError):
                requests.Session().send(request)
        assert len(sends) == 1
    finally:
        observer.restore()


@pytest.mark.parametrize("suffix", ["/../foreign", "/%2e%2e/foreign", "?query=foreign", "//foreign"])
def test_scope_rejects_path_normalization_escape(suffix):
    assert not ownership.scope_id(PREFIX + "Microsoft.Devices/IotHubs/test-hub" + suffix)


def test_owned_certificate_actions_are_recorded_and_unknown_post_is_blocked(tmp_path, monkeypatch):
    import requests
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-cert").casefold()
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "regular", Reader())
    observer.data["resources"][resource_id] = record(resource_id)
    observer.arm.request = Mock(return_value=(200, {"id": resource_id, "tags": {ownership.OWNER_TAG: "uid"}}))
    response = requests.Response()
    response.status_code = 200
    send = Mock(return_value=response)
    monkeypatch.setattr(requests.Session, "send", send)
    observer.install()
    try:
        for action in ("generateVerificationCode", "verify", "unexpected"):
            request = requests.Request(
                "POST", ownership.ARM + resource_id + "/certificates/test/" + action + "?api-version=api",
            ).prepare()
            if action == "unexpected":
                with pytest.raises(ownership.OwnershipError):
                    requests.Session().send(request)
            else:
                requests.Session().send(request)
        assert send.call_count == 2
        mutations = observer.data["resources"][resource_id]["mutations"]
        assert [item["action"] for item in mutations[1:]] == ["generateverificationcode", "verify"]
        assert ownership.descendants(observer.data) == {resource_id + "/certificates/test": "api"}
    finally:
        observer.restore()


def test_cleanup_requires_exact_descendant_absence(tmp_path):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-descendant").casefold()
    child_id = resource_id + "/providers/microsoft.authorization/roleassignments/owned-role"
    evidence = {"schemaVersion": 1, "installed": True, "runId": "uid", "phase": "entra", "violations": [],
                "resources": {resource_id: record(resource_id)}}
    evidence["resources"][resource_id]["mutations"].append(
        {"method": "PUT", "id": child_id, "apiVersion": "role-version", "status": 201})
    reader = Reader()
    reader.request = Mock(side_effect=lambda method, target, api: (200, {}) if target == child_id else (404, None))
    result = runner.cleanup_regular(reader, evidence, "uid", "entra", time.monotonic() + 30, tmp_path / "owner.json")
    assert not result["complete"] and result["absentIds"] == [resource_id]
    assert result["descendantIds"] == [child_id] and not result["absentDescendantIds"]


def test_budgets_leave_external_setup_below_github_cap():
    for suite, job_minutes in (("HubControl", 190), ("HubData", 360)):
        controller = sum(seconds + runner.CLEANUP for _, seconds in runner.BUDGETS[suite]) + runner.RESERVE
        assert controller + 15 * 60 == job_minutes * 60 <= 360 * 60


@pytest.mark.parametrize("kind,name", [
    ("Microsoft.Devices/IotHubs", "test-hub-" + "a" * 32),
    ("Microsoft.Devices/IotHubs", "aziotclitest-hub-" + "a" * 18),
    ("Microsoft.Storage/storageAccounts", "hubstoreabcd"),
    ("Microsoft.Storage/storageAccounts", "aziotclitest" + "a" * 12),
    ("Microsoft.ManagedIdentity/userAssignedIdentities", "a" * 32),
    ("Microsoft.ManagedIdentity/userAssignedIdentities", "aziotclitest" + "a" * 12),
    ("Microsoft.EventHub/namespaces", "aziotclitest" + "a" * 12),
    ("Microsoft.ServiceBus/namespaces", "sb" + "a" * 22),
    ("Microsoft.DocumentDB/databaseAccounts", "scos" + "a" * 32),
])
def test_actual_fixture_naming_contracts_and_foreign_preexistence(tmp_path, kind, name):
    reader = Reader()
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "regular", reader)
    resource_id = (PREFIX + kind + "/" + name).casefold()
    body = {"location": ownership.REGION, "properties": {"disableLocalAuth": True}}
    observer.prepare("PUT", resource_id, "api", body)
    assert reader.calls[-1] == ("GET", resource_id, "api")
    assert observer.data["resources"][resource_id]["before"] == 404
    foreign = ownership.Observer(tmp_path / "foreign.json", "uid", "regular", reader)
    reader.request = Mock(return_value=(200, {"id": resource_id, "tags": {ownership.OWNER_TAG: "uid"}}))
    with pytest.raises(ownership.OwnershipError, match="pre-existing"):
        foreign.prepare("PUT", resource_id, "api", body)
    assert not foreign.data["resources"]
    assert not ownership.planned_root(resource_id + "foreign")


def test_ownership_accepts_names_from_real_fixture_generators():
    from azext_iot.tests.iothub.conftest import generate_hub_id, generate_hub_depenency_id
    assert ownership.planned_root(PREFIX + "Microsoft.Devices/IotHubs/" + generate_hub_id())
    for kind in ownership.ROOT_TYPES - {("microsoft.devices", "iothubs")}:
        assert ownership.planned_root(PREFIX + "/".join(kind) + "/" + generate_hub_depenency_id())


@pytest.fixture
def wire(tmp_path, monkeypatch):
    """HTTP boundary without network, credentials, or real POSIX timers."""
    import requests
    reader = Reader()
    resources, requests_sent = {}, []

    def get(method, target, api):
        reader.calls.append((method, target, api))
        if method == "DELETE":
            for key in list(resources):
                if key == target or key.startswith(target + "/"):
                    del resources[key]
            return 202, None
        return (200, resources[target]) if target in resources else (404, None)

    def send(_session, request, **_kwargs):
        requests_sent.append(request)
        target = ownership.urlsplit(request.url).path.casefold()
        body = json.loads(request.body or "{}")
        if request.method == "PUT":
            if "/deployments/" in target:
                persisted = runner.read_json(tmp_path / "owner.json")
                assert persisted["resources"][target]["mutations"][-1]["status"] is None
                hub_targets = [mutation for item in persisted["resources"].values() for mutation in item["mutations"]
                               if mutation.get("deployment") == target]
                assert len(hub_targets) == len(body["properties"]["template"]["resources"])
                assert all(mutation["status"] is None for mutation in hub_targets)
            resources[target] = dict(body, id=target)
            resources[target].setdefault("properties", {})["provisioningState"] = "Succeeded"
            if "/deployments/" in target:
                for item in body["properties"]["template"]["resources"]:
                    parts = item["type"].split("/")
                    names = item["name"].split("/")
                    resource_path = PREFIX + parts[0] + "/" + parts[1] + "/" + names[0]
                    if len(parts) == 3:
                        resource_path += "/" + parts[2] + "/" + names[1]
                    resources[resource_path.casefold()] = dict(item, id=resource_path.casefold())
                    if len(parts) == 2:
                        resources[resource_path.casefold()]["properties"]["provisioningState"] = "Succeeded"
        elif request.method == "DELETE":
            resources.pop(target, None)
        return Mock(status_code=201 if request.method == "PUT" else 200, headers={},
                    json=lambda: resources.get(target, {}))

    reader.request = get
    monkeypatch.setattr(requests.Session, "send", send)
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "regular", reader)
    observer.install()

    def submit(method, target, body=None):
        request = requests.Request(method, ownership.ARM + target + "?api-version=api", json=body).prepare()
        return requests.Session().send(request)

    try:
        yield observer, reader, resources, requests_sent, submit
    finally:
        observer.restore()


def fixture_template():
    template = runner.read_json(Path(__file__).parent / "iothub/state/blank_hub_arm.json")
    template["resources"][0]["name"] = "aziotclitest-hub-" + "a" * 18
    return template


def test_observer_preserves_sdk_acknowledgement_timeout(wire, monkeypatch):
    import requests
    observer, _, _, _, _ = wire
    original = observer.original_send
    send = Mock(side_effect=original)
    monkeypatch.setattr(observer, "original_send", send)
    hub = PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32
    request = requests.Request(
        "PUT", ownership.ARM + hub + "?api-version=api",
        json={"properties": {"disableLocalAuth": True}},
    ).prepare()
    requests.Session().send(request, timeout=(10, 300))
    assert send.call_args.kwargs["timeout"] == (10, 300)


def test_transport_exception_records_only_type_and_never_authorizes_replay(wire, monkeypatch, tmp_path):
    import requests
    observer, _, _, _, submit = wire
    monkeypatch.setattr(observer, "original_send", Mock(side_effect=requests.ReadTimeout("private diagnostic")))
    hub = PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32
    with pytest.raises(requests.ReadTimeout):
        submit("PUT", hub, {"properties": {"disableLocalAuth": True}})
    persisted = runner.read_json(tmp_path / "owner.json")
    mutation = persisted["resources"][hub.casefold()]["mutations"][0]
    assert mutation["status"] is None and mutation["transportError"] == "ReadTimeout"
    assert "private diagnostic" not in json.dumps(persisted)
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        submit("PUT", hub, {"properties": {"disableLocalAuth": True}})


@pytest.mark.parametrize("create,certificates", [(False, False), (True, False), (True, True), (False, True)])
def test_state_deployment_exact_blank_and_provider_forms(wire, tmp_path, create, certificates):
    observer, reader, resources, requests_sent, submit = wire
    template = fixture_template()
    hub = template["resources"][0]
    hub["tags"] = {"abc": "def"}
    hub_id = (PREFIX + hub["type"] + "/" + hub["name"]).casefold()
    identity_id = (PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/" + "b" * 32).casefold()
    submit("PUT", identity_id, {"location": ownership.REGION})
    eventhub_name = "aziotclitest" + "d" * 12
    submit("PUT", (PREFIX + "Microsoft.EventHub/namespaces/" + eventhub_name).casefold(),
           {"location": ownership.REGION})
    hub["identity"] = {"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {identity_id: {}}}
    hub["properties"]["routing"]["endpoints"]["eventHubs"] = [{
        "name": "eventhub-userid", "authenticationType": "identityBased",
        "identity": {"userAssignedIdentity": identity_id}, "resourceGroup": ownership.GROUP,
        "subscriptionId": ownership.SUBSCRIPTION, "endpointUri": f"sb://{eventhub_name}.servicebus.windows.net",
        "entityPath": "events",
    }]
    if certificates:
        template["resources"].append({
            "type": "Microsoft.Devices/IotHubs/certificates", "name": hub["name"] + "/testCert",
            "apiVersion": hub["apiVersion"], "properties": {"certificate": "test-public-certificate"},
            "dependsOn": [f"[resourceId('Microsoft.Devices/IotHubs', '{hub['name']}')]"],
        })
    if not create:
        submit("PUT", hub_id, hub)
    name = "arm_deployment-" + hub["name"] if certificates else "c" * 32
    deployment = (PREFIX + "Microsoft.Resources/deployments/" + name).casefold()
    body = {"properties": {"mode": "Incremental", "parameters": {}, "template": template}}
    submit("POST", deployment + "/validate", body)
    submit("PUT", deployment, body)
    creates = [request for request in requests_sent if request.method == "PUT"]
    assert all(request.headers["If-None-Match"] == "*" for request in creates)
    assert creates[-1].url.startswith(ownership.ARM + deployment)
    persisted = runner.read_json(tmp_path / "owner.json")
    assert persisted["resources"][deployment]["deploymentTargets"][0] == hub_id
    mutations = persisted["resources"][hub_id]["mutations"]
    assert len([mutation for mutation in mutations if mutation.get("deployment") == deployment]) == len(template["resources"])
    assert resources[hub_id]["tags"] == {"abc": "def", ownership.OWNER_TAG: "uid"}
    # Simulate the SDK polling only /operations/...; the parent must reconcile.
    result = runner.cleanup_regular(reader, observer.data, "uid", "regular", time.monotonic() + 5,
                                    tmp_path / "owner.json")
    assert result["complete"], result
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    assert deployment in result["absentIds"]
    assert result["descendantIds"] == ([hub_id + "/certificates/testcert"] if certificates else [])
    assert not resources


@pytest.mark.parametrize("damage", [
    "complete", "linked", "nested", "expression", "copy", "foreign-hub", "foreign-cert",
    "foreign-identity", "second-hub", "parameters", "foreign-deployment",
])
def test_deployment_rejects_unplanned_targets_before_any_submission(wire, damage):
    observer, _, resources, requests_sent, submit = wire
    template = fixture_template()
    hub = template["resources"][0]
    deployment = (PREFIX + "Microsoft.Resources/deployments/arm_deployment-" + hub["name"]).casefold()
    props = {"mode": "Incremental", "template": template}
    if damage == "complete":
        props["mode"] = "Complete"
    elif damage == "linked":
        props["templateLink"] = {"uri": "https://foreign.invalid/template"}
    elif damage == "nested":
        hub["resources"] = [{"type": "Microsoft.Resources/deployments"}]
    elif damage == "expression":
        hub["name"] = "[parameters('name')]"
    elif damage == "copy":
        hub["copy"] = {"name": "x", "count": 100}
    elif damage == "foreign-hub":
        hub["name"] = "foreign"
    elif damage in ("foreign-cert", "second-hub"):
        template["resources"].append(dict(hub, name="foreign/cert" if damage == "foreign-cert" else hub["name"]))
    elif damage == "foreign-identity":
        hub["identity"] = {"userAssignedIdentities": {PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/x": {}}}
    elif damage == "parameters":
        props["parameters"] = {"name": {"value": "foreign"}}
    else:
        resources[deployment] = {"id": deployment, "tags": {ownership.OWNER_TAG: "foreign"}}
    with pytest.raises(ownership.OwnershipError):
        submit("PUT", deployment, {"properties": props})
    assert not requests_sent and not observer.data["resources"]


@pytest.mark.parametrize("action", ["routing/routes/$testnew", "routing/routes/$testall", "exportTemplate"])
def test_readonly_actions_require_exact_owned_roots(wire, action):
    observer, _, _, requests_sent, submit = wire
    hub = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    submit("PUT", hub, {"properties": {"disableLocalAuth": True}})
    target = (hub if action != "exportTemplate" else hub.split("/providers/")[0]) + "/" + action
    body = {"resources": [hub], "options": "SkipAllParameterization"} if action == "exportTemplate" else {}
    submit("POST", target, body)
    assert len(observer.data["resources"][hub]["mutations"]) == 1
    with pytest.raises(ownership.OwnershipError):
        submit("POST", target if action == "exportTemplate" else target.replace("test-hub-", "foreign-hub-"),
               {"resources": ["*"]} if action == "exportTemplate" else {})
    assert len(requests_sent) == 2


@pytest.mark.parametrize("status", [None, 202, 429, 500])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_parent_reconciles_only_acknowledged_async_acceptance(tmp_path, status, method):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    item = record(resource_id)
    if method == "DELETE":
        item["mutations"].append({"method": method, "id": resource_id, "apiVersion": "api", "status": status})
    else:
        item["mutations"][0]["status"] = status
        item["resolved"] = False
    item["uncertain"] = True
    evidence = {"schemaVersion": 1, "installed": True, "runId": "uid", "phase": "entra",
                "resources": {resource_id: item}, "violations": []}
    reader = Reader()
    if method == "PUT" and status == 202:
        reader.request = Mock(side_effect=[
            (200, {"id": resource_id, "tags": {ownership.OWNER_TAG: "uid"}, "properties": {"provisioningState": "Succeeded"}}),
            (404, None), (404, None),
        ])
    result = runner.cleanup_regular(reader, evidence, "uid", "entra", time.monotonic() + 1, tmp_path / "owner.json")
    assert result["complete"] is (status == 202)
    if status != 202:
        assert not reader.calls
        ownership.observe_get(evidence, resource_id, 404, None)
        assert item["uncertain"]


def test_route_definitive_rejection_is_evidence_not_a_pass_and_distinct_update_allowed(wire, monkeypatch):
    from azext_iot.tests.iothub.message_endpoint.test_iothub_message_route_int import generate_names

    observer, _, _, _, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    submit("PUT", hub_id, {"properties": {"disableLocalAuth": True}})
    observer.current_node = ownership.ROUTE_REJECTION_NODE
    invalid = {"properties": {"routing": {"routes": [{"endpointNames": generate_names(prefix="ep")}], "endpoints": {}}}}
    original = observer.original_send
    monkeypatch.setattr(observer, "original_send", Mock(return_value=Mock(status_code=400)))
    submit("PUT", hub_id, invalid)
    assert ownership.expected_rejection(observer.data["resources"][hub_id]["mutations"][-1])
    assert not observer.data["resources"][hub_id]["uncertain"]
    monkeypatch.setattr(observer, "original_send", original)
    submit("PUT", hub_id, {"properties": {"routing": {"routes": [{"endpointNames": ["events"]}]}}})
    assert not ownership.ownership_errors(observer.data, "uid", "regular")
    assert runner.phase_errors({}, [ownership.ROUTE_REJECTION_NODE], "HubControl", "regular", "uid")
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        submit("PUT", hub_id, invalid)


@pytest.mark.parametrize("status", [400, 401, 403, 408, 429, 500])
@pytest.mark.parametrize("damage", [None, "other-node", "no-removal", "no-reference", "changed-routes", "foreign-name"])
def test_endpoint_rejection_requires_actual_fixture_removal_and_unchanged_references(wire, monkeypatch, status, damage):
    from copy import deepcopy
    from azext_iot.tests.iothub.message_endpoint.test_iothub_message_endpoint_int import generate_ep_names

    observer, _, _, _, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    endpoint = generate_ep_names()[0] if damage != "foreign-name" else "unplanned-endpoint"
    routing = {
        "endpoints": {"serviceBusTopics": [{"name": endpoint}]},
        "routes": [{"name": "route", "endpointNames": [endpoint]}],
        "enrichments": [{"key": "key", "endpointNames": [endpoint], "value": "value"}],
    }
    submit("PUT", hub_id, {"properties": {"disableLocalAuth": True, "routing": routing}})
    observer.current_node = ownership.ENDPOINT_REJECTION_NODE if damage != "other-node" else "other-node"
    invalid = deepcopy(routing)
    invalid["endpoints"]["serviceBusTopics"] = []
    if damage == "no-removal":
        invalid["endpoints"] = deepcopy(routing["endpoints"])
    elif damage == "no-reference":
        invalid["routes"], invalid["enrichments"] = [], []
    elif damage == "changed-routes":
        invalid["routes"][0]["name"] = "different-route"
    body = {"properties": {"routing": invalid}}
    original = observer.original_send
    monkeypatch.setattr(observer, "original_send", Mock(return_value=Mock(status_code=status)))
    submit("PUT", hub_id, body)
    mutation = observer.data["resources"][hub_id]["mutations"][-1]
    assert ownership.expected_rejection(mutation) is (status == 400 and damage is None)
    assert bool(ownership.ownership_errors(observer.data, "uid", "regular")) is not (status == 400 and damage is None)
    if status == 400 and damage is None:
        monkeypatch.setattr(observer, "original_send", original)
        with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
            submit("PUT", hub_id, body)
        invalid["routes"], invalid["enrichments"] = [], []
        submit("PUT", hub_id, body)
        assert not observer.data["resources"][hub_id]["uncertain"]


@pytest.mark.parametrize("status", [202, 429, 500, None])
def test_transport_never_replays_accepted_or_ambiguous_update_even_after_get(wire, monkeypatch, status):
    observer, reader, resources, _, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    submit("PUT", hub_id, {"properties": {"disableLocalAuth": True}})
    sender = Mock(return_value=Mock(status_code=status, headers={}, content=b""))
    if status is None:
        sender.side_effect = TimeoutError("transport outcome unknown")
    monkeypatch.setattr(observer, "original_send", sender)
    update = {"properties": {"routing": {"routes": []}}}
    if status is None:
        with pytest.raises(TimeoutError):
            submit("PUT", hub_id, update)
    else:
        submit("PUT", hub_id, update)
    record_ = observer.data["resources"][hub_id]
    if status == 202:
        resources[hub_id]["properties"]["provisioningState"] = "Updating"
        reader.deadline = time.monotonic()
    # Even a subsequent exact GET404 must not turn unknown acceptance into permission.
    if status != 202:
        ownership.observe_get(observer.data, hub_id, 404, None)
        assert record_["uncertain"]
    with pytest.raises(ownership.OwnershipError, match="cannot be replayed"):
        submit("PUT", hub_id, update)
    assert sender.call_count == 1


@pytest.mark.parametrize("initial", [False, True])
def test_unexpected_400_is_not_success_or_initial_ownership(wire, monkeypatch, initial):
    observer, _, _, _, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    body = {"properties": {"disableLocalAuth": True}}
    if not initial:
        submit("PUT", hub_id, body)
    monkeypatch.setattr(observer, "original_send", Mock(return_value=Mock(status_code=400)))
    submit("PUT", hub_id, body)
    record_ = observer.data["resources"][hub_id]
    assert record_["resolved"] is not initial
    assert not record_["uncertain"]
    assert ownership.ownership_errors(observer.data, "uid", "regular")
    if initial:
        with pytest.raises(ownership.OwnershipError, match="Failed initial creation"):
            submit("PUT", hub_id, {"properties": {"disableLocalAuth": True, "routes": []}})


@pytest.mark.parametrize("status", [400, 429, 500])
def test_failed_cleanup_response_cannot_produce_passed_receipt(tmp_path, status):
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    evidence = {"schemaVersion": 1, "installed": True, "runId": "uid", "phase": "entra",
                "resources": {hub_id: record(hub_id)}, "violations": []}
    reader = Reader()
    reader.request = Mock(side_effect=[
        (200, {"id": hub_id, "tags": {ownership.OWNER_TAG: "uid"}}), (status, None), (404, None),
    ])
    result = runner.cleanup_regular(reader, evidence, "uid", "entra", time.monotonic() + 1, tmp_path / "owner.json")
    assert not result["complete"] and result["errors"] and not result["absentIds"]
    assert reader.request.call_count == 2
    assert ownership.ownership_errors(evidence, "uid", "entra")


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_pure_controller_helpers_do_not_need_real_platform_signals(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    assert run(tmp_path, damage="cancel")[0] == 1
    assert runner.read_json(tmp_path / "phases/hub-phases.json")["cancelled"]


def test_deployment_targets_wait_for_deployment_success_not_just_old_hub_state(wire, monkeypatch):
    observer, reader, resources, _, submit = wire
    template = fixture_template()
    hub = template["resources"][0]
    deployment = (PREFIX + "Microsoft.Resources/deployments/arm_deployment-" + hub["name"]).casefold()
    submit("PUT", deployment, {"properties": {"mode": "Incremental", "template": template}})
    resources[deployment]["properties"]["provisioningState"] = "Running"
    sleeps = []

    def progress(_seconds):
        sleeps.append(True)
        hub_id = (PREFIX + hub["type"] + "/" + hub["name"]).casefold()
        assert observer.data["resources"][hub_id]["uncertain"]
        resources[deployment]["properties"]["provisioningState"] = "Succeeded"

    monkeypatch.setattr(ownership.time, "sleep", progress)
    ownership.reconcile(reader, observer.data, time.monotonic() + 3, observer.save)
    assert len(sleeps) == 1
    assert not ownership.ownership_errors(observer.data, "uid", "regular")


@pytest.mark.parametrize("method,state", [("PUT", "Failed"), ("PUT", "Creating"), ("DELETE", "Succeeded")])
def test_async_nonterminal_or_failed_get_is_not_success(tmp_path, method, state):
    resource_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    observer = ownership.Observer(tmp_path / "owner.json", "uid", "regular", Reader())
    item = record(resource_id)
    item["mutations"].append({"method": method, "id": resource_id, "status": 202})
    item["uncertain"] = True
    observer.data["resources"][resource_id] = item
    ownership.observe_get(observer.data, resource_id, 200, {
        "id": resource_id, "tags": {ownership.OWNER_TAG: "uid"}, "properties": {"provisioningState": state},
    })
    assert item["uncertain"] and not item["mutations"][-1].get("reconciled")


def test_tag_removal_update_preserves_owner_and_foreign_descendant_is_never_mutated(wire):
    observer, _, resources, requests_sent, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    submit("PUT", hub_id, {"tags": {"fixture": "value"}, "properties": {"disableLocalAuth": True}})
    submit("PUT", hub_id, {"tags": None})
    assert resources[hub_id]["tags"] == {ownership.OWNER_TAG: "uid"}
    resources[hub_id]["tags"][ownership.OWNER_TAG] = "foreign"
    with pytest.raises(ownership.OwnershipError, match="ownership tag"):
        submit("PUT", hub_id + "/certificates/test", {"properties": {"certificate": "public"}})
    assert len(requests_sent) == 2 and observer.data["violations"]


def test_actual_cli_jsonc_deployment_creates_absent_hub_without_direct_put(wire):
    import requests
    from azure.core.pipeline import PipelineContext, PipelineRequest
    from azure.core.pipeline.transport import HttpRequest
    from azure.cli.command_modules.resource.custom import JsonCTemplatePolicy
    from azure.mgmt.resource.deployments import DeploymentsMgmtClient
    from azure.mgmt.resource.deployments.models import Deployment, DeploymentProperties

    observer, reader, resources, requests_sent, _ = wire
    template = fixture_template()
    hub = template["resources"][0]
    hub_id = (PREFIX + hub["type"] + "/" + hub["name"]).casefold()
    deployment = (PREFIX + "Microsoft.Resources/deployments/arm_deployment-" + hub["name"]).casefold()
    client = DeploymentsMgmtClient(object(), ownership.SUBSCRIPTION)
    model = Deployment(properties=DeploymentProperties(mode="Incremental", template=json.dumps(template)))
    serialized = client.deployments._serialize.body(model, "Deployment")
    # Verify real SDK tag support rather than simulating unsupported persistence.
    tagged = Deployment(properties=model.properties, tags={ownership.OWNER_TAG: "uid"})
    assert client.deployments._serialize.body(tagged, "Deployment")["tags"] == {ownership.OWNER_TAG: "uid"}
    url = ownership.ARM + deployment + "?api-version=" + client.deployments._config.api_version
    http = HttpRequest("PUT", url)
    http.set_json_body(serialized)
    JsonCTemplatePolicy().on_request(PipelineRequest(http, PipelineContext(None)))
    assert b", template:" in http.data
    with pytest.raises(json.JSONDecodeError):
        json.loads(http.data)
    assert ownership.request_body(http.data)["properties"]["template"] == template
    assert hub_id not in resources
    requests.Session().send(requests.Request("PUT", url, data=http.data).prepare())
    assert len(requests_sent) == 1 and requests_sent[0].url == url
    assert hub_id in resources
    creation = observer.data["resources"][hub_id]["mutations"][0]
    assert creation["status"] == 202 and creation["before"] == 404
    assert creation["deployment"] == deployment
    assert ("GET", hub_id, hub["apiVersion"]) in reader.calls
    ownership.reconcile(reader, observer.data, time.monotonic() + 1, observer.save)
    assert not ownership.ownership_errors(observer.data, "uid", "regular")


def test_confirmed_async_a_then_b_then_a_is_a_new_update(wire, monkeypatch):
    observer, reader, _, requests_sent, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    submit("PUT", hub_id, {"properties": {"disableLocalAuth": True}})
    original = observer.original_send

    def accepted(session, request, **kwargs):
        response = original(session, request, **kwargs)
        response.status_code = 202
        return response

    monkeypatch.setattr(observer, "original_send", accepted)
    body = {"properties": {"disableLocalAuth": True}, "tags": {"value": "A"}}
    submit("PUT", hub_id, body)
    ownership.reconcile(reader, observer.data, time.monotonic() + 1, observer.save)
    monkeypatch.setattr(observer, "original_send", original)
    submit("PUT", hub_id, dict(body, tags={"value": "B"}))
    submit("PUT", hub_id, body)
    assert len(requests_sent) == 4
    assert not ownership.ownership_errors(observer.data, "uid", "regular")


@pytest.mark.parametrize("damage", [None, "unknown", "disappeared", "capacity", "history"])
def test_same_name_generation_recreation_and_parent_cleanup(wire, tmp_path, damage):
    observer, reader, resources, requests_sent, submit = wire
    hub_id = (PREFIX + "Microsoft.Devices/IotHubs/test-hub-" + "a" * 32).casefold()
    body = {"properties": {"disableLocalAuth": True}}
    submit("PUT", hub_id, body)
    if damage == "disappeared":
        del resources[hub_id]
    else:
        submit("DELETE", hub_id)
    if damage == "unknown":
        observer.data["resources"][hub_id]["mutations"][-1]["status"] = None
        observer.data["resources"][hub_id]["uncertain"] = True
    if damage == "capacity":
        reader.count = 50
    if damage in ("unknown", "disappeared", "capacity"):
        with pytest.raises(ownership.OwnershipError):
            submit("PUT", hub_id, body)
        assert len(requests_sent) == (1 if damage == "disappeared" else 2)
        return
    submit("PUT", hub_id, body)
    current = observer.data["resources"][hub_id]
    assert current["generation"] == 2 and len(current["generations"]) == 1
    assert requests_sent[-1].headers["If-None-Match"] == "*"
    assert current["generations"][0]["mutations"][-1]["absenceConfirmed"]
    if damage == "history":
        current["generations"][0]["mutations"][-1]["status"] = None
    result = runner.cleanup_regular(reader, observer.data, "uid", "regular", time.monotonic() + 1,
                                    tmp_path / "owner.json")
    assert result["complete"] is (damage is None)
    assert bool([call for call in reader.calls if call[0] == "DELETE"]) is (damage is None)


@pytest.mark.parametrize("raw", [
    '{"properties": {template: {"resources": []}}}',
    '{"properties": {"mode": "Incremental", template: {resources: []}}}',
    '{"properties": {"mode": "Incremental", template: __import__("os")}}',
])
def test_cli_envelope_parser_rejects_non_policy_or_non_json_templates(raw):
    with pytest.raises((ownership.OwnershipError, json.JSONDecodeError)):
        ownership.request_body(raw)
