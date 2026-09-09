# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import (
    CLIInternalError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.workflows import services as subject
from azext_iot.adr.workflows.models import EndpointSpec, SetupRequest


SUB = "00000000-0000-0000-0000-000000000000"
RG = "test-rg"
NS_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}"
    "/providers/Microsoft.DeviceRegistry/namespaces/ns"
)
HUB_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}"
    "/providers/Microsoft.Devices/IotHubs/hub"
)
DPS_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}"
    "/providers/Microsoft.Devices/provisioningServices/dps"
)
SU_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}"
    "/providers/Microsoft.DeviceUpdate/updateInstances/su"
)


class _Serializable:
    def as_dict(self):
        return {"source": "as_dict"}


class _LegacySerializable:
    def serialize(self):
        return {"source": "serialize"}


def test_as_dict_and_value_helpers():
    assert subject.as_dict(None) == {}
    assert subject.as_dict({"a": 1}) == {"a": 1}
    assert subject.as_dict(_Serializable()) == {"source": "as_dict"}
    assert subject.as_dict(_LegacySerializable()) == {"source": "serialize"}
    assert subject.as_dict(SimpleNamespace(a=1)) == {"a": 1}
    assert subject.value_of({"snake": 1}, "camel", "snake") == 1
    assert subject.value_of({}, "missing") is None


def test_is_not_found():
    assert subject.is_not_found(ResourceNotFoundError("missing"))
    response = SimpleNamespace(
        status_code=404,
        reason="Not Found",
        headers={},
        request=SimpleNamespace(method="GET", url="https://example"),
    )
    assert subject.is_not_found(HttpResponseError(response=response))
    assert not subject.is_not_found(ValueError("other"))


def _cli_context():
    return SimpleNamespace(
        data={"subscription_id": SUB},
        cloud=SimpleNamespace(
            endpoints=SimpleNamespace(
                resource_manager="https://management.azure.com/"
            )
        ),
    )


@pytest.fixture
def service_fixture(mocker):
    embedded = mocker.patch.object(subject, "EmbeddedCLI").return_value
    namespace = mocker.patch.object(subject, "NamespaceProvider").return_value
    links = mocker.patch.object(subject, "LinkProvider").return_value
    update = mocker.patch.object(subject, "UpdateInstanceProvider").return_value
    subscription_factory = mocker.patch.object(
        subject, "get_subscription_service_client"
    )
    subscriptions = mocker.MagicMock()
    subscription_factory.return_value = (subscriptions, SUB)
    resources = mocker.patch.object(
        subject, "get_mgmt_service_client"
    ).return_value
    link_rbac = mocker.patch.object(
        subject, "LinkRbacManager"
    ).return_value
    cmd = SimpleNamespace(cli_ctx=_cli_context())
    service = subject.WorkflowServices(cmd, sleep=mocker.Mock())
    service.cli = embedded
    service.resources = resources
    return service, namespace, links, update, link_rbac


def test_subscription_and_namespace_operations(service_fixture, mocker):
    service, namespace, _, _, _ = service_fixture
    mocker.patch.object(subject, "get_subscription_id", return_value=SUB)
    assert service.subscription_id == SUB

    service.subscriptions.subscriptions.get.return_value = {"id": SUB}
    assert service.show_subscription(SUB) == {"id": SUB}
    service.subscriptions.subscriptions.get.side_effect = (
        ResourceNotFoundError("missing")
    )
    assert service.show_subscription(SUB) is None
    service.subscriptions.subscriptions.get.side_effect = ValueError("bad")
    with pytest.raises(ValueError):
        service.show_subscription(SUB)

    service.resources.resource_groups.get.return_value = {"name": RG}
    assert service.show_resource_group(RG) == {"name": RG}
    service.resources.resource_groups.get.side_effect = ResourceNotFoundError(
        "missing"
    )
    assert service.show_resource_group(RG) is None
    service.resources.resource_groups.get.side_effect = ValueError("bad")
    with pytest.raises(ValueError):
        service.show_resource_group(RG)

    namespace.show.return_value = {"name": "ns"}
    assert service.show_namespace("ns", RG) == {"name": "ns"}
    namespace.show.side_effect = ResourceNotFoundError("missing")
    assert service.show_namespace("ns", RG) is None
    namespace.show.side_effect = ValueError("bad")
    with pytest.raises(ValueError):
        service.show_namespace("ns", RG)

    service.cli.invoke.return_value.as_json.return_value = {
        "id": SUB,
        "name": "Production",
        "tenantId": "tenant",
        "user": {"name": "user@example.com", "type": "user"},
    }
    account = service.account_context()
    assert account["subscriptionName"] == "Production"
    assert account["userName"] == "user@example.com"
    service.cli.invoke.return_value.as_json.return_value = {
        "id": SUB,
        "name": "Production",
        "state": "Enabled",
        "tenantId": "tenant",
    }
    assert service.resolve_subscription("Production")["id"] == SUB

    service.subscriptions.subscriptions.list.return_value = [{
        "subscriptionId": SUB,
        "displayName": "Production",
        "state": "Enabled",
        "tenantId": "tenant",
    }]
    assert service.list_subscriptions()[0]["name"] == "Production"

    service.resources.resource_groups.list.return_value = [{
        "id": "/subscriptions/s/resourceGroups/rg",
        "name": RG,
        "location": "eastus",
        "tags": {"env": "test"},
    }]
    assert service.list_resource_groups()[0]["location"] == "eastus"

    namespace.list.return_value = [{
        "id": NS_ID,
        "name": "ns",
        "location": "eastus",
        "properties": {"provisioningState": "Succeeded"},
        "systemData": {"createdBy": "user@example.com"},
    }]
    assert service.list_namespaces(RG)[0]["createdBy"] == "user@example.com"

    namespace.show.side_effect = None
    namespace.create.return_value = {"name": "ns"}
    result = service.create_namespace(
        "ns",
        RG,
        "eastus",
        "SystemAssigned",
        None,
        tags={"env": "test"},
    )
    assert result["name"] == "ns"
    assert namespace.create.call_args.kwargs["outbound_mi_system_assigned"]
    assert namespace.create.call_args.kwargs["tags"] == {"env": "test"}

    namespace.update.return_value = {"name": "ns"}
    service.configure_outbound_identity(
        "ns", RG, "UserAssigned", "/uami"
    )
    assert namespace.update.call_args.kwargs[
        "outbound_mi_user_assigned"
    ] == "/uami"


@pytest.mark.parametrize(
    "kind, resource_id, factory_name, operation",
    [
        ("hub", HUB_ID, "iot_hub_service_factory", "iot_hub_resource"),
        ("dps", DPS_ID, "iot_service_provisioning_factory", "iot_dps_resource"),
    ],
)
def test_resolve_hub_and_dps(
    service_fixture, mocker, kind, resource_id, factory_name, operation
):
    service, _, _, _, _ = service_fixture
    client = mocker.patch.object(subject, factory_name).return_value
    getattr(client, operation).get.return_value = {"name": kind}
    endpoint = EndpointSpec(kind, kind, resource_id, "system-assigned")
    result = service.resolve_resource(endpoint)
    assert result["name"] == kind
    assert result["id"] == resource_id


def test_list_link_targets(service_fixture, mocker):
    service, _, _, update, _ = service_fixture
    hub_client = mocker.patch.object(
        subject, "iot_hub_service_factory"
    ).return_value
    hub_client.iot_hub_resource.list_by_resource_group.return_value = [{
        "id": HUB_ID,
        "name": "hub",
        "location": "eastus",
        "sku": {"name": "S1"},
        "identity": {"type": "SystemAssigned", "principalId": "hub-p"},
        "properties": {"provisioningState": "Succeeded"},
    }]
    hub = service.list_link_targets("hub", RG)[0]
    assert hub["sku"] == "S1"
    assert hub["principalId"] == "hub-p"

    dps_client = mocker.patch.object(
        subject, "iot_service_provisioning_factory"
    ).return_value
    dps_client.iot_dps_resource.list_by_resource_group.return_value = [{
        "id": DPS_ID,
        "name": "dps",
        "properties": {
            "provisioningState": "Succeeded",
            "allocationPolicy": "Hashed",
            "iotHubs": [{"name": "hub"}],
        },
    }]
    dps = service.list_link_targets("dps", RG)[0]
    assert dps["linkedHubs"] == ["hub"]
    assert dps["allocationPolicy"] == "Hashed"

    update.list.return_value = [{
        "id": SU_ID,
        "name": "su",
        "properties": {"accountName": "adu"},
    }]
    assert service.list_link_targets(
        "software-updates", RG
    )[0]["accountName"] == "adu"

    with pytest.raises(InvalidArgumentValueError, match="Unsupported"):
        service.list_link_targets("bad", RG)


def test_resolve_update_instance_and_invalid_resources(service_fixture):
    service, _, _, update, _ = service_fixture
    update.show.return_value = {"name": "su"}
    endpoint = EndpointSpec(
        "software-updates", "su", SU_ID, "system-assigned"
    )
    assert service.resolve_resource(endpoint)["name"] == "su"

    with pytest.raises(InvalidArgumentValueError, match="IoT Hub"):
        service.resolve_resource(
            EndpointSpec("hub", "bad", DPS_ID, "system-assigned")
        )
    with pytest.raises(InvalidArgumentValueError, match="DPS"):
        service.resolve_resource(
            EndpointSpec("dps", "bad", HUB_ID, "system-assigned")
        )
    with pytest.raises(InvalidArgumentValueError, match="Update Instance"):
        service.resolve_resource(
            EndpointSpec("software-updates", "bad", HUB_ID, "system-assigned")
        )
    with pytest.raises(InvalidArgumentValueError, match="Unsupported"):
        service.resolve_resource(
            EndpointSpec("other", "bad", HUB_ID, "system-assigned")
        )
    with pytest.raises(InvalidArgumentValueError, match="Invalid"):
        service.resolve_resource(
            EndpointSpec("hub", "bad", "/bad", "system-assigned")
        )


def test_resolve_resource_rejects_cross_subscription(
    service_fixture, mocker
):
    service, _, _, _, _ = service_fixture
    mocker.patch.object(subject, "get_subscription_id", return_value=SUB)
    cross_subscription = HUB_ID.replace(SUB, "other-subscription")
    with pytest.raises(InvalidArgumentValueError, match="Cross-subscription"):
        service.resolve_resource(
            EndpointSpec(
                "hub", "hub", cross_subscription, "system-assigned"
            )
        )


def test_identity_resolution(service_fixture):
    service, _, _, _, _ = service_fixture
    service.cli.invoke.return_value.as_json.return_value = {
        "principalId": "uami-principal"
    }
    assert service.resolve_uami("/uami")["principalId"] == "uami-principal"
    assert service.principal_for_identity(
        "user-assigned",
        "/uami",
        {"identity": {"userAssignedIdentities": {"/UAMI/": {}}}},
    ) == "uami-principal"
    assert service.principal_for_identity(
        "system-assigned", None, {"identity": {"principalId": "system"}}
    ) == "system"

    service.cli.invoke.return_value.as_json.return_value = []
    with pytest.raises(CLIInternalError, match="Unable to resolve"):
        service.resolve_uami("/uami")
    with pytest.raises(InvalidArgumentValueError, match="principal ID"):
        service.principal_for_identity("system-assigned", None, {})
    with pytest.raises(InvalidArgumentValueError, match="not attached"):
        service.principal_for_identity("user-assigned", "/uami", {})


def test_uami_rejects_cross_subscription(service_fixture, mocker):
    service, _, _, _, _ = service_fixture
    mocker.patch.object(subject, "get_subscription_id", return_value=SUB)
    with pytest.raises(InvalidArgumentValueError, match="Cross-subscription"):
        service.resolve_uami(
            "/subscriptions/other/resourceGroups/rg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/u"
        )


def test_namespace_outbound_principal(service_fixture):
    service, _, _, _, _ = service_fixture
    namespace = {
        "identity": {"principalId": "system"},
        "properties": {"outboundIdentity": {"type": "SystemAssigned"}},
    }
    assert service.namespace_outbound_principal(namespace) == "system"

    service.cli.invoke.return_value.as_json.return_value = {
        "principalId": "user"
    }
    namespace["properties"]["outboundIdentity"] = {
        "type": "UserAssigned",
        "userAssignedIdentity": "/uami",
    }
    namespace["identity"]["userAssignedIdentities"] = {"/uami": {}}
    assert service.namespace_outbound_principal(namespace) == "user"
    namespace["properties"]["outboundIdentity"] = {}
    with pytest.raises(InvalidArgumentValueError, match="outbound"):
        service.namespace_outbound_principal(namespace)


def test_create_update_instance(service_fixture):
    service, _, _, update, _ = service_fixture
    endpoint = EndpointSpec(
        "software-updates", "su", SU_ID, "system-assigned"
    )
    update.check_name.return_value = {"nameAvailable": True}
    update.create.return_value = {"name": "su"}
    assert service.create_update_instance(endpoint, "eastus")["name"] == "su"
    assert update.create.call_args.kwargs["mi_system_assigned"]

    update.check_name.return_value = {"name_available": False}
    with pytest.raises(InvalidArgumentValueError, match="not available"):
        service.create_update_instance(endpoint, "eastus")


def test_link_provider_calls(service_fixture):
    service, _, links, _, _ = service_fixture
    request = SetupRequest("ns", RG)
    dps = EndpointSpec("dps", "dps", DPS_ID, "system-assigned")
    hub = EndpointSpec("hub", "hub", HUB_ID, "system-assigned")
    su = EndpointSpec("software-updates", "su", SU_ID, "system-assigned")

    service.add_dps(request, dps)
    service.add_hub(request, hub)
    service.add_su(request, su)
    service.add_dps_and_hub(request, dps, hub)
    service.ensure_link_access(request, su)
    links.dps_add.assert_called_once()
    links.hub_add.assert_called_once()
    links.su_add.assert_called_once()
    links.link_add.assert_called_once()
    links.ensure_link_access.assert_called_once_with(
        link_type="su",
        namespace_name="ns",
        resource_group_name=RG,
        target_resource_id=SU_ID,
        mi_system_assigned=True,
        mi_user_assigned=None,
    )


def test_wait_for_link_states(service_fixture):
    service, _, _, _, _ = service_fixture
    service.show_namespace = lambda *_: {
        "properties": {
            "messaging": {
                "endpoints": {
                    "hub": {"linkingState": "Succeeded"}
                }
            }
        }
    }
    assert service.wait_for_link("ns", RG, "messaging", "hub")[
        "linkingState"
    ] == "Succeeded"

    service.show_namespace = lambda *_: {
        "properties": {
            "messaging": {
                "endpoints": {
                    "hub": {
                        "linkingState": "Failed",
                        "linkingError": {"message": "denied"},
                    }
                }
            }
        }
    }
    with pytest.raises(CLIInternalError, match="denied"):
        service.wait_for_link("ns", RG, "messaging", "hub")


def test_wait_for_link_timeout(service_fixture, mocker):
    service, _, _, _, _ = service_fixture
    mocker.patch.object(subject, "LINK_POLL_ATTEMPTS", 1)
    service.show_namespace = lambda *_: {
        "properties": {
            "messaging": {
                "endpoints": {"hub": {"linkingState": "InProgress"}}
            }
        }
    }
    with pytest.raises(CLIInternalError, match="Timed out"):
        service.wait_for_link("ns", RG, "messaging", "hub")
    service.sleep.assert_called_once()
