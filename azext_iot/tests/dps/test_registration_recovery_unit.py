# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Socket-free DPS acceptance recovery, real pipe lifecycles and SDK contracts."""

import base64
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import runpy
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
import requests
from azure.cli.core.azclierror import AzureConnectionError, AzureResponseError, CLIInternalError
from cryptography.hazmat.primitives.serialization import Encoding
from azext_iot.dps.providers import device_registration as device
from azext_iot.dps.services import _registration as registration
from azext_iot.dps.services import _registration_protocol as protocol
from azext_iot.dps.services import _registration_worker as worker
from azext_iot.tests.dps._csr import generate_csr


def _frame(value):
    output = io.StringIO()
    protocol.write_frame(output, value)
    return output.getvalue().encode()


ACCEPTED = _frame({"version": 1, "accepted": {"operationId": "4.operation-01"}})
FINAL = _frame({"version": 1, "ok": True, "result": {"status": "assigned"}})


def _provider():
    return device.DeviceRegistrationProvider(
        SimpleNamespace(cli_ctx=None), "device-01", id_scope="0ne00000000",
        provisioning_host="https://dps.invalid",
        device_symmetric_key=base64.b64encode(b"offline-device-secret").decode(),
    )


def _assert_followup(error):
    message = str(error)
    command = message.split("'")[1]
    args = shlex.split(command)
    assert args[:5] == ["az", "iot", "device", "registration", "operation-status"]
    for name, expected in (
        ("--operation-id", "4.operation-01"), ("--registration-id", "device-01"),
        ("--id-scope", "0ne00000000"), ("--host", "https://dps.invalid"),
    ):
        assert f"{name}={expected}" in args
    assert "same device authentication" in message
    assert "--compute-key" in message
    assert "may still complete" in message
    assert "resubmitting" in message


@pytest.mark.parametrize("data", [FINAL, ACCEPTED + FINAL])
def test_framed_response_retains_only_allowlisted_progress(data):
    communication = {}
    protocol.read_frames(io.BytesIO(data), communication)
    assert worker.decode_response(communication["output"]) == {"status": "assigned"}
    assert communication.get("operation_id") == ("4.operation-01" if data.startswith(ACCEPTED) else None)


@pytest.mark.parametrize("invalid", [
    b"", b"not JSON\n", b"[]\n", b"{}\n", b"\xff\n", b'{"version":1}\n',
    b'{"version":1,"accepted":{"operationId":"first","operationId":"second"}}\n',
    b'{"version":1,"version":1,"ok":true,"result":{}}\n',
    b'{"version":true,"ok":true}\n', b'{"version":2,"ok":true}\n',
    b'{"version":1,"accepted":[]}\n', b'{"version":1,"accepted":{}}\n',
    _frame({"version": 1, "accepted": {"operationId": "bad\nid"}}),
    _frame({"version": 1, "accepted": {"operationId": 123}}),
    _frame({"version": 1, "accepted": {"operationId": "x" * 257}}),
    _frame({"version": 1, "accepted": {"operationId": "op", "payload": "secret"}}),
    _frame({"version": 1, "accepted": {"operationId": "op"}, "headers": "secret"}),
    b'{"version":1,"accepted": {"operationId":"op"}}' + b" " * 1024 + b"\n",
    ACCEPTED, ACCEPTED[:-1], FINAL[:-1], FINAL + FINAL, FINAL + ACCEPTED,
    ACCEPTED + ACCEPTED, ACCEPTED + _frame({"version": 1, "accepted": {"operationId": "different"}}),
    b"[" * 2000 + b"]" * 2000 + b"\n",
])
def test_malformed_partial_duplicate_changed_and_trailing_frames_fail_closed(invalid):
    communication = {}
    with pytest.raises(CLIInternalError) as raised:
        protocol.read_frames(io.BytesIO(invalid), communication)
    assert "secret" not in str(raised.value)
    if invalid.startswith(ACCEPTED):
        assert communication["operation_id"] == "4.operation-01"
    else:
        assert "operation_id" not in communication


def test_output_bound_includes_progress_and_final(mocker):
    mocker.patch.object(protocol, "MAX_OUTPUT_BYTES", len(ACCEPTED + FINAL) - 1)
    communication = {}
    with pytest.raises(CLIInternalError, match="oversized"):
        protocol.read_frames(io.BytesIO(ACCEPTED + FINAL), communication)
    assert communication == {"operation_id": "4.operation-01"}


def test_timeout_text_does_not_invent_an_id_or_interpolate_shell_input():
    assert "Operation ID is unknown" in protocol.timeout_message()
    assert "operation-status" not in protocol.timeout_message()
    message = protocol.timeout_message("op", "bad;secret", "bad\nsecret", "$(secret)")
    assert "secret" not in message
    assert "--registration-id=<registration-id>" in message
    assert "--id-scope=<id-scope>" in message
    assert "--host=<same-provisioning-host>" in message
    assert "--operation-id=--not-a-flag" in protocol.timeout_message("--not-a-flag")


@pytest.mark.parametrize("body", [{}, [], {"operationId": "bad\nid"}, {"operationId": 42}])
def test_provider_rejects_unsafe_or_missing_acceptance_metadata(body):
    provider = _provider()
    with pytest.raises(AzureResponseError, match="operation"):
        provider._observe_acceptance(device._DeviceResponse(202, body, {}))
    assert provider._operation_id is None


def test_provider_never_replaces_accepted_id_or_reemits_progress():
    provider = _provider()
    observed = []
    provider._accepted_callback = observed.append
    response = device._DeviceResponse(202, {"operationId": "4.operation-01"}, {})
    provider._observe_acceptance(response)
    provider._observe_acceptance(response)
    provider._observe_acceptance(device._DeviceResponse(202, {}, {}))
    with pytest.raises(AzureResponseError, match="original operation.*4.operation-01"):
        provider._observe_acceptance(device._DeviceResponse(202, {"operationId": "changed"}, {}))
    assert observed == ["4.operation-01"]
    assert provider._operation_id == "4.operation-01"


@pytest.mark.parametrize("operation_id", ["4.operation-01", "key-secret", "passphrase", "bad\nid"])
def test_worker_progress_does_not_forward_response_payload_or_secrets(mocker, operation_id):
    passphrase = secrets.token_urlsafe(32)
    if operation_id == "passphrase":
        operation_id = passphrase
    request = {
        "provider": {"device_symmetric_key": "key-secret", "passphrase": passphrase},
        "body": {"csr": "csr-secret", "payload": {"value": "payload-secret"}}, "deadline": 100,
    }
    output = io.StringIO()
    mocker.patch.object(sys, "stdin", io.StringIO(json.dumps(request)))
    mocker.patch.object(sys, "stdout", output)

    def register(_values, body, deadline, accepted):
        assert body == request["body"] and deadline == 100
        accepted(operation_id)
        raise protocol.RegistrationTimeoutError(protocol.timeout_message(operation_id))

    mocker.patch.object(registration, "register_in_worker", register)
    worker.main()
    frames = output.getvalue().splitlines()
    if operation_id == "4.operation-01":
        assert json.loads(frames[0]) == {"version": 1, "accepted": {"operationId": operation_id}}
        assert len(frames[0]) < protocol.MAX_PROGRESS_BYTES
        assert json.loads(frames[1])["error"]["type"] == "AzureConnectionError"
    else:
        assert len(frames) == 1
        assert "unsafe registration operation metadata" in frames[0]
    for secret in ("key-secret", passphrase, "csr-secret", "payload-secret", "bad\\nid"):
        assert secret not in output.getvalue()


@pytest.mark.parametrize("origin", ["parent", "provider"])
@pytest.mark.parametrize("deadline_timeout", [False, True])
def test_only_deadline_errors_are_enriched_and_exception_chains_are_preserved(mocker, origin, deadline_timeout):
    provider = _provider()
    kind = protocol.RegistrationTimeoutError if deadline_timeout else AzureConnectionError
    error = kind("Offline connection failure")
    cause = OSError("Original offline transport failure")
    error.__cause__ = cause
    if origin == "parent":
        # Isolate the translation boundary; real worker reaping is tested below.
        mocker.patch.object(registration.subprocess, "Popen")

        def fail_worker(_worker, _request, communication, _deadline, _decode_response):
            communication["operation_id"] = "4.operation-01"
            raise error

        mocker.patch.object(registration, "_await_worker", side_effect=fail_worker)
        with pytest.raises(AzureConnectionError) as raised:
            registration.register_with_deadline(provider, {}, 5)
    else:
        client = mocker.patch.object(provider, "_get_client").return_value
        client.runtime_registration.register_device_and_issue_certificate.side_effect = error
        with pytest.raises(AzureConnectionError) as raised:
            provider._perform_registration({})
        client.runtime_registration.register_device_and_issue_certificate.assert_called_once()

    if deadline_timeout:
        assert type(raised.value) is AzureConnectionError
        assert raised.value.__cause__ is error
        if origin == "parent":
            _assert_followup(raised.value)
        else:
            assert "Operation ID is unknown" in str(raised.value)
    else:
        assert raised.value is error
        assert str(raised.value) == "Offline connection failure"
    assert error.__cause__ is cause


def test_parent_refuses_a_worker_from_another_extension(mocker):
    mocker.patch.object(worker, "__file__", "/unexpected/_registration_worker.py")
    popen = mocker.patch.object(subprocess, "Popen")
    with pytest.raises(CLIInternalError, match="unexpected worker location"):
        registration.register_with_deadline(_provider(), {}, 1)
    popen.assert_not_called()


def test_worker_source_remains_first_when_extension_dependency_path_is_added(mocker, tmp_path):
    import azure.cli.core.extension

    output = io.StringIO()
    mocker.patch.object(azure.cli.core.extension, "get_extension_path", return_value=str(tmp_path))
    mocker.patch.object(sys, "path", list(sys.path))
    mocker.patch.object(sys, "stdin", io.StringIO(json.dumps({
        "provider": {"device_symmetric_key": "key", "passphrase": None}, "body": {}, "deadline": 100,
    })))
    mocker.patch.object(sys, "stdout", output)
    mocker.patch.object(registration, "register_in_worker", return_value={})
    runpy.run_path(worker.__file__, run_name="__main__")
    assert sys.path[:2] == [str(Path(worker.__file__).resolve().parents[3]), str(tmp_path)]
    assert worker.decode_response(output.getvalue()) == {}


@pytest.mark.parametrize("diagnostics", [
    {"stage": "untrusted", "frames": []}, {"stage": "register", "frames": "untrusted"},
    {"stage": "register", "frames": [{"file": "dps/services/_registration.py", "line": 1}] * 9},
])
def test_worker_rejects_invalid_diagnostic_envelopes(diagnostics):
    value = {"version": 1, "ok": False, "error": {
        "type": "CLIInternalError", "message": "safe", "diagnostics": diagnostics,
    }}
    with pytest.raises(CLIInternalError, match="invalid response"):
        worker.decode_response(json.dumps(value))


def test_default_retry_after_ignores_other_headers():
    assert device._retry_after_seconds({"other": "secret"}) == 2
    assert device._retry_after_seconds({"other": "secret", "retry-after": "3"}) == 3


@pytest.mark.parametrize("with_csr", [False, True])
@pytest.mark.parametrize("expiry", ["post-response", "retry-after", "poll-retry", "post-poll", "pre-acceptance"])
def test_sdk_http_deadlines_retain_acceptance_before_post_response_check(mocker, with_csr, expiry):
    """Run the generated SDK and requests pipeline, not a mocked operation method."""
    clock = [10.0]
    mocker.patch.object(registration, "monotonic", side_effect=lambda: clock[0])
    mocker.patch.object(device, "monotonic", side_effect=lambda: clock[0])
    mocker.patch.object(registration, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay))
    blocked = mocker.Mock(side_effect=AssertionError("Network access is forbidden"))
    mocker.patch.object(socket.socket, "connect", blocked)
    mocker.patch.object(socket, "getaddrinfo", blocked)
    mocker.patch.object(requests.adapters.HTTPAdapter, "send", blocked)
    sent = []
    accepted = []
    provider = _provider()
    provider._accepted_callback = accepted.append
    body = {"registrationId": "device-01", "payload": {"private": "opaque-payload-secret"}}
    if with_csr:
        _, csr = generate_csr(("device-01",))
        body["csr"] = base64.b64encode(csr.public_bytes(Encoding.DER)).decode()

    def send(_session, prepared, **kwargs):
        sent.append(prepared)
        assert kwargs["allow_redirects"] is False
        assert sum(kwargs["timeout"]) <= 2
        response = requests.Response()
        response.request, response.url = prepared, prepared.url
        response.status_code = 202 if len(sent) == 1 else 200
        response.headers = {"Content-Type": "application/json", "Retry-After": "0"}
        result = {"operationId": "4.operation-01", "status": "assigning"}
        if expiry == "pre-acceptance":
            response.status_code = 429
        if expiry in ("retry-after", "pre-acceptance"):
            response.headers["Retry-After"] = "2"
        if expiry == "post-response" or (expiry == "post-poll" and len(sent) == 2):
            clock[0] = 12
        if expiry == "poll-retry" and len(sent) == 2:
            response.status_code = 503
            response.headers["Retry-After"] = "2"
        response._content = json.dumps(result).encode()
        response.raw = io.BytesIO(response.content)
        return response

    mocker.patch.object(requests.Session, "send", send)
    try:
        with pytest.raises(AzureConnectionError) as raised:
            provider._perform_registration(body, deadline=12)
    finally:
        provider.client.close()
    if expiry == "pre-acceptance":
        assert "Operation ID is unknown" in str(raised.value)
        assert not accepted
    else:
        _assert_followup(raised.value)
        assert accepted == ["4.operation-01"]
    assert json.loads(sent[0].body) == body
    assert [request.method for request in sent] == (
        ["PUT", "GET"] if expiry in ("poll-retry", "post-poll") else ["PUT"]
    )
    assert all("api-version=2026-11-02-preview" in request.url for request in sent)
    assert "opaque-payload-secret" not in str(raised.value)
    blocked.assert_not_called()


@pytest.fixture
def start_peer(mocker, tmp_path):
    """Redirect the executable only; exercise real pipes, deadline and reaping."""
    original = subprocess.Popen
    children = []
    before = set(threading.enumerate())

    with ExitStack() as processes:
        def install(driver):
            def start(args, **kwargs):
                assert args == [sys.executable, "-I", str(Path(worker.__file__).resolve())]
                config = tmp_path / f"private-cli-{len(children)}"
                config.mkdir(mode=0o700)
                env = dict(os.environ, AZURE_CONFIG_DIR=str(config), AZURE_TEST_RUN_LIVE="False")
                # Test drivers import SDK dependencies before the production
                # worker bootstrap. ADO can supply those only through the
                # parent's runtime sys.path; the empty child CLI profile cannot
                # discover that extension. Keep checkout source first.
                runtime_paths = list(dict.fromkeys([
                    str(Path(worker.__file__).resolve().parents[3]),
                    *(os.path.abspath(path) for path in sys.path),
                ]))
                child_driver = f"import sys\nsys.path[:0] = {runtime_paths!r}\n{driver}"
                child = processes.enter_context(original([sys.executable, "-I", "-c", child_driver], env=env, **kwargs))
                children.append(child)
                return child

            mocker.patch.object(registration.subprocess, "Popen", start)
            return children

        yield install
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
            assert child.stdin.closed and child.stdout.closed and child.stderr.closed
    assert not [
        thread for thread in threading.enumerate()
        if thread not in before and thread.name.startswith("iot-dps-registration")
    ]


@pytest.mark.parametrize("mode", [
    "success-fragmented", "partial-progress", "progress-hang", "stderr-flood",
    "oversized", "changed-id", "eof", "ignored-terminate", "closed-stdin",
])
def test_real_protocol_pipes_reap_all_threads_and_keep_only_complete_progress(start_peer, mode):
    if mode == "ignored-terminate" and os.name == "nt":
        pytest.skip("Windows TerminateProcess cannot be ignored by a signal handler")
    driver = (
        "import os, sys, json, time, signal\n"
        "assert os.environ['AZURE_TEST_RUN_LIVE'] == 'False'\n"
        "assert not os.listdir(os.environ['AZURE_CONFIG_DIR'])\n"
    )
    driver += "sys.stdin.close()\n" if mode == "closed-stdin" else "json.load(sys.stdin)\n"
    if mode == "ignored-terminate":
        driver += "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    if mode == "stderr-flood":
        driver += "sys.stderr.write('private-stderr-secret' * 100000); sys.stderr.flush()\n"
    if mode == "partial-progress":
        driver += f"sys.stdout.buffer.write({ACCEPTED[:-1]!r}); sys.stdout.flush()\ntime.sleep(60)\n"
    else:
        driver += (
            f"sys.stdout.buffer.write({ACCEPTED[:12]!r}); sys.stdout.flush()\n"
            "time.sleep(.01)\n"
            f"sys.stdout.buffer.write({ACCEPTED[12:]!r}); sys.stdout.flush()\n"
        )
        if mode in ("success-fragmented", "closed-stdin"):
            driver += f"sys.stdout.buffer.write({FINAL!r}); sys.stdout.flush()\n"
        elif mode == "oversized":
            driver += f"sys.stdout.buffer.write(b'x' * {protocol.MAX_OUTPUT_BYTES + 1}); sys.stdout.flush()\n"
        elif mode == "changed-id":
            driver += f"sys.stdout.buffer.write({ACCEPTED.replace(b'4.operation-01', b'changed-id')!r}); sys.stdout.flush()\n"
        elif mode != "eof":
            driver += "time.sleep(60)\n"
    children = start_peer(driver)
    started = time.monotonic()
    if mode in ("success-fragmented", "closed-stdin"):
        body = {"payload": "x" * 2097152} if mode == "closed-stdin" else {}
        assert registration.register_with_deadline(_provider(), body, 5) == {"status": "assigned"}
    elif mode in ("oversized", "changed-id", "eof"):
        with pytest.raises(CLIInternalError) as raised:
            registration.register_with_deadline(_provider(), {}, 5)
        assert "private-stderr-secret" not in str(raised.value)
    else:
        with pytest.raises(AzureConnectionError) as raised:
            registration.register_with_deadline(_provider(), {}, .6)
        if mode == "partial-progress":
            assert "Operation ID is unknown" in str(raised.value)
        else:
            _assert_followup(raised.value)
    assert time.monotonic() - started < 5
    assert children[0].poll() is not None


@pytest.mark.parametrize("with_csr", [False, True])
@pytest.mark.parametrize("mode", ["success", "retry-after", "blocked-poll", "post-response"])
@pytest.mark.parametrize("dependency_layout", ["default", "parent-only"])
def test_real_worker_sdk_acceptance_and_deadline_with_in_memory_http(
    start_peer, monkeypatch, tmp_path, with_csr, mode, dependency_layout,
):
    # Import and source guards, SDK serialization/signing, worker frames and
    # process termination are real. Only the HTTP boundary is in memory.
    dependency_path = None
    if dependency_layout == "parent-only":
        import msrestazure

        dependency_path = str(tmp_path / "parent-only-runtime")
        shutil.copytree(Path(msrestazure.__file__).parent, Path(dependency_path) / "msrestazure")
        monkeypatch.syspath_prepend(dependency_path)

    driver = f"""
import os, sys, socket, io, json, time, runpy, importlib.machinery
assert os.environ["AZURE_TEST_RUN_LIVE"] == "False"
assert not os.listdir(os.environ["AZURE_CONFIG_DIR"])
assert sys.path[0] == {str(Path(worker.__file__).resolve().parents[3])!r}
parent_dependency = {dependency_path!r}
if parent_dependency:
    class ParentOnlyDependency:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "msrestazure":
                if parent_dependency not in sys.path:
                    raise ModuleNotFoundError("No module named 'msrestazure'", name=fullname)
                return importlib.machinery.PathFinder.find_spec(fullname, [parent_dependency])
            return None
    sys.meta_path.insert(0, ParentOnlyDependency())
def blocked(*args, **kwargs):
    raise AssertionError("Network access is forbidden")
socket.socket.connect = socket.socket.connect_ex = blocked
socket.getaddrinfo = socket.create_connection = blocked
import requests
requests.adapters.HTTPAdapter.send = blocked
from azext_iot.dps.services import _registration
calls = []
def send(session, prepared, **kwargs):
    if parent_dependency:
        assert os.path.dirname(sys.modules["msrestazure"].__file__) == os.path.join(parent_dependency, "msrestazure")
    calls.append(prepared.method)
    assert prepared.url.startswith("https://dps.invalid/")
    assert "api-version=2026-11-02-preview" in prepared.url
    assert prepared.headers["Authorization"].startswith("SharedAccessSignature ")
    if prepared.method == "PUT":
        assert calls == ["PUT"]
        assert ("csr" in json.loads(prepared.body)) is {with_csr!r}
    else:
        assert calls == ["PUT", "GET"]
        assert "/operations/4.operation-01" in prepared.url
        if {mode!r} == "blocked-poll":
            time.sleep(60)
    response = requests.Response()
    response.status_code = 202 if prepared.method == "PUT" else 200
    response.headers = {{"Content-Type": "application/json", "Retry-After": "0"}}
    if {mode!r} == "retry-after":
        response.headers["Retry-After"] = "60"
    if {mode!r} == "post-response":
        _registration.monotonic = lambda: float("inf")
    response._content = json.dumps({{"operationId": "4.operation-01",
        "status": "assigning" if response.status_code == 202 else "assigned",
        "registrationState": {{"deviceId": "device-01"}}}}).encode()
    response.raw = io.BytesIO(response.content)
    response.request, response.url = prepared, prepared.url
    return response
requests.Session.send = send
runpy.run_path({worker.__file__!r}, run_name="__main__")
"""
    children = start_peer(driver)
    body = {"registrationId": "device-01", "payload": {"private": "payload-secret"}}
    if with_csr:
        _, csr = generate_csr(("device-01",))
        body["csr"] = base64.b64encode(csr.public_bytes(Encoding.DER)).decode()
    started = time.monotonic()
    if mode == "success":
        result = registration.register_with_deadline(_provider(), body, 5)
        assert result["status"] == "assigned"
        assert result["registrationState"]["registryDeviceExternalId"] == "device-01"
    else:
        with pytest.raises(AzureConnectionError) as raised:
            registration.register_with_deadline(_provider(), body, 3)
        _assert_followup(raised.value)
        assert "payload-secret" not in str(raised.value)
    assert time.monotonic() - started < 6
    assert children[0].poll() is not None


def test_cancellation_reaps_real_worker_and_blocked_writer(start_peer, mocker):
    start_peer("import time\ntime.sleep(60)\n")
    mocker.patch.object(registration, "_remaining", side_effect=[1, KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        registration.register_with_deadline(_provider(), {"payload": "x" * 2097152}, 5)


def test_deadline_race_reads_progress_before_formatting_error(start_peer, mocker):
    driver = f"""
import json, sys, time
json.load(sys.stdin)
sys.stdout.buffer.write({ACCEPTED!r})
sys.stdout.flush()
time.sleep(60)
"""
    start_peer(driver)
    gate = threading.Event()
    original_read = registration.read_frames
    original_stop = registration._stop_worker

    def delayed_read(stream, communication):
        assert gate.wait(5)
        original_read(stream, communication)

    def stop(child, communicator):
        gate.set()
        original_stop(child, communicator)

    mocker.patch.object(registration, "read_frames", delayed_read)
    mocker.patch.object(registration, "_stop_worker", stop)
    with pytest.raises(AzureConnectionError) as raised:
        registration.register_with_deadline(_provider(), {}, .6)
    _assert_followup(raised.value)
