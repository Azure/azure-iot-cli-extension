# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
import json
import logging
import os
import subprocess
import sys
import shlex
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import responses
from azure.cli.core.azclierror import ForbiddenError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from knack.util import CLIError

from azext_iot.tests.iothub import _sas_phase as subject
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.iothub._integration_helpers import assert_hub_policy


REPO = Path(__file__).resolve().parents[3]


def configuration(args=subject.NODES, **options):
    options.setdefault("capture", "fd")
    return SimpleNamespace(
        args=list(args), getoption=lambda name, default=None: options.get(name, default),
        getini=lambda _name: False, pluginmanager=Mock(),
    )


@pytest.fixture
def phase(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "True")
    monkeypatch.setenv("azext_iot_hubsas_subscription", "subscription")
    monkeypatch.setenv("azext_iot_hubsas_receipt", str(tmp_path / "receipt.json"))
    runtime = subject.HubSasPhase(configuration(), "hub", "storage", "rg", "centraluseuap")
    monkeypatch.setattr(runtime, "command", Mock())
    yield runtime
    runtime.restore()


@pytest.mark.parametrize("value,expected", [("regular", False), ("local-auth", True)])
def test_phase_is_explicit(value, expected, monkeypatch):
    monkeypatch.setenv(subject.ENV, value)
    assert subject.enabled() is expected


@pytest.mark.parametrize("value", ["", "true", "false", "sas", "LOCAL-AUTH"])
def test_invalid_phase_fails_closed(value, monkeypatch):
    monkeypatch.setenv(subject.ENV, value)
    with pytest.raises(pytest.UsageError):
        subject.enabled()


def test_default_is_regular(monkeypatch):
    monkeypatch.delenv(subject.ENV, raising=False)
    assert not subject.enabled()


@pytest.mark.parametrize("args", [
    [], ["azext_iot/tests/iothub"], list(reversed(subject.NODES)),
    subject.NODES[1:], subject.NODES + (subject.NODES[0],),
    subject.NODES + ("azext_iot/tests/dps",),
])
def test_exact_arguments_fail_before_constructors(args):
    with pytest.raises(pytest.UsageError):
        subject.validate_selection(configuration(args))


def test_exact_upload_first_arguments_are_accepted():
    subject.validate_selection(configuration())
    subject.validate_selection(configuration(["./" + node for node in subject.NODES]))


@pytest.mark.parametrize("options", [
    {"numprocesses": 1}, {"keyword": "_int"}, {"markexpr": "sas"}, {"deselect": [subject.NODES[0]]},
    {"capture": "no"}, {"showlocals": True}, {"reruns": 1},
])
def test_unsafe_execution_options_rejected(options):
    with pytest.raises(pytest.UsageError):
        subject.validate_selection(configuration(**options))


@pytest.mark.parametrize("pin", subject.PINS)
def test_resource_pins_are_rejected(pin, monkeypatch):
    monkeypatch.setenv(pin, "borrowed")
    with pytest.raises(pytest.UsageError):
        subject.validate_selection(configuration())


def test_collection_must_preserve_order(phase):
    phase.pytest_collection_modifyitems([SimpleNamespace(nodeid=node) for node in subject.NODES])
    with pytest.raises(pytest.UsageError):
        phase.pytest_collection_modifyitems([SimpleNamespace(nodeid=node) for node in reversed(subject.NODES)])


def test_all_six_existing_nodes_have_conditional_not_unconditional_skips():
    for node in subject.NODES:
        path, cls, method = node.split("::")
        tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
        owner = next(value for value in tree.body if isinstance(value, ast.ClassDef) and value.name == cls)
        function = next(value for value in owner.body if isinstance(value, ast.FunctionDef) and value.name == method)
        decorators = [ast.unparse(value) for value in function.decorator_list]
        assert len(decorators) == 1
        assert decorators[0].startswith("pytest.mark.skipif(not sas_phase_enabled(),")


def test_http_case_has_only_the_local_three_auth_matrix():
    path = REPO / subject.NODES[-1].split("::", maxsplit=1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    loops = [value for value in ast.walk(tree) if isinstance(value, ast.For) and ast.unparse(value.target) == "auth_phase"]
    assert len(loops) == 1 and ast.unparse(loops[0].iter) == "AUTH_TYPES"
    assert subject.AUTH_TYPES == ("key", "login", "cstring")


@pytest.mark.parametrize("method", ["test_device_messaging", "test_hub_monitor_events"])
def test_background_clients_use_scoped_scenario_context(method):
    path = REPO / subject.NODES[1].split("::", maxsplit=1)[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(value for value in tree.body if isinstance(value, ast.ClassDef) and value.name == "TestIoTHubMessaging")
    function = next(value for value in owner.body if isinstance(value, ast.FunctionDef) and value.name == method)
    factories = [
        value for value in ast.walk(function)
        if isinstance(value, ast.Call) and ast.unparse(value.func) == "iot_hub_service_factory"
    ]
    assert len(factories) == 1
    assert len(factories[0].args) == 1 and ast.unparse(factories[0].args[0]) == "self.cli_ctx"


@pytest.mark.parametrize("phase_name,disabled", [("regular", True), ("local-auth", False)])
def test_scenario_creation_preserves_default_and_explicit_cohort(phase_name, disabled, monkeypatch):
    monkeypatch.setenv(subject.ENV, phase_name)
    scenario = SimpleNamespace(entity_name="hub", entity_rg="rg", cmd=Mock(), storage_cstring="unit", storage_container="devices")
    IoTLiveScenarioTest._create_hub(scenario)
    command = scenario.cmd.call_args.args[0]
    assert f"--disable-local-auth {str(disabled).lower()}" in command
    assert "--location centraluseuap" in command and "--fc devices --fcs unit" in command
    assert_hub_policy({"location": "centraluseuap", "properties": {"disableLocalAuth": disabled}}, disabled)


def test_regular_policy_still_rejects_local_auth():
    with pytest.raises(AssertionError):
        assert_hub_policy({"location": "centraluseuap", "properties": {"disableLocalAuth": False}})


def test_receipt_precedes_writes_and_cannot_be_overwritten(phase):
    receipt = json.loads(phase.path.read_text(encoding="utf-8"))
    assert receipt["ids"] == phase.ids
    assert receipt["mutations"] == []
    assert len(receipt["consumerGroupIds"]) == 4
    phase.command.assert_not_called()
    with pytest.raises(pytest.UsageError):
        subject.HubSasPhase(configuration(), "hub", "storage", "rg", "centraluseuap")


def test_wrong_first_constructor_cannot_create(phase):
    with pytest.raises(subject.HubSasError):
        phase.provision(SimpleNamespace(_testMethodName="test_device_messaging"))
    phase.command.assert_not_called()


def test_preexisting_resource_never_adopted_or_deleted(phase, monkeypatch):
    monkeypatch.setattr(phase, "read", Mock(return_value={"id": "borrowed"}))
    with pytest.raises(subject.HubSasError):
        phase.provision(SimpleNamespace(_testMethodName="test_device_upload_file"))
    phase.cleanup()
    phase.command.assert_not_called()


def test_constructor_failure_is_not_replayed(phase, monkeypatch):
    monkeypatch.setattr(phase, "read", Mock(return_value=None))
    phase.command.side_effect = ServiceRequestError("Uncertain create")
    scenario = SimpleNamespace(_testMethodName="test_device_upload_file")
    with pytest.raises(ServiceRequestError):
        phase.provision(scenario)
    with pytest.raises(subject.HubSasError, match="not be replayed"):
        phase.provision(scenario)
    assert phase.command.call_count == 1


def test_one_cohort_is_shared_without_recreating_or_regranting(phase, monkeypatch):
    target = {"id": phase.ids["hub"], "properties": {"disableLocalAuth": False}}
    reads = iter([None, None, None, target, {"id": phase.ids["role"]}])
    monkeypatch.setattr(phase, "read", lambda _kind: next(reads))
    waits = Mock()
    monkeypatch.setattr(subject, "sleep", waits)
    phase.command.return_value = {"user": {"name": "caller"}}
    scenario = SimpleNamespace(_testMethodName="test_device_upload_file", cmd=Mock(), _create_hub=Mock())
    scenario.cmd.return_value.get_output_in_json.return_value = {"connectionString": "unit-storage-cstring"}
    assert phase.provision(scenario) is target
    assert phase.provision(SimpleNamespace(_testMethodName="test_device_messaging")) is target
    assert phase.provision(SimpleNamespace(_testMethodName="test_iothub_c2d_messages_http")) is target
    scenario._create_hub.assert_called_once()
    assert phase.command.call_count == 3  # Storage create, account metadata, one role create.
    assert [call.args[0] for call in waits.call_args_list] == [10, 120]
    assert scenario.storage_cstring == "unit-storage-cstring"


def request(phase, method="PUT", kind="storage"):
    return requests.Request(method, "https://management.azure.com" + phase.ids[kind], json={
        "location": "centraluseuap", "tags": {"runUid": subject.UID},
        "properties": {"disableLocalAuth": False}, "sku": {"name": "S1"},
    }).prepare()


@pytest.mark.parametrize("status", [None, 200, 201, 202, 400, 403, 500, 502])
def test_transport_records_before_send_and_never_replays(phase, monkeypatch, status):
    observed = []

    def transport(_session, _request, **_kwargs):
        observed.append(json.loads(phase.path.read_text(encoding="utf-8"))["mutations"])
        if status is None:
            raise requests.ConnectionError("Uncertain")
        return SimpleNamespace(status_code=status)

    monkeypatch.setattr(requests.Session, "send", transport)
    phase.install()
    session = requests.Session()
    if status is None:
        with pytest.raises(requests.ConnectionError):
            session.send(request(phase))
    else:
        session.send(request(phase))
    with pytest.raises(subject.HubSasError, match="Repeated"):
        session.send(request(phase))
    assert len(observed) == 1 and observed[0]


def test_unowned_transport_fails_before_send(phase, monkeypatch):
    transport = Mock()
    monkeypatch.setattr(requests.Session, "send", transport)
    phase.install()
    outside = requests.Request("DELETE", "https://management.azure.com/subscriptions/other/hub").prepare()
    with pytest.raises(subject.HubSasError):
        requests.Session().send(outside)
    transport.assert_not_called()


@pytest.mark.parametrize("wrong", ["location", "owner", "dla", "sku"])
def test_resource_write_policy_is_verified_before_transport(phase, monkeypatch, wrong):
    transport = Mock()
    monkeypatch.setattr(requests.Session, "send", transport)
    phase.install()
    prepared = request(phase, kind="hub")
    body = json.loads(prepared.body)
    if wrong == "location":
        body["location"] = "westus2"
    elif wrong == "owner":
        body["tags"]["runUid"] = "other"
    elif wrong == "dla":
        body["properties"]["disableLocalAuth"] = True
    else:
        body["sku"]["name"] = "S2"
    prepared.body = json.dumps(body)
    with pytest.raises(subject.HubSasError):
        requests.Session().send(prepared)
    transport.assert_not_called()


def cleanup_resource(phase, monkeypatch, *, deleting=False):
    key = "PUT " + phase.ids["storage"].casefold()
    phase.sent.add(key)
    phase.statuses[key] = 201
    resource = {"id": phase.ids["storage"], "tags": {"runUid": subject.UID},
                "properties": {"provisioningState": "Deleting" if deleting else "Succeeded"}}
    reads = iter([resource, None])
    monkeypatch.setattr(phase, "read", lambda kind: next(reads) if kind == "storage" else None)
    monkeypatch.setattr(subject, "sleep", lambda _seconds: None)

    def delete(_command):
        phase.sent.add("DELETE " + phase.ids["storage"].casefold())

    phase.command.side_effect = delete
    return resource


@pytest.mark.parametrize("deleting", [False, True])
def test_cleanup_observes_deleting_and_never_repeats_delete(phase, monkeypatch, deleting):
    cleanup_resource(phase, monkeypatch, deleting=deleting)
    phase.cleanup()
    assert phase.command.call_count == (0 if deleting else 1)
    assert phase.absent == set(phase.ids)


def test_cleanup_refuses_wrong_owner(phase, monkeypatch):
    resource = cleanup_resource(phase, monkeypatch)
    resource["tags"]["runUid"] = "other"
    with pytest.raises(subject.HubSasError, match="ownership"):
        phase.cleanup()
    phase.command.assert_not_called()


def test_cleanup_non404_propagates(phase, monkeypatch):
    cleanup_resource(phase, monkeypatch)
    phase.command.side_effect = ForbiddenError("Denied")
    with pytest.raises(ForbiddenError):
        phase.cleanup()


@pytest.mark.parametrize("error", [ResourceNotFoundError("Gone"), ForbiddenError("Denied")])
def test_reads_only_accept_actual_not_found(phase, error):
    phase.command.side_effect = error
    if isinstance(error, ResourceNotFoundError):
        assert phase.read("storage") is None
    else:
        with pytest.raises(ForbiddenError):
            phase.read("storage")


def test_uncertain_creation_first_404_does_not_prove_cleanup(phase, monkeypatch):
    clock = [0]
    monkeypatch.setattr(subject, "monotonic", lambda: clock[0])
    monkeypatch.setattr(subject, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(phase, "read", lambda _kind: None)
    phase.sent.add("PUT " + phase.ids["hub"].casefold())
    with pytest.raises(subject.HubSasError, match="budget"):
        phase.cleanup(timeout=10)
    assert "hub" not in phase.absent


def test_background_failure_surfaces_and_cleanup_is_bounded():
    tasks = subject.BackgroundTasks()
    thread = Mock()
    thread.is_alive.return_value = False
    stop = Mock()
    tasks.tasks = [(stop, thread, ["ValueError"])]
    with pytest.raises(subject.HubSasError, match="ValueError"):
        tasks.finish(timeout=0)
    stop.set.assert_called_once()
    thread.join.assert_called_once_with(0)
    assert not tasks.tasks


def test_real_background_worker_exception_reaches_owner():
    entered = threading.Event()

    def fail(value):
        assert value == "original-argument"
        entered.set()
        raise ValueError("Synthetic worker failure")

    tasks = subject.BackgroundTasks()
    tasks.start(method=fail, args={"value": "original-argument"}, max_runs=1, interval=0)
    assert entered.wait(2)
    with pytest.raises(subject.HubSasError, match="ValueError"):
        tasks.finish(timeout=2)


def test_unfinished_background_prevents_resource_cleanup(phase):
    thread = Mock()
    thread.is_alive.return_value = True
    phase.tasks.tasks = [(Mock(), thread, [])]
    with pytest.raises(subject.HubSasError, match="must not be deleted"):
        phase.cleanup()
    phase.command.assert_not_called()
    assert 0 <= thread.join.call_args.args[0] <= 90


@pytest.mark.parametrize("text", [
    "--login 'HostName=h;SharedAccessKey=secret-value'",
    "https://storage/blob?%73ig=secret-value",
    "Bearer secret-value",
    '{"primaryKey": "secret-value", "connectionString": "secret-value"}',
    "-----BEGIN PRIVATE KEY-----\nsecret-value\n-----END PRIVATE KEY-----",
])
def test_reports_redact_credentials(text):
    assert "secret-value" not in subject.sanitize(text)


def test_logging_filter_retains_pem_state_across_records(phase):
    phase.install()
    factory = logging.getLogRecordFactory()
    results = [
        factory("test", logging.ERROR, "", 0, line, (), None).getMessage()
        for line in ("-----BEGIN PRIVATE KEY-----", "secret-value", "-----END PRIVATE KEY-----")
    ]
    assert "secret-value" not in "".join(results)


def test_pytest_report_and_junit_are_sanitized_before_artifacts(phase, tmp_path):
    from _pytest.reports import TestReport
    from _pytest.junitxml import LogXML
    secret = "--login 'HostName=hub;SharedAccessKey=secret-value'"
    report = TestReport(
        nodeid=subject.NODES[0], location=("example.py", 1, "test"), keywords={},
        outcome="failed", longrepr=secret, when="call",
        sections=[("Captured stdout call", "https://storage/blob?sig=secret-value")],
        user_properties=[("diagnostic", "Bearer secret-value")],
    )
    hook = phase.pytest_runtest_makereport()
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(SimpleNamespace(get_result=lambda: report))
    assert phase.bad_report
    output = tmp_path / "junit.xml"
    junit = LogXML(str(output), prefix=None, logging="all", family="xunit2")
    junit.pytest_sessionstart()
    junit.pytest_runtest_logreport(report)
    report.when, report.outcome, report.longrepr = "teardown", "passed", None
    junit.pytest_runtest_logreport(report)
    junit.pytest_sessionfinish()
    assert "secret-value" not in output.read_text(encoding="utf-8")


def test_real_http_body_exercises_key_login_and_cstring(monkeypatch):
    from azext_iot.tests.iothub.messaging import test_iothub_c2d_messages_int as messaging
    monkeypatch.setattr(messaging, "sleep", Mock())
    scenario = object.__new__(messaging.TestIoTHubC2DMessages)
    scenario.entity_name, scenario.host_name, scenario.entity_rg = "hub", "hub.example", "rg"
    scenario.kwargs = {}
    scenario.generate_device_names = Mock(return_value=["device"])
    scenario.is_empty = Mock(return_value=None)
    sends = []

    def invoke(command, **_kwargs):
        args = shlex.split(command)
        result = {}
        if args[:4] == ["iot", "hub", "connection-string", "show"]:
            result = {"connectionString": "HostName=hub;SharedAccessKeyName=owner;SharedAccessKey=unit"}
        elif args[:4] == ["iot", "device", "c2d-message", "send"]:
            sends.append(args)
        elif args[:4] == ["iot", "device", "c2d-message", "receive"]:
            send = sends[-1]

            def value(flag):
                return send[send.index(flag) + 1]

            result = {
                "data": value("--data"), "etag": "etag",
                "properties": {
                    "system": {
                        "content-encoding": value("--ce"), "content-type": value("--ct"),
                        "iothub-correlationid": value("--cid"), "iothub-messageid": value("--mid"),
                        "iothub-expiry": value("--expiry"), "iothub-to": "/devices/device/messages/devicebound",
                        "iothub-ack": "none",
                    },
                    "app": dict(pair.split("=") for pair in value("-p").split(";")),
                },
            }
        return SimpleNamespace(get_output_in_json=lambda: result)

    scenario.cmd = invoke
    scenario.test_iothub_c2d_messages_http()
    assert len(sends) == 3
    assert sends[0][sends[0].index("--auth-type") + 1] == "key"
    assert sends[1][sends[1].index("--auth-type") + 1] == "login"
    assert "--login" in sends[2] and "--auth-type" not in sends[2]
    messaging.sleep.assert_called_once_with(30)


@pytest.mark.parametrize("passed,bad", [(subject.NODES[:-1], False), (subject.NODES, True), (subject.NODES, False)])
def test_phase_requires_every_node_pass_and_no_skips(phase, passed, bad):
    phase.passed, phase.bad_report = set(passed), bad
    phase.sent = {"PUT " + resource_id.casefold() for resource_id in phase.ids.values()}
    phase.absent = set(phase.ids)
    phase.cleanup = Mock()
    session = SimpleNamespace(exitstatus=0)
    phase.pytest_sessionfinish(session)
    assert (session.exitstatus == 0) == (len(passed) == 6 and not bad)


def test_six_pass_reports_without_provisioning_receipts_cannot_pass(phase):
    phase.passed = set(subject.NODES)
    session = SimpleNamespace(exitstatus=0)
    phase.pytest_sessionfinish(session)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize("mode", ["regular", "local-auth"])
def test_real_fresh_process_collection_never_constructs_or_authenticates(mode, tmp_path, monkeypatch):
    script = r'''
import os
import socket
import sys
import webbrowser
import traceback
import urllib3  # Resolve its local IPv6 bind-only capability probe before installing the socket guards.
from hubsas_parent_dependency import AVAILABLE
assert AVAILABLE

blocked = []
def forbidden(*args, **kwargs):
    blocked.append([(frame.name, frame.filename.rsplit("/", 1)[-1], frame.lineno)
                    for frame in traceback.extract_stack()[-8:]])
    raise AssertionError("Offline collection attempted construction/authentication/network/browser work.")

socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.socket.bind = forbidden
socket.socket.sendto = forbidden
socket.getaddrinfo = forbidden
webbrowser.open = forbidden
from azure.cli.core._profile import Profile
Profile.get_raw_token = forbidden
Profile.get_login_credentials = forbidden
from azure.cli.core import util
util.check_connectivity = lambda *args, **kwargs: False
util.get_latest_version_from_ame_storage = lambda *args, **kwargs: None
from azext_iot.common.embedded_cli import EmbeddedCLI
EmbeddedCLI.invoke = forbidden
from azext_iot.tests.iothub import IoTLiveScenarioTest
IoTLiveScenarioTest.__init__ = forbidden
from azext_iot.tests.iothub._sas_phase import NODES
from _pytest.skipping import evaluate_skip_marks
import pytest

class Proof:
    def pytest_collection_finish(self, session):
        assert not blocked, str(blocked)
        assert tuple(item.nodeid for item in session.items) == NODES
        skipped = sum(evaluate_skip_marks(item) is not None for item in session.items)
        assert skipped == (6 if os.environ["azext_iot_hub_auth_phase"] == "regular" else 0)
        print("SAFE_COLLECTION nodes=6 skipped=" + str(skipped))

sys.exit(pytest.main(["-c", "setup.cfg", "--collect-only", "-q", "-o", "addopts=",
                     "-o", "log_cli=false", *NODES], plugins=[Proof()]))
'''
    dependency_path = tmp_path / "parent-only-imports"
    dependency_path.mkdir()
    (dependency_path / "hubsas_parent_dependency.py").write_text("AVAILABLE = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(dependency_path))
    import_paths = dict.fromkeys([str(REPO), *(os.path.abspath(path) for path in sys.path)])
    env = dict(
        os.environ, PYTHONPATH=os.pathsep.join(import_paths),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
        AZURE_CONFIG_DIR=str(tmp_path / "profile"), AZURE_TEST_RUN_LIVE="False",
        azext_iot_testrg="unit-rg", azext_iot_hub_auth_phase=mode,
        azext_iot_hubsas_subscription="subscription", azext_iot_hubsas_receipt=str(tmp_path / "receipt.json"),
        azext_iot_testhub="", azext_iot_teststorageaccount="", azext_iot_teststoragecontainer="",
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO, env=env,
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SAFE_COLLECTION nodes=6 skipped=" + ("6" if mode == "regular" else "0") in result.stdout


@pytest.mark.parametrize("subscription", [None, "", " \t\n"])
def test_blank_subscription_fails_before_receipt_or_factory(subscription, tmp_path, monkeypatch):
    if subscription is None:
        monkeypatch.delenv("azext_iot_hubsas_subscription", raising=False)
    else:
        monkeypatch.setenv("azext_iot_hubsas_subscription", subscription)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setenv("azext_iot_hubsas_receipt", str(receipt))
    with pytest.raises(pytest.UsageError, match="explicit subscription"):
        subject.HubSasPhase(configuration(), "hub", "storage", "rg", "centraluseuap")
    assert not receipt.exists()


@pytest.fixture
def native_hub(phase, mocker):
    from azure.cli.core.mock import DummyCli
    from azext_iot import _factory
    phase.cli = SimpleNamespace(az_cli=DummyCli())
    phase.cli.az_cli.data["subscription_id"] = "default-subscription"
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 4102444800))
    selected = mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    phase.hub_operations()
    selected.assert_called_once_with(phase.cli.az_cli, subscription_id=phase.subscription)
    return phase.hub_client


def test_actual_show_namecheck_is_untyped_but_native_get_preserves_absence(phase, native_hub, mocker):
    from azext_iot.core import custom
    mocker.patch.object(custom, "_ensure_resource_group_existence", return_value=True)
    root = "https://centraluseuap.management.azure.com"
    availability = root + f"/subscriptions/{phase.subscription}/providers/Microsoft.Devices/checkNameAvailability"
    with responses.RequestsMock() as wire:
        wire.add("POST", availability, json={"nameAvailable": True}, status=200)
        wire.add("GET", root + phase.ids["hub"], json={"error": {"code": "ResourceNotFound"}}, status=404)
        with pytest.raises(CLIError, match="not found"):
            custom.iot_hub_get(
                SimpleNamespace(cli_ctx=phase.cli.az_cli), native_hub, phase.hub, phase.group,
            )
        assert phase.read("hub") is None
        assert [call.request.method for call in wire.calls] == ["POST", "GET"]
        assert all(native_hub._config.api_version in call.request.url for call in wire.calls)
        phase.command.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 502])
def test_native_hub_read_only_accepts_http_404(phase, native_hub, status):
    with responses.RequestsMock() as wire:
        wire.add("GET", "https://centraluseuap.management.azure.com" + phase.ids["hub"],
                 json={"error": {"code": "SyntheticFailure"}}, status=status)
        # Disable read retries in this synthetic failure proof, not in production.
        native_hub._config.retry_policy.total_retries = 0
        if status == 404:
            assert phase.read("hub") is None
        else:
            with pytest.raises(HttpResponseError) as error:
                phase.read("hub")
            assert error.value.status_code == status


def test_native_factory_failure_is_outside_absence_catch(phase, mocker):
    failure = HttpResponseError("Synthetic credential/factory failure")
    failure.status_code = 404
    mocker.patch("azext_iot._factory.iot_hub_service_factory", side_effect=failure)
    with pytest.raises(HttpResponseError) as error:
        phase.read("hub")
    assert error.value is failure


def test_native_hub_delete_submits_once_without_polling_and_then_reads(phase, native_hub):
    phase.install()
    root = "https://centraluseuap.management.azure.com"
    hub = {"id": phase.ids["hub"], "tags": {"runUid": subject.UID}, "properties": {}}
    with responses.RequestsMock() as wire:
        wire.add("GET", root + phase.ids["hub"], json=hub, status=200)
        wire.add("DELETE", root + phase.ids["hub"], json={"status": "Deleting"}, status=202,
                 headers={"Azure-AsyncOperation": root + "/unexpected-background-poll"})
        wire.add("GET", root + phase.ids["hub"], json={"error": {"code": "ResourceNotFound"}}, status=404)
        assert phase.cleanup_one("hub", subject.monotonic() + 30) is False
        assert phase.cleanup_one("hub", subject.monotonic() + 30) is True
        assert [call.request.method for call in wire.calls] == ["GET", "DELETE", "GET"]
    assert "DELETE " + phase.ids["hub"].casefold() in phase.sent


def test_storage_native_delete_is_one_request_not_an_lro(phase):
    from azure.mgmt.storage import StorageManagementClient
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("offline-token", 4102444800))
    client = StorageManagementClient(credential, phase.subscription, retry_total=0)
    with responses.RequestsMock() as wire:
        wire.add("DELETE", "https://management.azure.com" + phase.ids["storage"], status=204)
        assert client.storage_accounts.delete(resource_group_name=phase.group, account_name=phase.storage) is None
        assert [call.request.method for call in wire.calls] == ["DELETE"]


@pytest.mark.parametrize("status", [None, 202, 500])
def test_uncertain_hub_does_not_starve_known_storage_cleanup(phase, monkeypatch, status):
    clock, events = [0], []
    monkeypatch.setattr(subject, "monotonic", lambda: clock[0])
    monkeypatch.setattr(subject, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    hub_key = "PUT " + phase.ids["hub"].casefold()
    phase.sent.update((hub_key, "PUT " + phase.ids["storage"].casefold()))
    if status is not None:
        phase.statuses[hub_key] = status
    storage = {"id": phase.ids["storage"], "tags": {"runUid": subject.UID}, "properties": {}}
    deleted = [False]

    def read(kind):
        events.append(("read", kind, clock[0]))
        return storage if kind == "storage" and not deleted[0] else None

    def delete(command):
        assert command.startswith("storage account delete")
        events.append(("delete", "storage", clock[0]))
        phase.sent.add("DELETE " + phase.ids["storage"].casefold())
        deleted[0] = True

    monkeypatch.setattr(phase, "read", read)
    phase.command.side_effect = delete
    with pytest.raises(subject.HubSasError, match="hub.*budget"):
        phase.cleanup(timeout=10)
    assert ("delete", "storage", 0) in events
    assert phase.command.call_count == 1
    assert phase.absent == {"role", "storage", "container"}
    assert "hub" in json.loads(phase.path.read_text(encoding="utf-8"))["cleanupFailures"]


@pytest.fixture
def subscription_profiles(phase, mocker):
    from azure.cli.core._profile import Profile
    accounts = [
        {"id": "default-subscription", "name": "A", "tenantId": "tenant-a", "isDefault": True,
         "user": {"name": "a@example.invalid", "type": "user"}},
        {"id": phase.subscription, "name": "B", "tenantId": "tenant-b", "isDefault": False,
         "user": {"name": "b@example.invalid", "type": "user"}},
    ]
    mocker.patch.object(Profile, "load_cached_subscriptions", return_value=accounts)
    selected = []

    def credential(_profile, account, **_kwargs):
        selected.append(account["id"])
        return SimpleNamespace(acquire_token=lambda *_args, **_kwargs: {
            "access_token": "offline-token", "expires_in": 3600,
        })

    mocker.patch.object(Profile, "_create_credential", autospec=True, side_effect=credential)
    persistent = mocker.patch.object(
        Profile, "set_active_subscription", side_effect=AssertionError("Shared profile must not be changed."),
    )
    return SimpleNamespace(accounts=accounts, selected=selected, persistent=persistent)


def test_native_device_cleanup_factory_and_oauth_use_scoped_original_context(phase, subscription_profiles):
    from azure.cli.core._profile import Profile
    from azure.cli.core.mock import DummyCli
    from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider
    context = DummyCli()
    context.data["subscription_id"] = "default-subscription"
    phase.install()
    phase.scope_context(context)
    target = {
        "id": phase.ids["hub"], "name": phase.hub, "location": "centraluseuap",
        "properties": {"hostName": "hub.azure-devices.net", "disableLocalAuth": False},
        "sku": {"name": "S1", "tier": "Standard", "capacity": 1},
    }
    with responses.RequestsMock() as wire:
        wire.add("GET", "https://centraluseuap.management.azure.com" + phase.ids["hub"],
                 json=target, status=200)
        wire.add("DELETE", "https://hub.azure-devices.net/devices/owned-device", status=204)
        provider = DeviceIdentityProvider(
            cmd=SimpleNamespace(cli_ctx=context), hub_name=phase.hub, rg=phase.group, auth_type_dataplane="login",
        )
        provider.service_sdk.devices.delete_identity(id="owned-device", if_match="*")
        assert [call.request.method for call in wire.calls] == ["GET", "DELETE"]
    assert len(subscription_profiles.selected) >= 2
    assert set(subscription_profiles.selected) == {phase.subscription}
    assert Profile(cli_ctx=context).get_subscription()["id"] == phase.subscription
    phase.restore()
    assert context.data["subscription_id"] == "default-subscription"
    assert "_hub_sas_subscription" not in context.data
    assert Profile(cli_ctx=context).get_subscription()["id"] == "default-subscription"
    assert [account["isDefault"] for account in subscription_profiles.accounts] == [True, False]
    subscription_profiles.persistent.assert_not_called()


def test_base_scopes_original_context_before_provisioning(phase, mocker, monkeypatch):
    from azure.cli.core.mock import DummyCli
    from azext_iot.tests import CaptureOutputLiveScenarioTest
    context = DummyCli()
    context.data["subscription_id"] = "default-subscription"
    monkeypatch.setenv(subject.ENV, "local-auth")
    monkeypatch.setattr(subject, "ACTIVE", phase)

    def initialize(scenario, _name):
        scenario.cli_ctx = context

    def provision(scenario):
        assert scenario.cli_ctx is context
        assert context.data["subscription_id"] == phase.subscription
        return {"location": "centraluseuap", "properties": {"hostName": "hub", "disableLocalAuth": False}}

    mocker.patch.object(CaptureOutputLiveScenarioTest, "__init__", initialize)
    mocker.patch.object(phase, "provision", side_effect=provision)
    IoTLiveScenarioTest("test_device_upload_file")


def test_real_shared_cleanup_helper_uses_b_at_factory_and_profile_boundaries(phase, subscription_profiles, mocker):
    from azure.cli.core._profile import Profile
    from azext_iot import _factory
    from azext_iot.tests import helpers
    original = helpers.cli
    phase.install()
    scoped = phase.get_cli()
    observed = []

    def execute(args, out_file):
        assert args[args.index("--subscription") + 1] == phase.subscription
        client = _factory.iot_hub_service_factory(scoped.az_cli)
        assert client._config.subscription_id == phase.subscription
        _, subscription, _ = Profile(cli_ctx=scoped.az_cli).get_raw_token(resource="https://iothubs.azure.net")
        observed.append((args[:4], subscription))
        result = [{"deviceId": "owned-device"}] if args[:4] == ["iot", "hub", "device-twin", "list"] else []
        scoped.az_cli.result = SimpleNamespace(error=None)
        out_file.write(json.dumps(result))
        return 0

    mocker.patch.object(scoped.az_cli, "invoke", side_effect=execute)
    phase.cleanup_devices()
    assert helpers.cli is original
    assert len(observed) == 4 and all(subscription == phase.subscription for _, subscription in observed)
    assert observed[-1][0] == ["iot", "hub", "device-identity", "delete"]
    assert set(subscription_profiles.selected) == {phase.subscription}
    subscription_profiles.persistent.assert_not_called()


def test_helper_context_is_restored_on_cleanup_failure(phase, mocker):
    from azext_iot.tests import helpers
    original = helpers.cli
    mocker.patch.object(helpers, "clean_up_iothub_device_config", side_effect=RuntimeError("Failed cleanup"))
    with pytest.raises(RuntimeError, match="Failed cleanup"):
        phase.cleanup_devices()
    assert helpers.cli is original


def test_phase_teardown_uses_scoped_cleanup_not_the_unpinned_alias(phase, mocker, monkeypatch):
    from azext_iot.tests import iothub
    monkeypatch.setenv(subject.ENV, "local-auth")
    monkeypatch.setattr(subject, "ACTIVE", phase)
    monkeypatch.setattr(iothub.settings.env, "azext_iot_testhub", None)
    scoped = mocker.patch.object(phase, "cleanup_devices")
    unpinned = mocker.patch.object(iothub, "clean_up_iothub_device_config")
    scenario = SimpleNamespace(
        stop_background=Mock(), entity_name=phase.hub, entity_rg=phase.group, _generated_device_ids=[],
    )
    IoTLiveScenarioTest.tearDown(scenario)
    scenario.stop_background.assert_called_once_with()
    scoped.assert_called_once_with()
    unpinned.assert_not_called()


def test_phase_fixture_deletions_use_the_scoped_embedded_cli(phase, mocker, monkeypatch):
    from azext_iot.tests.iothub import conftest as fixtures
    monkeypatch.setenv(subject.ENV, "local-auth")
    monkeypatch.setattr(subject, "ACTIVE", phase)
    scoped = phase.get_cli()
    invoke = mocker.patch.object(fixtures, "invoke_checked")
    fixtures._delete_fixture_resource("owned-delete", "owned")
    invoke.assert_called_once_with(scoped, "owned-delete", description="Deleting test resource 'owned'")
    assert scoped.user_subscription == phase.subscription
    assert scoped.az_cli.data["subscription_id"] == phase.subscription


def test_cleanup_error_does_not_stop_other_owned_deletions(phase, monkeypatch):
    clock = [0]
    monkeypatch.setattr(subject, "monotonic", lambda: clock[0])
    monkeypatch.setattr(subject, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    role_error = ForbiddenError("Role lookup denied")
    storage_deleted = [False]
    phase.sent.add("PUT " + phase.ids["storage"].casefold())

    def read(kind):
        if kind == "role":
            raise role_error
        if kind == "storage" and not storage_deleted[0]:
            return {"id": phase.ids["storage"], "tags": {"runUid": subject.UID}, "properties": {}}
        return None

    def delete(command):
        assert command.startswith("storage account delete")
        phase.sent.add("DELETE " + phase.ids["storage"].casefold())
        storage_deleted[0] = True

    monkeypatch.setattr(phase, "read", read)
    phase.command.side_effect = delete
    with pytest.raises(ForbiddenError) as error:
        phase.cleanup(timeout=10)
    assert error.value is role_error
    assert phase.command.call_count == 1 and "storage" in phase.absent
    assert phase.cleanup_failures == {"role": "ForbiddenError: Role lookup denied"}
