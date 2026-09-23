# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline proofs for the account-profile race mitigation and its workflow lifetime."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
from threading import Event, Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
import responses
import yaml

from azure.cli.core import _profile, cloud
from azure.cli.core._session import Session
from azure.cli.core.auth import identity, msal_credentials, persistence
from azure.cli.core.azclierror import AuthenticationError
from knack.config import CLIConfig

from azext_iot.tests import _refresh_ci_auth as auth


ROOT = Path(__file__).resolve().parents[2]
CLIENT = "a1111111-1111-1111-1111-111111111111"
TENANT = "b2222222-2222-2222-2222-222222222222"
SUBSCRIPTION = "c3333333-3333-3333-3333-333333333333"
OIDC_URL = "https://oidc.example.test/token?job=offline"
LIFETIME_START = 1800000000
ARM_SCOPE = "https://management.core.windows.net//.default"


@pytest.fixture
def configured(tmp_path, monkeypatch):
    config = tmp_path / "azure"
    config.mkdir()
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(config))
    monkeypatch.setenv("AZURE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("AZURE_TENANT_ID", TENANT)
    monkeypatch.setenv("TEST_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_URL", OIDC_URL)
    monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "offline-request-secret")
    monkeypatch.setattr(cloud, "CLOUD_CONFIG_FILE", str(config / "clouds.config"))
    for name in ("_msal_token_cache", "_msal_http_cache", "_service_principal_store_instance"):
        monkeypatch.setattr(identity.Identity, name, None)
    (config / "config").write_text(
        "[cloud]\nname=AzureCloud\n[core]\nuse_msal_http_cache=false\n"
        "instance_discovery=false\nencrypt_token_cache=false\n", encoding="utf-8",
    )
    account = {
        "id": SUBSCRIPTION, "name": "offline", "tenantId": TENANT, "isDefault": True,
        "environmentName": "AzureCloud", "user": {"type": "servicePrincipal", "name": CLIENT},
    }
    path = config / "azureProfile.json"
    path.write_text(json.dumps({"subscriptions": [account]}), encoding="utf-8-sig")
    return path


@pytest.fixture
def mocked_login(mocker):
    # The helper must never enter subscription discovery, session persistence, or
    # CLI command invocation, including on malformed-profile/error paths.
    mocker.patch.object(_profile.Profile, "login", side_effect=AssertionError("Subscription discovery is forbidden"))
    mocker.patch.object(Session, "save", side_effect=AssertionError("Account/session writes are forbidden"))
    login = mocker.patch.object(_profile, "_create_identity_instance")
    login.return_value.tenant_id = TENANT
    login.return_value._msal_app_kwargs = {"token_cache": "offline-cache"}
    credential = mocker.patch.object(msal_credentials, "ServicePrincipalCredential")
    response = Mock(status_code=200)
    response.json.return_value = {"value": "offline-assertion"}
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    get = mocker.patch.object(auth.requests, "get", return_value=response)
    return login, get, response, credential


@pytest.mark.parametrize("cloud_name,authority,resource", [
    ("AzureCloud", "https://login.microsoftonline.com", "https://management.core.windows.net/"),
    ("AzureUSGovernment", "https://login.microsoftonline.us", "https://management.core.usgovcloudapi.net/"),
])
@pytest.mark.parametrize("upper_environment", [False, True])
def test_refresh_uses_explicit_identity_active_cloud_scope_and_environment_config(
    configured, mocked_login, monkeypatch, cloud_name, authority, resource, upper_environment
):
    login, get, _, credential = mocked_login
    if upper_environment:
        for name in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "TEST_SUBSCRIPTION_ID"):
            monkeypatch.setenv(name, os.environ[name].upper())
    data = json.loads(configured.read_text(encoding="utf-8-sig"))
    data["subscriptions"][0]["environmentName"] = cloud_name
    configured.write_text(json.dumps(data), encoding="utf-8-sig")
    config = configured.parent / "config"
    config.write_text(config.read_text().replace("AzureCloud", cloud_name))
    before = configured.read_bytes()
    stat = configured.stat()
    auth.refresh()
    ctx = login.call_args.args[0]
    assert ctx.config.config_dir == str(configured.parent)
    assert ctx.config.getboolean("core", "encrypt_token_cache") is False
    login.assert_called_once_with(ctx, authority, tenant_id=TENANT)
    credential.assert_called_once_with(
        CLIENT, {"client_assertion": "offline-assertion"}, timeout=(10, 30), token_cache="offline-cache",
    )
    credential.return_value.acquire_token.assert_called_once_with([resource + "/.default"])
    login.return_value._service_principal_store.save_entry.assert_called_once_with(  # pylint: disable=protected-access
        {"client_id": CLIENT, "tenant": TENANT, "client_assertion": "offline-assertion"},
    )
    get.assert_called_once_with(
        OIDC_URL, params={"audience": "api://AzureADTokenExchange"},
        headers={"Authorization": "bearer offline-request-secret"},
        timeout=(10, 30), allow_redirects=False,
    )
    assert configured.read_bytes() == before
    assert configured.stat().st_mtime_ns == stat.st_mtime_ns


@pytest.mark.parametrize("defect", [
    "subscription", "tenant", "client", "user-type", "no-default", "duplicate-default",
    "wrong-cloud", "empty-accounts", "malformed", "missing-profile",
    "missing-explicit", "blank-explicit", "missing-user", "missing-id",
])
def test_bad_current_account_fails_before_request_without_repair(configured, mocked_login, monkeypatch, defect):
    login, get, _, _ = mocked_login
    profile = json.loads(configured.read_text(encoding="utf-8-sig"))
    account = profile["subscriptions"][0]
    if defect in ("subscription", "tenant"):
        account[{"subscription": "id", "tenant": "tenantId"}[defect]] = "other"
    elif defect in ("client", "user-type"):
        account["user"][{"client": "name", "user-type": "type"}[defect]] = "other"
    elif defect == "no-default":
        account["isDefault"] = False
    elif defect == "duplicate-default":
        profile["subscriptions"].append(account.copy())
    elif defect == "wrong-cloud":
        account["environmentName"] = "AzureUSGovernment"
    elif defect == "empty-accounts":
        profile["subscriptions"] = []
    elif defect == "missing-user":
        account.pop("user")
    elif defect == "missing-id":
        account.pop("id")
    elif defect == "missing-explicit":
        monkeypatch.delenv("TEST_SUBSCRIPTION_ID")
    elif defect == "blank-explicit":
        monkeypatch.setenv("AZURE_CLIENT_ID", " ")
    configured.write_text(json.dumps(profile) if defect != "malformed" else "{broken", encoding="utf-8-sig")
    before = configured.read_bytes()
    if defect == "missing-profile":
        configured.unlink()
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        auth.refresh()
    login.assert_not_called()
    get.assert_not_called()
    if defect == "missing-profile":
        assert not configured.exists()
    else:
        assert configured.read_bytes() == before


@pytest.mark.parametrize("status,payload,error", [
    (403, {"value": "must-not-use"}, RuntimeError),
    (302, {"value": "must-not-follow"}, RuntimeError),
    (200, {}, KeyError),
    (200, {"value": ""}, ValueError),
    (200, {"value": None}, ValueError),
    (200, {"value": 1}, ValueError),
])
def test_oidc_failures_cannot_reuse_old_credentials(configured, mocked_login, status, payload, error, capsys):
    login, _, response, _ = mocked_login
    response.status_code = status
    response.json.return_value = payload
    before = configured.read_bytes()
    with pytest.raises(error):
        auth.refresh()
    login.assert_not_called()
    assert configured.read_bytes() == before
    assert "refreshed" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["request", "json", "construct", "login", "persist", "profile-write"])
def test_refresh_exceptions_propagate_without_success(configured, mocked_login, failure, capsys):
    login, get, response, credential = mocked_login
    if failure == "request":
        get.side_effect = requests.Timeout("sensitive token URL")
    elif failure == "json":
        response.json.side_effect = ValueError("sensitive response")
    elif failure == "construct":
        credential.side_effect = requests.Timeout("sensitive discovery URL")
    elif failure == "login":
        credential.return_value.acquire_token.side_effect = requests.Timeout("sensitive assertion")
    elif failure == "persist":
        login.return_value._service_principal_store.save_entry.side_effect = OSError("offline cache write failed")
    else:
        credential.return_value.acquire_token.side_effect = lambda *_: configured.write_text("{}")
    with pytest.raises((requests.Timeout, ValueError, RuntimeError, OSError)):
        auth.refresh()
    if failure in ("request", "json", "construct", "login"):
        login.return_value._service_principal_store.save_entry.assert_not_called()  # pylint: disable=protected-access
    assert "refreshed" not in capsys.readouterr().out


def _local_http_transport(port):
    """Route only test HTTP destinations to loopback; retain Requests' real I/O."""
    original = requests.adapters.HTTPAdapter.send
    timeouts = []

    def send(adapter, request, **kwargs):
        parts = urlsplit(request.url)
        assert parts.hostname in ("oidc.example.test", "authority.example.test", "login.microsoftonline.com")
        timeouts.append(kwargs["timeout"])
        request.url = f"http://127.0.0.1:{port}{parts.path}" + ("?" + parts.query if parts.query else "")
        kwargs["proxies"] = {}
        return original(adapter, request, **kwargs)

    return send, timeouts


@pytest.fixture
def auth_http(configured, monkeypatch):
    (configured.parent / "clouds.config").write_text(
        "[AzureCloud]\nendpoint_active_directory=https://authority.example.test\n", encoding="utf-8",
    )
    config = configured.parent / "config"
    config.write_text(config.read_text().replace("instance_discovery=false", "instance_discovery=true"))
    state = SimpleNamespace(block=None, entered=Event(), release=Event(), stages=[])
    authority = f"https://authority.example.test/{TENANT}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):  # pylint: disable=invalid-name
            if self.path.startswith("/token?"):
                stage, payload = "oidc", {"value": "offline-http-assertion"}
            elif "/discovery/instance" in self.path:
                stage, payload = "instance", {
                    "tenant_discovery_endpoint": authority + "/v2.0/.well-known/openid-configuration",
                    "metadata": [{"preferred_network": "authority.example.test",
                                  "preferred_cache": "authority.example.test", "aliases": ["authority.example.test"]}],
                }
            else:
                assert self.path.endswith("/.well-known/openid-configuration")
                stage, payload = "discovery", {
                    "authorization_endpoint": authority + "/oauth2/v2.0/authorize",
                    "token_endpoint": authority + "/oauth2/v2.0/token",
                }
            self.respond(stage, payload)

        def do_POST(self):  # pylint: disable=invalid-name
            self.rfile.read(int(self.headers["Content-Length"]))
            self.respond("token", {"access_token": "offline-http-access", "expires_in": 3600, "token_type": "Bearer"})

        def respond(self, stage, payload):
            state.stages.append(stage)
            if stage == state.block:
                state.entered.set()
                state.release.wait()
                return
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = False
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    state.port = server.server_address[1]
    transport, state.timeouts = _local_http_transport(state.port)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", transport)
    monkeypatch.setattr(auth, "HTTP_TIMEOUT", (0.2, 0.2))
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("stage", [None, "oidc", "instance", "discovery", "token"])
def test_real_requests_bound_oidc_and_every_msal_http_stage(configured, auth_http, stage):
    before = configured.read_bytes()
    auth_http.block = stage
    started = time.monotonic()
    if stage:
        with pytest.raises(requests.RequestException):
            auth.refresh()
        assert auth_http.entered.is_set()
        assert not (configured.parent / "service_principal_entries.json").exists()
    else:
        auth.refresh()
        assert set(auth_http.stages) == {"oidc", "instance", "discovery", "token"}
        assert (configured.parent / "service_principal_entries.json").exists()
    assert time.monotonic() - started < 5
    assert auth_http.timeouts and set(auth_http.timeouts) == {(0.2, 0.2)}
    assert configured.read_bytes() == before


def _bounded_http_process(port, pause_cache=None):
    """Real subprocess entrypoint with fast intervals and controlled local HTTP."""
    transport, _ = _local_http_transport(port)
    directory = Path(os.environ["AZURE_CONFIG_DIR"])
    original_save = persistence.FilePersistence.save

    def save(cache, content):
        if Path(cache.get_location()).name != pause_cache:
            return original_save(cache, content)
        # Stop in the middle of the write while CLI's existing cache lock is held.
        with open(cache.get_location(), "w", encoding="utf-8") as stream:
            split = len(content) // 2
            stream.write(content[:split])
            stream.flush()
            (directory / "writing").touch()
            while not (directory / "release-write").exists():
                time.sleep(0.01)
            stream.write(content[split:])
        (directory / "write-finished").touch()
        return None

    class FastEvent(Event):
        def wait(self, timeout=None):
            return super().wait(0.01 if timeout == 240 else timeout)

    with patch.object(requests.adapters.HTTPAdapter, "send", transport), \
            patch.object(auth, "HTTP_TIMEOUT", (0.2, 0.2)), patch.object(auth, "Event", FastEvent), \
            patch.object(persistence.FilePersistence, "save", save):
        sys.argv = ["refresh", "--loop"]
        auth.main()


@pytest.mark.skipif(sys.platform != "linux", reason="Ubuntu workflow SIGTERM behavior")
@pytest.mark.parametrize("stage", ["instance", "discovery", "token"])
def test_sigterm_during_real_msal_http_stall_exits_with_failure(configured, auth_http, stage):
    before = configured.read_bytes()
    auth_http.block = stage
    code = (
        "from azext_iot.tests.test_refresh_ci_auth_unit import _bounded_http_process\n"
        f"_bounded_http_process({auth_http.port})"
    )
    with subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=os.environ.copy(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        try:
            assert auth_http.entered.wait(10)
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode != 0
            assert "::error::OIDC CLI credential refresh failed" in stderr
            assert "refreshed" not in stdout
            assert "offline-http" not in stdout + stderr
            assert configured.read_bytes() == before
            assert not (configured.parent / "service_principal_entries.json").exists()
        finally:
            auth_http.release.set()
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.skipif(sys.platform != "linux", reason="Ubuntu workflow SIGTERM behavior")
@pytest.mark.parametrize("cache_name", ["msal_token_cache.json", "service_principal_entries.json"])
def test_sigterm_never_interrupts_an_inflight_cli_cache_write(configured, auth_http, cache_name):
    before = configured.read_bytes()
    directory = configured.parent
    code = (
        "from azext_iot.tests.test_refresh_ci_auth_unit import _bounded_http_process\n"
        f"_bounded_http_process({auth_http.port}, {cache_name!r})"
    )
    with subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=os.environ.copy(),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        try:
            deadline = time.monotonic() + 10
            while not (directory / "writing").exists():
                assert process.poll() is None
                assert time.monotonic() < deadline
                time.sleep(0.01)
            with pytest.raises(json.JSONDecodeError):
                json.loads((directory / cache_name).read_text())
            process.terminate()
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=0.2)
            (directory / "release-write").touch()
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, stderr
            assert "refreshed" in stdout
            assert (directory / "write-finished").exists()
            assert json.loads((directory / cache_name).read_text())
            assert configured.read_bytes() == before
        finally:
            (directory / "release-write").touch()
            if process.poll() is None:
                process.wait(timeout=5)


def test_real_cli_cache_renewal_and_fresh_account_reads_share_config_without_profile_writes(configured, mocker):
    """Exercise actual Identity/MSAL/SecretStore, mocking only remote HTTP."""
    before, stat = configured.read_bytes(), configured.stat()
    lock = mocker.spy(persistence, "CrossPlatLock")
    mocker.patch.object(Session, "save", side_effect=AssertionError("Fresh account read tried to reset the profile"))
    stop = Event()
    reading = Event()

    def fresh_reads():
        count = 0
        while not stop.is_set():
            session = Session()
            session.load(str(configured))
            assert session["subscriptions"][0]["id"] == SUBSCRIPTION
            assert configured.read_bytes() == before
            count += 1
            reading.set()
        return count

    authority = f"https://login.microsoftonline.com/{TENANT}"
    token_url = authority + "/oauth2/v2.0/token"
    with ThreadPoolExecutor(max_workers=1) as executor, responses.RequestsMock() as remote:
        reader = executor.submit(fresh_reads)
        try:
            assert reading.wait(5)
            oidc_url = OIDC_URL + "&audience=api://AzureADTokenExchange"
            remote.add(responses.GET, oidc_url, json={"value": "offline-assertion-1"})
            remote.add(responses.GET, oidc_url, json={"value": "offline-assertion-2"})
            remote.add(responses.GET, authority + "/v2.0/.well-known/openid-configuration", json={
                "authorization_endpoint": authority + "/oauth2/v2.0/authorize",
                "token_endpoint": token_url,
            })
            for number in (1, 2, 3):
                # An expiring token makes MSAL acquire a fresh token on each pass.
                remote.add(responses.POST, token_url, json={
                    "access_token": f"offline-access-{number}", "expires_in": 60, "token_type": "Bearer",
                })
            auth.refresh()
            auth.refresh()
            entries = json.loads((configured.parent / "service_principal_entries.json").read_text())
            assert entries == [{"client_id": CLIENT, "tenant": TENANT, "client_assertion": "offline-assertion-2"}]
            tokens = json.loads((configured.parent / "msal_token_cache.json").read_text())["AccessToken"]
            assert {token["secret"] for token in tokens.values()} == {"offline-access-2"}
            assert lock.call_count == 2

            # Simulate a fresh CLI consumer rather than reusing the writer's objects.
            identity.Identity._service_principal_store_instance = None  # pylint: disable=protected-access
            identity.Identity._msal_token_cache = None  # pylint: disable=protected-access
            consumer = identity.Identity("https://login.microsoftonline.com", tenant_id=TENANT, use_msal_http_cache=False)
            credential = consumer.get_service_principal_credential(CLIENT)
            assert credential.acquire_token(["https://iothubs.azure.net/.default"])["access_token"] == "offline-access-3"
            posts = [parse_qs(call.request.body) for call in remote.calls if call.request.method == "POST"]
            assert [post["client_assertion"] for post in posts] == [
                ["offline-assertion-1"], ["offline-assertion-2"], ["offline-assertion-2"],
            ]
            assert all(post["client_id"] == [CLIENT] for post in posts)
            assert posts[0]["scope"] == ["https://management.core.windows.net//.default"]
        finally:
            stop.set()
        assert reader.result(timeout=5) > 0
    assert configured.read_bytes() == before
    assert configured.stat().st_mtime_ns == stat.st_mtime_ns


def _lifetime_profile():
    config_dir = os.environ["AZURE_CONFIG_DIR"]
    ctx = SimpleNamespace(config=CLIConfig(config_dir=config_dir, config_env_var_prefix="AZURE"))
    ctx.cloud = cloud.get_cloud(ctx, "AzureCloud")
    account = json.loads((Path(config_dir) / "azureProfile.json").read_text(encoding="utf-8-sig"))
    return _profile.Profile(cli_ctx=ctx, storage=account)


def _lifetime_http(remote):
    authority = f"https://login.microsoftonline.com/{TENANT}"
    remote.add(responses.GET, authority + "/v2.0/.well-known/openid-configuration", json={
        "authorization_endpoint": authority + "/oauth2/v2.0/authorize",
        "token_endpoint": authority + "/oauth2/v2.0/token",
    })
    generation = 1 if time.time() == LIFETIME_START else 2
    remote.add(responses.GET, OIDC_URL + "&audience=api://AzureADTokenExchange",
               json={"value": f"offline-assertion-{generation}"})
    posts = []

    def token_endpoint(request):
        body = parse_qs(request.body)
        posts.append(body)
        assertion = body["client_assertion"][0]
        assert assertion in ("offline-assertion-1", "offline-assertion-2")
        if assertion == "offline-assertion-1" and time.time() >= LIFETIME_START + 600:
            payload = {"error": "invalid_client", "error_description": "offline assertion expired"}
            return 400, {"Content-Type": "application/json"}, json.dumps(payload)
        scope = body["scope"][0]
        return 200, {"Content-Type": "application/json"}, json.dumps({
            "access_token": f"offline-access-{scope}-{assertion[-1]}", "expires_in": 3600, "token_type": "Bearer",
        })

    remote.add_callback(responses.POST, authority + "/oauth2/v2.0/token", callback=token_endpoint)
    return posts


def _write_lifetime_refresh(mode):
    """Independent process: actual CLI caches, only remote HTTP/profile writes mocked."""
    with patch("time.time", return_value=LIFETIME_START + 7200), responses.RequestsMock(
        assert_all_requests_are_fired=False,
    ) as remote:
        posts = _lifetime_http(remote)
        if mode == "helper":
            auth.refresh()
        else:
            profile = _lifetime_profile()
            account = profile.get_subscription()
            # Exercise the old az-login authentication path, not its unrelated
            # subscription discovery or destructive ACCOUNT persistence.
            with patch.object(_profile.SubscriptionFinder, "find_using_specific_tenant", return_value=[object()]), \
                    patch.object(_profile.Profile, "_normalize_properties", return_value=[account]), \
                    patch.object(_profile.Profile, "_set_subscriptions") as save_account:
                profile.login(
                    interactive=False, username=CLIENT, tenant=TENANT, is_service_principal=True,
                    password=identity.ServicePrincipalAuth.build_credential(client_assertion="offline-assertion-2"),
                )
                save_account.assert_called_once()
        assert len(posts) == 1 and posts[0]["client_assertion"] == ["offline-assertion-2"]
        # Model filesystem mtime on the same deterministic clock as MSAL. No sleeps
        # or cache singleton resets in the already-running consumer are required.
        cache = Path(os.environ["AZURE_CONFIG_DIR"]) / "msal_token_cache.json"
        os.utime(cache, (time.time(), time.time()))


def _assert_lifetime_refresh(writer_mode):
    # pylint: disable=protected-access
    configured = Path(os.environ["AZURE_CONFIG_DIR"]) / "azureProfile.json"
    before, stat = configured.read_bytes(), configured.stat()
    clock = [LIFETIME_START]
    data_scope = "https://iothubs.azure.net/.default"
    storage_scope = "https://storage.azure.com/.default"
    with ExitStack() as patches, responses.RequestsMock() as remote:
        patches.enter_context(patch("time.time", side_effect=lambda: clock[0]))
        patches.enter_context(patch.object(Session, "save", side_effect=AssertionError("Lifetime proof must not write ACCOUNT")))
        posts = _lifetime_http(remote)
        auth.refresh()
        profile = _lifetime_profile()
        assert profile.get_subscription() == json.loads(before.decode("utf-8-sig"))["subscriptions"][0]
        retained_sdk, _, _ = profile.get_login_credentials()
        assert retained_sdk.get_token(data_scope).token == f"offline-access-{data_scope}-1"
        store = identity.Identity._service_principal_store_instance
        token_cache = identity.Identity._msal_token_cache
        load = patches.enter_context(patch.object(store._secret_store, "load", wraps=store._secret_store.load))
        assert store._entries[0]["client_assertion"] == "offline-assertion-1"

        # Expire both the assertion (10 min) and the consumer's tokens (60 min).
        # The writer is a real separate process sharing only the on-disk config.
        clock[0] += 7200
        code = (
            "from azext_iot.tests.test_refresh_ci_auth_unit import _write_lifetime_refresh\n"
            f"_write_lifetime_refresh({writer_mode!r})"
        )
        writer = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=os.environ.copy(),
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert writer.returncode == 0, writer.stdout + writer.stderr
        assert store._entries[0]["client_assertion"] == "offline-assertion-1"
        assert retained_sdk.get_token(ARM_SCOPE).token == f"offline-access-{ARM_SCOPE}-2"
        assert len(posts) == 2, "Retained SDK credential must read the renewed ARM token without a token POST"
        load.assert_not_called()

        # A retained credential captures its assertion, unlike its persisted token
        # cache. Neither the new helper nor old az login can replace that object.
        with pytest.raises(AuthenticationError, match="offline assertion expired"):
            retained_sdk.get_token(data_scope)
        assert posts[-1]["client_assertion"] == ["offline-assertion-1"]
        load.assert_not_called()

        # Embedded CLI/raw-token commands create credentials for each request.
        # The same existing Profile and singleton store must reload the new entry.
        token, _, _ = profile.get_raw_token(scopes=[data_scope])
        assert token[1] == f"offline-access-{data_scope}-2"
        assert load.call_count == 1
        new_sdk, _, _ = profile.get_login_credentials()
        assert new_sdk.get_token(storage_scope).token == f"offline-access-{storage_scope}-2"
        assert load.call_count == 2
        assert [post["client_assertion"] for post in posts[-2:]] == [
            ["offline-assertion-2"], ["offline-assertion-2"],
        ]
        assert identity.Identity._service_principal_store_instance is store
        assert identity.Identity._msal_token_cache is token_cache
    assert configured.read_bytes() == before
    assert configured.stat().st_mtime_ns == stat.st_mtime_ns


@pytest.mark.parametrize("writer_mode", ["helper", "old-profile-login"])
def test_long_lived_cli_store_reload_and_sdk_assertion_lifetime_match_old_login(configured, mocker, writer_mode):
    # Other in-process CLI tests can wrap Profile.get_subscription. Prove that an
    # unrelated user's account cannot replace the lifetime consumer's real SP.
    foreign_account = mocker.patch.object(_profile.Profile, "get_subscription", return_value={
        "id": "foreign", "tenantId": "offline", "user": {"name": "offline", "type": "user"},
    })
    before, stat = configured.read_bytes(), configured.stat()
    code = (
        "from azext_iot.tests.test_refresh_ci_auth_unit import _assert_lifetime_refresh\n"
        f"_assert_lifetime_refresh({writer_mode!r})"
    )
    consumer = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=os.environ.copy(),
        capture_output=True, text=True, timeout=45, check=False,
    )
    assert consumer.returncode == 0, consumer.stdout + consumer.stderr
    foreign_account.assert_not_called()
    assert configured.read_bytes() == before
    assert configured.stat().st_mtime_ns == stat.st_mtime_ns


@pytest.mark.parametrize("ready_file", [False, True])
def test_loop_renews_every_240_seconds_and_stops_gracefully(tmp_path, monkeypatch, mocker, ready_file):
    ready = tmp_path / "ready"
    monkeypatch.setattr(sys, "argv", ["refresh", "--loop"] + (["--ready-file", str(ready)] if ready_file else []))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    event = mocker.patch.object(auth, "Event").return_value
    event.wait.side_effect = [False, False, True]
    handlers = mocker.patch.object(auth.signal, "signal")
    handlers.side_effect = lambda *_: not ready.exists() or pytest.fail("Ready before handlers were installed")
    refresh = mocker.patch.object(auth, "refresh")
    auth.main()
    assert refresh.call_count == 2
    assert [call.args for call in event.wait.call_args_list] == [(240,), (240,), (240,)]
    assert [call.args[0] for call in handlers.call_args_list] == [signal.SIGTERM, signal.SIGINT]
    for call in handlers.call_args_list:
        call.args[1](signal.SIGTERM, None)
    assert event.set.call_count == 2
    assert logging.root.manager.disable == logging.CRITICAL
    assert sys.excepthook is auth.report_failure
    if ready_file:
        assert ready.read_text() == "ready\n"


def test_ready_file_requires_loop(tmp_path, monkeypatch):
    ready = tmp_path / "ready"
    monkeypatch.setattr(sys, "argv", ["refresh", "--ready-file", str(ready)])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    with pytest.raises(SystemExit) as error:
        auth.main()
    assert error.value.code == 2
    assert not ready.exists()


@pytest.mark.skipif(sys.platform != "linux", reason="Ubuntu workflow SIGTERM handshake")
def test_real_loop_can_stop_immediately_after_readiness_without_refresh(tmp_path):
    ready = tmp_path / "ready"
    with subprocess.Popen(
        [sys.executable, auth.__file__, "--loop", "--ready-file", str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as process:
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() or ready.stat().st_size == 0:
                assert process.poll() is None, "Refresher exited before readiness"
                assert time.monotonic() < deadline, "Refresher did not become ready"
                time.sleep(0.01)
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            assert process.returncode == 0, stderr
            assert not stdout and not stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_loop_failure_is_not_swallowed_or_retried(monkeypatch, mocker):
    monkeypatch.setattr(sys, "argv", ["refresh", "--loop"])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    mocker.patch.object(auth.signal, "signal")
    event = mocker.patch.object(auth, "Event").return_value
    event.wait.return_value = False
    refresh = mocker.patch.object(auth, "refresh", side_effect=RuntimeError("offline-failure"))
    with pytest.raises(RuntimeError):
        auth.main()
    refresh.assert_called_once_with()


def test_script_entrypoint_single_refresh_and_sanitized_failure(monkeypatch, mocker, capsys):
    monkeypatch.setattr(sys, "argv", ["refresh"])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    # run_path also covers the real __main__ guard without contacting Azure.
    with pytest.raises(KeyError):
        runpy.run_path(str(Path(auth.__file__)), run_name="__main__")
    auth.report_failure(requests.Timeout, requests.Timeout("secret assertion / token URL"), None)
    captured = capsys.readouterr()
    assert "Timeout" in captured.err and "::error::" in captured.err
    assert "secret assertion" not in captured.err
    refresh = mocker.patch.object(auth, "refresh")
    auth.main()
    refresh.assert_called_once_with()


def test_real_process_failure_is_nonzero_and_never_prints_request_or_token_material(configured):
    proof = (
        "import logging, requests, runpy, sys\n"
        "def fail(*args, **kwargs):\n"
        "    logging.critical('offline-sensitive-http-log')\n"
        "    raise requests.Timeout('offline-sensitive-request-token-and-assertion')\n"
        "requests.get = fail\n"
        "script = sys.argv[1]\nsys.argv = [script]\n"
        "runpy.run_path(script, run_name='__main__')\n"
    )
    # Run the actual __main__/excepthook boundary, not pytest's exception renderer.
    result = subprocess.run(
        [sys.executable, "-c", proof, auth.__file__], cwd=configured.parent, env=os.environ.copy(),
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode != 0
    assert "Timeout" in result.stderr and "::error::" in result.stderr
    assert "offline-sensitive" not in result.stdout + result.stderr
    assert "offline-request-secret" not in result.stdout + result.stderr
    assert OIDC_URL not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    assert "refreshed" not in result.stdout


def workflow_step():
    workflow = yaml.safe_load((ROOT / ".github/workflows/int_test.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["int-test"]["steps"]
    return next(step for step in steps if step.get("id") == "run_tests")


def test_workflow_refresh_is_bound_to_test_lifetime_and_has_no_profile_writing_commands():
    step = workflow_step()
    script = step["run"]
    assert step["env"]["AZURE_CLIENT_ID"] == "${{ secrets.AZURE_CLIENT_ID }}"
    assert step["env"]["AZURE_TENANT_ID"] == "${{ secrets.AZURE_TENANT_ID }}"
    assert 'auth_python=".tox/$TEST_TOX_ENV/bin/python"' in script
    assert 'auth_python=".tox/DPS-phases/bin/python"' in script
    assert 'trap stop_auth EXIT' in script
    assert 'wait "$auth_pid"' in script
    assert script.index('"$auth_python" azext_iot/tests/_refresh_ci_auth.py\n') < script.index("run_service()")
    for forbidden in ("az login", "az account set", "curl ", "--federated-token", "AZURE_CONFIG_DIR="):
        assert forbidden not in script


@pytest.mark.skipif(sys.platform != "linux", reason="Ubuntu workflow Bash supervision")
@pytest.mark.parametrize("service", ["DPS", "HubControl", "HubData", "ADR", "ADU"])
@pytest.mark.parametrize("failure", [
    "none", "preflight", "startup", "startup-timeout", "refresh", "early-success",
    "shutdown-failure", "shutdown-timeout", "tests",
])
def test_workflow_supervision_never_masks_auth_or_test_failures(tmp_path, service, failure):
    """Execute the actual step shell, replacing only external Python/tox commands."""
    step = workflow_step()
    # A small fake interpreter records non-secret argv and models a cooperative
    # daemon. No actual test controller or Azure CLI command can be invoked.
    executable = tmp_path / "runtime"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, sys, time\nfrom pathlib import Path\n"
        "mode = os.environ['OFFLINE_FAILURE']\n"
        "if '_refresh_ci_auth.py' not in sys.argv[1]:\n"
        "    assert Path('ready').exists(), 'Tests started before the refresher was ready'\n"
        "    if mode == 'shutdown-timeout':\n"
        "        while not Path('test-cache.json').exists(): time.sleep(.01)\n"
        "    Path('tests-started').touch()\n"
        "    if mode in ('refresh', 'early-success'):\n"
        "        while not Path('failed').exists(): time.sleep(.01)\n"
        "        time.sleep(.1)\n"
        "    print('offline tests completed')\n"
        "    sys.exit(7 if mode == 'tests' else 0)\n"
        "if '--loop' not in sys.argv:\n"
        "    sys.exit(1 if mode == 'preflight' else 0)\n"
        "if mode == 'startup': sys.exit(1)\n"
        "time.sleep(.2)\n"
        "stopped = False\n"
        "def stop(*args):\n"
        "    global stopped\n"
        "    stopped = True\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "Path('ready').touch()\n"
        "if mode != 'startup-timeout':\n"
        "    Path(sys.argv[sys.argv.index('--ready-file') + 1]).write_text('ready\\n')\n"
        "if mode == 'shutdown-timeout':\n"
        "    Path('test-cache.json').write_text('{')\n"
        "    while not Path('release-cache').exists(): time.sleep(.01)\n"
        "    Path('test-cache.json').write_text('{\"complete\": true}')\n"
        "if mode in ('refresh', 'early-success'):\n"
        "    while not Path('tests-started').exists(): time.sleep(.01)\n"
        "    Path('failed').touch()\n"
        "    sys.exit(1 if mode == 'refresh' else 0)\n"
        "while not stopped: time.sleep(.01)\n"
        "Path('stopped').touch()\n"
        "sys.exit(1 if mode == 'shutdown-failure' else 0)\n", encoding="utf-8",
    )
    executable.chmod(0o755)
    runtime = tmp_path / ".tox" / ("DPS-phases" if service == "DPS" else service + "-int") / "bin"
    runtime.mkdir(parents=True)
    (runtime / "python").symlink_to(executable)
    (tmp_path / "tox").symlink_to(executable)
    env = dict(
        os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"], OFFLINE_FAILURE=failure,
        TEST_SERVICE=service, TEST_TOX_ENV=service + "-int", TEST_SUBSCRIPTION_ID=SUBSCRIPTION,
        RESOURCE_GROUP="offline-rg", TEST_REGION="offline",
    )
    try:
        result = subprocess.run(
            ["bash", "-c", step["run"].replace("SECONDS + 30", "SECONDS + 2").replace("SECONDS + 180", "SECONDS + 2")],
            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15, check=False,
        )
        if failure == "shutdown-timeout":
            assert "cache persistence was not force-killed" in result.stdout
            assert (tmp_path / "test-cache.json").read_text() == "{"
            assert (tmp_path / "test-result/auth-refresh.log").exists()
            assert not (tmp_path / "stopped").exists()
    finally:
        (tmp_path / "release-cache").touch()
        if failure == "shutdown-timeout":
            deadline = time.monotonic() + 5
            while not (tmp_path / "stopped").exists():
                assert time.monotonic() < deadline, "Workflow must not terminate the unfinished cache writer"
                time.sleep(0.01)
            assert json.loads((tmp_path / "test-cache.json").read_text()) == {"complete": True}
    assert (result.returncode == 0) == (failure == "none"), result.stdout + result.stderr
    if failure == "tests":
        assert result.returncode == 7
    if failure in ("preflight", "startup", "startup-timeout"):
        assert "offline tests completed" not in result.stdout
    else:
        assert "offline tests completed" in result.stdout
    if failure in ("none", "tests", "shutdown-failure"):
        assert (tmp_path / "stopped").exists(), "Refresher must be reaped before the step ends"
