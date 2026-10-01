# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline reproductions of integration investigations 5, 7 and 8."""

from copy import deepcopy
import json
from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.cli.core.commands.arm import show_exception_handler
from azure.cli.testsdk.base import ExecutionResult
from azure.core.credentials import AccessToken
from azure.core.exceptions import (
    ClientAuthenticationError,
    ServiceRequestError,
    ServiceResponseError,
)

from azext_iot.adr.providers.link import LinkProvider
from azext_iot.adr.providers.link_recovery import LinkDeadline, LinkRecovery
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr import _readiness as readiness

from azext_iot.tests.adr.test_adr_link_propagation_unit import Harness, NS_ID
from azext_iot.tests.adr.test_adr_link_unit import UAMI_ID
from azext_iot.tests.adr.test_adr_readiness_unit import (
    _http,
)


GROUP_SHOW = "iot adr ns group show --namespace ns -g rg -n group"
GROUP_ID = NS_ID + "/groups/group"
ARM = "https://centraluseuap.management.azure.com"


@pytest.fixture
def wrapper_scenario(mocker):
    # Exercise the *real* ARM show handler and testsdk wrapper, but never emit
    # telemetry or use a profile/credential/network.
    mocker.patch.object(ResourceNotFoundError, "print_error")
    mocker.patch.object(ResourceNotFoundError, "send_telemetry")
    cli = Mock(data={"subscription_id": "sub"})
    return SimpleNamespace(cli_ctx=cli, cmd=lambda text: ExecutionResult(cli, text))


def _outside_except(error):
    # Match Azure CLI command error handling: the exception is retained, but
    # its handler need not run inside the HTTP except block.
    show_exception_handler(error)


@pytest.mark.parametrize("url,method,status,code", [
    ("https://foreign.invalid" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    ("https://management.azure.com.evil.invalid" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID.replace("/sub/", "/foreign/"), "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID + "-foreign", "GET", 404, "ResourceNotFound"),
    (ARM + "/prefix" + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM.replace("https:", "http:") + GROUP_ID, "GET", 404, "ResourceNotFound"),
    (ARM + GROUP_ID, "POST", 404, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 403, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 502, "ResourceNotFound"),
    (ARM + GROUP_ID, "GET", 404, "AuthorizationFailed"),
])
def test_real_show_wrapper_rejects_foreign_http_evidence(wrapper_scenario, url, method, status, code):
    original = _http(status, code, method, resource_id=GROUP_ID)
    original.response.request.url = url
    wrapper_scenario.cli_ctx.invoke.side_effect = lambda *_args, **_kwargs: _outside_except(original)
    with pytest.raises((SystemExit, AssertionError)):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)
    wrapper_scenario.cli_ctx.invoke.assert_called_once()


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError, ServiceResponseError])
def test_authentication_and_transport_evidence_is_never_404(wrapper_scenario, error_type):
    error = _http(error_type=error_type, resource_id=GROUP_ID)
    wrapper_scenario.cli_ctx.invoke.side_effect = lambda *_args, **_kwargs: _outside_except(error)
    with pytest.raises(SystemExit):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)


@pytest.mark.parametrize("error_type", [ClientAuthenticationError, ServiceRequestError, ServiceResponseError])
@pytest.mark.parametrize("suppressed", [False, True])
def test_handler_traceback_never_discards_new_lookup_errors(wrapper_scenario, error_type, suppressed):
    missing = _http(resource_id=GROUP_ID)
    lookup_error = error_type("new lookup failure")

    def invoke(*_args, **_kwargs):
        try:
            raise lookup_error
        except error_type:
            try:
                _outside_except(missing)
            except SystemExit as error:
                if suppressed:
                    raise error from None
                raise

    wrapper_scenario.cli_ctx.invoke.side_effect = invoke
    with pytest.raises(SystemExit) as raised:
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)
    assert raised.value.__context__ is lookup_error


def test_real_handler_with_non_http_argument_and_bare_exit_cannot_prove_absence(wrapper_scenario):
    for error in (SimpleNamespace(status_code=404, message="missing"), SystemExit(3)):
        def invoke(*_args, **_kwargs):
            if isinstance(error, SystemExit):
                raise error
            _outside_except(error)
        wrapper_scenario.cli_ctx.invoke.side_effect = invoke
        with pytest.raises(SystemExit):
            readiness._get_resource(wrapper_scenario, GROUP_SHOW)


@pytest.mark.parametrize("conflict", ["cause", "status", "response"])
def test_exit_metadata_cannot_override_contradictory_lookup_evidence(wrapper_scenario, conflict):
    def invoke(*_args, **_kwargs):
        try:
            _outside_except(_http(resource_id=GROUP_ID))
        except SystemExit as error:
            if conflict == "cause":
                raise error from ClientAuthenticationError("lookup denied")
            if conflict == "status":
                error.status_code = 403
            else:
                error.response = SimpleNamespace(status_code=403)
            raise
    wrapper_scenario.cli_ctx.invoke.side_effect = invoke
    with pytest.raises(SystemExit):
        readiness._get_resource(wrapper_scenario, GROUP_SHOW)


def _rotation(mocker):
    harness = Harness(mocker, "hub", action="update")
    endpoint = harness.namespace["properties"]["messaging"]["endpoints"]["hub"]
    endpoint.update(
        linkingState="Succeeded",
        inboundCallerIdentity={"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
    )
    return harness


@pytest.mark.parametrize("view", ["converge", "stale-failure"])
def test_real_sdk_rotation_uses_sdk_status_before_exact_namespace_projection(mocker, mocked_response, view):
    harness = _rotation(mocker)
    harness.provider._await_terminal = MethodType(LinkProvider._await_terminal, harness.provider)
    old = deepcopy(harness.namespace)
    desired = deepcopy(old)
    desired["properties"]["messaging"]["endpoints"]["hub"] = {
        **deepcopy(harness.body), "linkingState": "Succeeded",
    }
    pending = deepcopy(old)
    pending["properties"]["provisioningState"] = "Updating"
    if view == "stale-failure":
        pending["properties"]["messaging"]["endpoints"]["hub"].update(
            linkingState="Failed", linkingError={"code": "AdrMiNotAuthorized"},
        )
    if view == "foreign":
        pending["properties"]["messaging"]["endpoints"]["hub"]["resourceId"] += "-foreign"
    if view == "terminal-old":
        pending["properties"]["provisioningState"] = "Succeeded"
    projected = deepcopy(desired)
    projected["properties"]["provisioningState"] = "Updating"
    reads = [pending, projected, desired]
    if view == "regression":
        reads = [projected, pending]
    writes, gets = [], []
    status_url = ARM + "/subscriptions/sub/providers/Microsoft.DeviceRegistry/locations/centraluseuap/asyncOperationStatuses/link"

    def respond(request):
        if "/asyncOperationStatuses/link" in request.url:
            return 200, {"Content-Type": "application/json"}, json.dumps({"status": "Succeeded"})
        if request.method == "PATCH":
            writes.append(json.loads(request.body))
            return 202, {
                "Content-Type": "application/json",
                "Azure-AsyncOperation": status_url,
                "Retry-After": "0",
            }, json.dumps(pending)
        gets.append(request.url)
        body = old if not writes else (pending if view == "timeout" else reads.pop(0) if reads else desired)
        return 200, {"Content-Type": "application/json"}, json.dumps(body)

    mocked_response.add_callback("GET", ARM + NS_ID, callback=respond)
    mocked_response.add_callback("PATCH", ARM + NS_ID, callback=respond)
    mocked_response.add_callback("GET", status_url, callback=respond)
    credential = Mock(spec=["get_token"], get_token=Mock(return_value=AccessToken("offline", 4102444800)))
    verify = mocker.spy(harness.provider._rbac, "verify_many")
    with DeviceRegistryMgmtClient(credential, "sub", base_url=ARM, retry_total=0) as client:
        harness.provider.client = client
        if view in {"converge", "stale-failure"}:
            result = harness.run(timeout_sec=5, wait_sec=1)
            assert result == desired
            assert harness.clock.now < 5
        else:
            with pytest.raises(AzureResponseError, match="timed out" if view == "timeout" else "changed"):
                harness.run(timeout_sec=5, wait_sec=1)
            if view == "timeout":
                assert harness.clock.now == 5
    assert writes == [{"properties": {"messaging": {"endpoints": {"hub": harness.body}}}}]
    verify.assert_not_called()  # In particular, no replay of the stale UAMI failure.
    assert len(mocked_response.calls) == len(gets) + len(writes) + 1


@pytest.mark.parametrize("drift", [
    "not-pending", "target", "type", "mixed", "identity", "settings", "namespace", "outbound",
])
def test_pending_projection_never_relaxes_external_drift_and_diagnostics_are_value_free(mocker, drift):
    harness = _rotation(mocker)
    expected = deepcopy(harness.body)
    expected["provisioning"]["allocationWeight"] = 30
    recovery = LinkRecovery(
        harness.provider, harness.namespace, "messaging", "hub", expected,
        LinkDeadline(clock=harness.clock.time, sleeper=harness.clock.sleep), Mock(),
    )
    recovery.pending = drift != "not-pending"
    current = deepcopy(harness.namespace)
    current["properties"]["provisioningState"] = "Updating"
    endpoint = current["properties"]["messaging"]["endpoints"]["hub"]
    if drift == "target":
        recovery.expected["resourceId"] += "-secret-target"
    elif drift == "type":
        recovery.expected["endpointType"] = "secret-type"
    elif drift == "mixed":
        endpoint["inboundCallerIdentity"] = deepcopy(expected["inboundCallerIdentity"])
    elif drift == "identity":
        endpoint["inboundCallerIdentity"]["userAssignedIdentity"] += "-secret-identity"
    elif drift == "settings":
        endpoint["provisioning"]["availability"] = "secret-setting"
    elif drift == "namespace":
        current["id"] += "-secret-namespace"
    elif drift == "outbound":
        current["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": "secret-outbound"}
    with pytest.raises(AzureResponseError, match="changed") as raised:
        recovery.inspect(current)
    assert "secret-" not in str(raised.value)
    assert recovery.snapshot is None
    recovery.verify.assert_not_called()
