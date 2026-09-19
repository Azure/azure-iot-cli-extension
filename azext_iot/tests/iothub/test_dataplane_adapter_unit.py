# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Maintained Hub adapter contracts, using generated SDKs and intercepted HTTP."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import requests
import responses
from azure.cli.core.azclierror import FileOperationError, InvalidArgumentValueError
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError
from azure.core.pipeline import PipelineContext, PipelineRequest
from azure.core.rest import HttpRequest
from msrest.exceptions import SerializationError
from msrestazure.azure_exceptions import CloudError

from azext_iot.iothub._authentication import HubAuthenticationPolicy
from azext_iot.iothub._client import HubClient, upload_file_to_container
from azext_iot.iothub._payload import (
    OWNED_IDENTITY_FIELDS, SCHEMAS, make_payload, project, restore_identity_properties, validate_identity_update,
)
from azext_iot.sdk.iothub.device import IotHubGatewayDeviceAPIs
from azext_iot.sdk.iothub.service import IotHubGatewayServiceAPIs
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, CASES, ENDPOINT


def adapter(side="service"):
    constructor = IotHubGatewayServiceAPIs if side == "service" else IotHubGatewayDeviceAPIs
    sdk = constructor(AzureKeyCredential("SharedAccessSignature offline"), endpoint=ENDPOINT, retry_total=0)
    return HubClient(sdk, {case[1] for case in CASES if case[0] == side})


@pytest.mark.parametrize("model", list(SCHEMAS))
def test_empty_modeled_properties_are_omitted(model):
    assert project(model, {}) == {}
    assert project(model, dict.fromkeys(SCHEMAS[model])) == {}


def test_identity_projection_preserves_auth_attributes_scopes_and_nested_names():
    identity = {
        "deviceId": "device", "status": "enabled", "deviceScope": "scope", "parentScopes": ["parent"],
        "attributes": {"adrDeviceProperties": "user value", "status": None},
        "authentication": {
            "type": "sas", "policyResourceId": "/policies/policy",
            "x509CaValidation": {"value": {"opaque": True}},
            "symmetricKey": {"primaryKey": "primary", "secondaryKey": "secondary"},
        },
        "adrDeviceProperties": {"uuid": "owned"}, "hub": "display-only",
    }
    original = deepcopy(identity)
    written = project("Device", identity)
    assert written == {key: value for key, value in identity.items() if key not in ("adrDeviceProperties", "hub")}
    written["attributes"]["status"] = "changed"
    assert identity == original
    assert project("ExportImportDevice", {"id": "d", "adrDeviceProperties": {"uuid": "owned"}}) == {"id": "d"}


def test_modeled_nulls_do_not_remove_dictionary_deletion_markers_or_reported_fields():
    assert project("Twin", {
        "tags": None, "properties": {"desired": {"remove": None}, "reported": {"keep": True}, "unknown": "drop"},
        "status": "enabled", "version": 2,
    }) == {"properties": {"desired": {"remove": None}, "reported": {"keep": True}}, "status": "enabled", "version": 2}
    assert project("Twin", {"properties": {"desired": None}}) == {"properties": {}}
    assert make_payload("Device", device_id="d", status_reason="reason") == {"deviceId": "d", "statusReason": "reason"}
    assert project("JobRequest", {"startTime": "2026-01-01T00:00:00Z"}) == {"startTime": "2026-01-01T00:00:00.000Z"}
    assert project("CloudToDeviceMethod", {"methodName": "noop", "payload": None}) == {"methodName": "noop"}


@pytest.mark.parametrize("value", ["not-object", [], 123])
def test_bad_modeled_input_fails(value):
    with pytest.raises(SerializationError):
        project("Device", value)


@pytest.mark.parametrize("operation", ["--set", "--add", "--remove"])
@pytest.mark.parametrize("path", [
    *OWNED_IDENTITY_FIELDS, "adrDeviceProperties.name", "adr_device_properties.uuid",
    ".adrDeviceProperties.uuid", "..device_resource_id", ".armSyncStatus.[0]", "ADRDEVICEPROPERTIES[0]",
])
def test_explicit_owned_metadata_mutation_rejected(operation, path):
    values = [path + "=value"] if operation == "--set" else [path]
    with pytest.raises(InvalidArgumentValueError, match="owned by ADR"):
        validate_identity_update(SimpleNamespace(ordered_arguments=[(operation, values)]))


@pytest.mark.parametrize("arguments", [
    None, [], [("--set", ["status=disabled", 'attributes={"adrDeviceProperties":"user"}'])],
    [("--add", ["attributes", "adrDeviceProperties=user"])],
    [("--set", ["attributes.items[0].armSyncStatus=user", "attributes.deviceResourceId=null"])],
    [("--remove", ["attributes.adrDeviceProperties"])],
    [("--set", ["=empty"])], [("--set", [".=empty"])],
])
def test_unrelated_user_content_is_not_readonly(arguments):
    validate_identity_update(SimpleNamespace(ordered_arguments=arguments))


@pytest.mark.parametrize("snapshot", [None, {}, {"status": "enabled"}, {
    "authentication": {"type": "sas", "policyResourceId": "policy", "unknown": "drop"},
    "attributes": {"keep": None}, "adrDeviceProperties": {"uuid": "source"},
    "deviceResourceId": "source", "armSyncStatus": {"status": "source"},
}])
def test_state_identity_extensions_preserved_without_source_owned_fields(snapshot):
    identity = {"deviceId": "destination"}
    result = restore_identity_properties(identity, snapshot)
    assert result is identity
    if snapshot and "authentication" in snapshot:
        assert result == {
            "deviceId": "destination", "authentication": {"type": "sas", "policyResourceId": "policy"},
            "attributes": {"keep": None},
        }
    else:
        assert result == {"deviceId": "destination"}


def test_all_owned_fields_are_excluded_only_at_identity_top_level():
    fields = dict.fromkeys(OWNED_IDENTITY_FIELDS, {"source": "owned"})
    assert project("Device", {**fields, "attributes": fields}) == {"attributes": fields}
    assert project("ExportImportDevice", {**fields, "tags": fields}) == {"tags": fields}


@pytest.mark.parametrize("authentication", [
    AzureKeyCredential("SharedAccessSignature supplied"), lambda: "Bearer refreshed",
    SimpleNamespace(signed_session=lambda: _session("SharedAccessSignature refreshed")),
])
def test_auth_policy_refreshes_per_request(authentication):
    policy = HubAuthenticationPolicy(authentication, ENDPOINT)
    for _ in range(2):
        request = PipelineRequest(HttpRequest("GET", ENDPOINT + "/devices"), PipelineContext(None))
        policy.on_request(request)
        assert request.http_request.headers["Authorization"].startswith(("Bearer ", "SharedAccessSignature "))


def _session(authorization):
    session = requests.Session()
    session.headers["Authorization"] = authorization
    return session


@pytest.mark.parametrize("origin,target", [
    (ENDPOINT, "http://hub.unit.invalid/devices"),
    (ENDPOINT, "https://other.unit.invalid/devices"),
    (ENDPOINT, "https://user@hub.unit.invalid/devices"),
    (ENDPOINT, "https://user:password@hub.unit.invalid/devices"),
    (ENDPOINT, "https://hub.unit.invalid:444/devices"),
    ("http://hub.unit.invalid", ENDPOINT),
    ("https://user:password@hub.unit.invalid", ENDPOINT),
    ("https://", "https:///devices"),
])
def test_credentials_never_acquired_for_wrong_origin(origin, target):
    authentication = Mock(side_effect=AssertionError("credential should not be acquired"))
    with pytest.raises(ServiceRequestError):
        HubAuthenticationPolicy(authentication, origin).on_request(
            PipelineRequest(HttpRequest("GET", target), PipelineContext(None))
        )
    authentication.assert_not_called()


@pytest.mark.parametrize("authorization", [
    "raw-shared-key", None, 123, "SharedAccessSignature-without-space", "Bearer SharedAccessSignature invalid",
])
def test_incomplete_authorization_is_never_sent(authorization):
    request = PipelineRequest(HttpRequest("GET", ENDPOINT + "/devices"), PipelineContext(None))
    with pytest.raises(ClientAuthenticationError, match="complete"):
        HubAuthenticationPolicy(lambda: authorization, ENDPOINT).on_request(request)
    assert "Authorization" not in request.http_request.headers


def test_explicit_default_https_port_is_the_same_origin():
    request = PipelineRequest(HttpRequest("GET", ENDPOINT + ":443/devices"), PipelineContext(None))
    HubAuthenticationPolicy(lambda: "Bearer offline", ENDPOINT).on_request(request)
    assert request.http_request.headers["Authorization"] == "Bearer offline"


@pytest.mark.parametrize("positional", [False, True])
@pytest.mark.parametrize("raw", [False, True])
def test_identity_write_real_wire_projection_and_read_retention(positional, raw):
    client = adapter()
    identity = {"deviceId": "device", "attributes": {"keep": True}, "adrDeviceProperties": {"uuid": "owned"}}
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + "/devices/device", json=identity)
        args = ("device", identity) if positional else ()
        kwargs = {} if positional else {"id": "device", "device": identity}
        result = client.devices.create_or_update_identity(*args, **kwargs, raw=raw, if_match='"etag"', timeout=9)
        assert (result.response.json() if raw else result) == identity
        import json
        assert json.loads(network.calls[0].request.body) == {"deviceId": "device", "attributes": {"keep": True}}
        assert network.calls[0].request.headers["If-Match"] == '"etag"'
        assert parse_qs(urlsplit(network.calls[0].request.url).query)["api-version"] == [API]
    client.close()


@pytest.mark.parametrize("group,path", [("devices", "/twins/device"), ("modules", "/twins/device/modules/module")])
def test_twin_replace_keeps_arbitrary_dictionary_and_nulls(group, path):
    client = adapter()
    payload = {"tags": None, "properties": {"desired": {"delete": None}}, "arbitrary": {"keep": None}}
    kwargs = {"id": "device", "device_twin_info": payload}
    if group == "modules":
        kwargs["mid"] = "module"
    with responses.RequestsMock() as network:
        network.add("PUT", ENDPOINT + path, json={})
        getattr(client, group).replace_twin(**kwargs)
        import json
        assert json.loads(network.calls[0].request.body) == payload
    client.close()


@pytest.mark.parametrize("raw", [False, True])
def test_d2c_body_is_not_lost_to_bodyless_swagger(raw):
    client = adapter("device")
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/device/messages/events", status=204)
        result = client.device.send_device_event(
            id="device", message=b"\x00\xffpayload", raw=raw, custom_headers={"content-type": "application/octet-stream"}
        )
        assert network.calls[0].request.body == b"\x00\xffpayload"
        assert network.calls[0].request.headers["content-type"] == "application/octet-stream"
        assert result.response.status_code == 204 if raw else result is None
    client.close()


@pytest.mark.parametrize("reject", [None, ""])
def test_c2d_rejection_is_presence_not_truthiness(reject):
    client = adapter("device")
    with responses.RequestsMock() as network:
        network.add("DELETE", ENDPOINT + "/devices/device/messages/deviceBound/lock", status=204)
        client.device.complete_device_bound_notification(
            id="device", etag="lock", reject=reject, params={"existing": "kept"},
        )
        parameters = parse_qs(urlsplit(network.calls[0].request.url).query, keep_blank_values=True)
        assert ("reject" in parameters) == (reject is not None)
        assert parameters["existing"] == ["kept"]
        if reject is not None:
            assert parameters["reject"] == [""]
    client.close()


def test_flattened_query_jobs_and_regeneration_arguments():
    client = adapter()
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/query", json=[{"$1": 42}], headers={"x-ms-continuation": "next"})
        result = client.query.get_twins("select count() from devices", raw=True)
        assert result.response.json() == [{"$1": 42}]
        assert result.response.headers["x-ms-continuation"] == "next"
        network.add("GET", ENDPOINT + "/jobs/v2/query", json=[])
        assert client.jobs.query_scheduled_jobs("scheduleUpdateTwin", "completed") == []
        parameters = parse_qs(urlsplit(network.calls[-1].request.url).query)
        assert parameters["jobType"] == ["scheduleUpdateTwin"]
        network.add("POST", ENDPOINT + "/devices/keys/regenerate", json={"rotatedKeys": [], "errors": []})
        assert client.service.bulk_regenerate_device_key_method(policy_key="primaryKey", devices=[])["errors"] == []
    client.close()


@pytest.mark.parametrize("raw", [False, True])
@pytest.mark.parametrize("status", [200, 204])
def test_apply_configuration_retains_historical_success_statuses(raw, status):
    client = adapter()
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/device/applyConfigurationContent", status=status)
        result = client.configuration.apply_on_edge_device(id="device", content={"modulesContent": {}}, raw=raw)
        assert result.response.status_code == status if raw else result is None
        assert len(network.calls) == 1
    client.close()


@pytest.mark.parametrize("group,method,kwargs,path", [
    ("devices", "get_identity", {"id": "device"}, "/devices/device"),
    ("device", "send_device_event", {"id": "device", "message": "payload"}, "/devices/device/messages/events"),
])
def test_http_errors_preserve_details_without_replay(group, method, kwargs, path):
    client = adapter("device" if group == "device" else "service")
    with responses.RequestsMock() as network:
        network.add("POST" if group == "device" else "GET", ENDPOINT + path, status=403,
                    json={"error": {"code": "Denied", "message": "specific failure"}})
        with pytest.raises(CloudError, match="specific failure") as error:
            getattr(getattr(client, group), method)(**kwargs)
        assert error.value.status_code == 403
        assert len(network.calls) == 1
    client.close()


def test_error_without_response_is_not_reclassified(mocker):
    client = adapter()
    error = HttpResponseError("credential failure")
    mocker.patch.object(client.sdk.devices, "get_identity", side_effect=error)
    with pytest.raises(HttpResponseError) as observed:
        client.devices.get_identity(id="device")
    assert observed.value is error
    client.close()


def test_user_response_hook_error_is_not_suppressed_as_successful_configuration_apply():
    client = adapter()
    failures = []

    def reject_response(response):
        error = HttpResponseError("User callback failed", response=response.http_response)
        failures.append(error)
        raise error

    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/device/applyConfigurationContent", status=200)
        with pytest.raises(HttpResponseError) as observed:
            client.configuration.apply_on_edge_device(
                id="device", content={"modulesContent": {}}, raw_response_hook=reject_response,
            )
        assert observed.value is failures[0]
        assert len(network.calls) == 1
    client.close()


@pytest.mark.parametrize("module", [False, True])
def test_identifiers_are_escaped_once_and_conditional_headers_are_preserved(module):
    client = adapter()
    device_id, module_id = "Device#?%+", "Module+#"
    path = "/devices/" + quote(device_id, safe="")
    group, kwargs = client.devices, {"id": device_id}
    if module:
        path += "/modules/" + quote(module_id, safe="")
        group, kwargs = client.modules, dict(kwargs, mid=module_id)
    with responses.RequestsMock() as network:
        network.add("GET", ENDPOINT + path, json={"deviceId": device_id}, headers={"ETag": '"opaque-tag"'})
        result = group.get_identity(**kwargs, raw=True)
        assert result.response.headers["etag"] == '"opaque-tag"'
        network.add("DELETE", ENDPOINT + path, status=204)
        assert group.delete_identity(**kwargs, if_match='"opaque-tag"') is None
        for call in network.calls:
            assert urlsplit(call.request.url).path == path
            assert parse_qs(urlsplit(call.request.url).query) == {"api-version": [API]}
        assert network.calls[1].request.headers["If-Match"] == '"opaque-tag"'
    client.close()


def test_missing_required_body_is_not_fabricated():
    client = adapter()
    with pytest.raises(TypeError):
        client.devices.create_or_update_identity(id="device")
    client.close()


def test_flattened_upload_request_and_void_completion_are_real_http():
    import json

    client = adapter("device")
    with responses.RequestsMock() as network:
        network.add("POST", ENDPOINT + "/devices/device/files", json={"correlationId": "correlation"}, status=200)
        assert client.device.create_file_upload_sas_uri(device_id="device", blob_name="blob") == {
            "correlationId": "correlation",
        }
        assert json.loads(network.calls[0].request.body) == {"blobName": "blob"}
        notification = {"correlationId": "correlation", "isSuccess": False, "statusDescription": "failed"}
        network.add("POST", ENDPOINT + "/devices/device/files/notifications", status=204)
        assert client.device.update_file_upload_status(
            device_id="device", file_upload_completion_status=notification,
        ) is None
        assert json.loads(network.calls[1].request.body) == notification
    client.close()


@pytest.mark.parametrize("status", [200, 201, 403])
@pytest.mark.parametrize("content", ["шеллы", b"\x00\xff"])
def test_blob_upload_is_separate_binary_safe_bounded_and_without_hub_credentials(status, content):
    with responses.RequestsMock() as network:
        network.add("PUT", "https://storage.unit.invalid/container/blob?sig=offline", status=status)
        if status == 403:
            with pytest.raises(FileOperationError, match="HTTP 403"):
                upload_file_to_container("storage.unit.invalid/container/blob?sig=offline", content, "application/octet-stream")
        else:
            assert upload_file_to_container(
                "storage.unit.invalid/container/blob?sig=offline", content, "application/octet-stream"
            ).status_code == status
        request = network.calls[0].request
        expected = content.encode("utf-8") if isinstance(content, str) else content
        assert request.body == expected
        assert request.headers["Content-Length"] == str(len(expected))
        assert request.headers["x-ms-blob-type"] == "BlockBlob"
        assert "Authorization" not in request.headers
        assert "api-version" not in parse_qs(urlsplit(request.url).query)


@pytest.mark.parametrize("endpoint", ["", "user:password@storage.unit.invalid/blob", "storage.unit.invalid/blob#fragment"])
def test_invalid_blob_endpoint_never_connects(endpoint):
    with pytest.raises(FileOperationError, match="Invalid"):
        upload_file_to_container(endpoint, b"body", "text/plain")


def test_blob_transport_error_is_redacted(mocker):
    put = mocker.patch("azext_iot.iothub._client.requests.put", side_effect=requests.Timeout("sig=secret"))
    with pytest.raises(FileOperationError) as error:
        upload_file_to_container("storage.unit.invalid/blob?sig=secret", b"body", "text/plain")
    assert "secret" not in str(error.value)
    assert put.call_args.kwargs["timeout"] == 60
    assert put.call_args.kwargs["allow_redirects"] is False
    client = adapter("device")
    assert client.device.upload_file_to_container is upload_file_to_container
    client.close()
