# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from datetime import timedelta

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, CLIInternalError
from azure.core import MatchConditions
from azure.core.polling import PollingMethod

from azext_iot.common import arm
from azext_iot.core import custom


@pytest.mark.parametrize("storage_identity", [None, "[system]", "/identities/user"])
def test_upsert_preserves_unknowns_and_merges_all_explicit_settings(preview_mgmt, storage_identity):
    cmd, client, hub, _, _ = preview_mgmt
    hub["identity"]["userAssignedIdentities"] = {"/identities/user": {"principalId": "readonly"}}
    hub["identity"]["type"] = "SystemAssigned,UserAssigned"
    hub["properties"]["future"] = {"keep": True}
    hub["properties"]["deviceRegistry"] = {"namespaceResourceId": "readonly"}
    before = deepcopy(hub)
    result = custom.iot_hub_create(
        cmd, client, "hub", "rg", sku="S2", unit=2, tags={"new": "tag"}, partition_count=8, retention_day=3,
        c2d_ttl=2, c2d_max_delivery_count=3, feedback_lock_duration=4, feedback_ttl=5, feedback_max_delivery_count=6,
        fileupload_notification_lock_duration=7, fileupload_notification_max_delivery_count=8, fileupload_notification_ttl=9,
        fileupload_storage_connectionstring="new-cs", fileupload_storage_container_name="uploads", fileupload_sas_ttl=10,
        fileupload_storage_authentication_type="identityBased" if storage_identity else "keyBased",
        fileupload_storage_identity=storage_identity, min_tls_version="1.2",
        enable_data_residency=True, disable_local_auth=True, disable_device_sas=True, disable_module_sas=True,
        enable_fileupload_notifications=True, system_identity=True,
    )
    assert result is client.iot_hub_resource.begin_create_or_update.return_value
    assert hub == before
    options = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert options["etag"] == "hub-etag" and options["match_condition"] == MatchConditions.IfNotModified
    body = options["iot_hub_description"]
    assert body["location"] == hub["location"]
    assert body["sku"] == {"name": "S2", "capacity": 2}
    assert body["tags"] == {"new": "tag"}
    assert body["identity"] == {
        "type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {"/identities/user": {}},
    }
    properties = body["properties"]
    assert properties["future"] == {"keep": True}
    assert "deviceRegistry" not in properties
    assert properties["eventHubEndpoints"]["events"] == {"retentionTimeInDays": 3, "partitionCount": 8}
    assert properties["cloudToDevice"] == {
        "maxDeliveryCount": 3, "defaultTtlAsIso8601": timedelta(hours=2),
        "feedback": {"lockDurationAsIso8601": timedelta(seconds=4),
                     "ttlAsIso8601": timedelta(hours=5), "maxDeliveryCount": 6},
    }
    assert properties["messagingEndpoints"]["fileNotifications"] == {
        "lockDurationAsIso8601": timedelta(seconds=7), "maxDeliveryCount": 8, "ttlAsIso8601": timedelta(hours=9),
    }
    storage = properties["storageEndpoints"]["$default"]
    assert storage["connectionString"] == "new-cs" and storage["containerName"] == "uploads"
    assert storage["sasTtlAsIso8601"] == timedelta(hours=10)
    if storage_identity == "/identities/user":
        assert storage["identity"] == {"userAssignedIdentity": storage_identity}
    else:
        assert "identity" not in storage
    assert all(properties[key] is True for key in (
        "enableDataResidency", "disableLocalAuth", "disableDeviceSAS", "disableModuleSAS", "enableFileUploadNotifications",
    ))
    assert properties["minTlsVersion"] == "1.2"


@pytest.mark.parametrize("arguments,path,value", [
    ({"location": "westus"}, (), None),
    ({"partition_count": 8}, ("eventHubEndpoints", "events", "partitionCount"), 8),
    ({"retention_day": 3}, ("eventHubEndpoints", "events", "retentionTimeInDays"), 3),
    ({"c2d_ttl": 2}, ("cloudToDevice", "defaultTtlAsIso8601"), timedelta(hours=2)),
    ({"c2d_max_delivery_count": 3}, ("cloudToDevice", "maxDeliveryCount"), 3),
    ({"feedback_lock_duration": 4}, ("cloudToDevice", "feedback", "lockDurationAsIso8601"), timedelta(seconds=4)),
    ({"feedback_ttl": 5}, ("cloudToDevice", "feedback", "ttlAsIso8601"), timedelta(hours=5)),
    ({"feedback_max_delivery_count": 6}, ("cloudToDevice", "feedback", "maxDeliveryCount"), 6),
    ({"fileupload_notification_lock_duration": 7},
     ("messagingEndpoints", "fileNotifications", "lockDurationAsIso8601"), timedelta(seconds=7)),
    ({"fileupload_notification_max_delivery_count": 8},
     ("messagingEndpoints", "fileNotifications", "maxDeliveryCount"), 8),
    ({"fileupload_notification_ttl": 9},
     ("messagingEndpoints", "fileNotifications", "ttlAsIso8601"), timedelta(hours=9)),
    ({"fileupload_sas_ttl": 10}, ("storageEndpoints", "$default", "sasTtlAsIso8601"), timedelta(hours=10)),
    ({"fileupload_storage_authentication_type": "keyBased"},
     ("storageEndpoints", "$default", "authenticationType"), "keyBased"),
])
def test_upsert_individual_options_preserve_other_settings(preview_mgmt, arguments, path, value):
    cmd, client, hub, _, _ = preview_mgmt
    hub["properties"] = {
        "eventHubEndpoints": {"events": {"retentionTimeInDays": 1, "partitionCount": 4}},
        "cloudToDevice": {
            "maxDeliveryCount": 10, "defaultTtlAsIso8601": timedelta(hours=1),
            "feedback": {
                "lockDurationAsIso8601": timedelta(seconds=5),
                "ttlAsIso8601": timedelta(hours=1), "maxDeliveryCount": 10,
            },
        },
        "messagingEndpoints": {"fileNotifications": {
            "lockDurationAsIso8601": timedelta(seconds=5),
            "ttlAsIso8601": timedelta(hours=1), "maxDeliveryCount": 10,
        }},
        "storageEndpoints": {"$default": {
            "connectionString": "existing", "containerName": "uploads",
            "sasTtlAsIso8601": timedelta(hours=1),
        }},
        "future": {"keep": True},
    }
    original = deepcopy(hub)
    expected = deepcopy(hub["properties"])
    if path:
        target = expected
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    custom.iot_hub_create(cmd, client, "hub", "rg", **arguments)

    written = client.iot_hub_resource.begin_create_or_update.call_args.kwargs
    assert written["iot_hub_description"]["properties"] == expected
    assert written["iot_hub_description"]["location"] == "westus"
    assert written["etag"] == "hub-etag"
    assert hub == original


def test_upsert_rejects_role_assignment_without_system_identity(preview_mgmt):
    cmd, client, hub, _, _ = preview_mgmt
    hub["identity"] = {"type": "UserAssigned"}
    with pytest.raises(ArgumentUsageError, match="system-assigned"):
        custom.iot_hub_create(cmd, client, "hub", "rg", identity_role="Reader", identity_scopes=["/scope"])
    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_create_role_callback_requires_returned_principal(preview_mgmt, mocker):
    cmd, client, _, _, _ = preview_mgmt
    poller = custom.iot_hub_create(cmd, client, "hub", "rg", identity_role="Reader", identity_scopes=["/scope"])
    polling_method = mocker.Mock(spec=PollingMethod)
    polling_method.resource.return_value = {"identity": {}}
    with pytest.raises(CLIInternalError, match="principalId"):
        poller.add_done_callback.call_args.args[0](polling_method)


@pytest.mark.parametrize("has_system", [False, True])
def test_identity_assign_requires_system_and_returned_principal(preview_mgmt, has_system):
    cmd, client, hub, _, wait = preview_mgmt
    hub["identity"] = {"type": "SystemAssigned" if has_system else "UserAssigned"}
    wait.return_value = {"identity": {}}
    with pytest.raises(CLIInternalError if has_system else ArgumentUsageError):
        custom.iot_hub_identity_assign(
            cmd, client, "hub", user_identities=["/identities/user"], identity_role="Reader", identity_scopes=["/scope"]
        )


@pytest.mark.parametrize("resource", [None, {}, {"id": 123}, {"id": ""}, {"id": "invalid"}])
def test_resource_metadata_fails_without_id_and_honors_context(resource):
    with pytest.raises(CLIInternalError, match="resource group"):
        arm.get_resource_group(resource)
    assert arm.get_resource_group(resource, fallback="rg") == "rg"
    with pytest.raises(CLIInternalError, match="subscription"):
        arm.get_subscription_id(resource)
    assert arm.get_subscription_id(resource, fallback="sub") == "sub"


def test_legacy_discovery_metadata_and_known_namespace_projections():
    assert arm.get_resource_group({"resourcegroup": "legacy-rg"}) == "legacy-rg"
    assert arm.get_resource_group({
        "resourcegroup": "legacy-rg", "id": "/subscriptions/sub/resourceGroups/actual-rg/providers/Microsoft.Devices/IotHubs/hub",
    }) == "actual-rg"
    original = {"properties": {
        "deviceRegistry": {"readOnly": True}, "deviceRegistryNamespace": {"readOnly": True},
        "deviceRegistryNamespaces": [{"readOnly": True}], "future": {"keep": True},
    }}
    assert arm.hub_description_for_write(original) == {"properties": {"future": {"keep": True}}}
    assert custom._dps_description_for_write(original) == {"properties": {"future": {"keep": True}}}
    assert len(original["properties"]) == 4
