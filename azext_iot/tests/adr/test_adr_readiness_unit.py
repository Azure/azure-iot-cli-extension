# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Offline state-machine proofs for ADR integration cleanup and Hub/DPS readiness."""

from copy import deepcopy
import shlex
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from azure.cli.core.azclierror import ArgumentUsageError, AzureResponseError, ResourceNotFoundError
from azure.core.credentials import AccessToken
from azure.core.exceptions import (
    ClientAuthenticationError, HttpResponseError, ResourceNotFoundError as SDKResourceNotFoundError, ServiceRequestError,
)
from azure.core.rest import HttpRequest
from knack.util import CLIError

from azext_iot.adr.common import DPS_ENDPOINT_TYPE, IOT_HUB_ENDPOINT_TYPE
from azext_iot.adr.providers.link_helpers import failed_link_recovery_commands
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.tests.adr import _readiness as readiness
from azext_iot.tests.adr import test_adr_group_int as group_scenarios
from azext_iot.tests.adr import test_adr_job_int as job_scenarios
from azext_iot.tests.adr import test_adr_job_run_int as run_scenarios
from azext_iot.tests.adr import test_adr_link_int as link_scenarios
from azext_iot.tests.adr.test_adr_cleanup_regressions_unit import _sdk_error


NS_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns"
HUB_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub"
DPS_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps"
UAMI_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/uami"
ADD = f"iot adr ns link hub add --ns ns -g rg -n secondary --hub-id {HUB_ID} --system-assigned-mi"
EXPECTED = {
    "resourceId": HUB_ID,
    "inboundCallerIdentity": {"type": "SystemAssigned"},
    "provisioning": {"availability": "Available", "allocationWeight": 2},
}
LINKS = {
    "hub": ("messaging", IOT_HUB_ENDPOINT_TYPE, "secondary"),
    "dps": ("provisioning", DPS_ENDPOINT_TYPE, "dps-primary"),
}
NAMESPACE_IDENTITY = {"type": "SystemAssigned", "principalId": "11111111-1111-4111-8111-111111111111"}


@pytest.fixture(params=["hub", "dps"])
def link_kind(request):
    return request.param


def _expected(kind):
    if kind == "hub":
        return deepcopy(EXPECTED)
    return {"resourceId": DPS_ID, "inboundCallerIdentity": {"type": "SystemAssigned"}}


def _add(kind):
    if kind == "hub":
        return ADD
    return f"iot adr ns link dps add --ns ns -g rg -n dps-primary --dps-id {DPS_ID} --system-assigned-mi"


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def _http(
    status=404, code="ResourceNotFound", method="GET", error_type=HttpResponseError,
    resource_id=NS_ID + "/jobs/job",
):
    error = error_type(message=f"({code}) synthetic service error")
    error.status_code = status
    error.error = SimpleNamespace(code=code)
    error.response = SimpleNamespace(
        status_code=status,
        request=HttpRequest(method, f"https://management.azure.com{resource_id}?api-version=2026-11-02-preview"),
    )
    return error


def _missing(kind):
    return _http(resource_id=NS_ID + {"job": "/jobs/job", "group": "/groups/group", "namespace": ""}[kind])


def _output(value):
    return Mock(get_output_in_json=lambda: deepcopy(value))


def _cleanup(scenario, clock, **kwargs):
    return readiness.delete_test_namespace(
        scenario, "ns", "rg", jobs=("job",), groups=("group",),
        clock=clock, sleeper=clock.sleep, **kwargs,
    )


def _commands(scenario):
    return [call.args[0] for call in scenario.cmd.call_args_list]


def test_owned_job_and_group_require_exact_get_404_before_namespace_delete():
    clock = Clock()
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output({"properties": {"provisioningState": "Deleting"}}), _http(),
        _output({}), _output({}), _sdk_error(_missing("group")),
        _output({"properties": {"provisioningState": "Succeeded"}}), _output(None),
        _missing("job"), _missing("group"), _missing("namespace"),
    ]
    _cleanup(scenario, clock)
    commands = _commands(scenario)
    assert "job show" in commands[0]
    assert "group show" in commands[2]
    assert commands[6] == "iot adr ns delete --namespace ns -g rg -y --no-wait"
    assert clock.sleeps == [10, 10, 10, 10]
    assert sum(" delete " in command for command in commands) == 1


@pytest.mark.parametrize("error", [
    _http(403), _http(502), _http(404, "AuthorizationFailed"),
    _http(error_type=ClientAuthenticationError),
    ServiceRequestError("credentials 404"),
    CLIError("404"), ResourceNotFoundError("status-less error"),
    SystemExit(3),
])
def test_child_lookup_failures_are_not_absence_and_never_delete_namespace(error):
    scenario = Mock()
    scenario.cmd.side_effect = error
    with pytest.raises(type(error)):
        _cleanup(scenario, Clock())
    assert len(_commands(scenario)) == 1
    assert "job show" in _commands(scenario)[0]


@pytest.mark.parametrize("output", [None, "", []])
def test_blank_get_is_not_absence(output):
    scenario = Mock()
    scenario.cmd.return_value = _output(output)
    with pytest.raises(AssertionError, match="not HTTP 404"):
        _cleanup(scenario, Clock())
    assert scenario.cmd.call_count == 1


@pytest.mark.parametrize("url,method", [
    ("https://login.microsoftonline.com/tenant/oauth2/token", "GET"),
    ("https://management.azure.com" + NS_ID + "/groups/other", "GET"),
    ("https://management.azure.com" + NS_ID + "/jobs/job", "POST"),
])
def test_credential_or_other_resource_http_404_is_not_child_absence(url, method):
    error = _http(method=method)
    error.response.request.url = url
    scenario = Mock()
    scenario.cmd.side_effect = error
    with pytest.raises(HttpResponseError):
        _cleanup(scenario, Clock())
    assert scenario.cmd.call_count == 1


def _cli_exit(error, code=3):
    wrapper = SystemExit(code)
    wrapper.__context__ = error
    return wrapper


@pytest.mark.parametrize("wrap", [lambda error: error, _sdk_error, _cli_exit])
def test_matching_resource_get_404_with_api_version_proves_absence(wrap):
    missing = _http()
    missing.response.request.url = "https://management.azure.com" + NS_ID + "/jobs/job?api-version=preview"
    scenario = Mock()
    scenario.cmd.side_effect = wrap(missing)
    assert readiness._get_resource(scenario, "iot adr ns job show --namespace ns -g rg -n job") is None


def _remove_response_metadata(error, missing):
    if missing == "response":
        del error.response
    elif missing == "response_status":
        del error.response.status_code
    elif missing == "request":
        del error.response.request
    elif missing in {"method", "url"}:
        delattr(error.response.request, missing)
    else:
        error.response.request.url = None if missing == "null_url" else 404


@pytest.mark.parametrize("missing", [
    "response", "response_status", "request", "method", "url", "null_url", "non_string_url",
])
@pytest.mark.parametrize("wrap", [lambda error: error, _sdk_error, _cli_exit])
def test_unproven_get_404_metadata_propagates_without_parent_delete(missing, wrap):
    error = _missing("job")
    _remove_response_metadata(error, missing)
    error = wrap(error)
    scenario = Mock()
    scenario.cmd.side_effect = error
    with pytest.raises(type(error)) as caught:
        _cleanup(scenario, Clock())
    assert caught.value is error
    assert scenario.cmd.call_count == 1


@pytest.mark.parametrize("code", [0, 1, 2])
def test_other_cli_exit_codes_cannot_prove_absence_even_with_get_404_context(code):
    scenario = Mock()
    error = _cli_exit(_missing("job"), code=code)
    scenario.cmd.side_effect = error
    with pytest.raises(SystemExit) as caught:
        _cleanup(scenario, Clock())
    assert caught.value is error
    assert scenario.cmd.call_count == 1


@pytest.mark.parametrize("error_type", [HttpResponseError, SDKResourceNotFoundError])
def test_lazy_credential_404_without_request_url_never_proves_resource_absence(mocked_response, error_type):
    error = _http(error_type=error_type)
    del error.response.request.url
    credential = Mock(spec=["get_token"])
    credential.get_token.side_effect = error
    with DeviceRegistryMgmtClient(credential, "sub", retry_total=0) as client:
        scenario = Mock()
        scenario.cmd.side_effect = lambda _command: client.jobs.get("rg", "ns", "job")
        with pytest.raises(HttpResponseError) as caught:
            _cleanup(scenario, Clock())
    assert caught.value is error
    assert credential.get_token.call_count == 1
    assert not mocked_response.calls
    assert scenario.cmd.call_count == 1


def test_real_sdk_get_404_and_testsdk_rethrow_gate_bounded_namespace_delete(mocked_response, mocker):
    namespace_url = "https://management.azure.com" + NS_ID
    absent = {"error": {"code": "ResourceNotFound", "message": "Owned resource was deleted"}}
    mocked_response.add("GET", namespace_url + "/jobs/job", status=404, json=absent)
    mocked_response.add(
        "GET", namespace_url + "/groups/group", json={"properties": {"provisioningState": "Deleting"}},
    )
    mocked_response.add("GET", namespace_url + "/groups/group", status=404, json=absent)
    mocked_response.add("GET", namespace_url, json={"properties": {"provisioningState": "Succeeded"}})
    mocked_response.add("GET", namespace_url, status=404, json=absent)
    mocked_response.add("DELETE", namespace_url, status=204)
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    proofs = []
    clock = Clock()
    with DeviceRegistryMgmtClient(credential, "sub", retry_total=0, polling_interval=0) as client:
        mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
        provider = NamespaceProvider(Mock())

        def command(text):
            try:
                if "job show" in text:
                    return _output(client.jobs.get("rg", "ns", "job"))
                if "group show" in text:
                    return _output(client.groups.get("rg", "ns", "group"))
                if "ns show" in text:
                    return _output(client.namespaces.get("rg", "ns"))
                assert text == "iot adr ns delete --namespace ns -g rg -y --no-wait"
                provider.delete("ns", "rg", no_wait=True)
                return _output(None)
            except HttpResponseError as error:
                shaped = _sdk_error(error)
                proofs.append(shaped)
                raise shaped

        _cleanup(SimpleNamespace(cmd=command), clock)
    assert clock.sleeps == [10, 10]
    assert len(proofs) == 5
    assert all(error.response.status_code == 404 and error.response.request.method == "GET" for error in proofs)
    assert [(call.request.method, urlsplit(call.request.url).path) for call in mocked_response.calls] == [
        ("GET", NS_ID + "/jobs/job"),
        ("GET", NS_ID + "/groups/group"),
        ("GET", NS_ID + "/groups/group"),
        ("GET", NS_ID),
        ("DELETE", NS_ID),
        ("GET", NS_ID + "/jobs/job"),
        ("GET", NS_ID + "/groups/group"),
        ("GET", NS_ID),
    ]


def test_lingering_child_exhausts_deadline_without_parent_delete():
    clock = Clock()
    scenario = Mock()
    scenario.cmd.return_value = _output({})
    with pytest.raises(AssertionError, match="owned job GET still readable"):
        _cleanup(scenario, clock, timeout=25)
    assert clock.sleeps == [10, 10, 5]
    assert all("job show" in command for command in _commands(scenario))


@pytest.mark.parametrize("translated", [False, True])
@pytest.mark.parametrize("code", ["CannotDeleteResource", "NamespaceNotEmpty"])
def test_explicit_child_rejection_rechecks_absence_before_retry(translated, code):
    rejection = _http(409, code, method="DELETE", resource_id=NS_ID)
    if translated:
        wrapped = AzureResponseError(f"({code}) translated guidance")
        wrapped.__cause__ = rejection
        rejection = _sdk_error(wrapped)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _missing("job"), _missing("group"), _output({}), rejection,
        _missing("job"), _missing("group"), _output({}), _output([]), _output([]), _output(None),
        _missing("job"), _missing("group"), _missing("namespace"),
    ]
    clock = Clock()
    _cleanup(scenario, clock)
    commands = _commands(scenario)
    assert sum(" delete " in command for command in commands) == 2
    assert commands[4:6] == commands[:2]
    assert clock.sleeps == [10, 10]


@pytest.mark.parametrize("error", [
    AzureResponseError("(NamespaceNotEmpty) metadata-less error"),
    _http(409, "Conflict", method="DELETE", resource_id=NS_ID),
    _http(409, "NamespaceNotEmpty", method="GET", resource_id=NS_ID),
    _http(202, "NamespaceNotEmpty", method="DELETE", resource_id=NS_ID),
    ServiceRequestError("DELETE timed out after acceptance"),
])
def test_uncertain_or_unrelated_delete_error_is_never_replayed(error):
    scenario = Mock()
    scenario.cmd.side_effect = [_missing("job"), _missing("group"), _output({}), error]
    with pytest.raises(type(error)):
        _cleanup(scenario, Clock())
    assert len(_commands(scenario)) == 4


@pytest.mark.parametrize("missing", [
    "response", "response_status", "request", "method", "url", "null_url", "non_string_url",
])
def test_unproven_delete_rejection_is_not_replayed(missing):
    error = _http(409, "CannotDeleteResource", method="DELETE", resource_id=NS_ID)
    _remove_response_metadata(error, missing)
    scenario = Mock()
    scenario.cmd.side_effect = [_missing("job"), _missing("group"), _output({}), error]
    with pytest.raises(HttpResponseError) as caught:
        _cleanup(scenario, Clock())
    assert caught.value is error
    assert len(_commands(scenario)) == 4


@pytest.mark.parametrize("already_deleting", [False, True])
def test_accepted_delete_only_polls_even_if_namespace_state_is_stale(already_deleting):
    scenario = Mock()
    accepted = [already_deleting]

    def command(cmd):
        if "job show" in cmd:
            raise _missing("job")
        if "group show" in cmd:
            raise _missing("group")
        if " delete " in cmd:
            assert not accepted[0]
            accepted[0] = True
            return _output(None)
        return _output({"properties": {"provisioningState": "Deleting" if already_deleting else "Succeeded"}})

    scenario.cmd.side_effect = command
    with pytest.raises(AssertionError, match="namespace DELETE accepted"):
        _cleanup(scenario, Clock(), timeout=25)
    assert sum(" delete " in cmd for cmd in _commands(scenario)) == (0 if already_deleting else 1)


def _namespace(ns_state="Failed", state="Failed", expected=None, message=None, *, kind="hub"):
    section, endpoint_type, name = LINKS[kind]
    endpoint = deepcopy(expected or _expected(kind))
    endpoint.update(endpointType=endpoint_type, linkingState=state)
    endpoint["linkingError"] = {
        "message": message or (
            f"The namespace's managed identity is not authorized to read the linked resource '{endpoint['resourceId']}'. "
            "Grant it read access on the resource, then resubmit the request."
        ),
    }
    return {
        "id": NS_ID,
        "identity": deepcopy(NAMESPACE_IDENTITY),
        "properties": {
            "provisioningState": ns_state,
            section: {"endpoints": {name: endpoint}},
        },
    }


def _link(scenario, clock, expected=None, *, kind="hub", **kwargs):
    # Existing transcripts below describe commands after submission. Supply the
    # new pre-add namespace snapshot separately; the alignment regressions also
    # exercise this GET, its deadline and identity failures directly.
    first = True

    def command(text):
        nonlocal first
        if first:
            first = False
            assert text == "iot adr ns show -n ns -g rg"
            return _output({
                "id": NS_ID, "identity": deepcopy(NAMESPACE_IDENTITY),
                "properties": {"provisioningState": "Succeeded"},
            })
        return scenario.cmd(text)

    helper = readiness.link_hub_with_readiness if kind == "hub" else readiness.link_dps_with_readiness
    return helper(
        SimpleNamespace(cmd=command), _add(kind), "ns", "rg", LINKS[kind][2], expected or _expected(kind),
        clock=clock, sleeper=clock.sleep, **kwargs,
    )


@pytest.mark.parametrize("user_assigned", [False, True])
@pytest.mark.parametrize("error_field", ["linkingError", "error", "provisioningStatus"])
def test_auth_recovery_updates_persisted_identity_and_requires_both_successes(user_assigned, error_field, link_kind):
    expected = _expected(link_kind)
    if user_assigned:
        expected["inboundCallerIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
    failed = _namespace(expected=expected, kind=link_kind)
    if error_field != "linkingError":
        section, _, name = LINKS[link_kind]
        endpoint = failed["properties"][section]["endpoints"][name]
        error = endpoint.pop("linkingError")
        if error_field == "provisioningStatus":
            endpoint["provisioningStatus"] = {"status": endpoint.pop("linkingState"), "error": error}
        else:
            endpoint["error"] = error
    snapshot = deepcopy(failed)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None),
        _output(_namespace("Updating", "InProgress", expected, kind=link_kind)),
        _output(failed), _output(failed), _output(None),
        _output(failed),  # A stale Failed GET after accepted update must not replay it.
        _output(_namespace("Updating", "Succeeded", expected, kind=link_kind)),
        _output(_namespace("Succeeded", "Succeeded", expected, kind=link_kind)),
    ]
    clock = Clock()
    endpoint = _link(scenario, clock, expected, kind=link_kind)
    commands = _commands(scenario)
    assert commands[0] == _add(link_kind) + " --no-wait"
    assert commands[4] == failed_link_recovery_commands(failed)[0] + " --no-wait"
    assert sum(" update " in command for command in commands) == 1
    assert endpoint["linkingState"] == "Succeeded"
    assert all(endpoint[key] == value for key, value in expected.items())
    assert failed == snapshot
    assert clock.now == 50


@pytest.mark.parametrize("user_assigned", [False, True])
def test_arm_id_casing_is_not_a_changed_link_target_or_identity(user_assigned, link_kind):
    persisted = _expected(link_kind)
    if user_assigned:
        persisted["inboundCallerIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
    expected = deepcopy(persisted)
    expected["resourceId"] = expected["resourceId"].casefold()
    if user_assigned:
        expected["inboundCallerIdentity"]["userAssignedIdentity"] = UAMI_ID.casefold()
    failed = _namespace(expected=persisted, kind=link_kind)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None), _output(failed), _output(failed), _output(None),
        _output(_namespace("Succeeded", "Succeeded", persisted, kind=link_kind)),
    ]
    result = _link(scenario, Clock(), expected, kind=link_kind)
    assert _commands(scenario)[3] == failed_link_recovery_commands(failed)[0] + " --no-wait"
    assert all(result[key] == value for key, value in persisted.items())


@pytest.mark.parametrize("error", [
    ArgumentUsageError("bad target"), AzureResponseError("RBAC preflight failed"),
    AzureResponseError("403 not authorized"), _http(403, "AuthorizationFailed"),
    ServiceRequestError("PATCH response lost"), CLIError("timeout"),
])
def test_link_write_errors_preserve_preflight_and_uncertain_acceptance(error, link_kind):
    scenario = Mock()
    scenario.cmd.side_effect = error
    with pytest.raises(type(error)) as raised:
        _link(scenario, Clock(), kind=link_kind)
    assert raised.value is error
    scenario.cmd.assert_called_once_with(_add(link_kind) + " --no-wait")


@pytest.mark.parametrize("message", [
    "not authorized", "Forbidden", "some unrelated failure", "resource-rejected-invalid",
    f"The linked resource's managed identity is not authorized to read the namespace '{NS_ID}'.",
    "The namespace's managed identity is not authorized to read the linked resource 'other'. "
    "Grant it read access on the resource, then resubmit the request.",
])
def test_other_terminal_link_failures_are_not_retried_or_reported_as_success(message, link_kind):
    scenario = Mock()
    scenario.cmd.side_effect = [_output(None), _output(_namespace(message=message, kind=link_kind))]
    with pytest.raises(AssertionError, match="Non-recoverable (Hub|DPS) link failure") as failure:
        _link(scenario, Clock(), kind=link_kind)
    assert message in str(failure.value)
    assert scenario.cmd.call_count == 2


@pytest.mark.parametrize("ns_state,state", [
    ("Updating", "Failed"), ("Failed", "InProgress"), ("Succeeded", "InProgress"),
    ("Succeeded", "Succeeded"),
])
def test_busy_and_successful_link_states_never_retry(ns_state, state, link_kind):
    scenario = Mock()
    scenario.cmd.return_value = _output(_namespace(ns_state, state, kind=link_kind))
    if state == ns_state == "Succeeded":
        _link(scenario, Clock(), kind=link_kind)
    else:
        with pytest.raises(AssertionError, match="Timed out"):
            _link(scenario, Clock(), kind=link_kind, timeout=25)
    assert not any(" update " in cmd for cmd in _commands(scenario))


def test_accepted_recovery_requires_progress_before_another_retry(link_kind):
    scenario = Mock()
    scenario.cmd.return_value = _output(_namespace(kind=link_kind))
    clock = Clock()
    with pytest.raises(AssertionError, match="recovery updates=1") as failure:
        _link(scenario, clock, kind=link_kind, timeout=65)
    assert "not authorized to read the linked resource" in str(failure.value)
    assert clock.now == 65
    assert sum(" update " in cmd for cmd in _commands(scenario)) == 1


def test_repeated_auth_failure_backoff_is_bounded_and_charges_cli_time(link_kind):
    scenario = Mock()
    clock = Clock()
    writes = []
    progressing = [False]

    def command(cmd):
        clock.now += 1  # CLI time counts, including reads and preflight/write.
        if " add " in cmd or " update " in cmd:
            writes.append(clock.now)
            progressing[0] = True
            return _output(None)
        if progressing[0]:
            progressing[0] = False
            return _output(_namespace("Updating", "InProgress", kind=link_kind))
        return _output(_namespace(kind=link_kind))

    scenario.cmd.side_effect = command
    with pytest.raises(AssertionError, match="Timed out"):
        _link(scenario, clock, kind=link_kind, timeout=180)
    assert clock.now == 180
    assert writes == [1, 25, 70, 126]
    assert max(clock.sleeps) == 10  # Actual GETs continue during 10/20/30s backoff.


@pytest.mark.parametrize("field,value", [
    ("resourceId", HUB_ID + "-other"),
    ("inboundCallerIdentity", {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}),
    ("provisioning", {"availability": "Unavailable", "allocationWeight": 9}),
    ("endpointType", "Microsoft.Devices/other"),
])
def test_recovery_never_retargets_or_changes_endpoint_settings(field, value, link_kind):
    namespace = _namespace(kind=link_kind)
    section, _, name = LINKS[link_kind]
    namespace["properties"][section]["endpoints"][name][field] = value
    scenario = Mock()
    scenario.cmd.side_effect = [_output(None), _output(namespace)]
    with pytest.raises(AssertionError, match="settings changed"):
        _link(scenario, Clock(), kind=link_kind)
    assert scenario.cmd.call_count == 2


def test_recovery_read_and_update_errors_are_not_hidden(link_kind):
    for responses in (
        [_output(None), _http(502, "BadGateway")],
        [_output(None), _output(_namespace(kind=link_kind)), _output(_namespace(kind=link_kind)),
         AzureResponseError("preflight denied")],
    ):
        scenario = Mock()
        scenario.cmd.side_effect = responses
        with pytest.raises((HttpResponseError, AzureResponseError)):
            _link(scenario, Clock(), kind=link_kind)
        assert scenario.cmd.call_count == len(responses)


@pytest.mark.parametrize("state", ["Failed", "InProgress"])
@pytest.mark.parametrize("section", ["messaging", "provisioning", "updating"])
def test_other_endpoint_failure_or_progress_cannot_trigger_link_recovery(state, section, link_kind):
    namespace = _namespace(kind=link_kind)
    own_section, _, name = LINKS[link_kind]
    if section == own_section:
        name = "unrelated"
    namespace["properties"].setdefault(section, {}).setdefault("endpoints", {})[name] = {"linkingState": state}
    scenario = Mock()
    scenario.cmd.return_value = _output(namespace)
    with pytest.raises(AssertionError):
        _link(scenario, Clock(), kind=link_kind, timeout=25)
    assert not any(" update " in cmd for cmd in _commands(scenario))


def test_deadline_exhausted_inside_cli_call_cannot_pass_or_start_another_write(link_kind):
    clock = Clock()
    scenario = Mock()

    def command(_cmd):
        clock.now += 25
        return _output(_namespace("Succeeded", "Succeeded", kind=link_kind))

    scenario.cmd.side_effect = command
    with pytest.raises(AssertionError, match="Timed out"):
        _link(scenario, clock, kind=link_kind, timeout=20)
    scenario.cmd.assert_called_once()


def test_recovery_commands_keep_exact_scope_and_no_permissions_shortcuts(link_kind):
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None), _output(_namespace(kind=link_kind)), _output(_namespace(kind=link_kind)), _output(None),
        _output(_namespace("Succeeded", "Succeeded", kind=link_kind)),
    ]
    _link(scenario, Clock(), kind=link_kind)
    update = shlex.split(_commands(scenario)[3])
    assert update == [
        "az", "iot", "adr", "ns", "link", link_kind, "update", "-n", LINKS[link_kind][2],
        "--ns", "ns", "-g", "rg", "--subscription", "sub",
        "--system-assigned-mi", "--no-wait",
    ]


@pytest.mark.parametrize("kind", ["su", "unknown", "messaging", None])
def test_readiness_kind_whitelist_rejects_unsupported_services_before_any_command(kind):
    scenario = Mock()
    with pytest.raises(AssertionError, match="only owned Hub/DPS adds"):
        readiness.link_with_readiness(
            scenario, ADD, "ns", "rg", "secondary", EXPECTED, link_kind=kind,
        )
    scenario.cmd.assert_not_called()


@pytest.mark.parametrize("command", [
    "iot adr ns link su add --ns ns -g rg",
    "iot adr ns link hub add --ns ns -g rg",
    "iot adr ns link dps update --ns ns -g rg",
])
def test_dps_readiness_cannot_submit_a_different_kind_or_operation(command):
    scenario = Mock()
    with pytest.raises(AssertionError, match="matching owned link add"):
        readiness.link_dps_with_readiness(scenario, command, "ns", "rg", "dps-primary", _expected("dps"))
    scenario.cmd.assert_not_called()


@pytest.mark.parametrize("authorization_failure", [True, False])
def test_native_namespace_get_drives_only_precise_link_recovery(mocked_response, link_kind, authorization_failure):
    """Exercise SDK GET serialization; mutations are offline command receipts."""
    failed = _namespace(kind=link_kind, message=None if authorization_failure else "resource-rejected-invalid")
    url = "https://management.azure.com" + NS_ID
    mocked_response.add("GET", url, json=failed)
    if authorization_failure:
        mocked_response.add("GET", url, json=failed)
        mocked_response.add("GET", url, json=_namespace("Updating", "InProgress", kind=link_kind))
        mocked_response.add("GET", url, json=_namespace("Succeeded", "Succeeded", kind=link_kind))
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    scenario = Mock()
    clock = Clock()
    with DeviceRegistryMgmtClient(credential, "sub", retry_total=0) as client:
        def command(text):
            if text.startswith("iot adr ns show "):
                return _output(client.namespaces.get("rg", "ns"))
            return _output(None)
        scenario.cmd.side_effect = command
        if authorization_failure:
            result = _link(scenario, clock, kind=link_kind)
            assert result["linkingState"] == "Succeeded"
            assert result["resourceId"] == _expected(link_kind)["resourceId"]
            assert clock.sleeps == [10, 10, 10]
        else:
            with pytest.raises(AssertionError, match="Non-recoverable"):
                _link(scenario, clock, kind=link_kind)
            assert not clock.sleeps
    writes = [cmd for cmd in _commands(scenario) if " add " in cmd or " update " in cmd]
    assert writes == [_add(link_kind) + " --no-wait"] + (
        [failed_link_recovery_commands(failed)[0] + " --no-wait"] if authorization_failure else []
    )
    assert len(mocked_response.calls) == (4 if authorization_failure else 1)
    assert all(call.request.method == "GET" and urlsplit(call.request.url).path == NS_ID
               for call in mocked_response.calls)


@pytest.mark.parametrize("ready", [True, False])
def test_link_lifecycle_routes_step_one_through_owned_dps_readiness_before_hubs(monkeypatch, ready):
    scenario = Mock()
    scenario.setup_full_infra.return_value = {"identity_resource_id": UAMI_ID}
    monkeypatch.setattr(link_scenarios, "generate_adr_namespace_name", lambda: "ns")
    monkeypatch.setattr(link_scenarios, "generate_dps_name", lambda: "dps")
    dps_readiness = Mock(side_effect=None if ready else RuntimeError("stop at DPS readiness"))
    hub_readiness = Mock()
    monkeypatch.setattr(link_scenarios, "link_dps_with_readiness", dps_readiness)
    monkeypatch.setattr(link_scenarios, "link_hub_with_readiness", hub_readiness)

    def command(text):
        if text.startswith("iot adr ns show "):
            return _output({"id": NS_ID, "identity": {"principalId": "namespace-system"}})
        if text.startswith("role assignment list "):
            assert "--assignee-object-id namespace-system" in text
            assert "--role 'Azure Device Registry Administrator'" in text
            assert f"--scope '{NS_ID}'" in text
            return _output([{"id": "self-role"}] if dps_readiness.called else [])
        if text.startswith("iot dps show "):
            return _output({"id": DPS_ID})
        if text.startswith("iot adr ns link dps wait "):
            return _output(None)
        raise RuntimeError("stop after DPS readiness")

    scenario.cmd.side_effect = command
    with pytest.raises(RuntimeError, match="stop (at|after) DPS readiness"):
        link_scenarios.TestADRLinkLifecycle.test_adr_link_lifecycle(scenario)
    rg = link_scenarios.TEST_RG
    dps_readiness.assert_called_once_with(
        scenario,
        f"iot adr ns link dps add --ns ns -g {rg} -n dps-primary --dps-id {DPS_ID} --user-assigned-mi {UAMI_ID}",
        "ns", rg, "dps-primary",
        {"resourceId": DPS_ID, "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}},
    )
    assert any("link dps wait" in cmd for cmd in _commands(scenario)) is ready
    hub_readiness.assert_not_called()
    scenario.cleanup_full_infra.assert_called_once()


@pytest.mark.parametrize("failure", [
    None, "combined", "final_dps", "final_hub", "setup", "preauthorized",
    "hub_failed", "hub_timeout", "namespace_not_empty", "pending_result",
])
def test_sequential_scenario_exercises_combined_command_without_helper_recovery(monkeypatch, failure):
    from azext_iot.tests.adr._helpers import wait_for_condition

    scenario = Mock()
    clock = Clock()
    monkeypatch.setattr(
        link_scenarios, "wait_for_condition",
        lambda *args, **kwargs: wait_for_condition(*args, **kwargs, clock=clock, sleeper=clock.sleep),
    )
    manager = Mock()
    monkeypatch.setattr(link_scenarios, "LinkRbacManager", manager)
    created = []
    identity = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
    dps = {
        "name": "dps-primary", "resourceId": DPS_ID, "endpointType": DPS_ENDPOINT_TYPE,
        "inboundCallerIdentity": identity, "linkingState": "Succeeded",
    }
    hub = {
        "name": "primary", "resourceId": HUB_ID, "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "inboundCallerIdentity": identity, "linkingState": "Succeeded",
        "provisioning": {"availability": "Available", "allocationWeight": 1},
    }
    monkeypatch.setattr(link_scenarios, "generate_adr_namespace_name", lambda: "ns")
    monkeypatch.setattr(link_scenarios, "generate_dps_name", lambda: "dps")
    monkeypatch.setattr(link_scenarios, "generate_hub_name", lambda: "hub")
    monkeypatch.setattr(link_scenarios, "generate_identity_name", lambda: "uami")
    dps_readiness, hub_readiness = Mock(), Mock()
    monkeypatch.setattr(link_scenarios, "link_dps_with_readiness", dps_readiness)
    monkeypatch.setattr(link_scenarios, "link_hub_with_readiness", hub_readiness)

    def create(command, *, kind, name, resource_group):
        if failure == "setup":
            raise RuntimeError("synthetic setup failure")
        created.append(kind)
        if kind == "hub":
            assert "--no-wait" in command
        return _output({
            "id": {"identity": UAMI_ID, "namespace": NS_ID, "dps": DPS_ID, "hub": HUB_ID}[kind],
            "principalId": "uami-principal",
            "identity": {"type": "SystemAssigned", "principalId": "ns-principal"},
            "properties": {"provisioningState": "Succeeded"},
        })

    def command(text):
        if text.startswith("iot hub show "):
            state = {"hub_failed": "Failed", "hub_timeout": "Creating"}.get(failure, "Active")
            return _output({"id": HUB_ID, "properties": {"state": state}})
        if text.startswith("iot adr ns show "):
            properties = {"provisioningState": "Succeeded"}
            if failure == "namespace_not_empty":
                properties["provisioning"] = {"endpoints": {"unexpected": dps}}
            return _output({
                "id": NS_ID, "properties": properties,
                "identity": {"type": "SystemAssigned", "principalId": "ns-principal"},
            })
        if text.startswith("iot adr ns link add "):
            assert clock() == 0
            manager.assert_not_called()
            assert f"--dps-id {DPS_ID} --dps-user-assigned-mi {UAMI_ID}" in text
            assert f"--hub-id {HUB_ID} --hub-user-assigned-mi {UAMI_ID}" in text
            assert "--hub-availability Available --hub-weight 1" in text
            assert link_scenarios._NATIVE_LINK_OPTIONS in text
            assert "--no-wait" not in text
            if failure == "combined":
                raise RuntimeError("synthetic combined command failure")
            return _output({"properties": {
                "provisioningState": "Succeeded",
                "provisioning": {"endpoints": {
                    "dps-primary": {**dps, "linkingState": "InProgress" if failure == "pending_result" else "Succeeded"},
                }},
                "messaging": {"endpoints": {"primary": hub}},
            }})
        if text.startswith("role assignment list "):
            linked = any(item.args[0].startswith("iot adr ns link add ") for item in scenario.cmd.call_args_list)
            return _output([{"id": "assignment"}] if linked or failure == "preauthorized" else [])
        if text.startswith("iot adr ns link hub list "):
            return _output([{**hub, "linkingState": "Failed" if failure == "final_hub" else "Succeeded"}])
        if text.startswith("iot adr ns link dps list "):
            return _output([{**dps, "linkingState": "Failed" if failure == "final_dps" else "Succeeded"}])
        raise AssertionError(f"Unexpected command: {text}")

    scenario.create_owned_resource.side_effect = create
    scenario.cmd.side_effect = command
    run = link_scenarios.TestADRLinkSequentialAdd.test_adr_link_sequential_add
    if failure:
        error_type = RuntimeError if failure in {"setup", "combined"} else AssertionError
        with pytest.raises(error_type):
            run(scenario)
    else:
        run(scenario)
    commands = _commands(scenario)
    setup_failed = failure in {"setup", "preauthorized", "hub_failed", "hub_timeout", "namespace_not_empty"}
    assert sum(text.startswith("iot adr ns link add ") for text in commands) == (0 if setup_failed else 1)
    if failure != "setup":
        assert created == ["identity", "namespace", "hub", "dps"]
        assert not any("role assignment create " in command for command in commands)
        assert clock() <= 600
        if not setup_failed:
            assert not clock.sleeps
    if failure is None or failure.startswith("final_"):
        assert sum(" link hub list " in text or " link dps list " in text for text in commands) == 2
    dps_readiness.assert_not_called()
    hub_readiness.assert_not_called()
    manager.assert_not_called()
    scenario.cleanup_full_infra.assert_called_once()


@pytest.mark.parametrize("arm_endpoint", [
    "https://centraluseuap.management.azure.com", "https://management.azure.com",
])
@pytest.mark.parametrize("registered_hubs,projection,hub_overrides,expected_failure", [
    ([], [], {}, None),
    ([{"hostName": "classic.azure-devices.net"}], [{"hostName": "classic.azure-devices.net"}], {}, None),
    ([{"name": "CLASSIC.azure-devices.net"}], [{"name": "CLASSIC.azure-devices.net"}], {}, None),
    ([{"name": "classic.azure-devices.net"}], [], {}, "brownfieldHubs"),
    ([], [{"name": "secondary.azure-devices.net"}], {}, "brownfieldHubs"),
    (
        [{"name": "classic.azure-devices.net", "connectionString": "synthetic-original-credential"}],
        [{"name": "classic.azure-devices.net", "connectionString": "synthetic-changed-credential"}],
        {}, "brownfieldHubs",
    ),
    ([], [], {"resourceId": HUB_ID + "-other"}, "Namespace Hub resource ID"),
    ([], [], {"linkingState": "Failed"}, "Namespace Hub linkingState"),
    ([], [], {"linkingState": "InProgress"}, "Namespace Hub linkingState"),
    ([], [], {
        "inboundCallerIdentity": {"type": "SystemAssigned", "userAssignedIdentity": UAMI_ID},
    }, "Namespace Hub inbound identity type"),
    ([], [], {
        "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID + "-other"},
    }, "Namespace Hub selected UAMI"),
    ([], [], {
        "resourceId": HUB_ID.upper(),
        "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID.upper()},
    }, None),
])
def test_link_lifecycle_reads_dps_projection_without_classic_hub_mutation(
    monkeypatch, arm_endpoint, registered_hubs, projection, hub_overrides, expected_failure,
):
    scenario = Mock()
    scenario.setup_full_infra.return_value = {"identity_resource_id": UAMI_ID}
    scenario.create_owned_resource.return_value = _output({
        "id": HUB_ID, "identity": {"type": "SystemAssigned, UserAssigned"},
    })
    monkeypatch.setattr(link_scenarios, "generate_adr_namespace_name", lambda: "ns")
    monkeypatch.setattr(link_scenarios, "generate_dps_name", lambda: "dps")
    monkeypatch.setattr(link_scenarios, "generate_hub_name", Mock(side_effect=["primary", "secondary", "tertiary"]))
    monkeypatch.setattr(link_scenarios, "TEST_ARM_ENDPOINT", arm_endpoint)
    events = []
    monkeypatch.setattr(
        link_scenarios, "link_dps_with_readiness", lambda *_args: events.append("dps ready"),
    )
    monkeypatch.setattr(
        link_scenarios, "link_hub_with_readiness", lambda *_args: events.append("hub ready"),
    )
    dps_shows = []

    def command(text):
        events.append(text)
        if "linked-hub" in text:
            raise AssertionError("The namespace-linked DPS Hub list is read-only")
        if text.startswith("iot adr ns show "):
            return _output({"id": NS_ID, "identity": {"principalId": "namespace-system"}})
        if text.startswith("role assignment list "):
            assert "--assignee-object-id namespace-system" in text
            assert "--role 'Azure Device Registry Administrator'" in text
            assert f"--scope '{NS_ID}'" in text
            return _output([{"id": "self-role"}] if "dps ready" in events else [])
        if text.startswith("iot dps show "):
            return _output({"id": DPS_ID, "properties": {"iotHubs": registered_hubs}})
        if text.startswith("rest "):
            assert shlex.split(text) == [
                "rest", "--method", "get", "--url",
                f"{arm_endpoint}{DPS_ID}?api-version={link_scenarios._ADR_DPS_API_VERSION}",
                "--resource", link_scenarios.TEST_ARM_RESOURCE,
            ]
            return _output({"id": DPS_ID, "properties": {"iotHubs": registered_hubs}})
        if "dps-cap-rejected" in text:
            raise ArgumentUsageError(link_scenarios.DPS_CAP_EXCEEDED_MSG)
        if (
            " identity remove " in text or " --remove identity." in text
            or text.startswith("iot hub create ")
        ):
            raise ArgumentUsageError("identity is used by an active ADR link")
        if text.startswith("iot adr ns link dps show "):
            dps_shows.append(text)
            return _output({
                "name": "dps-primary", "brownfieldHubs": projection if len(dps_shows) == 2 else registered_hubs,
            })
        if text.startswith("iot adr ns link dps list "):
            return _output([{"name": "dps-primary"}])
        if text.startswith("iot adr ns link hub show "):
            return _output({
                "name": "secondary", "resourceId": HUB_ID, "linkingState": "Succeeded",
                "inboundCallerIdentity": {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID},
                **hub_overrides,
            })
        if text.startswith("iot adr ns link hub list "):
            return _output([{"name": "secondary"}])
        if text.startswith("iot hub show "):
            return _output({"properties": {"deviceRegistry": {"namespaceResourceId": NS_ID}}})
        if text.startswith("iot adr ns link dps update "):
            raise RuntimeError("stop after projection assertion")
        assert any(part in text for part in (" wait ", "iot hub update ", "iot hub message-route ")), text
        return _output(None)

    scenario.cmd.side_effect = command
    expected_error = AssertionError if expected_failure else RuntimeError
    with pytest.raises(expected_error) as caught:
        link_scenarios.TestADRLinkLifecycle.test_adr_link_lifecycle(scenario)
    if expected_failure:
        assert expected_failure in str(caught.value)
    else:
        assert str(caught.value) == "stop after projection assertion"
    assert "synthetic-original-credential" not in str(caught.value)
    assert "synthetic-changed-credential" not in str(caught.value)
    hub_failure = expected_failure is not None and expected_failure.startswith("Namespace Hub")
    assert len(dps_shows) == (1 if hub_failure else 2)
    assert events.index("dps ready") < events.index("hub ready")
    if not hub_failure:
        projection_index = max(i for i, text in enumerate(events) if text == dps_shows[-1])
        assert events.index("hub ready") < projection_index
    assert not any("linked-hub" in text for text in _commands(scenario))
    assert sum(text.startswith("rest ") for text in _commands(scenario)) == (0 if hub_failure else 1)
    assert any("link dps update" in text for text in _commands(scenario)) is (expected_failure is None)
    scenario.cleanup_full_infra.assert_called_once()


def test_real_namespace_not_empty_translation_survives_testsdk_context_loss():
    original = HttpResponseError(message=(
        "(NamespaceNotEmpty) Namespace cannot be deleted while it contains child resources: "
        "1 group. Delete these resources before deleting the namespace."
    ))
    original.status_code = 409
    with pytest.raises(AzureResponseError) as caught:
        NamespaceProvider._raise_if_namespace_not_empty(original, "ns")
    translated = _sdk_error(caught.value)
    assert readiness._http_error(translated)[1] is None
    scenario = Mock()
    scenario.cmd.side_effect = [
        _missing("job"), _missing("group"), _output({}), translated,
        _missing("job"), _missing("group"), _output({}), _output([]), _output([]), _output(None),
        _missing("job"), _missing("group"), _missing("namespace"),
    ]
    _cleanup(scenario, Clock())
    assert sum(" delete " in cmd for cmd in _commands(scenario)) == 2


@pytest.mark.parametrize("module,method,jobs,groups", [
    (job_scenarios, job_scenarios.TestADRJobLifecycle.test_adr_job_lifecycle, ("job",), ("group",)),
    (job_scenarios, job_scenarios.TestADRJobLifecycle.test_adr_onboarding_update_job_lifecycle, ("job",), ()),
    (job_scenarios, job_scenarios.TestADRJobValidation.test_adr_job_validation_negatives, ("job",), ("group",)),
    (run_scenarios, run_scenarios.TestADRJobRunSurface.test_adr_job_run_surface_smoke, ("job",), ("group",)),
    (group_scenarios, group_scenarios.TestADRGroupLifecycle.test_adr_group_lifecycle, (), ("group",)),
    (group_scenarios, group_scenarios.TestADRGroupLifecycle.test_adr_group_delete_allows_immediate_name_reuse,
     (), ("group",)),
])
def test_all_job_group_scenarios_pass_known_children_even_after_setup_failure(
    monkeypatch, module, method, jobs, groups,
):
    monkeypatch.setattr(module, "generate_adr_namespace_name", lambda: "ns")
    monkeypatch.setattr(module, "_generate_group_name", lambda: "group")
    if module is not group_scenarios:
        monkeypatch.setattr(module, "_generate_job_name", lambda: "job")
    cleanup = Mock()
    helper_name = "delete_test_namespace" if module is group_scenarios else "_delete_test_namespace"
    monkeypatch.setattr(module, helper_name, cleanup)
    scenario = Mock()

    def command(cmd):
        if "ns create" in cmd or " delete " in cmd:
            return _output({})
        raise RuntimeError("intentional fixture setup failure")

    scenario.cmd.side_effect = command
    with pytest.raises(RuntimeError, match="intentional fixture setup failure"):
        method(scenario)
    expected = {}
    if jobs:
        expected["jobs"] = jobs
    if groups:
        expected["groups"] = groups
    cleanup.assert_called_once_with(scenario, "ns", module.TEST_RG, **expected)
