# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import (
    BadRequestError, InvalidArgumentValueError, RequiredArgumentMissingError, ResourceNotFoundError,
)
from azure.core import MatchConditions
from knack.util import CLIError

from azext_iot.core import custom


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("action,operation", [
    ("list", "list"), ("get", "get"), ("delete", "delete"),
    ("gen_code", "generate_verification_code"), ("verify", "verify"),
])
def test_certificate_operations_use_preview_contract(mocker, preview_mgmt, kind, action, operation):
    _, client, _, _, _ = preview_mgmt
    certificate_client = client.certificates if kind == "hub" else client.dps_certificate
    if action == "list":
        operation = "list_by_iot_hub" if kind == "hub" else "list"
    elif action == "verify":
        operation = "verify" if kind == "hub" else "verify_certificate"
    method = getattr(certificate_client, operation)
    expected = {"resource_group_name": "rg", "resource_name" if kind == "hub" else "provisioning_service_name": kind}
    arguments = {}
    if action != "list":
        arguments["certificate_name"] = "cert"
        expected["certificate_name"] = "cert"
    if action in ("delete", "gen_code", "verify"):
        arguments["etag"] = "cert-etag"
        expected.update(etag="cert-etag", match_condition=MatchConditions.IfNotModified)
    if action == "verify":
        arguments["certificate_path"] = "proof.pem"
        mocker.patch.object(custom, "open_certificate", return_value="proof-pem")
        expected["certificate_verification_body" if kind == "hub" else "request"] = {"certificate": "proof-pem"}
    result = getattr(custom, f"iot_{kind}_certificate_{action}")(client, kind, **arguments)
    assert result is method.return_value
    method.assert_called_once_with(**expected)


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("is_verified", [None, False, True])
def test_certificate_upload_preserves_preview_encoding(mocker, preview_mgmt, kind, action, is_verified):
    _, client, _, _, _ = preview_mgmt
    certificate_client = client.certificates if kind == "hub" else client.dps_certificate
    listing = certificate_client.list_by_iot_hub if kind == "hub" else certificate_client.list
    listing.return_value = {"value": [{"name": "unrelated"}] + ([{"name": "cert"}] if action == "update" else [])}
    read = mocker.patch.object(custom, "open_certificate", return_value="certificate-pem")
    arguments = {"is_verified": is_verified}
    if action == "update":
        arguments["etag"] = "cert-etag"
    result = getattr(custom, f"iot_{kind}_certificate_{action}")(client, kind, "cert", "cert.pem", **arguments)
    assert result is certificate_client.create_or_update.return_value
    properties = {"certificate": "certificate-pem" if kind == "hub" else b"certificate-pem"}
    if is_verified is not None:
        properties["isVerified"] = is_verified
    expected = {
        "resource_group_name": "rg", "resource_name" if kind == "hub" else "provisioning_service_name": kind,
        "certificate_name": "cert", "certificate_description": {"properties": properties},
    }
    if action == "update":
        expected.update(etag="cert-etag", match_condition=MatchConditions.IfNotModified)
    certificate_client.create_or_update.assert_called_once_with(**expected)
    read.assert_called_once_with("cert.pem")


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize("action,scenario,message", [
    ("create", "exists", "already exists"), ("update", "missing", "does not exist"),
    ("create", "empty", "Error uploading"), ("update", "empty", "Error uploading"),
    ("verify", "empty", "Error uploading"),
])
def test_certificate_invalid_inputs_do_not_write(mocker, preview_mgmt, kind, action, scenario, message):
    _, client, _, _, _ = preview_mgmt
    certificate_client = client.certificates if kind == "hub" else client.dps_certificate
    listing = certificate_client.list_by_iot_hub if kind == "hub" else certificate_client.list
    listing.return_value = {"value": [{"name": "cert"}] if scenario == "exists" or action == "update" else []}
    if scenario == "missing":
        listing.return_value = {"value": [{"name": "other"}]}
    read = mocker.patch.object(custom, "open_certificate", return_value="")
    arguments = {"etag": "cert-etag"} if action != "create" else {}
    with pytest.raises(CLIError, match=message):
        getattr(custom, f"iot_{kind}_certificate_{action}")(client, kind, "cert", "cert.pem", **arguments)
    certificate_client.create_or_update.assert_not_called()
    certificate_client.verify.assert_not_called()
    certificate_client.verify_certificate.assert_not_called()
    if scenario != "empty":
        read.assert_not_called()


@pytest.mark.parametrize("action", ["create", "update", "delete"])
@pytest.mark.parametrize("no_wait", [False, True])
def test_dps_policy_mutations(preview_mgmt, action, no_wait):
    cmd, client, _, dps, wait = preview_mgmt
    keep = {"keyName": "keep", "rights": "DeviceConnect"}
    policy = {"keyName": "policy", "rights": "EnrollmentRead", "primaryKey": "p", "secondaryKey": "s"}
    client.iot_dps_resource.list_keys.return_value = [keep] + ([] if action == "create" else [policy])
    arguments = {"no_wait": no_wait}
    if action in ("create", "update"):
        arguments.update(primary_key="" if action == "update" else "p", secondary_key="" if action == "update" else "s",
                         rights=["EnrollmentRead", "EnrollmentWrite", "EnrollmentRead"])
    result = getattr(custom, f"iot_dps_policy_{action}")(cmd, client, "dps", "policy", **arguments)
    policies = dps["properties"]["authorizationPolicies"]
    assert policies[0] == keep
    if action == "delete":
        assert policies == [keep]
    else:
        assert len(policies) == 2
        assert policies[1]["keyName"] == "policy"
        assert set(policies[1]["rights"].split(",")) == {"EnrollmentRead", "EnrollmentWrite"}
        assert policies[1]["primaryKey"] == (None if action == "update" else "p")
        assert policies[1]["secondaryKey"] == (None if action == "update" else "s")
    client.iot_dps_resource.begin_create_or_update.assert_called_once_with(
        resource_group_name="rg", provisioning_service_name="dps", iot_dps_description=dps
    )
    if no_wait:
        assert result is client.iot_dps_resource.begin_create_or_update.return_value
        wait.assert_not_called()
    else:
        wait.assert_called_once_with(client.iot_dps_resource.begin_create_or_update.return_value)
        expected = client.iot_dps_resource.list_keys if action == "delete" else client.iot_dps_resource.list_keys_for_key_name
        assert result is expected.return_value


@pytest.mark.parametrize("action", ["create", "update", "delete"])
def test_dps_policy_conflicts_do_not_write(preview_mgmt, action):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_dps_resource.list_keys.return_value = [{"keyName": "POLICY"}] if action == "create" else []
    arguments = {"rights": ["DeviceConnect"]} if action == "create" else {}
    with pytest.raises((BadRequestError, ResourceNotFoundError), match="already exists|doesn't exist"):
        getattr(custom, f"iot_dps_policy_{action}")(cmd, client, "dps", "policy", **arguments)
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


def test_dps_create_unavailable_name_does_not_write(preview_mgmt):
    cmd, client, _, _, _ = preview_mgmt
    client.iot_dps_resource.check_provisioning_service_name_availability.return_value = {
        "nameAvailable": False, "message": "DPS name is taken"
    }
    with pytest.raises(BadRequestError, match="DPS name is taken"):
        custom.iot_dps_create(cmd, client, "dps", "rg")
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("disable_local_auth,expected", [(None, True), (True, True), (False, False)])
def test_dps_create_local_auth_default(preview_mgmt, disable_local_auth, expected):
    cmd, client, _, _, _ = preview_mgmt
    custom.iot_dps_create(cmd, client, "dps", "rg", disable_local_auth=disable_local_auth)
    body = client.iot_dps_resource.begin_create_or_update.call_args.kwargs["iot_dps_description"]
    assert body["properties"]["disableLocalAuth"] is expected


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("use_connection_string", [False, True])
def test_dps_classic_link_creation_and_namespace_warning(mocker, preview_mgmt, no_wait, use_connection_string):
    cmd, client, _, dps, wait = preview_mgmt
    dps["properties"]["deviceRegistryNamespaces"] = [{"resourceId": "/namespace"}]
    dps["properties"]["iotHubs"] = [
        {"name": "ignored.device.azure-devices.net", "applyAllocationPolicy": False}
    ]
    client.iot_hub_resource.get_keys_for_key_name.return_value = {"keyName": "iothubowner", "primaryKey": "key"}
    warning = mocker.patch.object(custom.logger, "warning")
    connection_string = "HostName=hub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=key"
    arguments = {"connection_string": connection_string} if use_connection_string else {"hub_name": "hub"}
    result = custom.iot_dps_linked_hub_create(
        cmd, client, "dps", allocation_weight=0, apply_allocation_policy=False, no_wait=no_wait, **arguments
    )
    assert dps["properties"]["iotHubs"][-1] == {
        "connectionString": connection_string, "location": "westus", "hostName": "hub.azure-devices.net",
        "allocationWeight": 0, "applyAllocationPolicy": False,
    }
    assert all("namespace-side" in call.args[0] for call in warning.call_args_list)
    assert warning.called
    client.iot_dps_resource.begin_create_or_update.assert_called_once_with(
        resource_group_name="rg", provisioning_service_name="dps", iot_dps_description=dps
    )
    if no_wait:
        assert result is client.iot_dps_resource.begin_create_or_update.return_value
        wait.assert_not_called()
    else:
        assert result == dps["properties"]["iotHubs"]
        wait.assert_called_once_with(client.iot_dps_resource.begin_create_or_update.return_value)


@pytest.mark.parametrize("scenario,message", [
    ("no-input", "name or connection string"), ("invalid-cs", "valid IoT Hub connection string"),
    ("missing-location", "IoT Hub location"), ("missing-uami", "not configured"),
])
def test_dps_link_create_errors(preview_mgmt, scenario, message):
    cmd, client, _, dps, _ = preview_mgmt
    arguments = {}
    if scenario == "invalid-cs":
        arguments["connection_string"] = "SharedAccessKeyName=owner;SharedAccessKey=key"
    elif scenario == "missing-location":
        arguments["connection_string"] = "HostName=hub.azure-devices.net;SharedAccessKeyName=owner;SharedAccessKey=key"
        client.iot_hub_resource.list_by_subscription.return_value = []
    elif scenario == "missing-uami":
        dps["identity"] = {"type": "SystemAssigned"}
        arguments.update(hub_name="hub", authentication_type="UserAssigned", user_assigned_identity="/identities/user")
    with pytest.raises((RequiredArgumentMissingError, InvalidArgumentValueError), match=message):
        custom.iot_dps_linked_hub_create(cmd, client, "dps", **arguments)
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("short_name", [False, True])
@pytest.mark.parametrize("no_wait", [False, True])
def test_dps_link_show_and_delete(preview_mgmt, short_name, no_wait):
    cmd, client, _, dps, wait = preview_mgmt
    target = {"name": "hub.azure-devices.net", "location": "westus"}
    keep = {"name": "keep.azure-devices.net", "location": "eastus"}
    dps["properties"]["iotHubs"] = [target, keep]
    name = "hub" if short_name else target["name"]
    assert custom.iot_dps_linked_hub_get(cmd, client, "dps", name) == target
    result = custom.iot_dps_linked_hub_delete(cmd, client, "dps", name, no_wait=no_wait)
    assert dps["properties"]["iotHubs"] == [keep]
    client.iot_dps_resource.begin_create_or_update.assert_called_once_with(
        resource_group_name="rg", provisioning_service_name="dps", iot_dps_description=dps
    )
    if no_wait:
        assert result is client.iot_dps_resource.begin_create_or_update.return_value
        wait.assert_not_called()
    else:
        assert result == [keep]
        wait.assert_called_once_with(client.iot_dps_resource.begin_create_or_update.return_value)


@pytest.mark.parametrize("action", ["get", "delete"])
def test_dps_missing_link_does_not_write(preview_mgmt, action):
    cmd, client, _, _, _ = preview_mgmt
    with pytest.raises(ResourceNotFoundError, match="does not exist|doesn't exist"):
        getattr(custom, f"iot_dps_linked_hub_{action}")(cmd, client, "dps", "missing.azure-devices.net")
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


def test_dps_remove_identity_requires_selector(preview_mgmt):
    _, client, _, _, _ = preview_mgmt
    with pytest.raises(RequiredArgumentMissingError, match="Specify --system-assigned"):
        custom.dps_identity_remove(client, "dps")
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("identity", [None, {"type": "None"}])
def test_dps_remove_absent_identity_does_not_write(preview_mgmt, identity):
    _, client, _, dps, _ = preview_mgmt
    dps["identity"] = identity
    assert custom.dps_identity_remove(client, "dps", system_assigned=True) is dps
    client.iot_dps_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("no_wait", [False, True])
def test_dps_link_update_preserves_unselected_entries(preview_mgmt, no_wait):
    cmd, client, _, dps, wait = preview_mgmt
    keep = {"name": "other.azure-devices.net", "hostName": "other.azure-devices.net", "authenticationType": "KeyBased"}
    dps["properties"]["iotHubs"] = [
        {"name": "hub.azure-devices.net", "authenticationType": "KeyBased"}, keep
    ]
    result = custom.iot_dps_linked_hub_update(
        cmd, client, "dps", linked_hub="hub.azure-devices.net", allocation_weight=0,
        apply_allocation_policy=False, no_wait=no_wait,
    )
    expected = {
        "name": "hub.azure-devices.net", "hostName": "hub.azure-devices.net", "authenticationType": "KeyBased",
        "allocationWeight": 0, "applyAllocationPolicy": False,
    }
    assert dps["properties"]["iotHubs"] == [expected, keep]
    if no_wait:
        assert result is client.iot_dps_resource.begin_create_or_update.return_value
        wait.assert_not_called()
    else:
        assert result == expected
        wait.assert_called_once_with(client.iot_dps_resource.begin_create_or_update.return_value)


def test_dps_link_update_requires_attached_user_identity(preview_mgmt):
    cmd, client, _, dps, _ = preview_mgmt
    dps["identity"] = {"type": "SystemAssigned"}
    dps["properties"]["iotHubs"] = [{"name": "hub.azure-devices.net", "authenticationType": "KeyBased"}]
    with pytest.raises(InvalidArgumentValueError, match="not configured"):
        custom.iot_dps_linked_hub_update(
            cmd, client, "dps", linked_hub="hub.azure-devices.net",
            authentication_type="UserAssigned", user_assigned_identity="/identities/user"
        )
    client.iot_dps_resource.begin_create_or_update.assert_not_called()
