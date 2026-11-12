# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Opaque HTTP C2D payloads through the real generated client and recording transport."""

from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
import responses
from azure.cli.core.azclierror import AzureInternalError
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, IncompleteReadError, ServiceResponseError
from azure.core.pipeline.policies import SansIOHTTPPolicy
from msrestazure.azure_exceptions import CloudError

from azext_iot.iothub._client import HubClient
from azext_iot.iothub.providers.device_messaging import DeviceMessagingProvider, NON_DECODABLE_PAYLOAD
from azext_iot.sdk.iothub.device import IotHubGatewayDeviceAPIs
from azext_iot.tests.iothub.test_dataplane_wire_unit import API, ENDPOINT, RecordingTransport


DEVICE = "Device #?%+"
PATH = "/devices/" + quote(DEVICE, safe="") + "/messages/deviceBound"


class ReceiveTransport(RecordingTransport):
    def __init__(self):
        super().__init__()
        self.responses = []

    def send(self, request, **kwargs):
        response = super().send(request, **kwargs)
        self.responses.append(response)
        return response


@pytest.fixture
def client():
    transport = ReceiveTransport()
    sdk = IotHubGatewayDeviceAPIs(
        AzureKeyCredential("SharedAccessSignature offline"), endpoint=ENDPOINT,
        transport=transport, retry_total=0, redirect_max=0,
    )
    wrapped = HubClient(sdk, ("device",))
    yield wrapped, transport
    wrapped.close()


def register(network, body, content_type, status=200, headers=None):
    network.add(
        "GET", ENDPOINT + PATH, body=body, status=status, content_type=content_type,
        headers={"ETag": '"opaque-lock"', "IotHub-App-Example": "kept", **(headers or {})},
        match=[responses.matchers.query_param_matcher({"api-version": API})],
    )


@pytest.mark.parametrize("content_type,body", [
    ("application/octet-stream", b"0x68 0x65 0x6c 0x6c 0x6f 0x20 0x77 0x6f 0x72 0x6c 0x64"),
    ("application/json", b"Ping from Az CLI IoT Extension"),
], ids=["live-octet-message", "live-json-labelled-plain-message"])
def test_live_receive_regressions(client, content_type, body):
    wrapped, transport = client
    with responses.RequestsMock() as network:
        register(network, body, content_type)
        result = wrapped.device.receive_device_bound_notification(id=DEVICE, raw=True).response
        assert result.status_code == 200
        assert result.content == body
        assert result.headers["etag"] == '"opaque-lock"'
        assert len(network.calls) == len(transport.requests) == 1


@pytest.mark.parametrize("content_type,body", [
    ("application/octet-stream", b"\x00\xff\x80\r\n"),
    ("text/plain; charset=utf-8", "a message \u2603".encode()),
    ("application/json", b' { "exact": null, "order": [2, 1] }\r\n'),
    ("application/json", b'{"incomplete":'),
    ("application/xml", b"<not-closed"),
    (None, b"no content type; not JSON"),
    ("application/octet-stream", b""),
    ("text/plain", "hello".encode("utf-16")),
])
@pytest.mark.parametrize("raw", [False, True])
def test_receive_preserves_opaque_bytes_and_request_headers(client, content_type, body, raw):
    wrapped, transport = client
    observed = []
    with responses.RequestsMock() as network:
        register(network, body, content_type)
        result = wrapped.device.receive_device_bound_notification(
            DEVICE, raw=raw, timeout=9, custom_headers={"IotHub-MessageLockTimeout": "30"},
            raw_response_hook=lambda response: observed.append(response.http_response),
        )
        if raw:
            assert result.response.content == body
            assert result.response.headers["IotHub-App-Example"] == "kept"
            assert result.response.headers.get("content-type") == content_type
        else:
            assert result is None
        assert observed[0].content == body
        assert observed[0].is_closed
        request = transport.requests[0]
        assert request.method == "GET"
        assert request.headers["IotHub-MessageLockTimeout"] == "30"
        assert request.headers["Authorization"] == "SharedAccessSignature offline"
        assert len(network.calls) == len(transport.requests) == len(observed) == 1


@pytest.mark.parametrize("status", [201, 202, 206, 304, 400, 401, 403, 404, 409, 412, 429, 500, 503])
@pytest.mark.parametrize("content_type,body", [
    ("application/octet-stream", b"not a successful receive"),
    ("application/json", b'{"Message":"real resource failure"}'),
    ("application/json", b"not-json error detail"),
])
def test_receive_rejects_all_noncontract_statuses_without_replay(client, status, content_type, body):
    wrapped, transport = client
    observed = []
    with responses.RequestsMock() as network:
        register(network, b"" if status == 304 else body, content_type, status=status)
        with pytest.raises(CloudError) as error:
            wrapped.device.receive_device_bound_notification(
                id=DEVICE, raw=True, raw_response_hook=lambda response: observed.append(response.http_response),
            )
        assert error.value.status_code == status
        assert observed[0].status_code == status
        assert observed[0].is_closed
        assert len(network.calls) == len(transport.requests) == 1


@pytest.mark.parametrize("content_type,body,expected", [
    ("application/octet-stream", b"message text", "message text"),
    ("application/json", b"Ping from Az CLI IoT Extension", "Ping from Az CLI IoT Extension"),
    ("application/json", b'{"keep":null}', '{"keep":null}'),
    ("application/octet-stream", b"\xff\x00", NON_DECODABLE_PAYLOAD),
    ("application/octet-stream", b"", None),
])
@pytest.mark.parametrize("ack", [None, "complete", "abandon", "reject"])
def test_provider_receive_and_settlement_use_actual_raw_message(client, content_type, body, expected, ack):
    wrapped, transport = client
    provider = DeviceMessagingProvider.__new__(DeviceMessagingProvider)
    provider.device_id, provider.device_sdk = DEVICE, wrapped
    with responses.RequestsMock() as network:
        register(network, body, content_type)
        if ack:
            path = PATH + "/opaque-lock" + ("/abandon" if ack == "abandon" else "")
            parameters = {"api-version": API, **({"reject": ""} if ack == "reject" else {})}

            def exact_query(request):
                actual = parse_qs(urlsplit(request.url).query, keep_blank_values=True)
                return actual == {key: [value] for key, value in parameters.items()}, "Exact settlement query differs"

            network.add(
                "POST" if ack == "abandon" else "DELETE", ENDPOINT + path, status=204,
                match=[exact_query],
            )
        result = provider._c2d_message_receive(ack=ack)
        assert result["etag"] == "opaque-lock"
        assert result["properties"]["app"] == {"Example": "kept"}
        assert result.get("data") == expected
        assert result.get("ack") == ack
        assert len(network.calls) == len(transport.requests) == (2 if ack else 1)


def test_provider_empty_queue_never_settles(client):
    wrapped, transport = client
    provider = DeviceMessagingProvider.__new__(DeviceMessagingProvider)
    provider.device_id, provider.device_sdk = DEVICE, wrapped
    with responses.RequestsMock() as network:
        register(network, b"", "application/octet-stream", status=204)
        assert provider._c2d_message_receive(ack="complete") is None
        assert len(network.calls) == len(transport.requests) == 1


def test_provider_real_failure_is_not_valid_message_text(client):
    wrapped, _ = client
    provider = DeviceMessagingProvider.__new__(DeviceMessagingProvider)
    provider.device_id, provider.device_sdk = DEVICE, wrapped
    with responses.RequestsMock() as network:
        register(network, b"actual backend failure", "text/plain", status=500)
        with pytest.raises(AzureInternalError, match="actual backend failure"):
            provider._c2d_message_receive()
        assert len(network.calls) == 1


def test_receive_user_hook_error_propagates_and_closes_response(client):
    wrapped, transport = client
    failures, observed = [], []

    def reject(response):
        observed.append(response.http_response)
        failure = HttpResponseError("caller callback failed", response=response.http_response)
        failures.append(failure)
        raise failure

    with responses.RequestsMock() as network:
        register(network, b"valid message", "application/octet-stream")
        with pytest.raises(HttpResponseError) as error:
            wrapped.device.receive_device_bound_notification(id=DEVICE, raw=True, raw_response_hook=reject)
        assert error.value is failures[0]
        assert not isinstance(error.value, CloudError)
        assert observed[0].is_closed
        assert len(network.calls) == len(transport.requests) == 1


def test_receive_credential404_never_becomes_a_resource_error():
    failure = HttpResponseError(
        "credential acquisition failed", response=SimpleNamespace(status_code=404, reason="", headers={}),
    )

    class FailingCredentialPolicy(SansIOHTTPPolicy):
        def on_request(self, _request):
            raise failure

    transport = RecordingTransport()
    with IotHubGatewayDeviceAPIs(
        AzureKeyCredential("unused"), endpoint=ENDPOINT, transport=transport,
        authentication_policy=FailingCredentialPolicy(),
    ) as sdk:
        wrapped = HubClient(sdk, ("device",))
        with pytest.raises(HttpResponseError) as error:
            wrapped.device.receive_device_bound_notification(id=DEVICE, raw=True)
        assert error.value is failure
        assert not transport.requests


def test_receive_transport_failure_never_replays(client):
    wrapped, transport = client
    failure = ServiceResponseError("response lost")
    with responses.RequestsMock() as network:
        register(network, failure, "application/octet-stream")
        with pytest.raises(ServiceResponseError) as error:
            wrapped.device.receive_device_bound_notification(id=DEVICE, raw=True)
        assert error.value is failure
        assert len(transport.requests) == 1


def test_receive_partial_body_read_failure_closes_response_without_replay(client):
    wrapped, transport = client
    with responses.RequestsMock() as network:
        register(network, b"short", "application/octet-stream", headers={"Content-Length": "128"})
        with pytest.raises(IncompleteReadError):
            wrapped.device.receive_device_bound_notification(id=DEVICE, raw=True)
        assert len(network.calls) == len(transport.requests) == 1
        assert transport.responses[0].is_closed


@pytest.mark.parametrize("raw", [False, True])
def test_receive_cls_and_parameters_preserve_callback_contract(client, raw):
    wrapped, transport = client
    callbacks = []

    def callback(response, data, headers):
        callbacks.append(response)
        assert data is None and headers == {}
        assert response.http_response.is_closed
        return response.http_response.content

    with responses.RequestsMock() as network:
        network.add(
            "GET", ENDPOINT + PATH, body=b"payload", content_type="application/octet-stream",
            match=[responses.matchers.query_param_matcher({"api-version": API, "extra": "kept"})],
        )
        result = wrapped.device.receive_device_bound_notification(
            id=DEVICE, raw=raw, cls=callback, params={"extra": "kept"},
        )
        assert (result.response.content if raw else result) == b"payload"
        assert len(callbacks) == (0 if raw else 1)
        assert len(transport.requests) == 1


def test_receive_explicit_error_mapping_is_not_lost(client):
    wrapped, transport = client

    class SpecificFailure(Exception):
        def __init__(self, response):
            self.response = response

    with responses.RequestsMock() as network:
        register(network, b"precise failure", "application/octet-stream", status=422)
        with pytest.raises(SpecificFailure) as error:
            wrapped.device.receive_device_bound_notification(id=DEVICE, error_map={422: SpecificFailure})
        assert error.value.response.status_code == 422
        assert error.value.response.content == b"precise failure"
        assert error.value.response.is_closed
        assert len(transport.requests) == 1


def test_nonreceive_json_operations_still_require_json(client):
    wrapped, transport = client
    with responses.RequestsMock() as network:
        network.add(
            "POST", ENDPOINT + "/devices/" + quote(DEVICE, safe="") + "/files",
            body=b"not a file upload JSON document", content_type="application/json",
        )
        with pytest.raises(CloudError) as error:
            wrapped.device.create_file_upload_sas_uri(device_id=DEVICE, blob_name="file.bin", raw=True)
        assert error.value.status_code == 200  # A genuine decode failure, not opaque-message semantics.
        assert len(transport.requests) == 1
