# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Consolidated original-child contracts, exercised without sockets or Azure."""

import base64
from copy import deepcopy
import io
import json
import ssl
import subprocess
import runpy
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    AzureConnectionError, AzureResponseError, CLIInternalError, InvalidArgumentValueError,
    MutuallyExclusiveArgumentError, RequiredArgumentMissingError,
)
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError, ServiceRequestError
from azure.core.pipeline import PipelineContext, PipelineRequest
from azure.core.rest import HttpRequest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from azext_iot import _factory, _validators
from azext_iot.dps.providers import device_registration as device
from azext_iot.dps.services import _registration as registration
from azext_iot.dps.services import _registration_worker as worker
from azext_iot.dps.services._authentication import DpsAuthenticationPolicy
from azext_iot.dps.services._csr import normalize_csr
from azext_iot.dps.services._enrollment import handle_service_error
from azext_iot.operations import dps


@pytest.fixture
def csr_material():
    key = ec.generate_private_key(ec.SECP256R1())

    def make(names=("reg",)):
        request = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name) for name in names])
        ).sign(key, hashes.SHA256())
        return request.public_bytes(Encoding.PEM).decode(), request.public_bytes(Encoding.DER)

    return make


@pytest.mark.parametrize("encoding", ["pem", "der", "file", "new-pem"])
def test_csr_inputs_normalize_to_der(csr_material, tmp_path, encoding):
    pem, der = csr_material()
    value = pem if encoding != "der" else base64.b64encode(der).decode()
    if encoding == "new-pem":
        value = pem.replace("CERTIFICATE REQUEST", "NEW CERTIFICATE REQUEST")
    if encoding == "file":
        path = tmp_path / "request.pem"
        path.write_text(value)
        value = str(path)
    encoded = normalize_csr(device._read_csr_argument(value), "reg")
    assert base64.b64decode(encoded) == der
    assert "-----" not in encoded


@pytest.mark.parametrize("names", [(), ("other",), ("reg", "reg")])
def test_csr_common_name_is_exactly_registration_id(csr_material, names):
    with pytest.raises(InvalidArgumentValueError, match="Common Name"):
        normalize_csr(csr_material(names)[0], "reg")


@pytest.mark.parametrize("kind", ["bad-signature", "multiple", "garbage", "unicode"])
def test_invalid_csr_never_reaches_service(csr_material, kind):
    pem, der = csr_material()
    values = {
        "bad-signature": base64.b64encode(der[:-1] + bytes([der[-1] ^ 1])).decode(),
        "multiple": pem + pem, "garbage": "not PKCS10", "unicode": "\u2603",
    }
    with pytest.raises(InvalidArgumentValueError):
        normalize_csr(values[kind], "reg")


@pytest.mark.parametrize("kind", ["key", "callable", "session"])
def test_authentication_renews_on_each_request(mocker, kind):
    endpoint = "https://custom.example.test:8443"
    if kind == "key":
        credential = AzureKeyCredential("first")
    elif kind == "callable":
        credential = Mock(side_effect=["first", "second"])
    else:
        credential = SimpleNamespace(signed_session=mocker.MagicMock())
        session = credential.signed_session.return_value.__enter__.return_value
        session.headers = {"Authorization": "first"}
    policy = DpsAuthenticationPolicy(credential, endpoint)
    request = PipelineRequest(HttpRequest("GET", endpoint + "/enrollments"), PipelineContext(None))
    policy.on_request(request)
    assert request.http_request.headers["Authorization"] == "first"
    if kind == "key":
        credential.update("second")
    elif kind == "session":
        session.headers["Authorization"] = "second"
    policy.on_request(request)
    assert request.http_request.headers["Authorization"] == "second"
    if kind == "session":
        assert credential.signed_session.call_count == 2
        assert credential.signed_session.return_value.__exit__.call_count == 2


@pytest.mark.parametrize("url", [
    "http://custom.test/path", "https://different.test/path", "https://custom.test:8443/path",
    "https://user@custom.test/path", "https://user:password@custom.test/path",
])
def test_authentication_refuses_cross_origin_or_plaintext(url):
    source = Mock()
    policy = DpsAuthenticationPolicy(source, "https://custom.test")
    request = PipelineRequest(HttpRequest("GET", url), PipelineContext(None))
    with pytest.raises(ServiceRequestError, match="different origin"):
        policy.on_request(request)
    source.assert_not_called()
    assert "Authorization" not in request.http_request.headers


@pytest.mark.parametrize("host", [
    "http://dps.test", "https://dps.test/path", "https://dps.test?q=secret",
    "https://dps.test#fragment", "https://user:secret@dps.test", "https://", "",
])
def test_dps_endpoint_validation(host):
    with pytest.raises(InvalidArgumentValueError):
        _factory._as_https_endpoint(host)


def test_dps_device_factory_renews_sas_and_blocks_redirects(mocker):
    tokens = mocker.patch.object(_factory, "get_dps_sas_auth_header", side_effect=["one", "two"])
    constructor = mocker.patch("azext_iot.sdk.dps.device.ProvisioningDeviceClient")
    _factory.dps_device_service_factory(None, id_scope="scope", registration_id="reg", device_symmetric_key="key")
    options = constructor.call_args.kwargs
    assert options["redirect_max"] == 0
    tokens.assert_not_called()
    request = PipelineRequest(HttpRequest("PUT", options["endpoint"] + "/register"), PipelineContext(None))
    options["authentication_policy"].on_request(request)
    assert request.http_request.headers["Authorization"] == "one"
    options["authentication_policy"].on_request(request)
    assert request.http_request.headers["Authorization"] == "two"
    assert tokens.call_count == 2


def test_x509_transport_keeps_encrypted_key_context(mocker):
    context = mocker.patch.object(_factory.ssl, "create_default_context").return_value
    session = mocker.patch.object(_factory.requests, "Session").return_value
    transport = _factory._dps_x509_transport("cert.pem", "key.pem", "test-passphrase")
    context.load_cert_chain.assert_called_once_with(certfile="cert.pem", keyfile="key.pem", password="test-passphrase")
    adapter = session.mount.call_args.args[1]
    assert adapter.poolmanager.connection_pool_kw["ssl_context"] is context
    assert adapter.proxy_manager_for("http://proxy.test").connection_pool_kw["ssl_context"] is context
    mocker.patch.object(
        _factory.HTTPAdapter, "build_connection_pool_key_attributes",
        return_value=({"host": "device.test"}, {"cert_file": "old", "key_file": "old"}), create=True,
    )
    assert adapter.build_connection_pool_key_attributes(SimpleNamespace(url="https://device.test"), True) == (
        {"host": "device.test"}, {"ssl_context": context},
    )
    transport.close()


def test_x509_transport_legacy_requests_and_certificate_failure(mocker):
    adapter = _factory._MutualTlsAdapter(ssl.create_default_context())
    mocker.patch.object(_factory.HTTPAdapter, "build_connection_pool_key_attributes", None, create=True)
    assert adapter.build_connection_pool_key_attributes(None, True) == ({}, {"ssl_context": adapter._ssl_context})
    mocked = mocker.patch.object(_factory.ssl, "create_default_context").return_value
    mocked.load_cert_chain.side_effect = ssl.SSLError("invalid certificate")
    with pytest.raises(InvalidArgumentValueError, match="certificate files"):
        _factory._dps_x509_transport("cert.pem", "key.pem", None)


@pytest.mark.parametrize("args", [{}, {"device_symmetric_key": "key"}, {"certificate_file": "cert"}])
def test_device_factory_incomplete_auth(args):
    with pytest.raises(RequiredArgumentMissingError):
        _factory.dps_device_service_factory(None, **args)


@pytest.mark.parametrize("top", [0, -2, -1, True, "1"])
def test_query_limit_validation_prevents_query(top):
    operation = Mock()
    if top == 0:
        result = dps._execute_dps_query(operation, [], top)
        assert isinstance(result, list) and not result
    else:
        with pytest.raises(InvalidArgumentValueError):
            dps._execute_dps_query(operation, [], top)
    operation.assert_not_called()


@pytest.mark.parametrize("page", [None, {}, "invalid"])
def test_query_rejects_non_array_page(page):
    with pytest.raises(AzureResponseError, match="JSON array"):
        dps._execute_dps_query(Mock(return_value=(page, {})), [])


def test_query_repeated_continuation_fails_and_overfetch_is_truncated():
    operation = Mock(return_value=([{"id": 1}], {"x-ms-continuation": "repeated"}))
    with pytest.raises(AzureResponseError, match="repeated continuation"):
        dps._execute_dps_query(operation, [])
    assert operation.call_count == 2
    operation = Mock(return_value=([1, 2, 3], {}))
    assert dps._execute_dps_query(operation, [], top=2) == [1, 2]
    assert operation.call_args.kwargs["x_ms_max_item_count"] == 2
    assert operation.call_args.kwargs["headers"]["Cache-Control"] == "no-cache, must-revalidate"


def test_enrollment_unknown_nested_fields_and_input_are_preserved():
    original = {
        "etag": "readonly", "future": {"arbitrary": [1, 2]},
        "initialTwin": {"future": 1, "tags": {"$metadata": {}, "value": 1},
                        "properties": {"future": 2, "desired": {"$version": 3, "setting": 4}}},
        "attestation": {"x509": {"clientCertificates": {"primary": {"certificate": "pem", "info": {"readonly": 1}}}}},
    }
    snapshot = deepcopy(original)
    result = dps._drop_readonly_enrollment(original)
    assert original == snapshot
    assert result["future"] == original["future"]
    assert result["initialTwin"] == {
        "future": 1, "tags": {"value": 1}, "properties": {"future": 2, "desired": {"setting": 4}},
    }
    assert result["attestation"] == original["attestation"]
    assert "etag" not in result
    updated = dps._get_updated_inital_twin(original, initial_twin_tags='{"new": "tag"}')
    assert updated["future"] == 1
    assert updated["tags"] == {"new": "tag"}
    assert updated["properties"] == {"future": 2, "desired": {"setting": 4}}
    assert original == snapshot


@pytest.mark.parametrize("values", [
    ("UPPER", "authority", "policy"), ("ab", "authority", "policy"),
    ("namespace", "a", "policy"), ("namespace", "authority", "invalid_policy"),
    ("namespace", "authority", 42), ("namespace", "authority", "x" * 64),
])
def test_certificate_reference_name_validation(values):
    with pytest.raises(InvalidArgumentValueError):
        dps._validate_adr_certificate_reference(*values)


def test_certificate_reference_clear_conflict_and_partial():
    clear = dps._validate_adr_certificate_reference("", "", "")
    assert dps._drop_readonly_enrollment({"future": True, **clear}) == {"future": True}
    with pytest.raises(MutuallyExclusiveArgumentError):
        dps._validate_adr_certificate_reference("namespace", "authority", "policy", "other")
    with pytest.raises(RequiredArgumentMissingError):
        dps._validate_adr_certificate_reference("", None, None)


@pytest.mark.parametrize("top,expected", [(0, 0), (-1, None), (2, 2), (None, None)])
def test_dps_cli_limits_keep_unlimited_alias(top, expected):
    args = SimpleNamespace(top=top)
    _validators.process_dps_top(args)
    assert args.top == expected
    _validators.process_dps_top(SimpleNamespace())


@pytest.mark.parametrize("body", [
    {"errorCode": 401001, "message": "Denied"}, {"error": {"code": "Denied", "message": "Denied"}},
    {"error": "unexpected"}, ["unexpected"], None,
])
def test_service_error_codes_and_cause(body):
    error = HttpResponseError(message="service failure")
    error.status_code = 418
    error.response = Mock()
    error.response.json.return_value = body
    with pytest.raises(AzureResponseError) as raised:
        handle_service_error(error)
    assert raised.value.__cause__ is error
    if isinstance(body, dict) and body.get("errorCode"):
        assert "401001" in str(raised.value)


@pytest.mark.parametrize("timeout", [0, -1, True, None, "1", float("inf"), float("nan")])
def test_invalid_registration_timeout(timeout):
    with pytest.raises(InvalidArgumentValueError, match="positive, finite"):
        registration.registration_deadline(timeout)


@pytest.mark.parametrize("output", [
    "", "{}", "[]", '{"version": 2}', '{"version":1,"ok":true,"result":[]}',
    '{"version":1,"ok":null}', '{"version":1,"ok":false,"error":{"type":"Unknown"}}',
    '{"version":1,"ok":false,"error":{"type":"ValueError","message":false}}',
])
def test_invalid_worker_protocol_is_not_success(output):
    with pytest.raises(CLIInternalError, match="invalid response"):
        worker.decode_response(output)


def test_worker_error_roundtrip_redacts_secrets_and_retains_cause():
    error = HttpResponseError(message="key-secret")
    error.status_code = 403
    error.__cause__ = ValueError("SharedAccessSignature sig=secret")
    encoded = worker._error_to_json(error, ["key-secret"])
    assert "secret" not in json.dumps(encoded)
    with pytest.raises(HttpResponseError) as raised:
        worker.decode_response(json.dumps({"version": 1, "ok": False, "error": encoded}))
    assert raised.value.status_code == 403
    assert isinstance(raised.value.__cause__, ValueError)
    assert worker._error_to_json(RuntimeError("private text"), []) == {
        "type": "CLIInternalError", "message": "Unexpected DPS registration worker error (RuntimeError).",
    }


@pytest.fixture
def fake_worker(mocker):
    child = mocker.MagicMock()
    child.returncode = 0
    child.poll.return_value = 0
    child.communicate.return_value = (b'{"version":1,"ok":true,"result":{"status":"assigned"}}', b"private stderr")
    popen = mocker.patch.object(registration.subprocess, "Popen", return_value=child)
    return child, popen


def bootstrap_provider():
    provider = SimpleNamespace(
        registration_id="reg", id_scope="scope", device_endpoint="device.custom.test",
        enrollment_group_id=None, _device_symmetric_key_input="key", compute_key=False,
        device_symmetric_key=b"key", certificate_file=None, key_file=None, passphrase=None,
    )
    provider._validate_attestation_params = Mock()
    return provider


def assert_worker_closed(child):
    for stream in (child.stdin, child.stdout, child.stderr):
        stream.close.assert_called_once()


def test_worker_secrets_only_on_pipe_and_exact_endpoint(fake_worker):
    child, popen = fake_worker
    result = registration.register_with_deadline(bootstrap_provider(), {"registrationId": "reg"}, 10)
    assert result == {"status": "assigned"}
    assert len(popen.call_args.args[0]) == 3
    assert popen.call_args.args[0][1] == "-I"
    request = json.loads(child.communicate.call_args.args[0])
    assert request["provider"]["device_symmetric_key"] == "key"
    assert request["provider"]["provisioning_host"] == "device.custom.test"
    assert request["body"] == {"registrationId": "reg"}
    assert_worker_closed(child)


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), OSError("pipe error")])
def test_worker_communication_failure_is_reaped(fake_worker, failure):
    child, _ = fake_worker
    child.poll.return_value = None
    child.communicate.side_effect = failure
    with pytest.raises(type(failure)):
        registration.register_with_deadline(bootstrap_provider(), {}, 10)
    child.terminate.assert_called_once()
    assert_worker_closed(child)


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("worker", .2), KeyboardInterrupt()])
def test_worker_kill_after_grace_or_cancellation(fake_worker, failure):
    child, _ = fake_worker
    child.poll.return_value = None
    child.wait.side_effect = [failure, None]
    if isinstance(failure, subprocess.TimeoutExpired):
        registration._stop_worker(child)
    else:
        with pytest.raises(KeyboardInterrupt):
            registration._stop_worker(child)
    child.kill.assert_called_once()
    assert child.wait.call_count == 2
    assert_worker_closed(child)


@pytest.mark.parametrize("failure", ["start", "exit", "protocol", "thread", "deadline"])
def test_worker_failure_paths_are_explicit_and_clean(fake_worker, mocker, failure):
    child, popen = fake_worker
    if failure == "start":
        popen.side_effect = OSError("cannot spawn")
    elif failure == "exit":
        child.returncode = 7
    elif failure == "protocol":
        child.communicate.return_value = (b"invalid JSON", b"SECRET")
    elif failure == "thread":
        mocker.patch.object(registration.Thread, "start", side_effect=RuntimeError("cannot start thread"))
    else:
        mocker.patch.object(registration, "_remaining", side_effect=[1, 1, AzureConnectionError("timed out")])
    with pytest.raises((CLIInternalError, RuntimeError, AzureConnectionError)) as raised:
        registration.register_with_deadline(bootstrap_provider(), {}, 10)
    assert "SECRET" not in str(raised.value)
    if failure != "start":
        assert_worker_closed(child)


@pytest.mark.parametrize("success", [True, False])
def test_worker_main_uses_single_rest_implementation(mocker, success):
    values = {"device_symmetric_key": "key", "passphrase": None}
    request = {"provider": values, "body": {"csr": "csr-secret"}, "deadline": 100}
    incoming, outgoing = io.StringIO(json.dumps(request)), io.StringIO()
    mocker.patch.object(worker.sys, "stdin", incoming)
    mocker.patch.object(worker.sys, "stdout", outgoing)
    call = mocker.patch.object(registration, "register_in_worker", return_value={"status": "assigned"})
    if not success:
        call.side_effect = ValueError("csr-secret")
    worker.main()
    result = json.loads(outgoing.getvalue())
    assert result["ok"] is success
    if success:
        assert result["result"] == {"status": "assigned"}
    else:
        assert result["error"]["message"] == "[REDACTED]"


def test_worker_reuses_provider_and_closes_client(mocker):
    provider = mocker.patch.object(device, "DeviceRegistrationProvider").return_value
    provider._perform_registration.return_value = {"status": "assigned"}
    assert registration.register_in_worker({"registration_id": "reg"}, {"payload": {}}, 100) == {"status": "assigned"}
    provider._perform_registration.assert_called_once_with({"payload": {}}, deadline=100)
    provider.client.close.assert_called_once()


def test_deadline_options_and_registration_dispatch(mocker):
    mocker.patch.object(registration, "monotonic", return_value=10)
    assert registration.registration_deadline(5) == 15
    with pytest.raises(AzureConnectionError):
        registration._remaining(10)
    assert device.DeviceRegistrationProvider._request_options(20) == {
        "connection_timeout": 5, "read_timeout": 5, "retry_total": 0, "logging_enable": False,
    }
    provider = device.DeviceRegistrationProvider(
        SimpleNamespace(cli_ctx=None), "reg", id_scope="scope", device_symmetric_key="key"
    )
    dispatch = mocker.patch.object(registration, "register_with_deadline", return_value={"status": "assigned"})
    assert provider.create(payload={"site": "factory"}, timeout=5) == {"status": "assigned"}
    dispatch.assert_called_once_with(provider, {"registrationId": "reg", "payload": {"site": "factory"}}, 5)


def test_worker_hard_deadline_reaps_nonresponsive_process(fake_worker, mocker):
    child, _ = fake_worker
    mocker.patch.object(registration, "Event").return_value.wait.return_value = False
    with pytest.raises(AzureConnectionError, match="timed out"):
        registration.register_with_deadline(bootstrap_provider(), {}, 10)
    assert_worker_closed(child)


@pytest.mark.parametrize("stale", [False, True])
def test_worker_entrypoint_and_import_provenance(mocker, stale):
    request = {"provider": {"device_symmetric_key": "key", "passphrase": None}, "body": {}, "deadline": 100}
    outgoing = io.StringIO()
    mocker.patch.object(worker.sys, "stdin", io.StringIO(json.dumps(request)))
    mocker.patch.object(worker.sys, "stdout", outgoing)
    mocker.patch.object(worker.sys, "path", list(worker.sys.path))
    invoke = mocker.patch.object(registration, "register_in_worker", return_value={"status": "assigned"})
    if stale:
        mocker.patch.object(registration, "__file__", "/unexpected/_registration.py")
    runpy.run_module(worker.__name__, run_name="__main__")
    result = json.loads(outgoing.getvalue())
    assert result["ok"] is not stale
    if stale:
        invoke.assert_not_called()
        assert "unexpected extension" in result["error"]["message"]
    else:
        invoke.assert_called_once()
        assert result["result"] == {"status": "assigned"}


def test_factory_x509_branch_and_non_json_error(mocker):
    transport = mocker.patch.object(_factory, "_dps_x509_transport").return_value
    client = mocker.patch("azext_iot.sdk.dps.device.ProvisioningDeviceClient")
    _factory.dps_device_service_factory(None, certificate_file="cert", key_file="key")
    assert client.call_args.kwargs["transport"] is transport
    error = HttpResponseError("not JSON")
    error.response = Mock()
    error.response.json.side_effect = ValueError()
    with pytest.raises(AzureResponseError) as raised:
        handle_service_error(error)
    assert raised.value.__cause__ is error


@pytest.mark.parametrize("value,delay", [("2", 2), ("nonsense", 1), ("nan", 1), ("-1", 1), (None, 1)])
def test_deadline_retry_after_values(mocker, value, delay):
    mocker.patch.object(registration, "monotonic", return_value=1)
    sleep = mocker.patch.object(registration, "sleep")
    registration._wait({"Retry-After": value}, 20)
    sleep.assert_called_once_with(delay)
    with pytest.raises(AzureConnectionError, match="next permitted retry"):
        registration._wait({"Retry-After": "20"}, 20)


def test_deadline_http_date_retry_and_wire_response(mocker):
    from datetime import datetime, timezone

    mocker.patch.object(registration, "monotonic", return_value=1)
    now = mocker.patch.object(registration, "datetime")
    now.now.return_value = datetime(2026, 9, 10, tzinfo=timezone.utc)
    sleep = mocker.patch.object(registration, "sleep")
    date = "Thu, 10 Sep 2026 00:00:02 GMT"
    registration._wait({"Retry-After": date}, 20)
    sleep.assert_called_once_with(2)
    response = SimpleNamespace(http_response=SimpleNamespace(headers={"Retry-After": date}, status_code=202))

    def send(**kwargs):
        kwargs["raw_response_hook"](response)
        assert "Retry-After" not in response.http_response.headers
        return kwargs["cls"](response, {"operationId": "op"}, {})

    result = registration.call_with_deadline(send, 20, cls=device._capture_device_response)
    assert result.status_code == 202
    assert result.headers == {"Retry-After": date}


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 403])
def test_deadline_transient_http_errors_share_budget(mocker, status):
    mocker.patch.object(registration, "monotonic", return_value=1)
    sleep = mocker.patch.object(registration, "sleep")
    error = HttpResponseError(message="test service failure")
    error.status_code = status
    error.response = None
    operation = Mock(side_effect=[error, {"assigned": True}])
    if status == 403:
        with pytest.raises(Exception) as raised:
            registration.call_with_deadline(operation, 20, cls=device._capture_device_response)
        assert raised.value.__cause__ is error
        sleep.assert_not_called()
    else:
        assert registration.call_with_deadline(operation, 20, cls=device._capture_device_response) == {"assigned": True}
        assert operation.call_count == 2
        sleep.assert_called_once_with(1)
        assert all(call.kwargs["retry_total"] == 0 for call in operation.call_args_list)


def test_deadline_preserves_network_and_timeout_causes(mocker):
    from azure.core.exceptions import ServiceResponseError

    mocker.patch.object(registration, "monotonic", return_value=1)
    for error in (ServiceRequestError("connect"), ServiceResponseError("read")):
        with pytest.raises(AzureConnectionError) as raised:
            registration.call_with_deadline(Mock(side_effect=error), 20, cls=device._capture_device_response)
        assert raised.value.__cause__ is error
    error = HttpResponseError(message="retry")
    error.status_code = 429
    error.response = SimpleNamespace(headers={"retry-after": "20"})
    with pytest.raises(AzureConnectionError) as raised:
        registration.call_with_deadline(Mock(side_effect=error), 20, cls=device._capture_device_response)
    assert raised.value.__cause__ is error


def test_real_provider_deadline_flow_uses_register_and_operation_status(mocker):
    clock = [1]
    mocker.patch.object(registration, "monotonic", side_effect=lambda: clock[0])
    mocker.patch.object(registration, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay))
    provider = device.DeviceRegistrationProvider(
        SimpleNamespace(cli_ctx=None), "reg", id_scope="scope", device_symmetric_key="key", clock=lambda: clock[0],
    )
    provider.client = Mock()
    operations = provider.client.runtime_registration
    operations.register_device_and_issue_certificate.return_value = device._DeviceResponse(202, {"operationId": "op"}, {})
    operations.operation_status_lookup_preview.return_value = device._DeviceResponse(
        200, {"registrationState": {"deviceId": "assigned-device"}}, {},
    )
    result = provider._perform_registration({"registrationId": "reg", "payload": {"x": 1}}, deadline=10)
    assert result["registrationState"]["registryDeviceExternalId"] == "assigned-device"
    assert operations.register_device_and_issue_certificate.call_args.kwargs["device_registration"]["payload"] == {"x": 1}
    assert operations.operation_status_lookup_preview.call_args.kwargs["operation_id"] == "op"
    assert operations.operation_status_lookup_preview.call_args.kwargs["read_timeout"] < 5


@pytest.mark.parametrize("mode", ["success", "blocked-request", "blocked-stdin"])
def test_actual_process_deadline_and_pipe_cleanup_without_network(mocker, tmp_path, mode):
    """Adapt child worker liveness tests to a socket-free protocol peer."""
    peer = tmp_path / "offline_peer.py"
    peer.write_text(
        "import json, sys, time\n"
        + ("time.sleep(60)\n" if mode == "blocked-stdin" else "")
        + "json.load(sys.stdin)\n"
        + ("time.sleep(60)\n" if mode == "blocked-request" else "")
        + "json.dump({'version': 1, 'ok': True, 'result': {'status': 'assigned'}}, sys.stdout)\n"
    )
    original_popen = subprocess.Popen
    children = []

    def start(_args, **kwargs):
        child = original_popen([sys.executable, "-I", str(peer)], **kwargs)  # pylint: disable=consider-using-with
        children.append(child)
        return child

    mocker.patch.object(registration.subprocess, "Popen", side_effect=start)
    started = time.monotonic()
    try:
        if mode == "success":
            assert registration.register_with_deadline(bootstrap_provider(), {}, 5) == {"status": "assigned"}
        else:
            with pytest.raises(AzureConnectionError, match="timed out"):
                registration.register_with_deadline(bootstrap_provider(), {"payload": "x" * 2097152}, .2)
            assert time.monotonic() - started < 5
        child = children[0]
        assert child.poll() is not None
        assert child.stdin.closed and child.stdout.closed and child.stderr.closed
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
