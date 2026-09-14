# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Executable onboarding contracts at the SDK, plan, and asynchronous read boundaries."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import shlex
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.adr.ui.core.session import Session
from azext_iot.adr.ui.screens.onboard import create, identity, pickers, steps
from azext_iot.adr.ui.screens.onboard.flow import Flow, PlanItem, Step, StepState


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
PREFIX = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/"
UAMI_ID = PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/link-identity"
CHOICE = identity.IdentityChoice(
    mode=identity.USER_ASSIGNED, uami_id=UAMI_ID, uami_name="link-identity",
    create_uami=True, uami_resource_group="rg", uami_location="eastus2",
)
SCOPE = {"namespace_name": "ns", "resource_group_name": "rg"}


def context(**extra):
    return {**SCOPE, "subscription_id": SUBSCRIPTION, "namespace": {}, **extra}


def session_with(**providers):
    session = Session(SimpleNamespace(cli_ctx=object()))
    session._providers.update(providers)
    return session


@pytest.mark.parametrize("kind,label", [
    ("namespace", "namespace"), ("dps", "DPS"), ("hub", "IoT Hub"), ("su", "update instance"),
    ("resource_group", "resource_group"),
])
def test_create_request_review_labels_identify_the_actual_resource_kind(kind, label):
    assert create.CreateRequest(kind, "target", "rg", "eastus2").label == label


@pytest.mark.parametrize("kind,factory,collection,name_arg,body_arg", [
    ("hub", "iot_hub_service_factory", "iot_hub_resource", "resource_name", "iot_hub_description"),
    ("dps", "iot_service_provisioning_factory", "iot_dps_resource",
     "provisioning_service_name", "iot_dps_description"),
])
@pytest.mark.parametrize("choice,sku", [(identity.system_choice(), None), (CHOICE, "S2")])
def test_create_target_forwards_reviewed_capacity_identity_and_location(
    monkeypatch, kind, factory, collection, name_arg, body_arg, choice, sku,
):
    client = Mock()
    factory_mock = Mock(return_value=SimpleNamespace(**{collection: client}))
    monkeypatch.setattr("azext_iot._factory." + factory, factory_mock)
    catalog = pickers.ResourceCatalog(SimpleNamespace(cli_ctx=object()))
    request = create.CreateRequest(kind, "target", "rg", "eastus2", sku=sku, capacity=2, identity=choice)

    result = getattr(create, "create_" + kind)(catalog, request)

    expected_identity = (
        {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID: {}}}
        if choice.is_user_assigned else {"type": "SystemAssigned"}
    )
    factory_mock.assert_called_once_with(catalog.cmd.cli_ctx)
    client.begin_create_or_update.assert_called_once_with(**{
        "resource_group_name": "rg", name_arg: "target",
        body_arg: {"location": "eastus2", "sku": {"name": sku or "S1", "capacity": 2},
                   "identity": expected_identity, "properties": {}},
    })
    assert result is client.begin_create_or_update.return_value


@pytest.mark.parametrize("choice", [identity.system_choice(), CHOICE])
def test_update_instance_creation_uses_selected_identity_without_other_resources(choice):
    provider = Mock()
    session = session_with(update_instance=provider)
    request = create.CreateRequest("su", "updates", "rg", "eastus2", identity=choice)
    assert create.create_update_instance(session, request) is provider.create.return_value
    provider.create.assert_called_once_with(
        update_instance_name="updates", resource_group_name="rg", location="eastus2",
        mi_system_assigned=not choice.is_user_assigned,
        mi_user_assigned=[UAMI_ID] if choice.is_user_assigned else None, no_wait=True,
    )
    assert set(session._providers) == {"update_instance"}


def test_identity_lookup_skips_other_attachments_and_missing_principals():
    resource = {"identity": {"userAssignedIdentities": {
        "/unrelated": {"principalId": "wrong"}, UAMI_ID.upper(): {"principalId": "reviewed"},
    }}}
    assert identity.principal_of(resource, CHOICE) == "reviewed"
    resource["identity"]["userAssignedIdentities"][UAMI_ID.upper()] = None
    assert identity.principal_of(resource, CHOICE) == ""
    assert identity.principal_of({}, CHOICE) == ""
    assert identity.identity_flags(CHOICE) == ((), {"user_assigned_mi": UAMI_ID})
    assert identity.identity_flags(identity.system_choice()) == (("--system-assigned-mi",), {})
    assert identity.identity_command_flags(CHOICE) == f"--user-assigned-mi {UAMI_ID}"
    assert identity.identity_command_flags(identity.system_choice()) == "--system-assigned-mi"
    assert identity._resource_group({"id": "/malformed"}) == ""
    assert identity._resource_group({"id": PREFIX + "resource/target"}) == "rg"


def test_reviewed_identity_choice_survives_resource_id_casing_and_trailing_slash():
    ctx = context()
    identity.set_choice(ctx, "hub", CHOICE, "/subscriptions/target/hubs/hub/")
    assert identity.get_choice(ctx, "hub", "/SUBSCRIPTIONS/TARGET/HUBS/HUB") is CHOICE
    assert identity.has_choice(ctx, "hub", "/subscriptions/target/hubs/hub")
    identity.remove_choice(ctx, "hub", "/SUBSCRIPTIONS/TARGET/HUBS/HUB/")
    assert not identity.has_choice(ctx, "hub", "/subscriptions/target/hubs/hub")


@pytest.mark.parametrize("selected", [False, True])
def test_assignment_matrix_preserves_each_resource_identity(selected):
    ctx = context()
    identity.set_choice(ctx, "namespace", CHOICE)
    expected = [("Namespace -> targets", "ns", CHOICE)]
    for kind, direction in (
        ("dps", "DPS -> namespace"), ("hub", "Hub -> namespace"), ("su", "Updates -> namespace"),
    ):
        request = create.CreateRequest(kind, kind, "rg", "eastus2", identity=CHOICE)
        if selected:
            candidate = pickers.Candidate(kind, request.arm_id(SUBSCRIPTION))
            ctx[{"dps": "selected_dps", "hub": "selected_hubs", "su": "selected_sus"}[kind]] = (
                candidate if kind == "dps" else [candidate]
            )
            identity.set_choice(ctx, kind, CHOICE, candidate.resource_id)
        else:
            ctx["create_" + kind] = request
        expected.append((direction, kind, CHOICE))
    assert identity.assignment_rows(ctx) == expected


def test_uami_creation_preserves_the_reviewed_location_and_returns_sdk_result(monkeypatch):
    client = Mock()
    factory = Mock(return_value=SimpleNamespace(user_assigned_identities=client))
    monkeypatch.setattr("azure.cli.command_modules.identity._client_factory._msi_client_factory", factory)
    session = session_with()
    assert identity.create_uami(session, CHOICE) is client.create_or_update.return_value
    factory.assert_called_once_with(session.cmd.cli_ctx)
    client.create_or_update.assert_called_once_with(
        resource_group_name="rg", resource_name="link-identity", parameters={"location": "eastus2"},
    )


@pytest.mark.parametrize("kind,factory,collection", [
    ("hub", "iot_hub_service_factory", "iot_hub_resource"),
    ("dps", "iot_service_provisioning_factory", "iot_dps_resource"),
    ("su", "adr_update_instance_service_factory", "update_instances"),
])
@pytest.mark.parametrize("choice,existing", [
    (CHOICE, {"type": "None"}),
    (CHOICE, {"type": "SystemAssigned", "principalId": "existing-system"}),
    (identity.system_choice(), {"type": "UserAssigned", "userAssignedIdentities": {"/keep": {}}}),
])
def test_attach_identity_is_additive_and_su_uses_identity_only_patch(monkeypatch, kind, factory, collection, choice, existing):
    client = Mock()
    monkeypatch.setattr("azext_iot._factory." + factory, Mock(return_value=SimpleNamespace(**{collection: client})))
    resource = {
        "name": "target", "id": PREFIX + "resources/target", "location": "eastus2",
        "identity": existing, "etag": "reviewed-etag", "properties": {"preserve": "value"},
    }
    before = deepcopy(resource)
    result = identity.attach_identity(pickers.ResourceCatalog(SimpleNamespace(cli_ctx=object())), kind, resource, choice)
    merged = {
        "type": "UserAssigned" if existing["type"] == "None" else "SystemAssigned, UserAssigned",
        "userAssignedIdentities": {UAMI_ID: {}} if choice.is_user_assigned else {"/keep": {}},
    }
    if kind == "su":
        client.begin_update.assert_called_once_with(
            resource_group_name="rg", update_instance_name="target", properties={"identity": merged},
        )
        client.begin_create_or_update.assert_not_called()
        assert result is client.begin_update.return_value
    else:
        name_arg, body_arg = (
            ("resource_name", "iot_hub_description") if kind == "hub"
            else ("provisioning_service_name", "iot_dps_description")
        )
        client.begin_create_or_update.assert_called_once_with(**{
            "resource_group_name": "rg", name_arg: "target", body_arg: {**resource, "identity": merged},
            **({"etag": "reviewed-etag"} if kind == "hub" else {}),
        })
        assert result is client.begin_create_or_update.return_value
    assert resource == before


def test_unknown_identity_attachment_fails_without_constructing_clients():
    catalog = Mock()
    with pytest.raises(ValueError, match="Unsupported identity attachment target 'device'"):
        identity.attach_identity(catalog, "device", {}, CHOICE)
    assert not catalog.mock_calls
    assert identity._merged_identity({}, identity.system_choice()) == {"type": "SystemAssigned"}


@pytest.mark.parametrize("method,key,factory,collection", [
    ("provisioning_services", "dps", "azext_iot._factory.iot_service_provisioning_factory", "iot_dps_resource"),
    ("hubs", "hub", "azext_iot._factory.iot_hub_service_factory", "iot_hub_resource"),
    ("update_instances", "su", "azext_iot._factory.adr_update_instance_service_factory", "update_instances"),
    ("user_assigned_identities", "uami",
     "azure.cli.command_modules.identity._client_factory._msi_client_factory", "user_assigned_identities"),
])
def test_catalog_provider_loaders_cache_and_retry_after_clear(monkeypatch, method, key, factory, collection):
    client = Mock()
    model = Mock(as_dict=Mock(return_value={"name": "target"}))
    client.list_by_subscription.return_value = [model]
    factory_mock = Mock(return_value=SimpleNamespace(**{collection: client}))
    monkeypatch.setattr(factory, factory_mock)
    catalog = pickers.ResourceCatalog(SimpleNamespace(cli_ctx=object()))

    assert getattr(catalog, method)() == [{"name": "target"}]
    assert getattr(catalog, method)() == [{"name": "target"}]
    factory_mock.assert_called_once_with(catalog.cmd.cli_ctx)
    client.list_by_subscription.assert_called_once_with()
    catalog.clear()
    client.list_by_subscription.side_effect = RuntimeError("Reader required")
    assert getattr(catalog, method)() == []
    assert catalog.error_for(key) == "Reader required"
    catalog.clear()
    client.list_by_subscription.side_effect = None
    assert getattr(catalog, method)() == [{"name": "target"}]
    assert catalog.error_for(key) is None


@pytest.mark.parametrize("states,expected", [
    (["Disabled", "Enabled"], ["s1"]),
    (["Disabled", "Warned"], ["s0", "s1"]),
])
def test_subscription_catalog_prefers_enabled_without_hiding_all_disabled(monkeypatch, states, expected):
    profile = Mock()
    profile.load_cached_subscriptions.return_value = [
        {"name": f"s{i}", "id": f"id{i}", "state": state} for i, state in enumerate(states)
    ]
    factory = Mock(return_value=profile)
    monkeypatch.setattr("azure.cli.core._profile.Profile", factory)
    catalog = pickers.ResourceCatalog(SimpleNamespace(cli_ctx=object()))
    listed = catalog.subscriptions()
    assert [item["name"] for item in listed] == expected
    assert all(item["identity"] == {"type": "n/a"} and item["location"] == "" for item in listed)
    assert catalog.subscriptions() == listed
    factory.assert_called_once_with(cli_ctx=catalog.cmd.cli_ctx)


def test_catalog_resource_groups_namespaces_and_dps_registration_use_scoped_reads(monkeypatch):
    groups = Mock()
    groups.list.return_value = [SimpleNamespace(name="rg", id="/groups/rg", location="eastus2")]
    monkeypatch.setattr(
        "azext_iot._factory.resource_service_factory", Mock(return_value=SimpleNamespace(resource_groups=groups)),
    )
    catalog = pickers.ResourceCatalog(SimpleNamespace(cli_ctx=object()))
    assert catalog.resource_groups() == [{
        "name": "rg", "id": "/groups/rg", "location": "eastus2", "identity": {"type": "n/a"},
    }]
    groups.list.assert_called_once_with()
    provider = Mock()
    provider.list.return_value = [{"name": "ns"}]
    session = session_with(namespace=provider)
    assert catalog.namespaces(session, "rg") == [{"name": "ns"}]
    assert catalog.namespaces(session, "rg") == [{"name": "ns"}]
    assert catalog.namespaces(session) == [{"name": "ns"}]
    assert provider.list.call_args_list == [call(resource_group_name="rg"), call(resource_group_name=None)]
    assert catalog.registered_hub_names({"properties": {"iotHubs": [
        {"name": "one.azure-devices.net"}, None, {}, "invalid",
    ]}}) == ["one.azure-devices.net", ""]
    assert catalog.registered_hub_names({}) == []
    assert pickers._resource_group_of({"resourceGroup": "explicit"}) == "explicit"
    assert pickers.ResourceCatalog._as_dict(SimpleNamespace(
        name="legacy", id="/legacy", location="eastus2", identity=SimpleNamespace(type="SystemAssigned"),
    )) == {"name": "legacy", "id": "/legacy", "location": "eastus2", "identity": {"type": "SystemAssigned"}}
    assert pickers.ResourceCatalog._as_dict(SimpleNamespace(name="minimal")) == {
        "name": "minimal", "id": "", "location": "", "identity": {},
    }


@pytest.mark.parametrize("invalidate", ["clear", "new-request"])
def test_late_catalog_failure_cannot_overwrite_a_newer_success(invalidate):
    catalog = pickers.ResourceCatalog(None)

    def stale_loader():
        if invalidate == "clear":
            catalog.clear()
        assert catalog._listed("hub", lambda: [{"name": "new"}]) == [{"name": "new"}]
        raise RuntimeError("obsolete authorization error")

    assert not catalog._listed("hub", stale_loader)
    assert catalog._listed("hub", Mock(side_effect=AssertionError("must use cache"))) == [{"name": "new"}]
    assert catalog.error_for("hub") is None


def test_flow_current_and_satisfied_include_no_phantom_action_after_completion():
    done = Step("namespace", "Namespace", detect=lambda ctx: ctx["ready"])
    pending = Step("hub", "Hub", after=("namespace",), detect=lambda ctx: ctx["linked"])
    flow = Flow([done, pending], {"ready": False, "linked": False})
    assert flow.current() is done
    assert flow.satisfied() == []
    assert StepState.CURRENT.is_actionable and StepState.PENDING.is_actionable
    assert not StepState.BLOCKED.is_actionable and not StepState.SATISFIED.is_actionable
    flow.context.update(ready=True, linked=True)
    assert flow.current() is None
    assert flow.satisfied() == [done, pending]
    assert flow.is_complete and flow.progress() == (2, 2)


def test_no_su_request_reconciliation_is_a_noop_and_completed_setup_has_no_preflight():
    ctx = context(namespace={"properties": {"outboundIdentity": {"type": "SystemAssigned"}}})
    before = deepcopy(ctx)
    steps.reconcile_software_updates_creation(ctx)
    assert ctx == before
    assert not steps.plan_preflight(ctx)
    assert steps.principal_of({"identity": "invalid"}) == ""
    assert steps.principal_of({"identity": {"principalId": "pid"}}) == "pid"
    with pytest.raises(ValueError, match="principal lookup needs a resource id"):
        steps.grant_command("", "Reader", "/scope")


@pytest.mark.parametrize("read_only", [True, False])
def test_preflight_blocks_readonly_or_a_freshly_discovered_region_conflict(read_only):
    target = pickers.Candidate("dps", "/dps", location="eastus2")
    ctx = context(namespace={"location": "eastus2"}, selected_dps=target)
    plan = steps.plan_preflight(ctx)
    provider = Mock()
    provider.show.return_value = {"location": "westus2"}
    session = session_with(namespace=provider)
    session.read_only = read_only
    with pytest.raises(AzureResponseError, match="Read-only" if read_only else "Cross-region"):
        plan[0].invoke(session, ctx)
    assert provider.show.call_count == (0 if read_only else 1)
    assert ctx["namespace"] == {"location": "eastus2"}


def test_preflight_rejects_link_topology_changed_since_review():
    ctx = context(namespace={"location": "eastus2"})
    item, = steps.plan_preflight(ctx)
    fresh = {"location": "eastus2", "properties": {"provisioning": {"endpoints": {"unreviewed": {}}}}}
    provider = Mock(show=Mock(return_value=fresh))
    with pytest.raises(AzureResponseError, match="Namespace links or outbound identity changed"):
        item.invoke(session_with(namespace=provider), ctx)
    provider.show.assert_called_once_with(**SCOPE)
    assert ctx["namespace"] == {"location": "eastus2"}


def test_resource_group_plan_invokes_exact_reviewed_create(monkeypatch):
    groups = Mock()
    factory = Mock(return_value=SimpleNamespace(resource_groups=groups))
    monkeypatch.setattr("azext_iot._factory.resource_service_factory", factory)
    request = create.CreateRequest("resource_group", "new-rg", "", "eastus2")
    session = session_with()
    item, = steps.plan_resource_group(context(create_resource_group=request))
    assert item.command == "az group create -n new-rg --location eastus2"
    assert item.invoke(session, {}) is groups.create_or_update.return_value
    factory.assert_called_once_with(session.cmd.cli_ctx)
    groups.create_or_update.assert_called_once_with("new-rg", {"location": "eastus2"})


def test_uami_plan_deduplicates_case_insensitive_ids_and_invokes_once(monkeypatch):
    create_identity = Mock()
    monkeypatch.setattr(steps, "create_uami", create_identity)
    duplicate = identity.IdentityChoice(mode="user", create_uami=True, uami_id=UAMI_ID.upper())
    ctx = context(identity_choices={"namespace": CHOICE, "hub": duplicate})
    item, = steps.plan_uamis(ctx)
    assert item.command == "az identity create -n link-identity -g rg -l eastus2"
    session = session_with()
    assert item.invoke(session, ctx) is create_identity.return_value
    create_identity.assert_called_once_with(session, CHOICE)


@pytest.mark.parametrize("representation", ["dict", "serialized", "object", "timeout"])
def test_uami_readiness_is_bounded_and_reports_principal_without_real_sleep(monkeypatch, representation):
    sleeper = Mock()
    monkeypatch.setattr("time.sleep", sleeper)
    client = Mock()
    monkeypatch.setattr(
        "azure.cli.command_modules.identity._client_factory._msi_client_factory",
        Mock(return_value=SimpleNamespace(user_assigned_identities=client)),
    )
    ready = {
        "dict": {"principalId": "ready"},
        "serialized": SimpleNamespace(as_dict=lambda: {"principal_id": "ready"}),
        "object": SimpleNamespace(principal_id="ready"),
    }.get(representation)
    client.get.side_effect = [{}, ready] if ready is not None else None
    client.get.return_value = {}
    notify = Mock()
    verify = steps.plan_uamis(context(identity_choices={"namespace": CHOICE}))[0].verify
    if representation == "timeout":
        with pytest.raises(AzureResponseError, match="Timed out waiting for UAMI 'link-identity' principalId"):
            verify(session_with(), {}, notify)
        assert client.get.call_count == sleeper.call_count == 30
        assert notify.call_args_list == [call("Waiting for principalId")] * 30
    else:
        assert verify(session_with(), {}, notify) is ready
        assert client.get.call_count == 2
        sleeper.assert_called_once_with(2)
        assert notify.call_args_list == [call("Waiting for principalId"), call("principalId: ready")]
    assert all(args == call(resource_group_name="rg", resource_name="link-identity") for args in client.get.call_args_list)


@pytest.mark.parametrize("kind,planner,create_key,link_key,link_method", [
    ("dps", steps.plan_provisioning, "dps-create", "dps", "dps_add"),
    ("hub", steps.plan_messaging, "hub-create", "hub-0", "hub_add"),
])
def test_planned_target_create_and_link_closures_capture_reviewed_resource(
    monkeypatch, kind, planner, create_key, link_key, link_method,
):
    creator = Mock()
    monkeypatch.setattr(steps, "create_" + kind, creator)
    request = create.CreateRequest(kind, "new-target", "rg", "eastus2", identity=CHOICE)
    catalog = object()
    ctx = context(**{"create_" + kind: request, "_catalog": catalog})
    plan = {item.key: item for item in planner(ctx)}
    provider = Mock()
    session = session_with(link=provider)
    assert plan[create_key].invoke(session, ctx) is creator.return_value
    creator.assert_called_once_with(catalog, request)
    assert plan[link_key].invoke(session, ctx) is getattr(provider, link_method).return_value
    getattr(provider, link_method).assert_called_once_with(**{
        **SCOPE, "endpoint_name": "dps" if kind == "dps" else "new-target",
        f"{kind}_resource_id": request.arm_id(SUBSCRIPTION), "mi_system_assigned": False,
        "mi_user_assigned": UAMI_ID, "no_wait": True,
    })


@pytest.mark.parametrize("kind,expected_flag", [
    ("hub", "--user-assigned"), ("dps", "--mi-user-assigned"), ("su", "--user-assigned-mi"),
])
def test_selected_target_identity_plan_uses_user_identity_and_returns_attachment(monkeypatch, kind, expected_flag):
    attach = Mock()
    monkeypatch.setattr(steps, "attach_identity", attach)
    target = pickers.Candidate("target", "/target", resource_group="rg")
    item, = steps._plan_target_identity({}, kind, target, CHOICE)
    assert f"{expected_flag} {UAMI_ID}" in item.command
    catalog = object()
    session = session_with()
    assert item.invoke(session, {"_catalog": catalog}) is attach.return_value
    attach.assert_called_once_with(catalog, kind, {"name": "target", "id": "/target", "resourceGroup": "rg"}, CHOICE)


@pytest.mark.parametrize("choice,attached", [
    (identity.system_choice(), {"type": "SystemAssigned, UserAssigned"}),
    (CHOICE, {"type": "UserAssigned", "userAssignedIdentities": {UAMI_ID.upper(): {}}}),
])
def test_already_attached_identity_produces_no_redundant_mutation(choice, attached):
    target = pickers.Candidate("target", "/target", raw={"identity": attached})
    assert not steps._plan_target_identity({}, "su", target, choice)


@pytest.mark.parametrize("status,error,message", [
    ("Failed", {"message": "grant propagation failed"}, ": grant propagation failed"),
    ("Canceled", "backend canceled", ": backend canceled"),
    ("Failed", {}, "."),
])
def test_endpoint_failure_preserves_service_reason_and_stops_polling(monkeypatch, status, error, message):
    sleeper = Mock(side_effect=AssertionError("terminal failure must not sleep"))
    monkeypatch.setattr("time.sleep", sleeper)
    endpoint = {"provisioningStatus": {"status": status}, "linkingError": error}
    provider = Mock(show=Mock(return_value={"properties": {"provisioning": {"endpoints": {"dps": endpoint}}}}))
    session = session_with(namespace=provider)
    item = steps.plan_provisioning(context(selected_dps=pickers.Candidate("target", "/target")))[-1]
    with pytest.raises(AzureResponseError) as raised:
        item.verify(session, context())
    assert str(raised.value) == f"Endpoint 'dps' linking failed{message}"
    provider.show.assert_called_once_with(**SCOPE)
    sleeper.assert_not_called()


def test_endpoint_missing_service_address_has_bounded_retry_and_timeout_detail(monkeypatch):
    sleeper = Mock()
    monkeypatch.setattr("time.sleep", sleeper)
    endpoint = {"linkingState": "Succeeded"}
    provider = Mock(show=Mock(return_value={"properties": {"updating": {"endpoints": {"su": endpoint}}}}))
    ctx = context(selected_sus=[pickers.Candidate("updates", "/updates")], _link_poll_attempts=2, _link_poll_interval=0)
    verify = steps.plan_software_updates(ctx)[-1].verify
    notify = Mock()
    with pytest.raises(AzureResponseError, match=r"Timed out.*last state: Succeeded"):
        verify(session_with(namespace=provider), ctx, notify)
    assert provider.show.call_count == 2
    assert sleeper.call_args_list == [call(0), call(0)]
    assert notify.call_args_list == [
        call("linkingState: Succeeded"), call("linkingState: Succeeded; waiting for serviceAddress"),
    ] * 2


@pytest.mark.parametrize("failure", ["identity", "target", "state", None])
def test_final_verification_checks_reviewed_identity_target_and_readiness(failure):
    target = pickers.Candidate("hub", "/hub")
    ctx = context(selected_hubs=[target])
    endpoint = {"resourceId": "/HUB/", "linkingState": "Succeeded"}
    payload = {
        "properties": {"outboundIdentity": {"type": "SystemAssigned"}, "messaging": {"endpoints": {"hub": endpoint}}},
    }
    messages = {
        "identity": "unexpected namespace outbound identity",
        "target": "could not match endpoint 'hub'",
        "state": "linkingState 'unknown'",
    }
    if failure == "identity":
        payload["properties"]["outboundIdentity"] = {"type": "UserAssigned"}
    elif failure == "target":
        endpoint["resourceId"] = "/unreviewed"
    elif failure == "state":
        endpoint.pop("linkingState")
    provider = Mock(show=Mock(return_value=payload))
    notify = Mock()
    item, = steps.plan_final_verification(ctx)
    assert item.invoke(session_with(), ctx) is None
    if failure:
        with pytest.raises(AzureResponseError, match=messages[failure]):
            item.verify(session_with(namespace=provider), ctx, notify)
        notify.assert_not_called()
    else:
        assert item.verify(session_with(namespace=provider), ctx, notify) is payload
        notify.assert_called_once_with("1 endpoint(s) ready")
    provider.show.assert_called_once_with(**SCOPE)


@pytest.mark.parametrize("command,expected", [
    ("az identity create -n identity -g rg", f"az identity create -n identity -g rg --subscription {SUBSCRIPTION}"),
    ("az group create -n rg -l eastus2", f"az group create -n rg -l eastus2 --subscription {SUBSCRIPTION}"),
    ("az iot hub identity assign -n hub --system-assigned",
     f"az iot hub identity assign -n hub --system-assigned --subscription {SUBSCRIPTION}"),
    ("az iot dps create -n dps --mi-system-assigned",
     f"az iot dps create -n dps --mi-system-assigned --subscription {SUBSCRIPTION}"),
    ("az identity show --ids /identity --subscription explicit", "az identity show --ids /identity --subscription explicit"),
    ("az identity show --ids /identity --subscription=explicit", "az identity show --ids /identity --subscription=explicit"),
    ("# az iot adr ns show", "# az iot adr ns show"),
    ("echo 'review only'", "echo 'review only'"),
])
def test_export_pins_all_azure_commands_but_preserves_explicit_target_scope(command, expected):
    item = PlanItem("operation", "Reviewed operation", command=command)
    flow = Flow([Step("operation", "Operation", plan=lambda _: [item])], context())
    assert flow.scoped_command(command) == expected
    script = flow.script()
    assert expected in script.splitlines()
    assert "az account set" not in script
    assert item.command == command
    if expected.startswith("az "):
        assert sum(token.startswith("--subscription") for token in shlex.split(expected)) == 1


def test_export_fails_closed_before_mutation_when_verifier_has_no_cli_equivalent():
    item = PlanItem("unsafe-export", "Unexportable readiness", command="az iot adr ns create -n ns -g rg", verify=Mock())
    script = Flow([Step("unsafe", "Unsafe", plan=lambda _: [item])], context()).script()
    assert "# No executable verification is available for: Unexportable readiness" in script
    assert script.index("exit 1") < script.index(item.command)
    item.verify.assert_not_called()


def test_reviewed_confirmation_script_matches_export_without_replanning():
    target = _target("su", "reviewed")
    ctx = context(selected_sus=[target])
    link = steps.plan_software_updates(ctx)[-1]
    final, = steps.plan_final_verification(ctx)
    requirements = steps.plan_permissions(ctx)
    planner = Mock(return_value=[*requirements, link, final])
    flow = Flow([Step("review", "Review", plan=planner)], ctx)
    reviewed = flow.build_plan()
    exported = flow.script()
    planner.reset_mock()
    planner.side_effect = AssertionError("confirmation must use the already-reviewed operations")

    copied = flow.script(plan=reviewed)
    assert copied == exported
    planner.assert_not_called()
    for item in (link, final):
        assert all(flow.scoped_command(command) in copied for command in item.verify_commands)
        assert all(f"radar_check=$({flow.scoped_command(check.command)})" in copied for check in item.verify_checks)
    assert "Verification failed:" in copied and "set -euo pipefail" in copied
    for item in requirements:
        if item.action == "required":
            assert f"# Remediation only: {item.command}" in copied
    assert not any(line.startswith("az role assignment create") for line in copied.splitlines())


@pytest.mark.parametrize("state", ["empty", "blocked", "unexportable"])
def test_reviewed_confirmation_preserves_empty_and_fail_closed_plans(state):
    item = PlanItem(
        "reviewed", "Reviewed operation", command="az iot adr ns create -n ns -g rg",
        action="blocked" if state == "blocked" else "create",
        blocked_reason="reviewed blocker", verify=Mock() if state == "unexportable" else None,
    )
    reviewed = [] if state == "empty" else [item]
    planner = Mock(side_effect=AssertionError("confirmation must not acquire new operations"))
    flow = Flow([Step("changed", "Changed", plan=planner)], context())
    copied = flow.script(plan=reviewed)
    planner.assert_not_called()
    if state == "empty":
        assert copied == Flow([], context()).script()
        assert item.command not in copied
    else:
        assert "exit 1" in copied
        if state == "blocked":
            assert "# BLOCKED Reviewed operation: reviewed blocker" in copied
            assert item.command not in copied
        else:
            assert copied.index("exit 1") < copied.index(item.command)
            item.verify.assert_not_called()


@pytest.mark.parametrize("same_target", [False, True])
def test_selected_and_created_dps_are_rejected_before_any_prerequisite(same_target):
    from azext_iot.adr.ui.screens.onboard.execution import execute_records

    request = create.CreateRequest("dps", "new", "rg", "eastus2")
    ctx = context(
        selected_dps=pickers.Candidate("existing", request.arm_id(SUBSCRIPTION) if same_target else "/existing"),
        create_dps=request, create_namespace=create.CreateRequest("namespace", "ns", "rg", "eastus2"),
        create_resource_group=create.CreateRequest("resource_group", "rg", "rg", "eastus2"), _catalog=Mock(),
    )
    flow = steps.build_flow(ctx)
    for plan in (flow.build_plan(), steps.plan_provisioning(ctx)):
        assert len(plan) == 1
        assert plan[0].action == "blocked"
        assert "Choose either an existing DPS or a new DPS, not both" in plan[0].blocked_reason
        assert plan[0].invoke is None
    assert not [line for line in flow.script().splitlines() if line.startswith("az ")]
    assert "exit 1" in flow.script()
    session = Mock()
    assert execute_records([], session, ctx, Mock())
    assert not session.mock_calls
    assert not ctx["_catalog"].mock_calls


def test_multiple_persisted_dps_links_cannot_be_silently_reduced_to_one_target():
    ctx = context(namespace={"properties": {"provisioning": {"endpoints": {"first": {}, "second": {}}}}})
    plan, = steps.build_flow(ctx).build_plan()
    assert plan.action == "blocked"
    assert plan.blocked_reason == "Only one DPS may be linked per namespace."
    assert plan.invoke is None


def _target(kind, name, choice=None):
    request = create.CreateRequest(kind, name, "rg", "eastus2")
    payload = {
        "name": name, "id": request.arm_id(SUBSCRIPTION), "location": "eastus2",
        "resourceGroup": "rg", "sku": {"name": "S1"},
        "identity": {"type": "SystemAssigned", "principalId": f"{name}-pid"},
        "properties": {"provisioningState": "Succeeded"},
    }
    if choice and choice.is_user_assigned:
        payload["identity"] = {
            "type": "UserAssigned", "userAssignedIdentities": {choice.uami_id: {"principalId": f"{name}-pid"}},
        }
    return pickers.Candidate(name, payload["id"], resource_group="rg", location="eastus2", raw=payload)


def _endpoint(target, kind, state="Succeeded", choice=None, address=True):
    inbound = (
        {"type": "UserAssigned", "userAssignedIdentity": choice.uami_id}
        if choice and choice.is_user_assigned else {"type": "SystemAssigned"}
    )
    payload = {
        "resourceId": target.resource_id,
        "endpointType": steps._LINK_TYPES[kind],
        "linkingState": state, "inboundCallerIdentity": inbound,
    }
    if kind == "su" and address:
        payload["serviceAddress"] = "https://updates.example"
    return payload


def _retry_session(live, targets, patch):
    """Run real link validation and inherited-role policy; replace only SDK/HTTP boundaries."""
    from azext_iot.adr.providers.link import LinkProvider
    from azext_iot.adr.rbac import LinkRbacManager

    cli = Mock()
    cli.invoke.side_effect = AssertionError("existing roles must not invoke grants")
    manager = LinkRbacManager(cli_ctx=Mock(), cli=cli)
    manager._assignment_exists = Mock(return_value=True)
    manager._resolve_adu_principal = Mock(return_value="adu-pid")
    manager._current_assignee_object_id = Mock(side_effect=AssertionError("no grant privilege is needed"))
    provider = LinkProvider.__new__(LinkProvider)
    provider._rbac = manager
    provider.client = SimpleNamespace(namespaces=SimpleNamespace(get=Mock(side_effect=lambda **_: deepcopy(live))))
    models = {target.name: target.raw for target in targets}
    provider._get_target = Mock(side_effect=lambda parsed, _strategy: models[parsed["name"]])
    provider._side_get_dps_resource = Mock(return_value={})
    provider._patch_endpoints = Mock(side_effect=patch)
    for operation in ("hub_add", "hub_update", "dps_add", "dps_update", "su_add", "su_update"):
        setattr(provider, operation, Mock(wraps=getattr(provider, operation)))
    session = session_with(namespace=SimpleNamespace(show=Mock(side_effect=lambda **_: deepcopy(live))), link=provider)
    return session, manager, cli


def _namespace_with_links():
    dps, hub = _target("dps", "dps"), _target("hub", "existing-hub")
    return {
        "id": PREFIX + "Microsoft.DeviceRegistry/namespaces/ns", "name": "ns", "location": "eastus2",
        "identity": {"type": "SystemAssigned", "principalId": "ns-pid"},
        "properties": {
            "outboundIdentity": {"type": "SystemAssigned"},
            "provisioning": {"endpoints": {"actual-dps": _endpoint(dps, "dps")}},
            "messaging": {"endpoints": {"actual-hub": _endpoint(hub, "hub")}},
        },
    }


def _records(flow):
    from azext_iot.adr.ui.screens.onboard.execution import ExecutionRecord

    plan = flow.build_plan()
    assert not [item.blocked_reason for item in plan if item.action == "blocked"]
    return [ExecutionRecord(item) for item in plan if item.invoke is not None]


def _run_reload_scenario(monkeypatch, ctx, session, scenario):
    from azext_iot.adr.ui.app import RadrApp
    from azext_iot.adr.ui.kinds.synthetic import build_synthetic_registry
    from azext_iot.adr.ui.screens.onboard.screen import OnboardScreen

    network = Mock(side_effect=AssertionError("retry regression attempted network I/O"))
    monkeypatch.setattr("requests.sessions.Session.request", network)
    monkeypatch.setattr("azext_iot.adr.ui.core.rbac.permissions_at_scope", Mock(return_value={}))
    monkeypatch.setattr("time.sleep", Mock())

    async def runner():
        app = RadrApp(registry=build_synthetic_registry())
        async with app.run_test(size=(140, 42)) as pilot:
            await app.workers.wait_for_complete()
            screen = OnboardScreen(session, scope=ctx, namespace=ctx["namespace"])
            await app.push_screen(screen)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert screen.is_attached
            scenario(screen)
            await app.workers.wait_for_complete()

    asyncio.run(runner())
    network.assert_not_called()


def test_two_hubs_partial_success_reload_executes_and_authorizes_only_missing_hub(monkeypatch):
    from azext_iot.adr.ui.screens.onboard.execution import ExecutionState, execute_records
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    first, second = _target("hub", "first"), _target("hub", "second")
    live = _namespace_with_links()
    live["properties"]["messaging"]["endpoints"] = {}
    ctx = context(namespace=deepcopy(live), selected_hubs=[first, second])
    failed_once = []

    def patch(**kwargs):
        name, endpoint = next(iter(kwargs["endpoints_patch"].items()))
        if name == "second" and not failed_once:
            failed_once.append(name)
            raise TimeoutError("second hub was not persisted")
        live["properties"]["messaging"]["endpoints"][name] = {**endpoint, "linkingState": "Succeeded"}

    session, manager, cli = _retry_session(live, [first, second], patch)

    def scenario(screen):
        initial = _records(screen.flow)
        assert not execute_records(initial, session, screen.context, lambda _: None)
        assert next(record for record in initial if record.item.key == "hub-0").state is ExecutionState.SUCCEEDED
        assert next(record for record in initial if record.item.key == "hub-1").state is ExecutionState.FAILED
        # A normalized ID match must work even when Azure changes casing/trailing slash.
        live["properties"]["messaging"]["endpoints"]["first"]["resourceId"] = first.resource_id.upper() + "/"
        screen._apply_namespace(deepcopy(live))
        assert not steps.has_messaging(screen.context)
        assert [target.resource_id for kind, target, _choice in role_targets(screen.context) if kind == "hub"] == [
            second.resource_id,
        ]
        retry = _records(screen.flow)
        assert [record.item.key for record in retry] == ["preflight", "grant-preflight", "hub-1", "verify-readiness"]
        script = screen.flow.script()
        additions = [shlex.split(line) for line in script.splitlines() if line.startswith("az iot adr ns link hub add ")]
        assert [args[args.index("--endpoint-name") + 1] for args in additions] == ["second"]
        final = next(record.item for record in retry if record.item.key == "verify-readiness")
        assert any("--endpoint-name first" in command for command in final.verify_commands)
        assert any("--endpoint-name second" in command for command in final.verify_commands)
        target_checks = [check for check in final.verify_checks if check.strip_trailing_slash]
        assert [check.expected for check in target_checks] == [first.resource_id, second.resource_id]
        assert all(f"radar_check=$({screen.flow.scoped_command(check.command)})" in script for check in target_checks)
        assert execute_records(retry, session, screen.context, lambda _: None)
        screen._apply_namespace(deepcopy(live))
        assert steps.has_messaging(screen.context)
        assert not role_targets(screen.context)

    _run_reload_scenario(monkeypatch, ctx, session, scenario)
    provider = session.provider("link")
    assert [args.kwargs["hub_resource_id"] for args in provider.hub_add.call_args_list] == [
        first.resource_id, second.resource_id, second.resource_id,
    ]
    provider.hub_update.assert_not_called()
    manager._current_assignee_object_id.assert_not_called()
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("planned", [False, True], ids=["selected-existing-hub", "create-additional-hub"])
def test_existing_ready_hub_does_not_hide_additional_hub_work(monkeypatch, planned):
    from azext_iot.adr.ui.screens.onboard.execution import execute_records
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    hub = _target("hub", "additional")
    live = _namespace_with_links()
    ctx = context(namespace=deepcopy(live))
    creator = Mock(return_value=None)
    monkeypatch.setattr(steps, "create_hub", creator)
    if planned:
        ctx["create_hub"] = create.CreateRequest("hub", hub.name, "rg", "eastus2")
        ctx["_catalog"] = object()
    else:
        ctx["selected_hubs"] = [hub]

    def patch(**kwargs):
        name, endpoint = next(iter(kwargs["endpoints_patch"].items()))
        live["properties"]["messaging"]["endpoints"][name] = {**endpoint, "linkingState": "Succeeded"}

    session, _manager, cli = _retry_session(live, [hub], patch)
    assert not steps.has_messaging(ctx)
    assert [(kind, target.resource_id) for kind, target, _choice in role_targets(ctx)] == [("hub", hub.resource_id)]
    assert execute_records(_records(steps.build_flow(ctx)), session, ctx, lambda _: None)
    assert creator.call_count == int(planned)
    assert set(live["properties"]["messaging"]["endpoints"]) == {"actual-hub", "additional"}
    ctx["namespace"] = deepcopy(live)
    assert steps.has_messaging(ctx)
    assert not any(item.key == "hub-create" for item in steps.build_flow(ctx).build_plan())
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("kind", ["dps", "hub"])
@pytest.mark.parametrize("state", ["Pending", "Failed", "Succeeded"])
@pytest.mark.parametrize("planned", [False, True], ids=["selected-target", "persisted-create-request"])
def test_matching_persisted_dps_and_hub_use_actual_endpoint_name_and_identity_only_retry(monkeypatch, kind, state, planned):
    from azext_iot.adr.ui.screens.onboard.execution import execute_records
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    target = _target(kind, "retry-target")
    live = _namespace_with_links()
    section = steps._LINK_SECTIONS[kind]
    live["properties"][section]["endpoints"] = {"persisted-name": _endpoint(target, kind, state)}
    ctx = context(namespace=deepcopy(live))
    if planned:
        ctx[f"create_{kind}"] = create.CreateRequest(kind, target.name, "rg", "eastus2")
    else:
        ctx["selected_dps" if kind == "dps" else "selected_hubs"] = target if kind == "dps" else [target]
    creator = Mock(side_effect=AssertionError("persisted target must not be created again"))
    monkeypatch.setattr(steps, "create_" + kind, creator)

    def patch(**kwargs):
        assert kwargs["section"] == section
        assert set(kwargs["endpoints_patch"]) == {"persisted-name"}
        assert kwargs["endpoints_patch"]["persisted-name"]["resourceId"] == target.resource_id
        live["properties"][section]["endpoints"]["persisted-name"] = _endpoint(target, kind)

    session, _manager, cli = _retry_session(live, [target], patch)
    planner = steps.plan_provisioning if kind == "dps" else steps.plan_messaging
    if state == "Succeeded":
        assert not planner(ctx)
        assert not role_targets(ctx)
    else:
        links = [item for item in planner(ctx) if item.category == "link"]
        assert len(links) == 1
        assert f"link {kind} update" in links[0].command and f"--{kind}-id" not in links[0].command
        assert [(target_kind, resource.resource_id) for target_kind, resource, _choice in role_targets(ctx)] == [
            (kind, target.resource_id),
        ]
    assert execute_records(_records(steps.build_flow(ctx)), session, ctx, lambda _: None)
    provider = session.provider("link")
    getattr(provider, kind + "_add").assert_not_called()
    assert getattr(provider, kind + "_update").call_count == int(state != "Succeeded")
    if state != "Succeeded":
        assert f"{kind}_resource_id" not in getattr(provider, kind + "_update").call_args.kwargs
    creator.assert_not_called()
    cli.invoke.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_unselected_failed_existing_link_is_not_reported_done(kind):
    target = _target(kind, "existing")
    ctx = context(namespace=_namespace_with_links())
    ctx["namespace"]["properties"][steps._LINK_SECTIONS[kind]]["endpoints"] = {
        "actual-name": _endpoint(target, kind, "Failed"),
    }
    assert not (steps.has_messaging(ctx) if kind == "hub" else steps.has_provisioning(ctx))
    plan = steps.build_flow(ctx).build_plan()
    item, = [item for item in plan if item.category == "link"]
    assert f"link {kind} update" in item.command
    assert "--endpoint-name actual-name" in item.command
    assert any(item.key == "preflight" for item in plan)


@pytest.mark.parametrize("planned", [False, True])
def test_existing_dps_cannot_be_replaced_by_a_selected_or_created_target(planned):
    ctx = context(namespace=_namespace_with_links())
    target = _target("dps", "different")
    if planned:
        ctx["create_dps"] = create.CreateRequest("dps", target.name, "rg", "eastus2")
    else:
        ctx["selected_dps"] = target
    flow = steps.build_flow(ctx)
    item, = flow.build_plan()
    assert item.action == "blocked" and "replacing the linked target is not supported" in item.blocked_reason
    assert item.invoke is None
    assert "exit 1" in flow.script()
    assert not any(line.startswith("az ") for line in flow.script().splitlines())


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_completed_link_with_changed_selected_identity_still_plans_identity_only_update(kind):
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    choice = replace(CHOICE, create_uami=False)
    target = _target(kind, "target", choice)
    ctx = context(namespace=_namespace_with_links())
    ctx["namespace"]["properties"][steps._LINK_SECTIONS[kind]] = {"endpoints": {
        "actual-endpoint": _endpoint(target, kind),
    }}
    ctx[{"hub": "selected_hubs", "dps": "selected_dps", "su": "selected_sus"}[kind]] = (
        target if kind == "dps" else [target]
    )
    identity.set_choice(ctx, kind, choice, target.resource_id)
    plan = steps.build_flow(ctx).build_plan()
    item, = [item for item in plan if item.category == "link"]
    assert item.action == "modify"
    assert f"link {kind} update" in item.command
    assert f"--{kind}-id" not in item.command
    assert f"--user-assigned-mi {choice.uami_id}" in item.command
    assert role_targets(ctx) == [(kind, target, choice)]
    assert not any(item.category == "identity" and item.invoke for item in plan)


def test_completed_selected_su_is_not_relinked_or_reauthorized():
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    target = _target("su", "updates")
    ctx = context(namespace=_namespace_with_links(), selected_sus=[target])
    ctx["namespace"]["properties"]["updating"] = {"endpoints": {"real-su": _endpoint(target, "su")}}
    assert steps.software_updates_linked(ctx)
    assert not steps.plan_software_updates(ctx)
    assert not role_targets(ctx)
    item, = steps.plan_final_verification(ctx)
    provider = Mock(show=Mock(return_value=ctx["namespace"]))
    assert item.verify(session_with(namespace=provider), ctx) is ctx["namespace"]
    provider.show.assert_called_once_with(**SCOPE)


def test_outbound_change_keeps_existing_ready_link_identity_choices_and_deduplicates_shared_roles():
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    ctx = context(namespace=_namespace_with_links())
    identity.set_choice(ctx, "namespace", replace(CHOICE, create_uami=False))
    ctx["namespace"]["properties"]["messaging"]["endpoints"]["actual-hub"]["inboundCallerIdentity"] = {
        "type": "UserAssigned", "userAssignedIdentity": UAMI_ID,
    }
    targets = role_targets(ctx)
    assert [(kind, choice.mode) for kind, _target_resource, choice in targets] == [("dps", "system"), ("hub", "user")]
    assert targets[1][2].uami_id == UAMI_ID
    hubs = [_target("hub", "one"), _target("hub", "two")]
    for hub in hubs:
        identity.set_choice(ctx, "hub", replace(CHOICE, create_uami=False), hub.resource_id)
    ctx["selected_hubs"] = hubs
    roles = steps.plan_permissions(ctx)
    reverse = [item for item in roles if item.key.startswith("grant-hub-to-ns")]
    assert len(reverse) == 1
    assert UAMI_ID in reverse[0].command
    assert all(item.invoke is None for item in roles if item.action == "required")


@pytest.mark.parametrize("state,address", [("Pending", True), ("Failed", True), ("Succeeded", False)])
@pytest.mark.parametrize("mode", ["system", "user"])
@pytest.mark.parametrize("retry_ready", [False, True], ids=["retry-not-ready", "retry-ready"])
def test_su_post_accept_timeout_reload_preserves_identity_and_readiness_obligation(
    monkeypatch, state, address, mode, retry_ready,
):
    from azext_iot.adr.ui.screens.onboard.execution import execute_records
    from azext_iot.adr.ui.screens.onboard.permissions import role_targets

    choice = replace(CHOICE, create_uami=False) if mode == "user" else identity.system_choice()
    target = _target("su", "updates", choice)
    live = _namespace_with_links()
    request = create.CreateRequest("su", target.name, "rg", "eastus2", identity=choice)
    ctx = context(namespace=deepcopy(live), create_su=request, _link_poll_attempts=2, _link_poll_interval=0)
    creator = Mock(return_value=None)
    monkeypatch.setattr(steps, "create_update_instance", creator)
    patches = []

    def patch(**kwargs):
        patches.append(kwargs)
        if len(patches) == 1:
            live["properties"]["updating"] = {"endpoints": {
                "persisted-su": _endpoint(target, "su", state, choice, address),
            }}
            raise TimeoutError("local timeout after link acceptance")
        assert set(kwargs["endpoints_patch"]) == {"persisted-su"}
        live["properties"]["updating"]["endpoints"]["persisted-su"] = _endpoint(
            target, "su", "Succeeded" if retry_ready else state, choice, True if retry_ready else address,
        )

    session, manager, cli = _retry_session(live, [target], patch)

    def scenario(screen):
        assert not execute_records(_records(screen.flow), session, screen.context, lambda _: None)
        creator.assert_called_once()
        screen._apply_namespace(deepcopy(live))
        assert "create_su" not in screen.context
        assert screen.context["selected_sus"][0].resource_id == target.resource_id
        assert identity.get_choice(screen.context, "su", target.resource_id) == choice
        assert not steps.software_updates_linked(screen.context)
        assert [(kind, resource.resource_id) for kind, resource, _choice in role_targets(screen.context)] == [
            ("su", target.resource_id),
        ]
        retry = _records(screen.flow)
        assert [record.item.key for record in retry] == ["preflight", "grant-preflight", "su", "verify-readiness"]
        link = next(record.item for record in retry if record.item.key == "su")
        assert "link su update" in link.command and "--su-id" not in link.command
        assert execute_records(retry, session, screen.context, lambda _: None) is retry_ready
        screen._apply_namespace(deepcopy(live))
        assert steps.software_updates_linked(screen.context) is retry_ready
        if not retry_ready:
            verify = steps.plan_final_verification(screen.context)[0].verify
            with pytest.raises(AzureResponseError, match="linkingState|without a serviceAddress"):
                verify(session, screen.context)
            assert any(item.key == "su" and item.invoke is not None for item in screen.flow.build_plan())

    _run_reload_scenario(monkeypatch, ctx, session, scenario)
    creator.assert_called_once()
    session.provider("link").su_add.assert_called_once()
    session.provider("link").su_update.assert_called_once()
    assert "su_resource_id" not in session.provider("link").su_update.call_args.kwargs
    manager._current_assignee_object_id.assert_not_called()
    cli.invoke.assert_not_called()
