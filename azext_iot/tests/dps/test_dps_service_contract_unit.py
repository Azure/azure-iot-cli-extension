# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import base64
import hashlib
import hmac
import json
from copy import deepcopy
from urllib.parse import parse_qs, quote_plus

import pytest
import responses
from azure.cli.core.azclierror import (
    AzureResponseError, BadRequestError, InvalidArgumentValueError, RequiredArgumentMissingError,
)

from azext_iot._factory import SdkResolver
from azext_iot.common.shared import SdkType
from azext_iot.common.sas_token_auth import BasicSasTokenAuthentication
from azext_iot.constants import IOTDPS_RESOURCE_ID
from azext_iot.operations import dps


HOST = "dps-test.custom.example"
KEY = base64.b64encode(b"service-test-key").decode()
REFERENCES = {"namespaceName": "my-namespace", "certificateAuthorityName": "my-authority",
              "certificatePolicyName": "my-policy"}


@pytest.fixture
def service(mocker):
    target = {"entity": HOST, "policy": "owner", "primarykey": KEY}
    mocker.patch.object(dps.DPSDiscovery, "get_target", return_value=target)
    with responses.RequestsMock() as transport:
        yield transport


@pytest.mark.parametrize("auth", ["sas", "login", "override"])
def test_service_auth_and_endpoint(auth, mocker):
    target = {"entity": HOST, "policy": "owner", "primarykey": KEY, "cmd": mocker.Mock()}
    override = None
    if auth == "login":
        target["policy"] = "login"
        token = mocker.patch("azext_iot.common.auth.get_aad_token",
                             return_value={"tokenType": "Bearer", "accessToken": "aad-token"})
    if auth == "override":
        override = BasicSasTokenAuthentication("SharedAccessSignature explicit-token")
    sdk = SdkResolver(target, auth_override=override).get_sdk(SdkType.dps_sdk)
    with responses.RequestsMock() as transport:
        transport.get(f"https://{HOST}/enrollments/test", json={"registrationId": "test"})
        assert sdk.individual_enrollment.get(id="test") == {"registrationId": "test"}
        request = transport.calls[0].request
        assert "api-version=2026-11-02-preview" in request.url
        assert "IoTPlatformCliExtension/" in request.headers["User-Agent"]
        authorization = request.headers["Authorization"]
        if auth == "sas":
            fields = parse_qs(authorization.split(" ", 1)[1])
            assert fields["sr"] == [HOST]
            assert fields["skn"] == ["owner"]
            signature = hmac.new(base64.b64decode(KEY),
                                 f'{quote_plus(HOST)}\n{fields["se"][0]}'.encode(), hashlib.sha256).digest()
            assert fields["sig"] == [base64.b64encode(signature).decode()]
        elif auth == "login":
            assert authorization == "Bearer aad-token"
            token.assert_called_once_with(cli_ctx=target["cmd"].cli_ctx, resource=IOTDPS_RESOURCE_ID)
        else:
            assert authorization == "SharedAccessSignature explicit-token"


@pytest.mark.parametrize("group", [False, True])
def test_reference_create_and_update_preserve_wire(service, group):
    path = "enrollmentGroups" if group else "enrollments"
    prefix = "iot_dps_device_enrollment_group" if group else "iot_dps_device_enrollment"
    record = {
        "attestation": {"type": "symmetricKey", "symmetricKey": {"primaryKey": KEY}},
        "initialTwin": {"tags": {"site": "factory"}, "properties": {"desired": {"nested": {"values": [1, 2]}}}},
        "allocationPolicy": "hashed", "iotHubs": ["hub-one", "hub-two"], "capabilities": {"iotEdge": True},
        "optionalDeviceInformation": {"manufacturer": "test"}, "customFutureField": {"kept": True},
        "createdDateTimeUtc": "server-owned", "lastUpdatedDateTimeUtc": "server-owned",
        **REFERENCES,
    }
    service.put(f"https://{HOST}/{path}/test", json=record)
    args = {} if group else {"attestation_type": "symmetricKey"}
    created = getattr(dps, prefix + "_create")(
        None, enrollment_id="test", primary_key=KEY, adr_namespace=REFERENCES["namespaceName"],
        adr_ca_name=REFERENCES["certificateAuthorityName"],
        credential_policy_name=REFERENCES["certificatePolicyName"], **args
    )
    assert created == record
    body = json.loads(service.calls[0].request.body)
    assert {key: body[key] for key in REFERENCES} == REFERENCES
    assert "credentialPolicyName" not in body
    service.get(f"https://{HOST}/{path}/test", json=record)
    service.post(f"https://{HOST}/{path}/test/attestationmechanism", json=record["attestation"])
    getattr(dps, prefix + "_update")(None, enrollment_id="test", credential_policy_name="replacement", etag='"etag"')
    updated = json.loads(service.calls[-1].request.body)
    assert service.calls[-1].request.headers["If-Match"] == '"etag"'
    assert updated["namespaceName"] == REFERENCES["namespaceName"]
    assert updated["certificateAuthorityName"] == REFERENCES["certificateAuthorityName"]
    assert updated["certificatePolicyName"] == "replacement"
    for key in ("initialTwin", "allocationPolicy", "iotHubs", "capabilities", "optionalDeviceInformation", "customFutureField"):
        assert updated[key] == record[key]
    assert "createdDateTimeUtc" not in updated
    assert "lastUpdatedDateTimeUtc" not in updated
    getattr(dps, prefix + "_update")(
        None, enrollment_id="test", adr_namespace="", adr_ca_name="", credential_policy_name=""
    )
    assert not REFERENCES.keys() & json.loads(service.calls[-1].request.body).keys()


@pytest.mark.parametrize("supplied", [
    ("namespace", None, None), (None, "authority", None), (None, None, "policy"),
    ("namespace", "", "policy"), ("", "", None), ("BadNamespace", "authority", "policy"),
    ("n", "authority", "policy"), ("namespace-", "authority", "policy"), ("a" * 65, "authority", "policy"),
    ("namespace", "bad/name", "policy"), ("namespace", "authority", "a" * 64),
    ("namespace", 123, "policy"),
])
def test_invalid_references(supplied):
    with pytest.raises((InvalidArgumentValueError, RequiredArgumentMissingError)):
        dps._validate_adr_certificate_reference(*supplied)


@pytest.mark.parametrize("record", [{}, {"initialTwin": None}, {"initialTwin": {"properties": None}},
                                    {"initialTwin": {"tags": {}, "properties": {"desired": None}}}])
def test_null_initial_twin(record):
    assert dps._get_updated_inital_twin(record) == {"tags": {}, "properties": {"desired": {}}}


@pytest.mark.parametrize("top", [None, 0, 1, 2, 3, 4])
@pytest.mark.parametrize("group", ["individual", "group", "registration"])
def test_continuation_and_top_wire(service, top, group):
    path, method = {
        "individual": ("enrollments/query", dps.iot_dps_device_enrollment_list),
        "group": ("enrollmentGroups/query", dps.iot_dps_device_enrollment_group_list),
        "registration": ("registrations/test/query", dps.iot_dps_registration_list),
    }[group]
    kwargs = {"enrollment_id": "test"} if group == "registration" else {}
    if top != 0:
        service.post(f"https://{HOST}/{path}", json=[{"id": 1}], headers={"x-ms-continuation": "opaque+/="})
        if top is None or top > 1:
            service.post(f"https://{HOST}/{path}", json=[{"id": 2}, {"id": 3}])
    result = method(None, top=top, **kwargs)
    assert result == [{"id": i} for i in range(1, (3 if top is None else min(top, 3)) + 1)]
    for index, call in enumerate(service.calls):
        assert call.request.headers["Cache-Control"] == "no-cache, must-revalidate"
        if top is not None:
            assert call.request.headers["x-ms-max-item-count"] == str(top - index)
        if index:
            assert call.request.headers["x-ms-continuation"] == "opaque+/="
        if group != "registration":
            assert json.loads(call.request.body) == {"query": "SELECT *"}


@pytest.mark.parametrize("page", [None, {}, {"value": []}])
def test_query_rejects_non_array(service, page):
    service.post(f"https://{HOST}/enrollments/query", body=json.dumps(page), content_type="application/json")
    with pytest.raises(AzureResponseError, match="invalid page"):
        dps.iot_dps_device_enrollment_list(None)


def test_query_empty_page_continues_and_repeated_token_fails(service):
    service.post(f"https://{HOST}/enrollments/query", json=[], headers={"x-ms-continuation": "repeat"})
    with pytest.raises(AzureResponseError, match="repeated continuation"):
        dps.iot_dps_device_enrollment_list(None)
    assert len(service.calls) == 2


def test_query_negative_top():
    with pytest.raises(InvalidArgumentValueError):
        dps._execute_dps_query(None, [], -1)


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("action", ["update", "delete"])
def test_etag_conflict_preserves_service_error(service, group, action):
    path = "enrollmentGroups" if group else "enrollments"
    prefix = "iot_dps_device_enrollment_group" if group else "iot_dps_device_enrollment"
    if action == "update":
        record = {"attestation": {"type": "tpm", "tpm": {"endorsementKey": "key"}}}
        service.get(f"https://{HOST}/{path}/test", json=record)
    service.add("PUT" if action == "update" else "DELETE", f"https://{HOST}/{path}/test",
                status=412, json={"errorCode": 412001, "message": "ETag mismatch"})
    with pytest.raises(AzureResponseError) as raised:
        getattr(dps, prefix + "_" + action)(None, enrollment_id="test", etag='"stale"')
    assert raised.value.__cause__.status_code == 412
    assert "412001" in str(raised.value) and "ETag mismatch" in str(raised.value)
    assert service.calls[-1].request.headers["If-Match"] == '"stale"'


@pytest.mark.parametrize("side", ["primary", "secondary"])
@pytest.mark.parametrize("kind", ["signingCertificates", "caReferences"])
def test_group_removal_without_replacement(service, side, kind):
    record = {"attestation": {"type": "x509", "x509": {kind: {"primary": "one", "secondary": "two"}}}}
    service.get(f"https://{HOST}/enrollmentGroups/test", json=record)
    service.put(f"https://{HOST}/enrollmentGroups/test", json={})
    kwargs = {"remove_certificate" if side == "primary" else "remove_secondary_certificate": True}
    dps.iot_dps_device_enrollment_group_update(None, enrollment_id="test", **kwargs)
    sent = json.loads(service.calls[-1].request.body)["attestation"]["x509"][kind]
    assert side not in sent
    assert len(sent) == 1


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("action", [
    "metadata", "reference", "replace-primary", "replace-secondary", "remove-primary", "remove-secondary",
])
def test_update_retains_info_only_x509_certificates_on_wire(service, mocker, group, action):
    path = "enrollmentGroups" if group else "enrollments"
    kind = "signingCertificates" if group else "clientCertificates"
    certificates = {
        "primary": {"info": {"subjectName": "CN=primary", "sha1Thumbprint": "a" * 40, "sha256Thumbprint": "b" * 64}},
        "secondary": {"info": {"subjectName": "CN=secondary", "sha1Thumbprint": "c" * 40, "sha256Thumbprint": "d" * 64}},
    }
    record = {
        "attestation": {"type": "x509", "x509": {kind: certificates}},
        "provisioningStatus": "enabled",
        "etag": '"original"',
        "createdDateTimeUtc": "server-owned",
        **REFERENCES,
    }
    service.get(f"https://{HOST}/{path}/test", json=record)
    service.put(f"https://{HOST}/{path}/test", json={})
    certificate_reader = mocker.patch.object(dps, "open_certificate", return_value="replacement-pem")
    expected = deepcopy(certificates)
    kwargs = {"provisioning_status": "disabled"}
    if action == "reference":
        kwargs["credential_policy_name"] = "replacement-policy"
    elif action.startswith("replace-"):
        side = action.split("-", 1)[1]
        kwargs["certificate_path" if side == "primary" else "secondary_certificate_path"] = "replacement.pem"
        expected[side] = {"certificate": "replacement-pem"}
    elif action.startswith("remove-"):
        side = action.split("-", 1)[1]
        kwargs["remove_certificate" if side == "primary" else "remove_secondary_certificate"] = True
        del expected[side]

    updater = dps.iot_dps_device_enrollment_group_update if group else dps.iot_dps_device_enrollment_update
    updater(None, enrollment_id="test", etag='"original"', **kwargs)

    assert [call.request.method for call in service.calls] == ["GET", "PUT"]
    request = service.calls[-1].request
    body = json.loads(request.body)
    assert body["attestation"]["x509"][kind] == expected
    assert body["provisioningStatus"] == "disabled"
    assert body["namespaceName"] == REFERENCES["namespaceName"]
    assert body["certificateAuthorityName"] == REFERENCES["certificateAuthorityName"]
    assert body["certificatePolicyName"] == (
        "replacement-policy" if action == "reference" else REFERENCES["certificatePolicyName"]
    )
    assert {"etag", "createdDateTimeUtc"}.isdisjoint(body)
    assert request.headers["If-Match"] == '"original"'
    assert "api-version=2026-11-02-preview" in request.url
    if action.startswith("replace-"):
        certificate_reader.assert_called_once_with("replacement.pem")
    else:
        certificate_reader.assert_not_called()


def test_unchanged_reference_not_resolved():
    record = deepcopy(REFERENCES)
    record.update(dps._validate_adr_certificate_reference())
    assert record == REFERENCES


@pytest.mark.parametrize("body", [
    "not-json", "null", "[]", '{"error": "unstructured"}',
    '{"error": {"code": "Conflict", "message": "nested"}}',
    '{"errorCode": 0, "message": ""}',
])
def test_service_error_shapes(service, body):
    service.get(f"https://{HOST}/enrollments/test", status=400, body=body, content_type="application/json")
    with pytest.raises(BadRequestError) as raised:
        dps.iot_dps_device_enrollment_get(None, enrollment_id="test")
    assert raised.value.__cause__.status_code == 400
    if "nested" in body:
        assert "(Conflict) nested" in str(raised.value)


@pytest.mark.parametrize("kind", ["signingCertificates", "caReferences"])
def test_certificate_update_without_changes(kind):
    certificate = {"primary": {"certificate": "primary"}, "secondary": {"certificate": "secondary"}}
    record = {"x509": {kind: certificate}}
    updater = (dps._get_updated_attestation_with_x509_signing_cert if kind == "signingCertificates"
               else dps._get_updated_attestation_with_x509_ca_cert)
    assert updater(record, None, None, False, False) == record


def test_connection_string_missing_named_resource(mocker):
    mocker.patch.object(dps.DPSDiscovery, "find_resource", return_value=None)
    assert dps.iot_dps_connection_string_show(None, dps_name="missing") is None


def test_service_does_not_follow_auth_redirect(service):
    from azure.core.exceptions import TooManyRedirectsError
    service.get(f"https://{HOST}/enrollments/test", status=302, headers={"Location": "https://other.example/enrollment"})
    with pytest.raises(AzureResponseError) as raised:
        dps.iot_dps_device_enrollment_get(None, enrollment_id="test")
    assert isinstance(raised.value.__cause__, TooManyRedirectsError)
    assert len(service.calls) == 1
