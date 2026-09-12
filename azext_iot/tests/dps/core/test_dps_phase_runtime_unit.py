# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.

"""No Azure: real SDK HTTP pipelines and real tox/xdist with local-only fixtures."""

import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import requests
import responses
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError, ServiceResponseError
from azure.core.pipeline import Pipeline
from azure.core.pipeline.policies import HTTPPolicy
from azure.core.pipeline.transport import RequestsTransport
from azure.core.pipeline.transport import HttpRequest

from azext_iot import _factory
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.dps import _phase_receipts as receipts, _phase_runtime as runtime

ROOT = Path(__file__).resolve().parents[4]
RUNNER = runpy.run_path(str(ROOT / "scripts/run_dps_phases.py"))
SUB_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SUB_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
UID = "b" * 32
ARM = "https://centraluseuap.management.azure.com"


@pytest.fixture
def scope(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv(receipts.DIRECTORY_ENV, str(tmp_path))
    monkeypatch.setenv(receipts.RUN_UID_ENV, UID)
    monkeypatch.setenv(receipts.SUBSCRIPTION_ENV, SUB_B)
    monkeypatch.setenv(receipts.RESOURCE_GROUP_ENV, "group")
    monkeypatch.setenv("azext_iot_dps_test_phase", "regular")
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("fake-unit-token", 9999999999))
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    return tmp_path


def _client(factory_name):
    cli = EmbeddedCLI()
    return getattr(_factory, factory_name)(cli.az_cli, subscription_id=SUB_B)


def _owned(kind):
    receipts.before_create("owned", "group", UID, kind)
    resource_type = "IotHubs" if kind == "hub" else "provisioningServices"
    return ARM + f"/subscriptions/{SUB_B}/resourceGroups/group/providers/Microsoft.Devices/{resource_type}/owned"


@responses.activate
@pytest.mark.parametrize("factory_name,kind", [
    ("iot_hub_service_factory", "hub"), ("adr_iot_hub_service_factory", "hub"),
    ("iot_service_provisioning_factory", "nh"), ("adr_iot_service_provisioning_factory", "nh"),
])
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_real_factory_pipeline_never_resends_uncertain_owned_mutation(scope, factory_name, kind, method, failure):
    url = _owned(kind)
    if failure == "read-timeout":
        responses.add(method, url, body=requests.exceptions.ReadTimeout("synthetic timeout after acceptance"))
    else:
        responses.add(method, url, status=504, json={"error": {"code": "GatewayTimeout"}})
    responses.add(method, url, status=200, json={})  # A forbidden retry would consume this and appear successful.
    with runtime.activate(SUB_B):
        client = _client(factory_name)
        with runtime.owned_write("owned", method):
            if failure == "read-timeout":
                with pytest.raises(ServiceResponseError):
                    client.send_request(HttpRequest(method, url))
            else:
                assert client.send_request(HttpRequest(method, url)).status_code == 504
    assert len(responses.calls) == 1


@responses.activate
def test_transport_fence_blocks_policy_resends_but_allows_distinct_later_updates(scope):
    url = _owned("nh")
    responses.add(responses.PUT, url, json={})
    responses.add(responses.PUT, url, status=504)
    responses.add(responses.PUT, url, json={})
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        with runtime.owned_write("owned", "PUT"):
            client.send_request(HttpRequest("PUT", url))
            with pytest.raises(runtime.ScopeError, match="replay"):
                client.send_request(HttpRequest("PUT", url))
        assert len(responses.calls) == 1
        # A later logical operation is fenced too: 504 must NOT consume the 200.
        assert client.send_request(HttpRequest("PUT", url)).status_code == 504
        assert len(responses.calls) == 2
        # Only an explicitly separate operation may consume the next response.
        assert client.send_request(HttpRequest("PUT", url)).status_code == 200
    assert len(responses.calls) == 3


def _real_cli(mocker):
    from azure.cli.core import MainCommandsLoader
    from azure.cli.core._profile import Profile
    from azext_iot import IoTExtCommandsLoader

    mocker.patch.object(Profile, "get_subscription", autospec=True, side_effect=lambda _self, subscription=None: {
        "id": subscription or SUB_A, "name": "offline", "tenantId": SUB_A,
        "user": {"name": SUB_A, "type": "servicePrincipal"}, "environmentName": "AzureCloud",
    })
    credential = SimpleNamespace(get_token=lambda *_args, **_kwargs: AccessToken("fake-unit-token", 9999999999))
    mocker.patch.object(Profile, "get_login_credentials", return_value=(credential, SUB_B, SUB_A))

    class LocalExtensionLoader(MainCommandsLoader):
        def load_command_table(self, args):
            extension = IoTExtCommandsLoader(cli_ctx=self.cli_ctx)
            self.command_table.update(extension.load_command_table(args))
            self.cmd_to_loader_map.update({name: [extension] for name in self.command_table})
            return self.command_table

    cli = EmbeddedCLI(capture_stderr=True)
    # Deterministic local discovery; the main loader's argument reflection,
    # parser, validators, handlers, factories and SDK transports are all real.
    cli.az_cli.commands_loader_cls = LocalExtensionLoader
    cli.az_cli.data["subscription_id"] = SUB_A
    cli.user_subscription = SUB_A
    return cli


def _arm_resources(url):
    hub_url = _owned("hub")
    host = "owned.azure-devices.net"
    resource = {
        "id": url.removeprefix(ARM), "name": "owned", "location": "centraluseuap",
        "sku": {"name": "S1", "capacity": 1}, "identity": {"type": "SystemAssigned"},
        "properties": {"provisioningState": "Succeeded", "disableLocalAuth": False, "iotHubs": [
            {"name": host, "hostName": host, "authenticationType": "KeyBased", "connectionString": "synthetic"},
        ]},
    }
    responses.add("GET", url, json=resource)
    responses.add("HEAD", ARM + f"/subscriptions/{SUB_B}/resourcegroups/group", status=204)
    responses.add("POST", ARM + f"/subscriptions/{SUB_B}/providers/Microsoft.Devices/checkNameAvailability",
                  json={"nameAvailable": False, "reason": "AlreadyExists"})
    responses.add("GET", hub_url, json={
        "id": hub_url.removeprefix(ARM), "name": "owned", "location": "centraluseuap",
        # The ADR branch's existing KeyBased helper requires this legacy field.
        # This synthetic response exercises the write guard, not RP response capability.
        "resourcegroup": "group",
        "properties": {"hostName": host, "deviceHostName": host},
    })
    responses.add("POST", hub_url + "/IotHubKeys/iothubowner/listkeys", json={
        "keyName": "iothubowner", "primaryKey": "eA==",
    })
    return resource


@responses.activate
@pytest.mark.parametrize("command", [
    "identity assign --system-assigned",
    "linked-hub create --hub-name owned --hub-resource-group group --authentication-type KeyBased",
    "linked-hub create --hub-name owned --hub-resource-group group --authentication-type SystemAssigned",
    "linked-hub update --hub-name owned --authentication-type SystemAssigned",
    "linked-hub delete --linked-hub owned.azure-devices.net",
])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_real_cli_later_identity_and_link_writes_are_not_replayed(scope, mocker, command, failure):
    url = _owned("nh")
    resource = _arm_resources(url)
    cli = _real_cli(mocker)
    if failure == "read-timeout":
        responses.add("PUT", url, body=requests.exceptions.ReadTimeout("synthetic accepted write timeout"))
    else:
        responses.add("PUT", url, status=504, json={"error": {"code": "GatewayTimeout", "message": "synthetic"}})
    responses.add("PUT", url, json=resource)
    with runtime.activate(SUB_B, existing=(cli,)):
        name_option = "--name" if command.startswith("identity") else "--dps-name"
        with pytest.raises((HttpResponseError, ServiceResponseError)):
            cli.invoke(f"iot dps {command} {name_option} owned -g group")
        writes = [call for call in responses.calls if call.request.method == "PUT"]
        assert len(writes) == 1
        body = json.loads(writes[0].request.body)
        if command.startswith("identity"):
            assert body["identity"]["type"] == "SystemAssigned"
        elif command.startswith("linked-hub delete"):
            assert body["properties"]["iotHubs"] == []
        else:
            link = body["properties"]["iotHubs"][-1]
            if "SystemAssigned" in command:
                assert link["authenticationType"] == "SystemAssigned"
            else:
                assert link["connectionString"].startswith("HostName=")
        # No leaked boundary on exception, even on a separate CLI instance. The
        # new explicit command is NOT an automatic retry of the failed command.
        other = EmbeddedCLI(capture_stderr=True)
        other.az_cli.commands_loader_cls = cli.az_cli.commands_loader_cls
        other.invoke("iot dps identity assign --name owned -g group --system-assigned")
        assert other.success()
    assert len([call for call in responses.calls if call.request.method == "PUT"]) == 2
    assert all(call.request.url.startswith(ARM + f"/subscriptions/{SUB_B}/") for call in responses.calls)
    assert len(list(scope.glob("mutation-*.json"))) == 2
    assert cli.user_subscription == SUB_A


@responses.activate
@pytest.mark.parametrize("method", ["PUT", "DELETE", "POST"])
def test_pipeline_context_fence_rejects_policy_reentry_above_retry_policy(scope, method):
    class ReenterPolicy(HTTPPolicy):
        def send(self, request):
            self.next.send(request)
            return self.next.send(request)

    url = _owned("nh") + "/certificates/unit"
    responses.add(method, url, json={})
    transport = runtime.ScopedTransport(RequestsTransport(), SUB_B)
    pipeline = Pipeline(transport, policies=[ReenterPolicy(), runtime.OwnedRetryPolicy()])
    with pytest.raises(runtime.ScopeError, match="repeated ARM mutation"):
        pipeline.run(HttpRequest(method, url))
    assert len(responses.calls) == 1


@responses.activate
@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("failure", ["read-timeout", "504"])
def test_actual_cli_authorization_factory_fences_owned_role_assignment_writes(scope, mocker, method, failure):
    from azure.cli.command_modules.role._client_factory import _auth_client_factory
    from azure.mgmt.authorization.models import RoleAssignmentCreateParameters
    owned = _owned("nh").removeprefix(ARM)
    url = ARM + owned + f"/providers/Microsoft.Authorization/roleAssignments/{SUB_A}"
    cli = _real_cli(mocker)
    if failure == "read-timeout":
        responses.add(method, url, body=requests.exceptions.ReadTimeout("synthetic accepted role write timeout"))
    else:
        responses.add(method, url, status=504, json={"error": {"code": "GatewayTimeout"}})
    responses.add(method, url, json={"id": url.removeprefix(ARM), "properties": {"principalId": SUB_A}})
    with runtime.activate(SUB_B, existing=(cli,)):
        client = _auth_client_factory(cli.az_cli, scope=owned)

        def operation():
            if method == "DELETE":
                return client.role_assignments.delete(owned, SUB_A)
            return client.role_assignments.create(owned, SUB_A, RoleAssignmentCreateParameters(
                role_definition_id=f"/subscriptions/{SUB_B}/providers/Microsoft.Authorization/roleDefinitions/{SUB_A}",
                principal_id=SUB_A,
            ))

        with pytest.raises((HttpResponseError, ServiceResponseError)):
            operation()
        assert len(responses.calls) == 1
        operation()
    assert len(responses.calls) == 2
    assert cli.az_cli.cloud.endpoints.resource_manager == "https://management.azure.com/"
    assert all(call.request.url.startswith(url) for call in responses.calls)


@responses.activate
@pytest.mark.parametrize("method,suffix", [
    ("PUT", "/certificates/unit"), ("DELETE", "/certificates/unit"),
    ("POST", "/certificates/unit/generateVerificationCode"), ("POST", "/certificates/unit/verify"),
    ("PATCH", ""),
])
def test_owned_children_and_actions_each_have_fresh_no_retry_boundary(scope, method, suffix):
    url = _owned("nh") + suffix
    responses.add(method, url, status=504)
    responses.add(method, url, json={})
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        assert client.send_request(HttpRequest(method, url)).status_code == 504
        assert len(responses.calls) == 1
        assert client.send_request(HttpRequest(method, url)).status_code == 200
    assert len(responses.calls) == 2


def test_fixture_role_visibility_never_submits_a_second_create(scope, mocker):
    from azext_iot.tests import helpers
    from azext_iot.tests.dps import conftest as fixtures
    owned = _owned("nh").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", side_effect=[[], [], [{"principalId": SUB_A}]])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}
    mocker.patch.object(runtime, "sleep")
    fallback = mocker.patch.object(fixtures, "assign_role_assignment")
    fixtures._assign_fixture_role(role="IoT DPS Data Contributor", scope=owned, assignee="unit")
    assert reads.call_count == 3
    create.assert_called_once()
    fallback.assert_not_called()


@pytest.mark.parametrize("failure", ["not-visible", "uncertain-create"])
def test_fixture_role_visibility_fails_without_repeating_create(scope, mocker, failure):
    from azext_iot.tests import helpers
    owned = _owned("nh").removeprefix(ARM)
    reads = mocker.patch.object(helpers, "get_role_assignments", return_value=[])
    create = mocker.patch.object(helpers, "invoke_checked")
    create.return_value.as_json.return_value = {"principalId": SUB_A}
    if failure == "uncertain-create":
        create.side_effect = ServiceResponseError("synthetic timeout")
    mocker.patch.object(runtime, "sleep")
    with pytest.raises((runtime.ScopeError, ServiceResponseError)):
        runtime.assign_role_assignment_once(role="role", scope=owned, assignee="unit", max_tries=2)
    create.assert_called_once()
    assert reads.call_count == (1 if failure == "uncertain-create" else 3)


@responses.activate
def test_unowned_arm_writes_are_rejected_but_unscoped_product_retries_unchanged(scope):
    url = _owned("nh")
    with runtime.activate(SUB_B):
        client = _client("iot_service_provisioning_factory")
        with pytest.raises(runtime.ScopeError, match="owned resource"):
            client.send_request(HttpRequest("PUT", url + "-borrowed"))
    assert not responses.calls
    # No product policy modification: the normal client still retries its 504.
    responses.add("PUT", url, status=504)
    responses.add("PUT", url, json={})
    assert _client("iot_service_provisioning_factory").send_request(HttpRequest("PUT", url)).status_code == 200
    assert len(responses.calls) == 2


@responses.activate
@pytest.mark.parametrize("factory_name,kind", [
    ("iot_hub_service_factory", "hub"), ("adr_iot_hub_service_factory", "hub"),
    ("iot_service_provisioning_factory", "nh"), ("adr_iot_service_provisioning_factory", "nh"),
])
def test_real_delete_poller_keeps_get_polling_without_repeating_delete(scope, factory_name, kind):
    url = _owned(kind)
    poll = ARM + f"/subscriptions/{SUB_B}/providers/Microsoft.Devices/operations/unit"
    responses.add(responses.DELETE, url, status=202, body="null",
                  headers={"Azure-AsyncOperation": poll, "Retry-After": "0"})
    responses.add(responses.GET, poll, json={"status": "InProgress"}, headers={"Retry-After": "0"})
    responses.add(responses.GET, poll, json={"status": "Succeeded"})
    with runtime.activate(SUB_B):
        client = _client(factory_name)
        with runtime.owned_write("owned", "DELETE"):
            if kind == "hub":
                poller = client.iot_hub_resource.begin_delete(
                    resource_group_name="group", resource_name="owned", polling_interval=0)
            else:
                poller = client.iot_dps_resource.begin_delete(
                    resource_group_name="group", provisioning_service_name="owned", polling_interval=0)
            result = poller.result(timeout=5)
            assert poller.done()
            assert result == ({"status": "Succeeded"} if kind == "hub" else None)
    assert [call.request.method for call in responses.calls] == ["DELETE", "GET", "GET"]


def test_separate_real_embedded_clis_and_link_transition_are_pinned_without_profile_switch(scope, mocker):
    from azure.cli.core._profile import Profile
    from azext_iot.common.auth import get_aad_token
    from azext_iot.tests.dps.core import test_dps_linked_hub_int as linked

    token_subscriptions = []

    def token(_self, resource=None, scopes=None, subscription=None, tenant=None, credential_out=None):
        token_subscriptions.append(subscription)
        return ("Bearer", "fake-unit-token", {}), subscription, "unit-tenant"

    mocker.patch.object(Profile, "get_raw_token", token)
    default = mocker.patch.object(Profile, "get_subscription", autospec=True,
                                  side_effect=lambda _self, subscription=None: {"id": subscription or SUB_A})
    instance = linked.cli  # This instance predates activation and has a cached default A.
    mocker.patch.dict(instance.az_cli.data, {"subscription_id": SUB_A})
    mocker.patch.object(instance, "user_subscription", SUB_A)
    mocker.patch.object(instance.az_cli, "result", SimpleNamespace(error=None))
    calls = []
    mode = ["KeyBased"]

    def dispatch(arguments, out_file):
        calls.append(arguments)
        assert arguments[arguments.index("--subscription") + 1] == SUB_B
        assert instance.az_cli.data["subscription_id"] == SUB_B
        get_aad_token(instance.az_cli)
        if "update" in arguments:
            mode[0] = "SystemAssigned"
        out_file.write(json.dumps([{
            "name": "unit.device.azure-devices.net", "hostName": "unit.device.azure-devices.net",
            "authenticationType": mode[0], "connectionString": "",
        }]))
        return 0

    mocker.patch.object(instance.az_cli, "invoke", side_effect=dispatch)
    hub = {"name": "unit", "properties": {"deviceHostName": "unit.device.azure-devices.net"}}
    mocker.patch.object(linked, "_require_gwv2_hub", return_value=hub)
    with runtime.activate(SUB_B):
        linked.test_linked_hub_create_keybased_then_switch_to_mi(
            {"name": "owned", "resourceGroup": "group"}, {"rg": "group"},
        )
        another = EmbeddedCLI()
        invoked = mocker.patch.object(another.az_cli, "invoke", return_value=0)
        another.invoke("iot dps enrollment list --dps-name owned -g group")
        assert invoked.call_args.args[0][-2:] == ["--subscription", SUB_B]
        assert Profile(cli_ctx=another.az_cli).get_subscription()["id"] == SUB_B
        with pytest.raises(runtime.ScopeError):
            another.invoke(f"iot dps show -n owned --subscription {SUB_A}")
        with pytest.raises(runtime.ScopeError):
            another.invoke("account set --subscription " + SUB_B)
    assert instance.az_cli.data["subscription_id"] == SUB_A
    assert instance.user_subscription == SUB_A
    assert Profile(cli_ctx=instance.az_cli).get_subscription()["id"] == SUB_A
    assert default.call_args.kwargs.get("subscription") is None
    assert len(calls) == 5 and token_subscriptions == [SUB_B] * 5


@pytest.mark.timeout(100)
def test_real_tox_xdist_timeout_allows_twelve_second_fixture_cleanup_and_ends_children(tmp_path, mocker):
    directory = tmp_path / "receipts"
    directory.mkdir()
    environment = dict(
        os.environ, PYTHONPATH=str(ROOT), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", VIRTUALENV_NO_PERIODIC_UPDATE="1",
        azext_iot_dps_phase_receipts=str(directory), azext_iot_dps_run_uid=UID,
        azext_iot_dps_test_subscription=SUB_B, azext_iot_dps_test_resource_group="group",
        azext_iot_dps_test_phase="regular",
    )
    config = tmp_path / "tox.ini"
    config.write_text(
        "[tox]\nenv_list=cleanup-proof\n[testenv:cleanup-proof]\npackage=skip\nsitepackages=true\n"
        "passenv=PYTHONPATH,PYTEST_DISABLE_PLUGIN_AUTOLOAD,AZURE_CONFIG_DIR,azext_*\n"
        "commands=python -m pytest -p xdist.plugin -n 2 --max-worker-restart=0 -q test_workers.py\n",
        encoding="utf-8",
    )
    (tmp_path / "conftest.py").write_text(
        "import socket\n"
        "def deny(*args, **kwargs): raise AssertionError('offline process cannot connect')\n"
        "socket.socket.connect = deny\n"
        "from azext_iot.tests.dps import _phase_runtime\n"
        "def pytest_sessionstart(session): _phase_runtime.start_worker(session)\n",
        encoding="utf-8",
    )
    (tmp_path / "test_workers.py").write_text(
        "import os,time,pytest\nfrom pathlib import Path\n"
        "@pytest.fixture(scope='session')\n"
        "def owned():\n"
        "    Path('started-'+str(os.getpid())).write_text('started')\n"
        "    yield\n"
        "    time.sleep(12)\n"
        "    Path('cleaned-'+str(os.getpid())).write_text('cleaned')\n"
        "@pytest.mark.parametrize('case',[0,1])\n"
        "def test_wait(owned,case):\n"
        "    while True: time.sleep(.1)\n",
        encoding="utf-8",
    )
    command = [sys.executable, "-m", "tox", "r", "-c", str(config), "-e", "cleanup-proof"]
    subprocess.run(command + ["--notest"], env=environment, check=True, capture_output=True, timeout=45)
    mocker.patch.dict(RUNNER["child"].__globals__, READ_SECONDS=1)
    started = time.monotonic()
    result = RUNNER["child"](command, environment, tmp_path / "log", runtime=10, cleanup=25)
    assert result["timed_out"] and result["interrupted"] and result["exit_code"] != 0
    assert 22 <= time.monotonic() - started < 40
    markers = sorted(tmp_path.glob("started-*"))
    assert len(markers) == 2
    for marker in markers:
        pid = int(marker.name.partition("-")[2])
        assert (tmp_path / f"cleaned-{pid}").is_file()
        assert not Path(f"/proc/{pid}").exists()
    for path in directory.glob("worker-*.json"):
        assert not Path(f"/proc/{json.loads(path.read_text())['parent_pid']}").exists()
    assert (directory / "stop-requested.json").is_file()
