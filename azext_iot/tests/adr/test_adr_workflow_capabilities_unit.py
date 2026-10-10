# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, CLIInternalError, InvalidArgumentValueError, ResourceNotFoundError

from azext_iot.adr.workflows import capabilities, services as adapters
from azext_iot.adr.workflows.models import CmsSpec, EndpointSpec, SetupRequest, WorkflowExecutionError
from azext_iot.adr.workflows.namespace import NamespaceWorkflow


SUB = "00000000-0000-0000-0000-000000000000"
OTHER_SUB = "11111111-1111-1111-1111-111111111111"
PREFIX = f"/subscriptions/{SUB}/resourceGroups/rg/providers/"
NS_ID = PREFIX + "Microsoft.DeviceRegistry/namespaces/ns"
UAMI = PREFIX + "Microsoft.ManagedIdentity/userAssignedIdentities/identity"
IDS = {
    "dps": PREFIX + "Microsoft.Devices/provisioningServices/my-dps",
    "hub": PREFIX + "Microsoft.Devices/IotHubs/my-hub",
    "software-updates": PREFIX + "Microsoft.DeviceUpdate/updateInstances/my-su",
}


def namespace():
    return {
        "id": NS_ID, "location": "eastus",
        "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
        "properties": {"provisioningState": "Succeeded", "outboundIdentity": {"type": "SystemAssigned"}},
    }


def target(kind):
    return {
        "id": IDS[kind], "location": "eastus", "sku": {"name": "S1", "capacity": 1},
        "identity": {"type": "SystemAssigned", "principalId": "target-principal"},
        "properties": {"provisioningState": "Succeeded"},
    }


def endpoint(kind="dps", **kwargs):
    return EndpointSpec(kind, kind, IDS[kind], "system-assigned", **kwargs)


def request(**kwargs):
    return SetupRequest("ns", "rg", subscription_id=SUB, **kwargs)


def ca(kind):
    properties = {"provisioningState": "Succeeded", "certificateAuthorityType": "Root" if kind == "root" else "ICA"}
    if kind == "intermediate":
        properties["issuer"] = {
            "issuerType": "Microsoft",
            "certificateAuthorityResourceId": NS_ID + "/certificateAuthorities/root",
            "certificateSigningRequest": "SECRET CSR",
        }
    if kind == "policy":
        properties = {"provisioningState": "Succeeded", "certificate": {"validityPeriodInDays": 30, "pem": "SECRET POLICY"}}
    return {"properties": properties, "certificateChain": "SECRET CHAIN"}


@pytest.fixture
def service(mocker):
    for name in ("NamespaceProvider", "LinkProvider", "UpdateInstanceProvider", "EmbeddedCLI", "LinkRbacManager"):
        mocker.patch.object(adapters, name)
    subscriptions = MagicMock()
    mocker.patch.object(adapters, "get_subscription_service_client", return_value=(subscriptions, SUB))
    resources = mocker.patch.object(adapters, "get_mgmt_service_client").return_value
    mocker.patch.object(adapters, "get_subscription_id", return_value=SUB)
    service = adapters.WorkflowServices(SimpleNamespace(cli_ctx=SimpleNamespace(data={"subscription_id": SUB})))
    cli = MagicMock()
    service.cli = cli
    service.namespace.show.return_value = namespace()
    service.namespace.create.return_value = namespace()
    resources.resource_groups.get.return_value = {"name": "rg", "location": "eastus"}
    subscriptions.subscriptions.list_locations.return_value = [{"name": "eastus"}]
    cli.invoke.return_value.as_json.return_value = {"principalId": "user-principal"}
    service.factory_mocks = {}
    for kind, name in (("hub", "adr_iot_hub_service_factory"), ("dps", "adr_iot_service_provisioning_factory"),
                       ("software-updates", "adr_update_instance_service_factory")):
        factory = mocker.patch.object(adapters, name)
        service.factory_mocks[kind] = factory
        client = factory.return_value
        operation = getattr(client, {"hub": "iot_hub_resource", "dps": "iot_dps_resource",
                                     "software-updates": "update_instances"}[kind])
        operation.get.return_value = target(kind)
        operation.check_name_availability.return_value = {"nameAvailable": True}
        operation.check_provisioning_service_name_availability.return_value = {"nameAvailable": True}
    service.update_instances.check_name.return_value = {"nameAvailable": True}
    return service


@pytest.fixture
def cms_store(service, mocker):
    store = {}
    authority = mocker.patch.object(adapters, "CertificateAuthorityProvider").return_value
    policy = mocker.patch.object(adapters, "CertificatePolicyProvider").return_value

    def kind_of(kwargs):
        return "policy" if "certificate_policy_name" in kwargs else kwargs["certificate_authority_name"]

    def show(**kwargs):
        kind = kind_of(kwargs)
        if kind not in store:
            raise ResourceNotFoundError("missing")
        return copy.deepcopy(store[kind])

    def create(**kwargs):
        kind = kind_of(kwargs)
        assert kind not in store, "CMS must never replace existing resources"
        store[kind] = ca(kind)
        return copy.deepcopy(store[kind])

    authority.show.side_effect = policy.show.side_effect = show
    authority.create.side_effect = policy.create.side_effect = create
    return store, authority, policy


def test_cms_plan_create_reuse_and_metadata_only(service, cms_store):
    store, authority, policy = cms_store
    workflow = NamespaceWorkflow(service)
    req = request(cms=CmsSpec())
    planned, _ = workflow.plan_setup(req)
    cms = [item for item in planned["items"] if item["id"].startswith("cms-")]
    assert [item["target"] for item in cms] == ["root", "intermediate", "default"]
    assert all(item["state"] == "Planned" for item in cms)
    assert all("--subscription " + SUB in item["command"] for item in cms)
    assert "--type Root" in cms[0]["command"]
    assert "--issuer-type Microsoft --issuer-ca-name root" in cms[1]["command"]
    assert "--ca-name intermediate --validity-days 30" in cms[2]["command"]
    authority.create.assert_not_called()
    policy.create.assert_not_called()
    applied = workflow.setup(req)
    assert applied["state"] == "Succeeded"
    assert len(store) == 3
    assert authority.create.call_count == 2 and policy.create.call_count == 1
    assert policy.create.call_args.kwargs["validity_days"] == 30
    assert authority.create.call_args.kwargs["issuer_type"] == "Microsoft"
    again, _ = workflow.plan_setup(req)
    assert all(item["state"] == "Satisfied" for item in again["items"])
    workflow.setup(req)
    assert authority.create.call_count == 2 and policy.create.call_count == 1
    material = json.dumps([planned, applied, again, service.show_cms(req, "intermediate"), service.show_cms(req, "policy")])
    assert "SECRET" not in material and "certificateSigningRequest" not in material and "certificateChain" not in material
    service.links.assert_not_called()
    service.link_rbac.ensure.assert_not_called()


@pytest.mark.parametrize("kind,mutate,match", [
    ("root", lambda p: p.update(provisioningState="Updating"), "wait for Succeeded"),
    ("root", lambda p: p.pop("provisioningState"), "unknown"),
    ("root", lambda p: p.update(certificateAuthorityType="ICA"), "type Root"),
    ("root", lambda p: p.update(issuer={"issuerType": "External"}), "unexpected issuer"),
    ("intermediate", lambda p: p.update(certificateAuthorityType="Root"), "type ICA"),
    ("intermediate", lambda p: p["issuer"].update(issuerType="External"), "never converts external"),
    ("intermediate", lambda p: p["issuer"].update(certificateAuthorityResourceId="/wrong"), "does not match"),
    ("intermediate", lambda p: p["issuer"].update(status="PendingActivation"), "not Active"),
    ("policy", lambda p: p["certificate"].update(validityPeriodInDays=60), "validity"),
    ("policy", lambda p: p.update(provisioningState="Failed"), "failed"),
])
def test_cms_conflicts_block_all_writes(service, cms_store, kind, mutate, match):
    store, authority, policy = cms_store
    store.update({name: ca(name) for name in ("root", "intermediate", "policy")})
    mutate(store[kind]["properties"])
    req = request(cms=CmsSpec(), dps=endpoint())
    workflow = NamespaceWorkflow(service)
    plan, _ = workflow.plan_setup(req)
    assert plan["state"] == "Blocked"
    with pytest.raises(ArgumentUsageError, match=match):
        workflow.setup(req)
    authority.create.assert_not_called()
    policy.create.assert_not_called()
    service.namespace.create.assert_not_called()
    service.namespace.update.assert_not_called()
    service.links.dps_add.assert_not_called()


def test_cms_read_error_is_not_missing_or_leaked(service, cms_store):
    _, authority, _ = cms_store
    authority.show.side_effect = RuntimeError("SECRET CHAIN")
    with pytest.raises(CLIInternalError, match="caller ARM permissions") as error:
        NamespaceWorkflow(service).plan_setup(request(cms=CmsSpec()))
    assert "SECRET" not in str(error.value)
    authority.create.assert_not_called()


@pytest.mark.parametrize("failed_kind", ["root", "intermediate", "policy"])
def test_cms_partial_failure_retry_reuses_completed_resources(service, cms_store, failed_kind):
    store, authority, policy = cms_store
    create_ca, create_policy = authority.create.side_effect, policy.create.side_effect

    def failing_create(**kwargs):
        kind = "policy" if "certificate_policy_name" in kwargs else kwargs["certificate_authority_name"]
        if kind == failed_kind:
            raise RuntimeError("SECRET payload")
        return create_ca(**kwargs)

    authority.create.side_effect = policy.create.side_effect = failing_create
    req = request(cms=CmsSpec())
    workflow = NamespaceWorkflow(service)
    with pytest.raises(WorkflowExecutionError) as error:
        workflow.setup(req)
    result = error.value.result
    assert "SECRET" not in json.dumps(result) and "SECRET" not in str(error.value)
    assert result["state"] == "Failed"
    assert len([item for item in result["items"] if item["id"].startswith("cms-")]) == (
        ("root", "intermediate", "policy").index(failed_kind)
    )
    completed = set(store)
    authority.create.reset_mock()
    policy.create.reset_mock()
    authority.create.side_effect, policy.create.side_effect = create_ca, create_policy
    assert workflow.setup(req)["state"] == "Succeeded"
    ca_names = {call.kwargs["certificate_authority_name"] for call in authority.create.call_args_list}
    assert not ca_names.intersection(completed)


def test_cms_progress_and_unknown_create_refused(service, cms_store):
    store, authority, policy = cms_store
    create = authority.create.side_effect

    def in_progress(**kwargs):
        result = create(**kwargs)
        store[kwargs["certificate_authority_name"]]["properties"]["provisioningState"] = "Creating"
        return result

    authority.create.side_effect = in_progress
    progress = MagicMock()

    def run(_, operation, *args, **kwargs):
        kwargs.pop("workflow_scope", None)
        kwargs.pop("mutation", None)
        return operation(*args, **kwargs)

    progress.run.side_effect = run
    workflow = NamespaceWorkflow(service, progress=progress)
    req = request(cms=CmsSpec())
    with pytest.raises(WorkflowExecutionError, match="wait for Succeeded"):
        workflow.setup(req)
    with pytest.raises(ArgumentUsageError, match="wait for Succeeded"):
        workflow.setup(req)
    assert authority.create.call_count == 1
    policy.create.assert_not_called()
    mutation = next(call for call in progress.run.call_args_list if call.args[0] == "Create CMS root")
    assert mutation.kwargs == {"workflow_scope": "cms", "mutation": True}


@pytest.mark.parametrize("stop_kind", ["root", "intermediate", "policy"])
def test_stop_before_cms_operation_preserves_completed_steps(service, cms_store, stop_kind):
    store, _, _ = cms_store
    progress = MagicMock()

    def run(label, operation, *args, **kwargs):
        scope, mutation = kwargs.pop("workflow_scope", None), kwargs.pop("mutation", False)
        if scope == "cms" and mutation and label == f"Create CMS {stop_kind}":
            raise RuntimeError("Stopped before operation")
        return operation(*args, **kwargs)

    progress.run.side_effect = run
    with pytest.raises(WorkflowExecutionError, match="Stopped before operation") as error:
        NamespaceWorkflow(service, progress=progress).setup(request(cms=CmsSpec()))
    completed = ("root", "intermediate", "policy")[:("root", "intermediate", "policy").index(stop_kind)]
    assert set(store) == set(completed)
    recorded = [item["id"] for item in error.value.result["items"] if item["id"].startswith("cms-")]
    assert recorded == [f"cms-{kind}" for kind in completed]


def test_cms_changed_after_plan_blocks_apply(service, cms_store):
    store, authority, _ = cms_store
    req = request(cms=CmsSpec())
    workflow = NamespaceWorkflow(service)
    workflow.plan_setup(req)
    store["root"] = ca("root")
    store["root"]["properties"]["certificateAuthorityType"] = "ICA"
    with pytest.raises(ArgumentUsageError, match="CMS setup is blocked"):
        capabilities.apply_cms(req, workflow._run, service, [])
    authority.create.assert_not_called()
    assert not capabilities.plan_cms(request(), None, workflow._run, service)
    # Namespace-only creation does not probe impossible child resources.
    assert len(capabilities.plan_cms(req, None, workflow._run, service)) == 3


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_release_target_creation_pins_subscription_and_reuses(service, mocker, kind):
    spec = endpoint(kind, create_if_missing=True, sku="S1", unit=1)
    factory = service.factory_mocks[kind]
    operation = getattr(factory.return_value, "iot_hub_resource" if kind == "hub" else "iot_dps_resource")
    operation.get.side_effect = [ResourceNotFoundError("missing"), target(kind), target(kind)]
    create = mocker.patch("azext_iot.core.custom.iot_" + kind + "_create")
    assert service.create_target(spec, "eastus") == target(kind)
    create.return_value.result.assert_called_once_with(timeout=2400)
    assert create.call_args.kwargs["sku"] == "S1" and create.call_args.kwargs["unit"] == 1
    assert create.call_args.kwargs["system_identity" if kind == "hub" else "mi_system_assigned"]
    assert "disable_local_auth" not in create.call_args.kwargs  # Preserve release defaults.
    assert factory.call_args.kwargs["subscription_id"] == SUB
    assert service.create_target(spec, "eastus") == target(kind)
    assert create.call_count == 1  # Existing target is never PUT.
    command = service.target_create_command(spec, "eastus")
    assert "--system-assigned-mi" in command and "--sku S1 --unit 1" in command


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_actual_release_create_payload_defaults_without_sdk_shortcuts(service, kind):
    """Exercise the real release function, mocking only ARM operations/poller."""
    spec = endpoint(kind, create_if_missing=True)
    operation = getattr(service.factory_mocks[kind].return_value, "iot_hub_resource" if kind == "hub" else "iot_dps_resource")
    operation.get.side_effect = [ResourceNotFoundError("missing"), target(kind)]
    service.create_target(spec, "eastus")
    operation.begin_create_or_update.assert_called_once()
    body = operation.begin_create_or_update.call_args.kwargs[
        "iot_hub_description" if kind == "hub" else "iot_dps_description"
    ]
    assert body["identity"]["type"] == "SystemAssigned"
    assert body["location"] == "eastus" and body["sku"] == {"name": "S1", "capacity": 1}
    if kind == "hub":
        assert body["properties"]["disableLocalAuth"] is True
    else:
        assert "disableLocalAuth" not in body["properties"]
    assert operation.check_name_availability.called if kind == "hub" else (
        operation.check_provisioning_service_name_availability.called
    )


def test_cross_subscription_existing_resource_reused_with_target_subscription(service):
    spec = replace(endpoint(create_if_missing=True), resource_id=IDS["dps"].replace(SUB, OTHER_SUB))
    plan, _ = NamespaceWorkflow(service).plan_setup(request(dps=spec))
    service.factory_mocks["dps"].assert_called_with(service.cmd.cli_ctx, subscription_id=OTHER_SUB)
    resource = next(item for item in plan["items"] if item["id"] == "resource-dps-dps")
    assert resource["state"] == "Satisfied"
    assert not any(item["action"] == "create" for item in plan["items"])
    assert all(item["command"].endswith("--subscription " + SUB) for item in plan["items"] if item.get("command"))


def test_target_create_uami_and_failures(service, mocker):
    spec = replace(endpoint("hub", create_if_missing=True), identity_type="user-assigned", user_assigned_identity=UAMI)
    resource = target("hub")
    resource["identity"] = {"userAssignedIdentities": {UAMI: {"principalId": "user-principal"}}}
    operation = service.factory_mocks["hub"].return_value.iot_hub_resource
    operation.get.side_effect = [ResourceNotFoundError("missing"), resource]
    create = mocker.patch("azext_iot.core.custom.iot_hub_create")
    service.create_target(spec, "eastus")
    assert create.call_args.kwargs["user_identities"] == [UAMI]
    assert "--user-assigned-mi " + UAMI in service.target_create_command(spec, "eastus")
    operation.get.side_effect = RuntimeError("forbidden")
    with pytest.raises(RuntimeError, match="forbidden"):
        service.create_target(spec, "eastus")
    assert create.call_count == 1


@pytest.mark.parametrize("kind", ["hub", "dps", "software-updates"])
def test_cross_subscription_missing_target_blocks_namespace_creation(service, kind):
    service.namespace.show.side_effect = ResourceNotFoundError("missing namespace")
    operation = (
        service.factory_mocks["hub"].return_value.iot_hub_resource if kind == "hub" else
        service.factory_mocks["dps"].return_value.iot_dps_resource if kind == "dps" else
        service.factory_mocks["software-updates"].return_value.update_instances
    )
    operation.get.side_effect = ResourceNotFoundError("missing target")
    spec = replace(endpoint(kind, create_if_missing=True), resource_id=IDS[kind].replace(SUB, OTHER_SUB))
    kwargs = {"hubs": (spec,)} if kind == "hub" else {"dps" if kind == "dps" else "software_updates": spec}
    with pytest.raises(InvalidArgumentValueError, match="outside the namespace subscription"):
        NamespaceWorkflow(service).setup(request(outbound_identity_type="SystemAssigned", **kwargs))
    service.namespace.create.assert_not_called()
    service.namespace.update.assert_not_called()
    operation.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("change,match", [
    ({"location": "westus"}, "Cross-region"),
    ({"sku": {"name": "B1"}}, "Standard"),
    ({"properties": {"provisioningState": "Creating"}}, "Succeeded"),
    ({"identity": {}}, "not enabled"),
])
def test_existing_target_validation_precedes_namespace_write(service, change, match):
    service.namespace.show.side_effect = ResourceNotFoundError("missing")
    resource = target("hub")
    resource.update(change)
    service.factory_mocks["hub"].return_value.iot_hub_resource.get.return_value = resource
    with pytest.raises(InvalidArgumentValueError, match=match):
        NamespaceWorkflow(service).setup(request(outbound_identity_type="SystemAssigned", hubs=(endpoint("hub"),)))
    service.namespace.create.assert_not_called()


@pytest.mark.parametrize("field,value", [("sku", "S2"), ("unit", 2)])
def test_existing_creation_options_are_constraints_not_updates(service, field, value):
    with pytest.raises(InvalidArgumentValueError, match=field):
        service.validate_setup_target(endpoint("hub", **{field: value}), target("hub"), "eastus")


@pytest.mark.parametrize("spec,location,match", [
    (replace(endpoint("hub"), resource_id=IDS["hub"].replace("my-hub", "x")), "eastus", "resourceName"),
    (endpoint("hub", sku="B1"), "eastus", "sku"),
    (endpoint("dps", unit=False), "eastus", "unit"),
    (endpoint("hub"), "qatarcentral", "data-residency"),
    (replace(endpoint(), identity_type="bad"), "eastus", "identity"),
    (endpoint(), "not-a-region", "location"),
])
def test_target_creation_preflight_errors(service, spec, location, match):
    with pytest.raises(InvalidArgumentValueError, match=match):
        service.validate_target_creation(spec, location)


def test_creation_name_availability_and_groups(service):
    client = service.factory_mocks["hub"].return_value.iot_hub_resource
    client.check_name_availability.return_value = {"nameAvailable": False}
    with pytest.raises(InvalidArgumentValueError, match="unavailable"):
        service.validate_target_creation(endpoint("hub"), "eastus")
    service.resources.resource_groups.get.side_effect = ResourceNotFoundError("missing")
    with pytest.raises(InvalidArgumentValueError, match="resourceGroup"):
        service.validate_target_creation(endpoint(), "eastus")
    service.resources.resource_groups.get.side_effect = None
    service.validate_target_creation(endpoint("software-updates"), "eastus")
    service.update_instances.check_name.assert_called_once_with("my-su")


def test_scope_and_identity_prerequisites(service):
    assert service.setup_location(request(), namespace()) == "eastus"
    assert service.setup_location(request(), None) == "eastus"
    with pytest.raises(InvalidArgumentValueError, match="conflicts"):
        service.setup_location(request(location="westus"), namespace())
    with pytest.raises(InvalidArgumentValueError, match="could not be resolved"):
        service.setup_location(request(), {"id": NS_ID})
    service.resources.resource_groups.get.side_effect = ResourceNotFoundError("missing")
    with pytest.raises(InvalidArgumentValueError, match="resourceGroup"):
        service.setup_location(request(), None)
    service.validate_setup_identity(request(outbound_user_assigned_identity=UAMI), namespace())
    service.cli.invoke.assert_called_once()
    identityless = namespace()
    identityless["identity"] = {}
    with pytest.raises(InvalidArgumentValueError, match="system-assigned"):
        service.validate_setup_identity(request(dps=endpoint(), outbound_identity_type="SystemAssigned"), identityless)
    with pytest.raises(ArgumentUsageError, match="--subscription"):
        NamespaceWorkflow(service).plan_setup(replace(request(), subscription_id=OTHER_SUB))


def test_target_creation_plan_apply_and_role_disclosure(service, mocker):
    spec = endpoint(create_if_missing=True, sku="S1", unit=1)
    operation = service.factory_mocks["dps"].return_value.iot_dps_resource
    operation.get.side_effect = ResourceNotFoundError("missing")
    workflow = NamespaceWorkflow(service)
    req = request(dps=spec)
    plan, _ = workflow.plan_setup(req)
    item = next(item for item in plan["items"] if item["id"] == "resource-dps-dps")
    assert item["action"] == "create" and item["command"].endswith("--subscription " + SUB)
    roles = next(item for item in plan["items"] if item["id"].startswith("roles-"))
    assert roles["action"] == "role" and roles["state"] == "Planned"
    assert roles["details"] == {
        "roleValidation": "pending", "roles": [], "linkedPrincipalId": None,
        "namespaceScope": NS_ID, "targetScope": IDS["dps"],
    }
    create = mocker.patch.object(service, "create_target", return_value=target("dps"))
    mocker.patch.object(service, "wait_for_link")
    result = workflow.setup(req)
    assert result["state"] == "Succeeded"
    create.assert_called_once_with(spec, "eastus")
    service.links.dps_add.assert_called_once()
    operation.get.side_effect = None
    namespace_resource = namespace()
    namespace_resource["properties"]["provisioning"] = {"endpoints": {"dps": {
        "resourceId": IDS["dps"], "linkingState": "Succeeded", "inboundCallerIdentity": {"type": "SystemAssigned"},
    }}}
    service.namespace.show.return_value = namespace_resource
    plan, _ = workflow.plan_setup(req)
    roles = next(item for item in plan["items"] if item["id"].startswith("roles-"))
    assert roles["details"]["roles"]
    assert all(role["principalId"] and role["scope"] for role in roles["details"]["roles"])
    assert "including on reuse" in roles["message"]
    assert plan == workflow.plan_setup(req)[0]  # Confirmation comparison is deterministic.


def test_link_failed_or_changed_after_plan_is_not_replayed(service):
    workflow = NamespaceWorkflow(service)
    for state, resource_id in (("Failed", IDS["dps"]), ("Succeeded", IDS["hub"])):
        link = {"resourceId": resource_id, "linkingState": state, "inboundCallerIdentity": {"type": "SystemAssigned"}}
        with pytest.raises(ArgumentUsageError, match="changed or failed"):
            workflow._apply_one_link(request(), endpoint(), {"dps": link}, [])
    service.links.ensure_link_access.assert_not_called()
    service.links.dps_add.assert_not_called()


def test_hub_provisioning_option_conflict_blocks_instead_of_ignoring(service):
    ns = namespace()
    ns["properties"]["provisioning"] = {"endpoints": {"dps": {
        "resourceId": IDS["dps"], "linkingState": "Succeeded",
    }}}
    ns["properties"]["messaging"] = {"endpoints": {"hub": {
        "resourceId": IDS["hub"], "linkingState": "Succeeded",
        "inboundCallerIdentity": {"type": "SystemAssigned"},
        "provisioning": {"availability": "Available", "allocationWeight": 100},
    }}}
    service.namespace.show.return_value = ns
    with pytest.raises(ArgumentUsageError, match="provisioning options"):
        NamespaceWorkflow(service).setup(request(hubs=(endpoint("hub", availability="Disabled"),)))
    service.links.hub_add.assert_not_called()


def test_target_failure_after_creation_preserves_partial_result(service, mocker):
    service.namespace.show.side_effect = ResourceNotFoundError("missing namespace")
    operation = service.factory_mocks["dps"].return_value.iot_dps_resource
    operation.get.side_effect = ResourceNotFoundError("missing")
    mocker.patch.object(service, "create_target", side_effect=RuntimeError("creation failed"))
    with pytest.raises(WorkflowExecutionError) as error:
        NamespaceWorkflow(service).setup(request(dps=endpoint(create_if_missing=True), outbound_identity_type="SystemAssigned"))
    assert error.value.result["items"][0]["id"] == "namespace"
    assert error.value.result["items"][0]["state"] == "Succeeded"
    service.links.dps_add.assert_not_called()


@pytest.mark.parametrize("kind", ["hub", "dps"])
def test_existing_namespace_region_wins_over_resource_group_for_plan_and_setup(service, mocker, kind):
    ns = namespace()
    ns["location"] = "australiaeast"
    if kind == "hub":
        ns["properties"]["provisioning"] = {"endpoints": {"dps": {
            "resourceId": IDS["dps"], "linkingState": "Succeeded",
        }}}
    service.namespace.show.return_value = ns
    service.resources.resource_groups.get.return_value = {"name": "rg", "location": "westus"}
    service.subscriptions.subscriptions.list_locations.return_value = [
        {"name": "australiaeast"}, {"name": "westus"},
    ]
    spec = endpoint(kind, create_if_missing=True)
    req = request(**({"hubs": (spec,)} if kind == "hub" else {"dps": spec}))
    assert req.location is None
    operation = getattr(service.factory_mocks[kind].return_value, "iot_hub_resource" if kind == "hub" else "iot_dps_resource")
    operation.get.side_effect = ResourceNotFoundError("missing target")
    workflow = NamespaceWorkflow(service)

    plan, _ = workflow.plan_setup(req)
    item = next(item for item in plan["items"] if item["id"] == f"resource-{kind}-{kind}")
    assert plan["state"] == "Planned"
    assert item["details"]["location"] == "australiaeast"
    assert "--location australiaeast" in item["command"] and "westus" not in item["command"]
    operation.begin_create_or_update.assert_not_called()

    created = target(kind)
    created["location"] = "australiaeast"
    operation.get.side_effect = [
        ResourceNotFoundError("missing in plan"),
        ResourceNotFoundError("missing before apply"),
        ResourceNotFoundError("missing before release create"),
        created,
    ]
    mocker.patch.object(service, "wait_for_link")
    result = workflow.setup(req)
    assert result["state"] == "Succeeded"
    operation.begin_create_or_update.assert_called_once()
    body = operation.begin_create_or_update.call_args.kwargs[
        "iot_hub_description" if kind == "hub" else "iot_dps_description"
    ]
    assert body["location"] == "australiaeast"
    assert req.location is None
    service.namespace.create.assert_not_called()
