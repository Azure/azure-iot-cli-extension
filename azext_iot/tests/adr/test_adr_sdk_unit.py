# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import inspect
import json
from functools import partial
from io import StringIO
from threading import current_thread, main_thread
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.polling import LROPoller
from azure.cli.core.mock import DummyCli
from azure.cli.core import MainCommandsLoader

from azext_iot.adr.providers.group import GroupProvider
from azext_iot.adr.providers.report import ReportProvider
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient, operations
from azext_iot.common.utility import wait_for_terminal_state
from azext_iot import IoTExtCommandsLoader
from azext_iot.adr.providers.base import ADRProvider


SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
API_VERSION = "2026-11-02-preview"
NAMESPACE_URL = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
    "/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/namespace"
)
GENERATE_URL = f"{NAMESPACE_URL}/generateReport"
LATEST_URL = f"{NAMESPACE_URL}/getLatestReport"
STATUS_URL = f"{NAMESPACE_URL}/operationStatuses/report"
RESULT_URL = f"{NAMESPACE_URL}/operationResults/report"
REPORT_SELECTORS = [
    {"reportType": "NamespaceUpdateComplianceReport"},
    {"reportType": "GroupBestUpdatesComplianceReport", "reportTarget": "group"},
    {"reportType": "GroupInstallableUpdatesReport", "reportTarget": "group"},
]
CA_URL = f"{NAMESPACE_URL}/certificateAuthorities/ca"
CA_LOCATION = f"{NAMESPACE_URL}/operationResults/ca"


class ADRWireCommandsLoader(MainCommandsLoader):
    def load_command_table(self, args):
        loader = IoTExtCommandsLoader(self.cli_ctx)
        self.command_table = loader.load_command_table(args)
        self.cmd_to_loader_map = {name: [loader] for name in self.command_table}
        return self.command_table


@pytest.fixture
def ca_wire_cli(wire_client, mocker, ca_pki):
    mocker.patch("azure.cli.core._profile.Profile.get_subscription", return_value={
        "id": SUBSCRIPTION, "name": "offline", "environmentName": "AzureCloud",
    })
    mocker.patch("azure.cli.core._profile.Profile.get_login_credentials", return_value=(
        Mock(), SUBSCRIPTION, "offline-tenant",
    ))
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    mocker.patch(
        "azext_iot.adr.providers.base.wait_for_terminal_state",
        partial(wait_for_terminal_state, wait_sec=0),
    )
    ticks = [0]

    def advance(seconds):
        ticks[0] += max(seconds, 1)

    mocker.patch("azext_iot.adr.providers.base.monotonic", side_effect=lambda: ticks[0])
    mocker.patch("azext_iot.adr.providers.base.sleep", side_effect=advance)
    return DummyCli(commands_loader_cls=ADRWireCommandsLoader)


def _invoke_ca(cli, action, pki, tmp_path, *, no_wait=False, query=None):
    args = ["iot", "adr", "ns", "ca", action, "-n", "ca", "--ns", "namespace", "-g", "rg", "-o", "json"]
    if action == "activate":
        path = tmp_path / "chain.pem"
        path.write_bytes(pki["chain"].encode("utf-8"))
        args.extend(["--certificate-chain-file", str(path)])
    else:
        args.append("--yes")
    if no_wait:
        args.append("--no-wait")
    if query:
        args.extend(["--query", query])
    output = StringIO()
    code = cli.invoke(args, out_file=output)
    return code, output.getvalue()


def _ca_resource(pki, action, *, completed=False):
    issuer = dict(pki["resource"]["properties"]["issuer"]) if action == "activate" else {"issuerType": "Microsoft"}
    if completed:
        issuer.update({"futureField": "preserved"})
        if action == "activate":
            issuer.update(status="Active", thumbprint="service-thumbprint")
    return {"id": CA_URL, "name": "ca", "properties": {
        "certificateAuthorityType": "ICA", "issuer": issuer, "provisioningState": "Succeeded",
    }}


@pytest.mark.parametrize("action", ["activate", "revoke"])
@pytest.mark.parametrize("response_kind", ["inline", "204", "empty", "succeeded"])
@pytest.mark.parametrize("workaround", [True, False])
@pytest.mark.parametrize("no_wait", [True, False])
def test_ca_action_command_wire_completion_matrix(
    ca_wire_cli, ca_pki, wire_client, mocked_response, mocker, tmp_path,
    action, response_kind, workaround, no_wait,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    before = _ca_resource(ca_pki, action)
    after = _ca_resource(ca_pki, action, completed=True)
    mocked_response.add("GET", CA_URL, json=before)
    if not no_wait:
        mocked_response.add("GET", CA_URL, json=after)
    action_url = f"{CA_URL}/{'activate' if action == 'activate' else 'revokeAndRotate'}"
    headers = {} if response_kind == "inline" else {"Location": CA_LOCATION, "Retry-After": "1"}
    mocked_response.add("POST", action_url, status=204 if response_kind == "inline" else 202, headers=headers)
    if response_kind != "inline":
        mocked_response.add(
            "GET", CA_LOCATION, status=204 if response_kind == "204" else 200,
            json=None if response_kind == "204" else ({} if response_kind == "empty" else {"status": "Succeeded"}),
        )
    method = "begin_activate" if action == "activate" else "begin_revoke_and_rotate"
    begin = mocker.spy(wire_client.certificate_authorities, method)
    wait = mocker.spy(ADRProvider, "_wait")
    code, output = _invoke_ca(ca_wire_cli, action, ca_pki, tmp_path, no_wait=no_wait)
    assert code == 0, ca_wire_cli.result.error
    if no_wait:
        assert not output.strip() or json.loads(output) is None
        wait.assert_not_called()
    else:
        assert json.loads(output) == after
        wait.assert_called_once()
    assert isinstance(begin.spy_return, LROPoller)
    begin.spy_return.result()
    calls = list(mocked_response.calls)
    resource_gets = [call for call in calls if urlsplit(call.request.url).path == urlsplit(CA_URL).path]
    assert len(resource_gets) == (1 if no_wait else 2)
    posts = [call for call in calls if call.request.method == "POST"]
    assert len(posts) == 1
    if action == "activate":
        assert json.loads(posts[0].request.body) == {"certificateChain": ca_pki["chain"]}
    if not no_wait:
        assert calls.index(resource_gets[-1]) > calls.index(posts[0])
        if response_kind != "inline":
            assert any(call.request.url == CA_LOCATION for call in calls[:calls.index(resource_gets[-1])])


@pytest.mark.parametrize("action", ["activate", "revoke"])
@pytest.mark.parametrize("failure,workaround,no_wait", [
    (failure, workaround, no_wait) for failure in (
        "initial400", "initial403", "initial409", "failed", "empty-failure", "timeout",
        "read403", "read404", "read500", "readtransport",
    ) for workaround in (True, False) for no_wait in (False, True)
    if (failure != "timeout" or workaround) and (not no_wait or failure.startswith("initial"))
])
def test_ca_action_command_wire_failures(
    ca_wire_cli, ca_pki, mocked_response, tmp_path, action, failure, workaround, no_wait, caplog, mocker, wire_client,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    method = "begin_activate" if action == "activate" else "begin_revoke_and_rotate"
    begin = mocker.spy(wire_client.certificate_authorities, method)
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, action))
    url = f"{CA_URL}/{'activate' if action == 'activate' else 'revokeAndRotate'}"
    if failure.startswith("initial"):
        mocked_response.add(
            "POST", url, status=int(failure[7:]), json={"error": {"code": "ActionRejected", "message": "denied"}},
        )
    elif failure.startswith("read"):
        mocked_response.add("POST", url, status=204)
        if failure == "readtransport":
            mocked_response.add("GET", CA_URL, body=RequestsConnectionError("read connection lost"))
        else:
            mocked_response.add(
                "GET", CA_URL, status=int(failure[4:]), json={"error": {"code": "ReadFailed", "message": "read denied"}},
            )
    else:
        headers = {"Location": CA_LOCATION, "Retry-After": "30"}
        if not workaround:
            headers["Azure-AsyncOperation"] = CA_LOCATION
        mocked_response.add("POST", url, status=202, headers=headers)
        body = {"status": "Running" if failure == "timeout" else "Failed"}
        if failure == "failed":
            body["error"] = {"code": "ActionFailed", "message": "action rejected"}
        if failure == "timeout":
            def status_response(_request):
                status = body if current_thread() is main_thread() else {"status": "Succeeded"}
                return 200, {"Content-Type": "application/json"}, json.dumps(status)
            mocked_response.add_callback("GET", CA_LOCATION, callback=status_response)
        else:
            mocked_response.add("GET", CA_LOCATION, json=body)
    code, output = _invoke_ca(ca_wire_cli, action, ca_pki, tmp_path, no_wait=no_wait)
    assert code != 0
    assert not output.strip()
    error = str(ca_wire_cli.result.error)
    expected = {"failed": "action rejected", "empty-failure": "did not include",
                "timeout": "Timed out"}
    if failure.startswith("read"):
        assert "action completed" in caplog.text
        assert ("read connection lost" if failure == "readtransport" else "read denied") in error
    else:
        if failure != "empty-failure" or workaround:
            assert ("denied" if failure.startswith("initial") else expected[failure]) in error
        assert "action completed" not in caplog.text
    if not failure.startswith(("initial", "read")):
        if failure == "timeout" or workaround:
            begin.spy_return.result()
        else:
            with pytest.raises(HttpResponseError):
                begin.spy_return.result()
    calls = list(mocked_response.calls)
    assert len([call for call in calls if call.request.method == "POST"]) == 1
    assert len([call for call in calls if urlsplit(call.request.url).path == urlsplit(CA_URL).path]) == (
        2 if failure.startswith("read") else 1
    )


@pytest.mark.parametrize("action", ["activate", "revoke"])
def test_ca_activation_actual_query(ca_wire_cli, ca_pki, mocked_response, tmp_path, action):
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, action))
    route = "activate" if action == "activate" else "revokeAndRotate"
    mocked_response.add("POST", f"{CA_URL}/{route}", status=204)
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, action, completed=True))
    code, output = _invoke_ca(
        ca_wire_cli, action, ca_pki, tmp_path,
        query="{prov:properties.provisioningState,status:properties.issuer.status}",
    )
    assert code == 0
    assert json.loads(output) == {"prov": "Succeeded", "status": "Active" if action == "activate" else None}


@pytest.mark.parametrize("no_wait", [False, True])
def test_activation_negative_certificates_never_post(ca_wire_cli, ca_pki, mocked_response, tmp_path, no_wait):
    from azext_iot.tests.adr._certificate_fixtures import negative_certificate_chains

    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, "activate"))
    for _label, chain, findings in negative_certificate_chains(ca_pki["resource"]):
        code, output = _invoke_ca(ca_wire_cli, "activate", {"chain": chain}, tmp_path, no_wait=no_wait)
        assert code != 0
        assert not output.strip()
        for finding in findings:
            assert finding in str(ca_wire_cli.result.error)
    assert len(mocked_response.calls) == 5
    assert all(call.request.method == "GET" for call in mocked_response.calls)


@pytest.mark.parametrize("action", ["activate", "revoke"])
@pytest.mark.parametrize("target", ["root", "wrong-issuer", "missing"])
def test_ca_action_preflight_wire_never_posts(ca_wire_cli, ca_pki, mocked_response, tmp_path, action, target):
    resource = _ca_resource(ca_pki, action)
    if target == "root":
        resource["properties"]["certificateAuthorityType"] = "Root"
    elif target == "wrong-issuer":
        resource["properties"]["issuer"]["issuerType"] = "Microsoft" if action == "activate" else "External"
    if target == "missing":
        mocked_response.add("GET", CA_URL, status=404, json={"error": {"code": "ResourceNotFound", "message": "CA missing"}})
    else:
        mocked_response.add("GET", CA_URL, json=resource)
    code, output = _invoke_ca(ca_wire_cli, action, ca_pki, tmp_path)
    assert code != 0
    assert not output.strip()
    assert ("CA missing" if target == "missing" else "requires an ICA") in str(ca_wire_cli.result.error)
    assert len(mocked_response.calls) == 1
    assert mocked_response.calls[0].request.method == "GET"


@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("finding", ["future", "margin", "extensions", "missing-csr", "bad-csr", "extra-eku"])
def test_activation_warning_wire_preserves_original_text(
    ca_wire_cli, mocked_response, tmp_path, no_wait, finding, caplog, wire_client, mocker,
):
    from datetime import timedelta
    from azext_iot.tests.adr._certificate_fixtures import certificate_fixture

    pki = certificate_fixture(
        remaining=timedelta(days=365 if finding == "margin" else 730),
        starts=timedelta(days=1 if finding == "future" else -1),
        copy_extensions=finding != "extensions", extra_eku=finding == "extra-eku",
    )
    if finding in ("missing-csr", "bad-csr"):
        pki["resource"]["properties"]["issuer"]["certificateSigningRequest"] = None if finding == "missing-csr" else "bad"
    pki["chain"] = " \n" + pki["chain"].replace("\n", "\r\n") + "\t"
    mocked_response.add("GET", CA_URL, json=_ca_resource(pki, "activate"))
    mocked_response.add("POST", f"{CA_URL}/activate", status=204)
    if not no_wait:
        mocked_response.add("GET", CA_URL, json=_ca_resource(pki, "activate", completed=True))
    begin = mocker.spy(wire_client.certificate_authorities, "begin_activate")
    code, output = _invoke_ca(ca_wire_cli, "activate", pki, tmp_path, no_wait=no_wait)
    assert (tmp_path / "chain.pem").read_bytes() == pki["chain"].encode("utf-8")
    assert code == 0, ca_wire_cli.result.error
    expected = {"future": "not yet valid", "margin": "365 days", "extensions": "missing requested",
                "missing-csr": "not verified", "bad-csr": "not verified"}
    if finding in expected:
        assert expected[finding] in caplog.text
    begin.spy_return.result()
    post = next(call for call in mocked_response.calls if call.request.method == "POST")
    # The CLI's existing text-file reader normalizes newlines; preflight does
    # not additionally alter the decoded text, ordering, or surrounding space.
    assert json.loads(post.request.body) == {"certificateChain": pki["chain"].replace("\r\n", "\n")}
    if not no_wait:
        assert json.loads(output)["id"] == CA_URL


@pytest.mark.parametrize("action", ["activate", "revoke"])
def test_action_output_does_not_repair_stale_snapshot(ca_wire_cli, ca_pki, mocked_response, tmp_path, action):
    before = _ca_resource(ca_pki, action)
    mocked_response.add("GET", CA_URL, json=before)
    route = "activate" if action == "activate" else "revokeAndRotate"
    mocked_response.add("POST", f"{CA_URL}/{route}", status=204)
    code, output = _invoke_ca(ca_wire_cli, action, ca_pki, tmp_path)
    assert code == 0
    assert json.loads(output) == before
    assert len(mocked_response.calls) == 3


@pytest.mark.parametrize("async_failure", [False, True])
@pytest.mark.parametrize("detail,hint", [
    ({"code": "CertificateExpiringSoon", "message": "too short"}, "remaining certificate validity"),
    ({"code": "InvalidPropertyValue",
      "message": "properties.certificateProperties.extendedKeyUsage requires at least one value"}, "missing extended key usage"),
    ({"code": "InvalidCertificateChain", "message": "unknown nested failure"}, None),
    ({"code": "AuthorizationFailed", "message": "denied"}, None),
])
def test_activation_wire_hint_preserves_service_error(
    ca_wire_cli, ca_pki, mocked_response, tmp_path, async_failure, detail, hint, caplog, wire_client, mocker,
):
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, "activate"))
    headers = {"x-ms-correlation-request-id": "action-correlation"}
    if async_failure:
        mocked_response.add("POST", f"{CA_URL}/activate", status=202, headers={"Location": CA_LOCATION})
        mocked_response.add("GET", CA_LOCATION, json={"status": "Failed", "error": detail}, headers=headers)
    else:
        mocked_response.add("POST", f"{CA_URL}/activate", status=400, json={"error": detail}, headers=headers)
    begin = mocker.spy(wire_client.certificate_authorities, "begin_activate")
    code, output = _invoke_ca(ca_wire_cli, "activate", ca_pki, tmp_path)
    assert code != 0
    assert not output.strip()
    error = str(ca_wire_cli.result.error)
    assert detail["code"] in error
    assert detail["message"] in error
    warnings = [record for record in caplog.records if record.name.endswith("certificate_helpers")]
    assert len(warnings) == (1 if hint else 0)
    if hint:
        assert hint in warnings[0].message
    if async_failure:
        assert "Correlation ID from the Location-status response: action-correlation" in error
        begin.spy_return.result()
    assert len([call for call in mocked_response.calls if urlsplit(call.request.url).path == urlsplit(CA_URL).path]) == 1


@pytest.mark.parametrize("workaround", [True, False])
@pytest.mark.parametrize("inline", [True, False])
@pytest.mark.parametrize("detail,expected", [
    ({"code": "RealCode", "message": "real reason"}, "RealCode"),
    ({"code": "OnlyCode"}, "OnlyCode"),
    ({"message": "only message"}, "only message"),
    (None, None), ({}, None), ("absent", None), ("malformed", None), ({"code": 4, "message": []}, None),
])
def test_policy_create_real_command_failure(
    ca_wire_cli, ca_pki, mocked_response, wire_client, mocker, workaround, inline, detail, expected,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    policy_url = f"{CA_URL}/certificatePolicies/policy"
    status_url = f"{NAMESPACE_URL}/operationStatuses/policy"
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, "revoke"))
    body = {"id": policy_url, "name": "policy", "properties": {"provisioningState": "Failed", "error": detail}}
    if detail == "absent":
        body["properties"].pop("error")
        detail = None
    headers = {"x-ms-correlation-request-id": "write-correlation"}
    if not inline:
        headers.update({"Azure-AsyncOperation": status_url, "Retry-After": "1"})
    mocked_response.add("PUT", policy_url, status=201 if not inline else 200, json=body, headers=headers)
    if not inline:
        if workaround:
            mocked_response.add("GET", policy_url, json=body, headers={"x-ms-correlation-request-id": "get-correlation"})
        mocked_response.add("GET", status_url, json={"status": "Failed", "error": detail})
    begin = mocker.spy(wire_client.certificate_policies, "begin_create_or_replace")
    wait = mocker.spy(ADRProvider, "_wait")
    output = StringIO()
    code = ca_wire_cli.invoke([
        "iot", "adr", "ns", "ca", "policy", "create", "-n", "policy", "--ca", "ca",
        "--ns", "namespace", "-g", "rg", "--vd", "60", "--location", "eastus", "-o", "json",
    ], out_file=output)
    assert isinstance(begin.spy_return, LROPoller)
    wait.assert_called_once()
    if inline and not workaround:
        # The unmodified SDK treats headerless HTTP 200 as completed, even when
        # the resource says Failed. The enabled ADR workaround detects this.
        assert code == 0
        assert json.loads(output.getvalue()) == body
        assert begin.spy_return.result() == body
        return
    assert code != 0
    assert not output.getvalue().strip()
    error = str(ca_wire_cli.result.error)
    if workaround:
        assert "provisioningState='Failed'" in error
        assert (expected or "did not include a detailed error") in error
        assert "Check Azure Activity Log for this resource around the operation time" in error
        source = "initial operation response" if inline else "resource-status response"
        correlation = "write-correlation" if inline else "get-correlation"
        assert f"Correlation ID from the {source}: {correlation}" in error
        assert policy_url in error
        assert "None" not in error
    elif expected:
        assert expected in error
    # Join the real SDK worker, including its independently observed failure.
    if inline:
        assert begin.spy_return.result() == body
    else:
        with pytest.raises(HttpResponseError):
            begin.spy_return.result()
    writes = [call for call in mocked_response.calls if call.request.method == "PUT"]
    assert len(writes) == 1
    assert json.loads(writes[0].request.body)["properties"]["certificate"]["validityPeriodInDays"] == 60


@pytest.mark.parametrize("outcome,workaround", [
    (outcome, workaround) for outcome in ("success", "timeout", "400", "403", "409")
    for workaround in (True, False) if outcome != "timeout" or workaround
])
def test_policy_create_real_command_outcomes(
    ca_wire_cli, ca_pki, mocked_response, wire_client, mocker, outcome, workaround,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    policy_url = f"{CA_URL}/certificatePolicies/policy"
    status_url = f"{NAMESPACE_URL}/operationStatuses/policy"
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, "revoke"))
    body = {"id": policy_url, "name": "policy", "properties": {"provisioningState": "Succeeded"}}
    if outcome.isdigit():
        mocked_response.add(
            "PUT", policy_url, status=int(outcome), json={"error": {"code": "PolicyRejected", "message": "real rejection"}},
        )
    else:
        mocked_response.add("PUT", policy_url, status=201, json=body,
                            headers={"Azure-AsyncOperation": status_url, "Retry-After": "30"})
        mocked_response.add("GET", status_url, json={"status": "Succeeded"})

        def resource_response(_request):
            resource = body if outcome == "success" or current_thread() is not main_thread() else {
                **body, "properties": {"provisioningState": "Creating"},
            }
            return 200, {"Content-Type": "application/json"}, json.dumps(resource)

        mocked_response.add_callback("GET", policy_url, callback=resource_response)
    begin = mocker.spy(wire_client.certificate_policies, "begin_create_or_replace")
    output = StringIO()
    code = ca_wire_cli.invoke([
        "iot", "adr", "ns", "ca", "policy", "create", "-n", "policy", "--ca", "ca",
        "--ns", "namespace", "-g", "rg", "--vd", "60", "--location", "eastus", "-o", "json",
    ], out_file=output)
    if outcome == "success":
        assert code == 0, ca_wire_cli.result.error
        assert json.loads(output.getvalue()) == body
    else:
        assert code != 0
        assert ("Timed out" if outcome == "timeout" else "real rejection") in str(ca_wire_cli.result.error)
        assert not output.getvalue().strip()
    if not outcome.isdigit():
        begin.spy_return.result()
    assert len([call for call in mocked_response.calls if call.request.method == "PUT"]) == 1


@pytest.mark.parametrize("workaround", [True, False])
def test_policy_create_preserves_unsupported_async_auth_behavior(
    ca_wire_cli, ca_pki, mocked_response, wire_client, mocker, workaround,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", workaround)
    policy_url = f"{CA_URL}/certificatePolicies/policy"
    status_url = f"{NAMESPACE_URL}/operationStatuses/policy"
    mocked_response.add("GET", CA_URL, json=_ca_resource(ca_pki, "revoke"))
    mocked_response.add(
        "PUT", policy_url, status=201, json={"properties": {"provisioningState": "Creating"}},
        headers={"Azure-AsyncOperation": status_url, "x-ms-correlation-request-id": "write-correlation"},
    )
    mocked_response.add(
        "GET", status_url, status=500,
        json={"error": {"code": "AuthenticationFailed", "message": "ARM PoP token authentication failed"}},
    )
    if workaround:
        mocked_response.add(
            "GET", policy_url, json={"id": policy_url, "properties": {"provisioningState": "Failed"}},
            headers={"x-ms-correlation-request-id": "get-correlation"},
        )
    begin = mocker.spy(wire_client.certificate_policies, "begin_create_or_replace")
    output = StringIO()
    code = ca_wire_cli.invoke([
        "iot", "adr", "ns", "ca", "policy", "create", "-n", "policy", "--ca", "ca",
        "--ns", "namespace", "-g", "rg", "--vd", "60", "--location", "eastus", "-o", "json",
    ], out_file=output)
    assert code != 0
    assert not output.getvalue().strip()
    error = str(ca_wire_cli.result.error)
    if workaround:
        assert "resource-status response did not include a detailed error" in error
        assert "get-correlation" in error
        assert "ARM PoP" not in error
    else:
        assert "ARM PoP token authentication failed" in error
    with pytest.raises(HttpResponseError, match="ARM PoP"):
        begin.spy_return.result()
    assert len([call for call in mocked_response.calls if call.request.method == "PUT"]) == 1


@pytest.fixture
def wire_client():
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    with DeviceRegistryMgmtClient(
        credential,
        SUBSCRIPTION,
        polling_interval=0,
        retry_total=0,
        logging_enable=True,
    ) as client:
        yield client


def _assert_api_version(request):
    assert parse_qs(urlsplit(request.url).query) == {"api-version": [API_VERSION]}


def _mock_report_generation(mocked_response, status_code):
    headers = {}
    if status_code == 202:
        headers = {
            "Azure-AsyncOperation": STATUS_URL,
            "Location": RESULT_URL,
            "Retry-After": "0",
        }
        mocked_response.add("GET", STATUS_URL, json={"status": "InProgress"})
        mocked_response.add("GET", STATUS_URL, json={"status": "Succeeded"})
        mocked_response.add("GET", RESULT_URL, status=204)
    mocked_response.add("POST", GENERATE_URL, status=status_code, headers=headers)


@pytest.mark.parametrize(
    "operation_group",
    [
        operations.NamespaceAssetsOperations,
        operations.NamespaceDevicesOperations,
        operations.NamespaceDiscoveredAssetsOperations,
        operations.NamespaceDiscoveredDevicesOperations,
    ],
)
def test_namespace_child_lists_use_namespace_operation_name(operation_group):
    assert hasattr(operation_group, "list_by_namespace")
    assert not hasattr(operation_group, "list_by_resource_group")


def test_adr_sdk_is_modeless_and_synchronous():
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.aio") is None
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.models") is None
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.types") is None
    operation_groups = [
        group for name, group in inspect.getmembers(operations, inspect.isclass)
        if name.endswith("Operations")
    ]
    assert len(operation_groups) == 24
    methods = [
        method for group in operation_groups
        for name, method in inspect.getmembers(group, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert len(methods) == 109
    assert all(not inspect.iscoroutinefunction(method) for method in methods)


def test_adr_client_and_api_version_match_preview_contract():
    client = DeviceRegistryMgmtClient(
        credential=object(),
        subscription_id="00000000-0000-0000-0000-000000000000",
        base_url="https://centraluseuap.management.azure.com",
    )

    assert client._config.api_version == "2026-11-02-preview"
    assert hasattr(client, "namespaces")
    assert hasattr(client, "certificate_authorities")
    assert hasattr(client, "certificate_policies")


@pytest.mark.parametrize("status_code", [200, 204])
@pytest.mark.parametrize("no_wait", [False, True])
def test_group_delete_wire_is_synchronous(
    fixture_cmd, wire_client, mocked_response, mocker, status_code, no_wait
):
    mocked_response.add("DELETE", f"{NAMESPACE_URL}/groups/group", status=status_code)
    provider = GroupProvider(fixture_cmd, client=wire_client)
    wait = mocker.spy(provider, "_wait")

    assert provider.delete("group", "namespace", "rg", no_wait=no_wait) is None

    assert not hasattr(wire_client.groups, "begin_delete")
    wait.assert_not_called()
    assert len(mocked_response.calls) == 1
    request = mocked_response.calls[0].request
    assert request.method == "DELETE"
    assert urlsplit(request.url).path.endswith("/namespaces/namespace/groups/group")
    _assert_api_version(request)


def test_group_delete_wire_rejects_async_response(fixture_cmd, wire_client, mocked_response):
    mocked_response.add("DELETE", f"{NAMESPACE_URL}/groups/group", status=202)
    provider = GroupProvider(fixture_cmd, client=wire_client)

    with pytest.raises(HttpResponseError) as raised:
        provider.delete("group", "namespace", "rg", no_wait=True)

    assert raised.value.status_code == 202
    assert len(mocked_response.calls) == 1


@pytest.mark.parametrize("status_code", [202, 204])
def test_generate_report_wire_returns_none_after_arm_polling(wire_client, mocked_response, status_code):
    _mock_report_generation(mocked_response, status_code)

    poller = wire_client.namespaces.begin_generate_report("rg", "namespace", REPORT_SELECTORS[0])

    assert isinstance(poller, LROPoller)
    assert poller.result() is None
    calls = mocked_response.calls
    assert [call.request.method for call in calls] == (
        ["POST", "GET", "GET", "GET"] if status_code == 202 else ["POST"]
    )
    _assert_api_version(calls[0].request)
    assert json.loads(calls[0].request.body) == REPORT_SELECTORS[0]
    if status_code == 202:
        assert [call.request.url for call in calls[1:]] == [STATUS_URL, STATUS_URL, RESULT_URL]


def test_generate_report_wire_rejects_old_200_response(wire_client, mocked_response):
    mocked_response.add("POST", GENERATE_URL, status=200)

    with pytest.raises(HttpResponseError) as raised:
        wire_client.namespaces.begin_generate_report("rg", "namespace", REPORT_SELECTORS[0])

    assert raised.value.status_code == 200
    assert len(mocked_response.calls) == 1


@pytest.mark.parametrize("selector", REPORT_SELECTORS)
@pytest.mark.parametrize("status_code", [202, 204])
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("use_workaround", [False, True])
def test_generate_report_wire_output_and_no_wait(
    fixture_cmd, wire_client, mocked_response, mocker,
    selector, status_code, no_wait, use_workaround,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", use_workaround)
    _mock_report_generation(mocked_response, status_code)
    report = {**selector, "generatedAt": "2026-09-10T04:00:00Z", "reportData": {"deviceCount": 3}}
    if not no_wait:
        mocked_response.add("POST", LATEST_URL, json=report)
    provider = ReportProvider(fixture_cmd, client=wire_client)
    begin = mocker.spy(wire_client.namespaces, "begin_generate_report")
    wait = mocker.spy(provider, "_wait")

    result = provider.generate(
        "namespace", "rg", selector["reportType"],
        group_name=selector.get("reportTarget"), no_wait=no_wait, wait_sec=0,
    )

    if no_wait:
        assert result is begin.spy_return
        assert isinstance(result, LROPoller)
        wait.assert_not_called()
    else:
        assert result == report
        wait.assert_called_once()
    # Join the real SDK poller before the mocked transport is torn down.
    assert begin.spy_return.result() is None
    action_calls = [call for call in mocked_response.calls if call.request.method == "POST"]
    assert [urlsplit(call.request.url).path for call in action_calls] == [
        urlsplit(url).path for url in ([GENERATE_URL] if no_wait else [GENERATE_URL, LATEST_URL])
    ]
    for call in action_calls:
        assert json.loads(call.request.body) == selector
        assert call.request.headers["Content-Type"] == "application/json"
        _assert_api_version(call.request)
    if status_code == 202 and not no_wait:
        latest_index = list(mocked_response.calls).index(action_calls[1])
        assert any(
            call.request.url == RESULT_URL for call in list(mocked_response.calls)[:latest_index]
        )


def test_generate_report_wire_failure_does_not_retrieve_latest(
    fixture_cmd, wire_client, mocked_response, mocker
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", False)
    mocked_response.add(
        "POST", GENERATE_URL, status=202, headers={"Azure-AsyncOperation": STATUS_URL}
    )
    mocked_response.add(
        "GET", STATUS_URL,
        json={"status": "Failed", "error": {"code": "ReportFailed", "message": "Report generation failed"}},
    )
    provider = ReportProvider(fixture_cmd, client=wire_client)

    with pytest.raises(HttpResponseError, match="Report generation failed"):
        provider.generate("namespace", "rg", REPORT_SELECTORS[0]["reportType"])

    assert [call.request.method for call in mocked_response.calls] == ["POST", "GET"]
