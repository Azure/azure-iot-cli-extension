# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Retained wire tests against the real, synchronous June DPS management SDK."""

import base64
from copy import deepcopy
import json
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import ResourceModifiedError

from azext_iot.core import custom
from azext_iot.sdk.dps.mgmt import IotDpsClient


SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
BASE_URL = f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
RESOURCE_URL = f"{BASE_URL}/resourceGroups/test-rg/providers/Microsoft.Devices/provisioningServices/test-dps"
CERTIFICATE_URL = f"{RESOURCE_URL}/certificates/test-cert"
USER_ID = f"{BASE_URL}/resourceGroups/test-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/test-id"
CERTIFICATE = "-----BEGIN CERTIFICATE-----\ntest-certificate\n-----END CERTIFICATE-----"


@pytest.fixture
def stable_client():
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    with IotDpsClient(credential, SUBSCRIPTION, polling_interval=0) as client:
        yield client


@pytest.fixture
def dps_resource():
    return {
        "id": RESOURCE_URL.removeprefix("https://management.azure.com"),
        "name": "test-dps",
        "type": "Microsoft.Devices/provisioningServices",
        "location": "westus2",
        "etag": "resource-etag",
        "sku": {"name": "S1", "capacity": 1},
        "tags": {"existing": "tag"},
        "identity": {"type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {USER_ID: {}}},
        "properties": {
            "provisioningState": "Succeeded",
            "serviceOperationsHostName": "test-dps.azure-devices-provisioning.net",
            "idScope": "test-scope",
            "disableLocalAuth": True,
            "enableDataResidency": True,
            "allocationPolicy": "Hashed",
            "iotHubs": [],
        },
    }


def assert_stable_requests(mocked_response):
    assert mocked_response.calls
    for call in mocked_response.calls:
        assert parse_qs(urlsplit(call.request.url).query)["api-version"] == ["2026-06-01-preview"]


@pytest.mark.parametrize(
    "identity_args,expected_identity",
    [
        ({}, None),
        ({"mi_system_assigned": False}, None),
        ({"mi_system_assigned": True}, {"type": "SystemAssigned"}),
        ({"mi_user_assigned": [USER_ID]}, {"type": "UserAssigned", "userAssignedIdentities": {USER_ID: {}}}),
        (
            {"mi_system_assigned": True, "mi_user_assigned": [USER_ID]},
            {"type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {USER_ID: {}}},
        ),
    ],
)
def test_create_serializes_stable_resource(
    fixture_cmd, stable_client, mocked_response, dps_resource, identity_args, expected_identity
):
    mocked_response.add(
        "POST", f"{BASE_URL}/providers/Microsoft.Devices/checkProvisioningServiceNameAvailability",
        json={"nameAvailable": True},
    )
    mocked_response.add("PUT", RESOURCE_URL, json=dps_resource)

    result = custom.iot_dps_create(
        fixture_cmd, stable_client, "test-dps", "test-rg", location="westus2", **identity_args
    ).result()

    assert result == dps_resource
    assert json.loads(mocked_response.calls[0].request.body) == {"name": "test-dps"}
    body = json.loads(mocked_response.calls[1].request.body)
    assert body["location"] == "westus2"
    assert body["sku"] == {"name": "S1", "capacity": 1}
    assert body["properties"] == {}
    assert body.get("identity") == expected_identity
    if not identity_args:
        assert "identity" not in body
    assert "deviceRegistryNamespace" not in body["properties"]
    assert "disableLocalAuth" not in body["properties"]
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize("tags", [None, {}, {"changed": "tag"}])
@pytest.mark.parametrize("identity_args", [{}, {"mi_system_assigned": True}, {"mi_user_assigned": [USER_ID]}])
def test_get_put_update_preserves_supported_properties(
    stable_client, mocked_response, dps_resource, tags, identity_args
):
    mocked_response.add("GET", RESOURCE_URL, json=dps_resource)
    mocked_response.add("PUT", RESOURCE_URL, json=dps_resource)
    parameters = custom.iot_dps_get(stable_client, "test-dps", "test-rg")
    result = custom.iot_dps_update(
        stable_client, "test-dps", parameters, "test-rg", tags=tags, **identity_args
    ).result()

    assert result == dps_resource
    # The ADR identity guard re-reads the original identity before the PUT.
    assert [call.request.method for call in mocked_response.calls] == ["GET", "GET", "PUT"]
    body = json.loads(mocked_response.calls[-1].request.body)
    assert body["properties"] == custom._dps_description_for_write(dps_resource)["properties"]
    assert body["properties"]["disableLocalAuth"] is True
    assert "deviceRegistryNamespace" not in body["properties"]
    assert body["tags"] == (dps_resource["tags"] if tags is None else tags)
    assert "id" not in body
    assert "etag" not in body
    # Partial identity options must not remove an unmentioned linked identity.
    assert body["identity"] == dps_resource["identity"]
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize("handler", [custom.dps_identity_assign, custom.dps_identity_remove])
def test_identity_roundtrip_preserves_local_auth(stable_client, mocked_response, dps_resource, handler):
    mocked_response.add("GET", RESOURCE_URL, json=dps_resource)
    mocked_response.add("PUT", RESOURCE_URL, json=dps_resource)

    assert handler(stable_client, "test-dps", "test-rg", system_assigned=True).result() == dps_resource

    body = json.loads(mocked_response.calls[1].request.body)
    assert body["properties"] == custom._dps_description_for_write(dps_resource)["properties"]
    assert body["identity"]["userAssignedIdentities"] == {USER_ID: {}}
    assert body["identity"]["type"] == (
        "SystemAssigned,UserAssigned" if handler is custom.dps_identity_assign else "UserAssigned"
    )
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize("authentication_type", ["KeyBased", "SystemAssigned", "UserAssigned"])
def test_linked_hub_authentication_roundtrip(
    fixture_cmd, stable_client, mocked_response, mocker, dps_resource, authentication_type
):
    mocker.patch("azext_iot.core.custom.iot_hub_service_factory")
    mocker.patch("azext_iot.core.custom.iot_hub_get", return_value={
        "location": "westus2", "properties": {"hostName": "test-hub.azure-devices.net"}
    })
    mocked_response.add("GET", RESOURCE_URL, json=dps_resource)
    mocked_response.add("PUT", RESOURCE_URL, json=dps_resource)
    args = {
        "authentication_type": authentication_type,
        "location": "westus2",
        "resource_group_name": "test-rg",
        "no_wait": True,
    }
    if authentication_type == "KeyBased":
        args["connection_string"] = "HostName=test-hub.azure-devices.net;SharedAccessKeyName=owner;SharedAccessKey=test-key"
    else:
        args["hub_name"] = "test-hub"
        if authentication_type == "UserAssigned":
            args["user_assigned_identity"] = USER_ID

    assert custom.iot_dps_linked_hub_create(fixture_cmd, stable_client, "test-dps", **args).result() == dps_resource

    body = json.loads(mocked_response.calls[1].request.body)
    entry = body["properties"]["iotHubs"][0]
    assert entry["hostName"] == "test-hub.azure-devices.net"
    assert entry["location"] == "westus2"
    assert body["properties"]["disableLocalAuth"] is True
    if authentication_type == "KeyBased":
        assert entry["connectionString"] == args["connection_string"]
    else:
        assert entry["authenticationType"] == authentication_type
        assert "connectionString" not in entry
    if authentication_type == "UserAssigned":
        assert entry["selectedUserAssignedIdentityResourceId"] == USER_ID
    else:
        assert "selectedUserAssignedIdentityResourceId" not in entry
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize("update", [False, True])
@pytest.mark.parametrize("is_verified", [None, False, True])
def test_certificate_upload_bytes_and_etag(stable_client, mocked_response, mocker, update, is_verified):
    mocker.patch("azext_iot.core.custom.open_certificate", return_value=CERTIFICATE)
    certificate = {"name": "test-cert", "etag": '"new-etag"', "properties": {"isVerified": True}}
    mocked_response.add("GET", f"{RESOURCE_URL}/certificates", json={"value": [certificate] if update else []})
    mocked_response.add("PUT", CERTIFICATE_URL, json=certificate)
    kwargs = {"resource_group_name": "test-rg", "is_verified": is_verified}
    handler = custom.iot_dps_certificate_update if update else custom.iot_dps_certificate_create
    if update:
        kwargs["etag"] = '"old-etag"'

    assert handler(stable_client, "test-dps", "test-cert", "test.pem", **kwargs) == certificate

    request = mocked_response.calls[1].request
    properties = json.loads(request.body)["properties"]
    assert properties["certificate"] == base64.b64encode(CERTIFICATE.encode("utf-8")).decode("ascii")
    if is_verified is None:
        assert "isVerified" not in properties
    else:
        assert properties["isVerified"] is is_verified
    if update:
        assert request.headers["If-Match"] == '"old-etag"'
    else:
        assert "If-Match" not in request.headers
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize(
    "handler,method,suffix,status",
    [
        (custom.iot_dps_certificate_delete, "DELETE", "", 204),
        (custom.iot_dps_certificate_gen_code, "POST", "/generateVerificationCode", 200),
        (custom.iot_dps_certificate_verify, "POST", "/verify", 200),
    ],
)
def test_certificate_conditional_operations(stable_client, mocked_response, mocker, handler, method, suffix, status):
    mocker.patch("azext_iot.core.custom.open_certificate", return_value=CERTIFICATE)
    response = {"name": "test-cert", "properties": {"isVerified": True}}
    mocked_response.add(method, CERTIFICATE_URL + suffix, json=response if status == 200 else None, status=status)
    kwargs = {"resource_group_name": "test-rg", "etag": '"certificate-etag"'}
    if handler is custom.iot_dps_certificate_verify:
        kwargs["certificate_path"] = "test.pem"

    result = handler(stable_client, "test-dps", "test-cert", **kwargs)

    assert result == (response if status == 200 else None)
    request = mocked_response.calls[0].request
    assert request.headers["If-Match"] == '"certificate-etag"'
    if handler is custom.iot_dps_certificate_verify:
        assert json.loads(request.body) == {"certificate": CERTIFICATE}
    assert_stable_requests(mocked_response)


def test_certificate_stale_etag_raises_sdk_error(stable_client, mocked_response):
    mocked_response.add("DELETE", CERTIFICATE_URL, status=412, json={
        "error": {"code": "PreconditionFailed", "message": "The certificate etag is stale."}
    })

    with pytest.raises(ResourceModifiedError, match="etag is stale"):
        custom.iot_dps_certificate_delete(stable_client, "test-dps", "test-cert", '"stale"', "test-rg")
    assert mocked_response.calls[0].request.headers["If-Match"] == '"stale"'
    assert_stable_requests(mocked_response)


@pytest.mark.parametrize("resource_group", [None, "test-rg"])
def test_resource_lists_use_stable_paging(stable_client, mocked_response, dps_resource, resource_group):
    url = (
        f"{BASE_URL}/providers/Microsoft.Devices/provisioningServices"
        if resource_group is None else RESOURCE_URL.rsplit("/", 1)[0]
    )
    mocked_response.add("GET", url, json={"value": [dps_resource]})

    assert list(custom.iot_dps_list(stable_client, resource_group)) == [dps_resource]
    assert_stable_requests(mocked_response)


def test_policy_get_and_put_preserve_wire_fields(fixture_cmd, stable_client, mocked_response, dps_resource):
    policy = {"keyName": "owner", "rights": "ServiceConfig", "primaryKey": "primary", "secondaryKey": "secondary"}
    mocked_response.add("POST", f"{RESOURCE_URL}/listkeys", json={"value": [policy]})
    mocked_response.add("POST", f"{RESOURCE_URL}/keys/owner/listkeys", json=policy)
    mocked_response.add("GET", RESOURCE_URL, json=dps_resource)
    mocked_response.add("PUT", RESOURCE_URL, json=dps_resource)

    assert custom.iot_dps_policy_get(stable_client, "test-dps", "owner", "test-rg") == policy
    assert custom.iot_dps_policy_update(
        fixture_cmd, stable_client, "test-dps", "owner", "test-rg", primary_key="replacement", no_wait=True
    ).result() == dps_resource

    body = json.loads(mocked_response.calls[-1].request.body)
    expected_policy = deepcopy(policy)
    expected_policy["primaryKey"] = "replacement"
    assert body["properties"]["authorizationPolicies"] == [expected_policy]
    assert body["properties"]["disableLocalAuth"] is True
    assert_stable_requests(mocked_response)


def test_delete_uses_stable_lro(stable_client, mocked_response):
    mocked_response.add("DELETE", RESOURCE_URL, status=204)

    assert custom.iot_dps_delete(stable_client, "test-dps", "test-rg").result() is None
    assert_stable_requests(mocked_response)
