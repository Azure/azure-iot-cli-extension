# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline execution of the live-smoke safety contract and exported ADR CLI commands."""

import asyncio
from copy import deepcopy
from functools import partial
from io import StringIO
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from azure.cli.core import MainCommandsLoader
from azure.cli.core.azclierror import AzureResponseError
from azure.cli.core.mock import DummyCli

from azext_iot import IoTExtCommandsLoader
from azext_iot.adr import commands_link, commands_namespace, commands_su, commands_wait
from azext_iot.adr.providers.wait import wait_for_resource
from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.screens.onboard import steps
from azext_iot.adr.ui.screens.onboard.create import CreateRequest
from azext_iot.adr.ui.screens.onboard.flow import Flow, PlanItem, Step
from azext_iot.adr.ui.screens.onboard.identity import IdentityChoice, create_uami, create_uami_command, set_choice
from azext_iot.adr.ui.screens.onboard.pickers import Candidate
from azext_iot.tests.adr import test_adr_radar_int as radar


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
DEFAULT_SUBSCRIPTION = "00000000-0000-0000-0000-000000000002"
PREFIX = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/"
UAMI_ID = PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/reviewed"


def test_unit_module_does_not_expose_collectable_testcase_classes():
    import unittest

    testcase_bindings = [
        name for name, value in globals().items()
        if isinstance(value, type) and issubclass(value, unittest.TestCase)
    ]
    assert not testcase_bindings, f"pytest collects TestCase aliases regardless of name: {testcase_bindings}"


@pytest.fixture
def offline_network(monkeypatch):
    network = Mock(side_effect=AssertionError("offline radar contract attempted network I/O"))
    monkeypatch.setattr("requests.sessions.Session.request", network)
    yield network
    network.assert_not_called()


class _OfflineADRLoader(MainCommandsLoader):
    def load_command_table(self, args):
        if args and args[0] in ("identity", "resource"):
            return super().load_command_table(args)
        loader = IoTExtCommandsLoader(self.cli_ctx)
        self.command_table = {
            name: command for name, command in loader.load_command_table(args).items()
            if name.startswith("iot adr ns")
        }
        self.cmd_to_loader_map = {name: [loader] for name in self.command_table}
        return self.command_table


@pytest.fixture
def offline_cli(monkeypatch, tmp_path, offline_network):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("AZURE_CORE_COLLECT_TELEMETRY", "false")
    subscriptions = [
        {"id": value, "name": value, "environmentName": "AzureCloud", "state": "Enabled",
         "isDefault": value == DEFAULT_SUBSCRIPTION, "tenantId": "offline-tenant"}
        for value in (DEFAULT_SUBSCRIPTION, SUBSCRIPTION)
    ]
    monkeypatch.setattr("azure.cli.core._profile.Profile.load_cached_subscriptions", Mock(return_value=subscriptions))
    monkeypatch.setattr(
        "azure.cli.core._profile.Profile.set_active_subscription",
        Mock(side_effect=AssertionError("export must not change the default subscription")),
    )
    monkeypatch.setattr("azure.cli.core._profile.Profile.get_subscription", Mock(side_effect=lambda subscription=None: {
        "id": subscription or DEFAULT_SUBSCRIPTION, "name": "offline", "environmentName": "AzureCloud",
    }))
    monkeypatch.setattr("azure.cli.core._profile.Profile.get_login_credentials", Mock(return_value=(
        Mock(), SUBSCRIPTION, "offline-tenant",
    )))
    cli = DummyCli(commands_loader_cls=_OfflineADRLoader)
    providers = {}
    for key, module, class_name in (
        ("namespace", commands_namespace, "NamespaceProvider"),
        ("link", commands_link, "LinkProvider"),
        ("update_instance", commands_su, "UpdateInstanceProvider"),
    ):
        provider = Mock()
        provider.command_subscriptions = []
        for method in ("create", "update", "show", "hub_add", "hub_update", "dps_add", "dps_update", "su_add", "su_update"):
            getattr(provider, method).return_value = {"accepted": key}

        def construct(cmd, _provider=provider, **_kwargs):
            _provider.command_subscriptions.append(cmd.cli_ctx.data["subscription_id"])
            return _provider

        factory = Mock(side_effect=construct)
        monkeypatch.setattr(module, class_name, factory)
        if key in ("namespace", "link"):
            monkeypatch.setattr(commands_wait, class_name, factory)
        providers[key] = provider
    session = Session(None)
    session._providers.update(providers)
    return cli, session


def _export_case(case, choice):
    scope = {"namespace_name": "ns", "resource_group_name": "rg"}
    ctx = {**scope, "subscription_id": SUBSCRIPTION}
    set_choice(ctx, "namespace", choice)
    if case == "namespace-create":
        ctx["create_namespace"] = CreateRequest(
            "namespace", "ns", "rg", "eastus2", identity=choice, tags={"purpose": "review only", "owner": "O'Brien"},
        )
        return ctx, steps.plan_namespace(ctx)[0], "namespace", "create"
    if case == "namespace-update":
        return ctx, steps.plan_identity(ctx)[0], "namespace", "update"
    if case == "instance-create":
        ctx["create_su"] = CreateRequest("su", "updates", "rg", "eastus2", identity=choice)
        return ctx, steps.plan_software_updates(ctx)[0], "update_instance", "create"
    if case == "namespace-show":
        ctx["selected_dps"] = Candidate("dps", PREFIX + "Microsoft.Devices/provisioningServices/dps")
        return ctx, steps.plan_final_verification(ctx)[0], "namespace", "show"
    kind = case.split("-")[0]
    request = CreateRequest(kind, "target", "rg", "eastus2", identity=choice)
    target = Candidate("target", request.arm_id(SUBSCRIPTION))
    set_choice(ctx, kind, choice, target.resource_id)
    if kind == "dps":
        ctx["selected_dps"] = target
        if case == "dps-update":
            ctx["namespace"] = {"properties": {"provisioning": {"endpoints": {
                "persisted-dps": {"resourceId": target.resource_id, "linkingState": "Failed"},
            }}}}
        return ctx, steps.plan_provisioning(ctx)[-1], "link", case.replace("-", "_")
    if kind == "hub":
        ctx["selected_hubs"] = [target]
        if case == "hub-update":
            ctx["namespace"] = {"properties": {"messaging": {"endpoints": {
                "persisted-hub": {"resourceId": target.resource_id, "linkingState": "Pending"},
            }}}}
        return ctx, steps.plan_messaging(ctx)[-1], "link", case.replace("-", "_")
    ctx["selected_sus"] = [target]
    if case == "su-update":
        ctx["namespace"] = {"properties": {"updating": {"endpoints": {
            "persisted-endpoint": {"resourceId": target.resource_id},
        }}}}
    return ctx, steps.plan_software_updates(ctx)[-1], "link", "su_update" if case == "su-update" else "su_add"


@pytest.mark.parametrize("mode", ["system", "user"])
@pytest.mark.parametrize("case", [
    "namespace-create", "namespace-update", "instance-create", "namespace-show",
    "dps-add", "dps-update", "hub-add", "hub-update", "su-add", "su-update",
])
def test_exported_adr_command_roundtrips_real_cli_parser_and_provider_kwargs(offline_cli, case, mode):
    cli, session = offline_cli
    choice = IdentityChoice(mode=mode, uami_id=UAMI_ID if mode == "user" else "")
    ctx, item, provider_name, method_name = _export_case(case, choice)
    flow = Flow([Step("export", "Export", plan=lambda _: [item])], ctx)
    script = flow.script()
    executable = [line for line in script.splitlines() if line.startswith("az ")]
    assert executable == [flow.scoped_command(command) for command in (item.command, *item.verify_commands)]
    for check in item.verify_checks:
        assert f"radar_check=$({flow.scoped_command(check.command)})" in script
    method = getattr(session.provider(provider_name), method_name)
    # Final verification uses subsequent waits and assertions; its invoker is a no-op.
    if case == "namespace-show":
        expected = {"namespace_name": "ns", "resource_group_name": "rg"}
    else:
        assert item.invoke(session, ctx) == {"accepted": provider_name}
        method.assert_called_once()
        expected = deepcopy(method.call_args.kwargs)
        assert expected.pop("no_wait") is True
        method.reset_mock()
    args = shlex.split(executable[0])
    assert args.pop(0) == "az"
    assert cli.invoke(args, out_file=StringIO()) == 0, cli.result.error
    assert session.provider(provider_name).command_subscriptions == [SUBSCRIPTION]
    from azure.cli.core._profile import Profile
    assert Profile(cli_ctx=cli).get_subscription()["id"] == DEFAULT_SUBSCRIPTION
    method.assert_called_once()
    actual = dict(method.call_args.kwargs)
    if case != "namespace-show":
        # The UI waits in its execution worker; exported CLI commands wait inline.
        assert actual.pop("no_wait") is False
    for key, value in expected.items():
        if key.endswith("system_assigned"):
            assert bool(actual.pop(key)) is value
        else:
            assert actual.pop(key) == value
    # CLI handlers send unset optional arguments explicitly; the plan needn't.
    assert all(value is None for value in actual.values())
    if case in ("su-update", "hub-update", "dps-update"):
        kind = case.split("-")[0]
        assert f"{kind}_resource_id" not in method.call_args.kwargs
        assert f"--{kind}-id" not in executable[0]


def test_export_requirements_are_comment_only_and_explain_batch_preflight_difference():
    ctx = {
        "subscription_id": SUBSCRIPTION, "namespace_name": "ns", "resource_group_name": "rg",
        "selected_sus": [Candidate("updates", PREFIX + "Microsoft.DeviceUpdate/updateInstances/updates")],
    }
    items = steps.plan_permissions(ctx)
    script = Flow([Step("roles", "Roles", plan=lambda _: items)]).script()
    assert "each use base RBAC preflight; the UI batches preflight" in script
    assert "Device Update Administrator" in script
    requirements = [item for item in items if item.action == "required"]
    assert len(requirements) == 4
    assert all(f"# Remediation only: {item.command}" in script for item in requirements)
    assert not any(line.startswith("az ") for line in script.splitlines())


@pytest.mark.parametrize("mode", ["system", "user"])
def test_exported_su_identity_attachment_roundtrips_identity_only_update(offline_cli, monkeypatch, mode):
    cli, session = offline_cli
    choice = IdentityChoice(mode=mode, uami_id=UAMI_ID if mode == "user" else "")
    target = Candidate("updates", PREFIX + "Microsoft.DeviceUpdate/updateInstances/updates", resource_group="rg")
    item, = steps._plan_target_identity({}, "su", target, choice)
    sdk = Mock()
    factory = Mock(return_value=SimpleNamespace(update_instances=sdk))
    monkeypatch.setattr(
        "azext_iot._factory.adr_update_instance_service_factory",
        factory,
    )
    catalog = SimpleNamespace(cmd=SimpleNamespace(cli_ctx=object()))
    assert item.invoke(session, {"_catalog": catalog}) is sdk.begin_update.return_value
    factory.assert_called_once_with(catalog.cmd.cli_ctx, subscription_id=SUBSCRIPTION)
    merged = (
        {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}}
        if mode == "user" else {"type": "SystemAssigned"}
    )
    sdk.begin_update.assert_called_once_with(
        resource_group_name="rg", update_instance_name="updates", properties={"identity": merged},
    )
    script = Flow([Step("identity", "Identity", plan=lambda _: [item])], {"subscription_id": DEFAULT_SUBSCRIPTION}).script()
    command, = [line for line in script.splitlines() if line.startswith("az ")]
    assert command.count("--subscription") == 1
    assert command.endswith(f"--subscription {SUBSCRIPTION}")
    assert cli.invoke(shlex.split(command)[1:], out_file=StringIO()) == 0, cli.result.error
    assert session.provider("update_instance").command_subscriptions == [SUBSCRIPTION]
    session.provider("update_instance").update.assert_called_once_with(
        update_instance_name="updates", resource_group_name="rg", tags=None,
        mi_system_assigned=True if mode == "system" else None,
        mi_user_assigned=[UAMI_ID] if mode == "user" else None, no_wait=False,
    )


def test_handbuilt_identity_create_export_uses_reviewed_subscription_and_sdk_arguments(offline_cli, monkeypatch):
    from azure.cli.command_modules.identity.aaz.latest.identity import Create

    cli, _session = offline_cli
    choice = IdentityChoice(
        mode="user", create_uami=True, uami_id=UAMI_ID, uami_name="reviewed",
        uami_resource_group="rg", uami_location="eastus2",
    )
    sdk = Mock()
    monkeypatch.setattr(
        "azure.cli.command_modules.identity._client_factory._msi_client_factory",
        Mock(return_value=SimpleNamespace(user_assigned_identities=sdk)),
    )
    session = Session(SimpleNamespace(cli_ctx=cli))
    assert create_uami(session, choice) is sdk.create_or_update.return_value
    parsed = []
    monkeypatch.setattr(Create, "_execute_operations", lambda command: parsed.append(
        (command.ctx.args.to_serialized_data(), command.ctx.subscription_id),
    ))
    monkeypatch.setattr(Create, "_output", Mock(return_value={}))
    item = PlanItem("uami", "Create reviewed identity", command=create_uami_command(choice))
    script = Flow([Step("uami", "Identity", plan=lambda _: [item])], {"subscription_id": SUBSCRIPTION}).script()
    command, = [line for line in script.splitlines() if line.startswith("az ")]
    assert command.endswith(f"--subscription {SUBSCRIPTION}")
    assert cli.invoke(shlex.split(command)[1:], out_file=StringIO()) == 0, cli.result.error
    assert len(parsed) == 1
    assert parsed[0][1] == SUBSCRIPTION
    arguments = parsed[0][0]
    kwargs = sdk.create_or_update.call_args.kwargs
    assert arguments["resource_name"] == kwargs["resource_name"] == "reviewed"
    assert arguments["resource_group"] == kwargs["resource_group_name"] == "rg"
    assert arguments["location"] == kwargs["parameters"]["location"] == "eastus2"


@pytest.fixture
def offline_waits(monkeypatch):
    sleeper = Mock()
    monkeypatch.setattr(commands_wait, "wait_for_resource", partial(wait_for_resource, sleeper=sleeper))
    return sleeper


@pytest.fixture
def bash_executable():
    executable = shutil.which("bash")
    if sys.platform == "win32":
        # Use Git Bash rather than the unrelated Windows WSL launcher.
        git = shutil.which("git")
        if git:
            candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe"
            if candidate.is_file():
                executable = str(candidate)
    assert executable, "The runnable Bash export contract requires Bash (Git Bash on Windows)."
    return executable


def _run_export_offline(cli, flow, bash_executable):
    """Roundtrip every command through the real parser; replay only those offline results in Bash."""
    reviewed = flow.build_plan()
    commands = []
    for item in reviewed:
        if item.action in ("exists", "blocked", "required"):
            continue
        commands.extend([item.command] if item.command else [])
        commands.extend(item.verify_commands)
        commands.extend(check.command for check in item.verify_checks)
    results = {}
    for command in commands:
        argv = shlex.split(flow.scoped_command(command))
        assert argv.pop(0) == "az"
        assert argv.count("--subscription") == 1 and argv[argv.index("--subscription") + 1] == SUBSCRIPTION
        output = StringIO()
        code = cli.invoke(argv, out_file=output)
        results[" ".join(argv)] = (code, output.getvalue())
    dispatch = ["az() {", "printf 'RADAR_CALL:%s\\n' \"$*\" >&2", 'case "$*" in']
    for arguments, (code, output) in results.items():
        dispatch.append(f"{shlex.quote(arguments)}) printf '%s' {shlex.quote(output)}; return {code} ;;")
    dispatch += ["*) return 99 ;;", "esac", "}"]
    exported = flow.script(plan=reviewed)
    assert exported == flow.script()
    process = subprocess.run(
        [bash_executable, "--noprofile", "--norc"],
        input="\n".join(dispatch) + "\n" + exported + "\nprintf '%s' export-succeeded\n",
        text=True, capture_output=True, check=False, timeout=15,
    )
    return process, results


def _link_export_context(kind, state="Succeeded", address=True):
    target = Candidate("reviewed", CreateRequest(kind, "reviewed", "rg", "eastus2").arm_id(SUBSCRIPTION))
    endpoint = {
        "resourceId": target.resource_id, "endpointType": steps._LINK_TYPES[kind],
        "linkingState": state, "inboundCallerIdentity": {"type": "SystemAssigned"},
    }
    if kind == "su" and address:
        endpoint["serviceAddress"] = "https://updates.example"
    name = "persisted.endpoint's-name"
    namespace = {"properties": {
        "provisioningState": "Succeeded", "outboundIdentity": {"type": "SystemAssigned"},
        steps._LINK_SECTIONS[kind]: {"endpoints": {name: endpoint}},
    }}
    ctx = {
        "subscription_id": SUBSCRIPTION, "namespace_name": "ns", "resource_group_name": "rg",
        "namespace": namespace,
        {"dps": "selected_dps", "hub": "selected_hubs", "su": "selected_sus"}[kind]:
            target if kind == "dps" else [target],
    }
    return ctx, endpoint, name


@pytest.mark.parametrize("kind", ["dps", "hub", "su"])
@pytest.mark.parametrize("outcome", ["ready", "pending", "failed", "missing"])
def test_exported_endpoint_waits_reject_namespace_only_lro_success(
    offline_cli, offline_waits, bash_executable, kind, outcome,
):
    cli, session = offline_cli
    ctx, endpoint, name = _link_export_context(kind, state="Pending")
    planner = {"dps": steps.plan_provisioning, "hub": steps.plan_messaging, "su": steps.plan_software_updates}[kind]
    item = planner(ctx)[-1]
    assert item.action == "modify" and item.target == name
    endpoint["linkingState"] = {"ready": "Succeeded", "pending": "Pending", "failed": "Failed", "missing": ""}[outcome]
    if outcome == "missing":
        ctx["namespace"]["properties"][steps._LINK_SECTIONS[kind]]["endpoints"].clear()
    session.provider("namespace").show.return_value = ctx["namespace"]
    session.provider("link")._get_namespace.return_value = ctx["namespace"]
    flow = Flow([Step("link", "Link", plan=lambda _: [item])], ctx)
    process, results = _run_export_offline(cli, flow, bash_executable)
    assert process.returncode == (0 if outcome == "ready" else 1), process.stderr
    assert ("export-succeeded" in process.stdout) is (outcome == "ready")
    assert session.provider("link").command_subscriptions == [SUBSCRIPTION] * (1 + len(item.verify_commands))
    assert session.provider("namespace").command_subscriptions == [SUBSCRIPTION]
    assert all(call.args == ("ns", "rg") for call in session.provider("link")._get_namespace.call_args_list)
    command, _result = next(iter(results.items()))
    assert f"{kind} update " in command and f"--endpoint-name {name}" in command
    if outcome in ("pending", "missing"):
        assert offline_waits.call_count >= 120
    else:
        offline_waits.assert_not_called()


@pytest.mark.parametrize("failure", [
    None, "pending", "failed", "missing-address", "target", "identity-type", "identity-id", "state-after-wait",
])
def test_final_export_asserts_normalized_targets_outbound_identity_and_su_readiness(
    offline_cli, offline_waits, bash_executable, failure,
):
    cli, session = offline_cli
    ctx, endpoint, _name = _link_export_context("su")
    choice = IdentityChoice(mode="user", uami_id=UAMI_ID)
    set_choice(ctx, "namespace", choice)
    ctx["create_namespace"] = CreateRequest("namespace", "ns", "rg", "eastus2", identity=choice)
    outbound = {"type": "User Assigned", "userAssignedIdentity": UAMI_ID.upper()}
    ctx["namespace"]["properties"]["outboundIdentity"] = outbound
    item, = steps.plan_final_verification(ctx)
    endpoint["resourceId"] = endpoint["resourceId"].upper() + "///"
    if failure in ("pending", "failed"):
        endpoint["linkingState"] = failure.title()
    elif failure == "missing-address":
        endpoint.pop("serviceAddress")
    elif failure == "target":
        endpoint["resourceId"] += "unreviewed"
    elif failure == "identity-type":
        outbound["type"] = "SystemAssigned"
    elif failure == "identity-id":
        outbound["userAssignedIdentity"] += "/unreviewed"
    wait_payload = deepcopy(ctx["namespace"])
    if failure == "state-after-wait":
        endpoint["linkingState"] = "Failed"
    session.provider("namespace").show.return_value = ctx["namespace"]
    session.provider("link")._get_namespace.return_value = wait_payload
    if failure is None:
        assert item.verify(session, ctx) is ctx["namespace"]
    else:
        with pytest.raises(AzureResponseError):
            item.verify(session, ctx)
    flow = Flow([Step("verify", "Verify", plan=lambda _: [item])], ctx)
    process, results = _run_export_offline(cli, flow, bash_executable)
    assert process.returncode == int(failure is not None), process.stderr
    assert ("export-succeeded" in process.stdout) is (failure is None)
    if failure in ("target", "identity-type", "identity-id", "state-after-wait"):
        assert all(code == 0 for code, _stdout in results.values())
        assert "Verification failed:" in process.stderr
    elif failure in ("pending", "failed", "missing-address"):
        assert any(code != 0 for code, _stdout in results.values())
    else:
        assert all(code == 0 for code, _stdout in results.values())
    if failure in ("pending", "missing-address"):
        assert offline_waits.call_count == 120
    else:
        offline_waits.assert_not_called()


def test_export_readiness_supports_nested_provisioning_status_without_linking_state(
    offline_cli, offline_waits, bash_executable,
):
    cli, session = offline_cli
    ctx, endpoint, _name = _link_export_context("hub")
    endpoint.pop("linkingState")
    endpoint["provisioningStatus"] = {"status": "sUcCeEdEd"}
    session.provider("namespace").show.return_value = ctx["namespace"]
    session.provider("link")._get_namespace.return_value = ctx["namespace"]
    item, = steps.plan_final_verification(ctx)
    process, results = _run_export_offline(cli, Flow([Step("verify", "Verify", plan=lambda _: [item])], ctx), bash_executable)
    assert process.returncode == 0, process.stderr
    assert process.stdout.endswith("export-succeeded")
    assert all(code == 0 for code, _stdout in results.values())
    offline_waits.assert_not_called()


@pytest.mark.parametrize("ready", [False, True])
def test_uami_export_waits_for_principal_via_supported_resource_wait(offline_cli, monkeypatch, bash_executable, ready):
    from azure.cli.command_modules.identity.aaz.latest.identity import Create
    from azure.cli.command_modules.resource import custom

    cli, _session = offline_cli
    monkeypatch.setattr(Create, "_execute_operations", Mock())
    monkeypatch.setattr(Create, "_output", Mock(return_value={}))
    choice = IdentityChoice(
        mode="user", create_uami=True, uami_id=UAMI_ID, uami_name="reviewed",
        uami_resource_group="rg", uami_location="eastus2",
    )
    ctx = {"subscription_id": SUBSCRIPTION}
    set_choice(ctx, "namespace", choice)
    item, = steps.plan_uamis(ctx)
    command, = item.verify_commands
    getter = Mock(return_value={"properties": {"principalId": "reviewed-principal" if ready else ""}})
    observed = []

    def construct(cli_ctx, parsed_id, *_args):
        observed.append((cli_ctx.data["subscription_id"], parsed_id))
        return SimpleNamespace(get_resource=getter)

    monkeypatch.setattr(custom, "_get_rsrc_util_from_parsed_id", construct)
    sleeper = Mock()
    monkeypatch.setattr("time.sleep", sleeper)
    flow = Flow([Step("identity", "Identity", plan=lambda _: [item])], ctx)
    assert command in flow.script()
    assert "No executable verification" not in flow.script()
    process, results = _run_export_offline(cli, flow, bash_executable)
    assert process.returncode == (0 if ready else 1), process.stderr
    assert ("export-succeeded" in process.stdout) is ready
    assert any(arguments.startswith("resource wait ") for arguments in results)
    assert any(arguments.startswith("resource show ") for arguments in results)
    assert observed and all(subscription == SUBSCRIPTION for subscription, _parsed_id in observed)
    assert all(parsed_id == {"resource_id": UAMI_ID} for _, parsed_id in observed)
    assert getter.call_count == (2 if ready else 31)
    assert sleeper.call_count == (0 if ready else 30)


def _smoke_session(namespace):
    session = Session(
        SimpleNamespace(cli_ctx=object()), namespace_name=namespace["name"], resource_group_name="rg", read_only=True,
    )
    session.scope.subscription_id = SUBSCRIPTION
    session.scope.subscription_name = "offline"
    session._providers["namespace"] = Mock(
        list=Mock(return_value=[{"name": "unrelated", "resourceGroup": "rg"}, namespace]),
        show=Mock(return_value=namespace),
    )
    session._providers["link"] = Mock(list_all=Mock(return_value=[]))
    for name in ("group", "job", "certificate_authority"):
        session._providers[name] = Mock(list=Mock(return_value=[]))
    return session


def test_live_smoke_navigation_contract_uses_only_scoped_reads_and_no_mutation(offline_network):
    namespace = {
        "name": "owned", "location": "eastus2", "resourceGroup": "rg",
        "id": PREFIX + "Microsoft.DeviceRegistry/namespaces/owned",
        "properties": {"provisioningState": "Succeeded"},
    }
    session = _smoke_session(namespace)
    asyncio.run(radar._browse_readonly_namespace(session, namespace))
    session.provider("namespace").list.assert_called_once_with(resource_group_name="rg")
    session.provider("link").list_all.assert_called_once_with(namespace_name="owned", resource_group_name="rg")
    for name in ("group", "job", "certificate_authority"):
        session.provider(name).list.assert_called_once_with(namespace_name="owned", resource_group_name="rg")
    # No resource creation, identity setup, permission probes or mutations occurred.
    assert set(session._providers) == {"namespace", "link", "group", "job", "certificate_authority"}
    for provider in session._providers.values():
        assert all(record[0] in ("list", "list_all") for record in provider.mock_calls)


@pytest.mark.parametrize("failure", [None, "create", "wait", "gui", "cleanup", "collision"])
def test_live_smoke_owns_before_create_and_joins_gui_before_scoped_cleanup(monkeypatch, offline_network, failure):
    name = "owned-smoke"
    monkeypatch.setattr(radar, "generate_adr_namespace_name", lambda: name)
    scenario = radar.TestADRRadar("test_radar_readonly_namespace_smoke")
    scenario._resource_is_absent = Mock(return_value=failure != "collision")
    events = []
    owned = ("namespace", name, radar.TEST_RG)
    namespace = {"name": name, "location": radar.TEST_LOCATION, "properties": {"provisioningState": "Succeeded"}}
    session = _smoke_session(namespace)
    session.scope.subscription_id = radar.TEST_SUBSCRIPTION
    session.scope.resource_group_name = radar.TEST_RG
    monkeypatch.setattr(radar, "Session", Mock(return_value=session))

    def cmd(command):
        if command == "account show":
            result = {"id": radar.TEST_SUBSCRIPTION}
        else:
            assert owned in scenario._owned_resources
            events.append(command)
            if failure == "create" and command.startswith("iot adr ns create"):
                raise RuntimeError("post-accept create timeout")
            if failure == "wait" and command.startswith("iot adr ns wait"):
                raise RuntimeError("provisioning deadline")
            result = {}
        return SimpleNamespace(get_output_in_json=lambda: result)

    scenario.cmd = Mock(side_effect=cmd)
    listed = Mock()
    monkeypatch.setattr(radar, "wait_for_listed_resource", listed)

    async def browse(actual_session, payload):
        assert actual_session is session and payload is namespace
        events.append("gui-workers-joined")
        if failure == "gui":
            raise RuntimeError("GUI assertion failed")

    browser = AsyncMock(side_effect=browse)
    monkeypatch.setattr(radar, "_browse_readonly_namespace", browser)

    def delete(*resource):
        assert resource == owned
        events.append("delete-owned-namespace")
        if failure == "cleanup":
            raise RuntimeError("delete denied")

    scenario._delete_owned_resource = Mock(side_effect=delete)
    if failure:
        message = {
            "create": "post-accept create timeout", "wait": "provisioning deadline", "gui": "GUI assertion failed",
            "cleanup": "ADR cleanup failed.*delete denied", "collision": "Refusing to overwrite existing namespace",
        }[failure]
        with pytest.raises((RuntimeError, AssertionError), match=message):
            scenario.test_radar_readonly_namespace_smoke()
    else:
        scenario.test_radar_readonly_namespace_smoke()
    scenario._resource_is_absent.assert_called_once_with("namespace", name, radar.TEST_RG)
    if failure == "collision":
        scenario._delete_owned_resource.assert_not_called()
        assert not events
    else:
        assert events[-1] == "delete-owned-namespace"
        scenario._delete_owned_resource.assert_called_once_with(*owned)
        assert events[0].startswith(f"iot adr ns create -n {name} ")
        assert "--no-wait" in events[0]
        assert "--outbound-" not in events[0]
        if failure not in ("create", "wait"):
            browser.assert_awaited_once()
            assert events[-2] == "gui-workers-joined"
            listed.assert_called_once()
        assert set(scenario._owned_resources) == ({owned} if failure == "cleanup" else set())
