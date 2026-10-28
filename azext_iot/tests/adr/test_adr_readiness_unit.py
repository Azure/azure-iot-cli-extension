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


@pytest.fixture(autouse=True)
def scoped_subscription(mocker):
    mocker.patch.object(readiness, "get_subscription_id", return_value="sub")


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
    resource_id=NS_ID + "/registryDevices/device", message=None,
):
    error = error_type(message=message or f"({code}) synthetic service error")
    error.status_code = status
    error.error = SimpleNamespace(code=code)
    error.response = SimpleNamespace(
        status_code=status,
        request=HttpRequest(method, f"https://management.azure.com{resource_id}?api-version=2026-11-01"),
    )
    return error


def _missing(kind):
    return _http(resource_id=NS_ID + {
        "device": "/registryDevices/device", "ca": "/certificateAuthorities/ca", "namespace": "",
    }[kind])


def _output(value):
    return Mock(get_output_in_json=lambda: deepcopy(value))


def _cleanup(scenario, clock, **kwargs):
    return readiness.delete_test_namespace(
        scenario, "ns", "rg", devices=("device",), certificate_authorities=("ca",),
        clock=clock, sleeper=clock.sleep, **kwargs,
    )


def _commands(scenario):
    return [call.args[0] for call in scenario.cmd.call_args_list]


def _bounded_update_timeouts(scenario, update_cmd):
    prefix = update_cmd + " --timeout "
    return [int(command[len(prefix):]) for command in _commands(scenario) if command.startswith(prefix)]


def test_owned_device_and_ca_require_exact_get_404_before_namespace_delete():
    clock = Clock()
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output({"properties": {"provisioningState": "Deleting"}}), _http(),
        _output({}), _output({}), _sdk_error(_missing("ca")),
        _output({"properties": {"provisioningState": "Succeeded"}}), _output(None),
        _missing("device"), _missing("ca"), _missing("namespace"),
    ]
    _cleanup(scenario, clock)
    commands = _commands(scenario)
    assert "device show" in commands[0]
    assert "ca show" in commands[2]
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
    assert "device show" in _commands(scenario)[0]


@pytest.mark.parametrize("output", [None, "", []])
def test_blank_get_is_not_absence(output):
    scenario = Mock()
    scenario.cmd.return_value = _output(output)
    with pytest.raises(AssertionError, match="not HTTP 404"):
        _cleanup(scenario, Clock())
    assert scenario.cmd.call_count == 1


@pytest.mark.parametrize("url,method", [
    ("https://login.microsoftonline.com/tenant/oauth2/token", "GET"),
    ("https://management.azure.com" + NS_ID + "/certificateAuthorities/other", "GET"),
    ("https://management.azure.com" + NS_ID + "/registryDevices/device", "POST"),
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
    missing.response.request.url = "https://management.azure.com" + NS_ID + "/registryDevices/device?api-version=preview"
    scenario = Mock()
    scenario.cmd.side_effect = wrap(missing)
    assert readiness._get_resource(scenario, "iot adr ns device show --namespace ns -g rg -n device") is None


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
    error = _missing("device")
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
    error = _cli_exit(_missing("device"), code=code)
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
        scenario.cmd.side_effect = lambda _command: client.namespaces.get("rg", "ns")
        with pytest.raises(HttpResponseError) as caught:
            _cleanup(scenario, Clock())
    assert caught.value is error
    assert credential.get_token.call_count == 1
    assert not mocked_response.calls
    assert scenario.cmd.call_count == 1


def test_real_sdk_get_404_and_testsdk_rethrow_gate_bounded_namespace_delete(mocked_response, mocker):
    namespace_url = "https://management.azure.com" + NS_ID
    absent = {"error": {"code": "ResourceNotFound", "message": "Owned resource was deleted"}}
    mocked_response.add("GET", namespace_url + "/registryDevices/device", status=404, json=absent)
    mocked_response.add(
        "GET", namespace_url + "/certificateAuthorities/ca", json={"properties": {"provisioningState": "Deleting"}},
    )
    mocked_response.add("GET", namespace_url + "/certificateAuthorities/ca", status=404, json=absent)
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

        def command(text, **_):
            try:
                if "device show" in text:
                    return _output(client.registry_devices.get("rg", "ns", "device"))
                if "ca show" in text:
                    return _output(client.certificate_authorities.get("rg", "ns", "ca"))
                if "ns show" in text:
                    return _output(client.namespaces.get("rg", "ns"))
                assert text == "iot adr ns delete --namespace ns -g rg -y --no-wait"
                provider.delete("ns", "rg", no_wait=True)
                return _output(None)
            except HttpResponseError as error:
                shaped = _sdk_error(error)
                proofs.append(shaped)
                raise shaped

        _cleanup(SimpleNamespace(cmd=command, cli_ctx=Mock(data={"subscription_id": "sub"})), clock)
    assert clock.sleeps == [10, 10]
    assert len(proofs) == 5
    assert all(error.response.status_code == 404 and error.response.request.method == "GET" for error in proofs)
    assert [(call.request.method, urlsplit(call.request.url).path) for call in mocked_response.calls] == [
        ("GET", NS_ID + "/registryDevices/device"),
        ("GET", NS_ID + "/certificateAuthorities/ca"),
        ("GET", NS_ID + "/certificateAuthorities/ca"),
        ("GET", NS_ID),
        ("DELETE", NS_ID),
        ("GET", NS_ID + "/registryDevices/device"),
        ("GET", NS_ID + "/certificateAuthorities/ca"),
        ("GET", NS_ID),
    ]


def test_lingering_child_exhausts_deadline_without_parent_delete():
    clock = Clock()
    scenario = Mock()
    scenario.cmd.return_value = _output({})
    with pytest.raises(AssertionError, match="owned device GET still readable"):
        _cleanup(scenario, clock, timeout=25)
    assert clock.sleeps == [10, 10, 5]
    assert all("device show" in command for command in _commands(scenario))


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
        _missing("device"), _missing("ca"), _output({}), rejection,
        _missing("device"), _missing("ca"), _output({}), _output([]), _output([]), _output(None),
        _missing("device"), _missing("ca"), _missing("namespace"),
    ]
    clock = Clock()
    _cleanup(scenario, clock)
    commands = _commands(scenario)
    assert sum(" delete " in command for command in commands) == 2
    assert commands[4:6] == commands[:2]
    assert commands[7:9] == [
        "iot adr ns device list --namespace ns -g rg",
        "iot adr ns ca list --namespace ns -g rg",
    ]
    assert clock.sleeps == [10, 10]


def test_child_index_rejection_without_owned_children_uses_only_ga_lists():
    rejection = _http(409, "NamespaceNotEmpty", method="DELETE", resource_id=NS_ID)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output({}), rejection, _output({}), _output([]), _output([]), _output(None), _missing("namespace"),
    ]
    clock = Clock()
    readiness.delete_test_namespace(scenario, "ns", "rg", clock=clock, sleeper=clock.sleep)
    assert _commands(scenario) == [
        "iot adr ns show --namespace ns -g rg",
        "iot adr ns delete --namespace ns -g rg -y --no-wait",
        "iot adr ns show --namespace ns -g rg",
        "iot adr ns device list --namespace ns -g rg",
        "iot adr ns ca list --namespace ns -g rg",
        "iot adr ns delete --namespace ns -g rg -y --no-wait",
        "iot adr ns show --namespace ns -g rg",
    ]
    assert clock.sleeps == [10, 10]


@pytest.mark.parametrize("kind", ["device", "ca"])
@pytest.mark.parametrize("children", [[{"name": "foreign"}], None, {}])
def test_foreign_or_unproven_children_prevent_replaying_rejected_namespace_delete(kind, children):
    rejection = _http(409, "NamespaceNotEmpty", method="DELETE", resource_id=NS_ID)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _missing("device"), _missing("ca"), _output({}), rejection,
        _missing("device"), _missing("ca"), _output({}),
        *([_output([])] if kind == "ca" else []), _output(children),
    ]
    with pytest.raises(HttpResponseError) as raised:
        _cleanup(scenario, Clock())
    assert raised.value is rejection
    assert sum(" delete " in cmd for cmd in _commands(scenario)) == 1
    assert _commands(scenario)[-1] == f"iot adr ns {kind} list --namespace ns -g rg"


@pytest.mark.parametrize("error", [
    AzureResponseError("(NamespaceNotEmpty) metadata-less error"),
    _http(409, "Conflict", method="DELETE", resource_id=NS_ID),
    _http(409, "NamespaceNotEmpty", method="GET", resource_id=NS_ID),
    _http(202, "NamespaceNotEmpty", method="DELETE", resource_id=NS_ID),
    ServiceRequestError("DELETE timed out after acceptance"),
])
def test_uncertain_or_unrelated_delete_error_is_never_replayed(error):
    scenario = Mock()
    scenario.cmd.side_effect = [_missing("device"), _missing("ca"), _output({}), error]
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
    scenario.cmd.side_effect = [_missing("device"), _missing("ca"), _output({}), error]
    with pytest.raises(HttpResponseError) as caught:
        _cleanup(scenario, Clock())
    assert caught.value is error
    assert len(_commands(scenario)) == 4


@pytest.mark.parametrize("already_deleting", [False, True])
def test_accepted_delete_only_polls_even_if_namespace_state_is_stale(already_deleting):
    scenario = Mock()
    accepted = [already_deleting]

    def command(cmd, **_):
        if "device show" in cmd:
            raise _missing("device")
        if "ca show" in cmd:
            raise _missing("ca")
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

    def command(text, **_):
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


@pytest.mark.parametrize("settings", [None, {}, {"availability": "Disabled"}, {"allocationWeight": 31}])
def test_readiness_accepts_late_hub_settings_without_replaying_add(settings):
    expected = _expected("hub")
    expected.pop("provisioning")
    if settings is not None:
        expected["provisioning"] = deepcopy(settings)
    failed = _namespace(expected=expected)
    populated = {**expected, "provisioning": {
        "availability": "Available", "allocationWeight": 1, **(settings or {}),
    }}
    succeeded = _namespace("Succeeded", "Succeeded", populated)
    succeeded["properties"]["messaging"]["endpoints"]["secondary"].pop("linkingError")
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None), _output(failed), _output(failed), _output(None), _output(succeeded),
    ]
    endpoint = _link(scenario, Clock(), expected)
    assert endpoint["linkingState"] == "Succeeded"
    assert endpoint["provisioning"] == populated["provisioning"]
    commands = _commands(scenario)
    assert sum(" add " in command for command in commands) == 1
    assert commands[3] == failed_link_recovery_commands(failed)[0] + " --no-wait"


@pytest.mark.parametrize("changed", [
    {}, {"availability": "Disabled", "allocationWeight": 1},
    {"availability": "Available", "allocationWeight": 2},
])
def test_readiness_freezes_service_populated_hub_settings(changed):
    expected = _expected("hub")
    expected.pop("provisioning")
    populated = {**expected, "provisioning": {"availability": "Available", "allocationWeight": 1}}
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None), _output(_namespace("Updating", "InProgress", expected)),
        _output(_namespace("Updating", "InProgress", populated)),
        _output(_namespace("Succeeded", "Succeeded", {**expected, "provisioning": changed})),
    ]
    with pytest.raises(AssertionError, match="settings changed"):
        _link(scenario, Clock(), expected)
    assert not any(" update " in command for command in _commands(scenario))


def _hub_data_read_message(host, context=""):
    return (
        f"The namespace's managed identity could not read the device count on hub '{host}'{context} because it lacks "
        "IoT Hub data-plane read access. Assign it a role that grants IoT Hub data-plane read "
        "(for example IoT Hub Data Reader) on the hub, then resubmit the request."
    )


@pytest.mark.parametrize("contextual", [False, True])
def test_hub_data_plane_read_failure_for_the_linked_hub_is_recovered(contextual):
    expected = _expected("hub")
    host = expected["resourceId"].rsplit("/", 1)[1].lower() + ".service.azure-devices.net"
    context = f" (endpoint 'secondary' being linked, resource '{HUB_ID}')" if contextual else ""
    failed = _namespace(expected=expected, message=_hub_data_read_message(host, context))
    if contextual:
        failed["properties"]["messaging"]["endpoints"]["secondary"]["linkingError"]["code"] = "AdrMiNotAuthorized"
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(None), _output(failed), _output(failed), _output(None),
        _output(_namespace("Succeeded", "Succeeded", expected)),
    ]

    endpoint = _link(scenario, Clock(), expected)

    assert endpoint["linkingState"] == "Succeeded"
    commands = _commands(scenario)
    assert sum(" update " in command for command in commands) == 1
    suffix = " --timeout 590" if contextual else " --no-wait"
    assert commands[3] == failed_link_recovery_commands(failed)[0] + suffix
    assert all(endpoint[key] == value for key, value in expected.items())


@pytest.mark.parametrize("contextual", [False, True])
@pytest.mark.parametrize("kind,host", [("hub", "otherhub.service.azure-devices.net"), ("dps", None)])
def test_hub_data_plane_read_failure_is_bound_to_the_linked_hub(kind, host, contextual):
    expected = _expected(kind)
    host = host or expected["resourceId"].rsplit("/", 1)[1].lower() + ".service.azure-devices.net"
    context = f" (endpoint '{LINKS[kind][2]}' being linked, resource '{expected['resourceId']}')" if contextual else ""
    message = _hub_data_read_message(host, context)
    failed = _namespace(expected=expected, message=message, kind=kind)
    if contextual:
        section, _, name = LINKS[kind]
        failed["properties"][section]["endpoints"][name]["linkingError"]["code"] = "AdrMiNotAuthorized"
    scenario = Mock()
    scenario.cmd.side_effect = [_output(None), _output(failed)]

    with pytest.raises(AssertionError, match="Non-recoverable (Hub|DPS) link failure"):
        _link(scenario, Clock(), expected, kind=kind)

    assert scenario.cmd.call_count == 2


@pytest.mark.parametrize("mutation", ["endpoint", "resource", "code", "details", "suffix"])
def test_contextual_hub_read_failure_requires_exact_endpoint_resource_and_error(mutation):
    name = "other-endpoint" if mutation == "endpoint" else "secondary"
    target = HUB_ID.replace("/rg/", "/other-rg/") if mutation == "resource" else HUB_ID
    message = _hub_data_read_message(
        "hub.service.azure-devices.net", f" (endpoint '{name}' being linked, resource '{target}')"
    )
    failed = _namespace(message=message)
    error = failed["properties"]["messaging"]["endpoints"]["secondary"]["linkingError"]
    error["code"] = "AdrMiNotAuthorized"
    if mutation == "code":
        error["code"] = "AuthorizationFailed"
    elif mutation == "details":
        error["details"] = [{"code": "OtherFailure"}]
    elif mutation == "suffix":
        error["message"] += " Another failure occurred."
    scenario = Mock()
    scenario.cmd.side_effect = [_output(None), _output(failed)]

    with pytest.raises(AssertionError, match="Non-recoverable Hub link failure"):
        _link(scenario, Clock())

    assert scenario.cmd.call_count == 2


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

    def command(cmd, **_):
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


@pytest.mark.parametrize("failure", [False, True])
def test_waited_recovery_charges_remaining_deadline_and_preserves_errors(link_kind, failure):
    scenario = Mock()
    clock = Clock()
    error = AzureResponseError("Authoritative recovery operation failed")
    namespace = _namespace(kind=link_kind)
    section, _, name = LINKS[link_kind]
    namespace["properties"][section]["endpoints"][name]["linkingError"]["code"] = "AdrMiNotAuthorized"

    def command(text):
        if " update " in text:
            assert text.endswith("--timeout 34")
            clock.now += 35
            if failure:
                raise error
            return _output(None)
        clock.now += 0.25
        return _output(namespace)

    scenario.cmd.side_effect = command
    with pytest.raises(AzureResponseError if failure else AssertionError) as caught:
        _link(scenario, clock, kind=link_kind, timeout=45)
    if failure:
        assert caught.value is error
    else:
        assert "Timed out" in str(caught.value)
    assert sum(" update " in cmd for cmd in _commands(scenario)) == 1
    assert " update " in _commands(scenario)[-1]


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
@pytest.mark.parametrize("section", ["messaging", "provisioning", ])
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

    def command(_cmd, **_):
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


@pytest.mark.parametrize("kind", ["unknown", "messaging", None])
def test_readiness_kind_whitelist_rejects_unsupported_services_before_any_command(kind):
    scenario = Mock()
    with pytest.raises(AssertionError, match="only owned Hub/DPS adds"):
        readiness.link_with_readiness(
            scenario, ADD, "ns", "rg", "secondary", EXPECTED, link_kind=kind,
        )
    scenario.cmd.assert_not_called()


@pytest.mark.parametrize("command", [

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
        def command(text, **_):
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

    def command(text, **_):
        if text.startswith("iot adr ns show "):
            return _output({"id": NS_ID, "identity": {"type": "SystemAssigned", "principalId": "namespace-system"}})
        if text.startswith("role assignment list "):
            assert "--assignee-object-id namespace-system" in text
            assert "--role 'Azure Device Registry Administrator'" in text
            assert f"--scope '{NS_ID}'" in text
            return _output([{"id": "self-role"}] if dps_readiness.called else [])
        if text.startswith("iot dps show "):
            return _output({"id": DPS_ID, "identity": {
                "principalId": "dps-system", "userAssignedIdentities": {UAMI_ID: {"principalId": "dps-user"}},
            }})
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


def _rotation_endpoint(state="Failed", identity_type="UserAssigned", *, code="IdentityRotationUpdateFailed", message=None):
    identity = {"type": identity_type}
    if identity_type == "UserAssigned":
        identity["userAssignedIdentity"] = UAMI_ID
    endpoint = {
        "resourceId": HUB_ID,
        "endpointType": IOT_HUB_ENDPOINT_TYPE,
        "linkingState": state,
        "inboundCallerIdentity": identity,
    }
    if state == "Failed":
        endpoint["linkingError"] = {
            "code": code,
            "message": message or (
                "IdentityRotationUpdateFailed: Hub resource reported IH400913: "
                "the system-assigned identity was denied namespace read access."
            ),
        }
    return endpoint


@pytest.mark.parametrize("message,expected", [
    ("IdentityRotationUpdateFailed: Hub resource reported IH400913: denied namespace read.", True),
    ("IdentityRotationUpdateFailed: AuthorizationFailed while reading namespace.", True),
    ("IdentityRotationUpdateFailed: target identity shape changed.", False),
    ("IH400913: denied namespace read.", True),
    ("Authentication failed: IdentityRotationUpdateFailed.", False),
    (
        "IdentityRotationUpdateFailed: The Hub resource rejected the link request as invalid. "
        "Verify the endpoint configuration, then resubmit the request.",
        True,
    ),
    (
        "IdentityRotationUpdateFailed: The DPS resource rejected the link request as invalid. "
        "Verify the endpoint configuration, then resubmit the request.",
        False,
    ),
    ("IdentityRotationUpdateFailed: The Hub resource rejected the link request as invalid.", False),
    (
        "IdentityRotationUpdateFailed: retry later. The Hub resource rejected the link request as invalid. "
        "Verify the endpoint configuration, then resubmit the request.",
        False,
    ),
])
def test_hub_rotation_authorization_classifier_is_specific(message, expected):
    endpoint = _rotation_endpoint(message=message)
    assert link_scenarios._is_identity_rotation_authorization_failure(endpoint=endpoint) is expected


def test_hub_rotation_authorization_classifier_requires_identity_rotation_code():
    endpoint = _rotation_endpoint(code="LinkUpdateFailed", message="IH400913: denied namespace read.")
    assert not link_scenarios._is_identity_rotation_authorization_failure(endpoint=endpoint)


_HUB_REJECTED = (
    "The Hub resource rejected the link request as invalid. Verify the endpoint configuration, then resubmit the request."
)


def _rotation_namespace():
    return {
        "id": NS_ID, "identity": {"type": "SystemAssigned", "principalId": "namespace-principal"},
        "properties": {
            "provisioningState": "Succeeded",
            "messaging": {"endpoints": {"secondary": _rotation_endpoint("Succeeded", "UserAssigned")}},
        },
    }


def _rotation_rejection(message=None):
    message = message or link_scenarios._HUB_ROTATION_CURRENT_MESSAGE
    error = _http(200, "LinkingFailed", resource_id=(
        "/subscriptions/sub/providers/Microsoft.DeviceRegistry/locations/centraluseuap/asyncOperationStatuses/rotation"
    ), message="(LinkingFailed) Failed. (IdentityRotationUpdateFailed) " + message)
    error.response.json = lambda: {
        "status": "Failed", "error": {
            "code": "LinkingFailed", "message": "Failed.",
            "details": [{
                "code": "IdentityRotationUpdateFailed", "message": message, "target": "properties.messaging.endpoints[secondary]",
            }],
        },
    }
    return error


def test_hub_rotation_rejection_requires_structural_or_attributed_evidence():
    from azure.core.exceptions import HttpResponseError

    extra = _rotation_endpoint(message=_HUB_REJECTED)
    extra["linkingError"]["details"] = [{"code": "Other"}]
    wrong_code = _rotation_endpoint(code="LinkInitiateFailed", message="IdentityRotationUpdateFailed: " + _HUB_REJECTED)
    not_failed = _rotation_endpoint(message=_HUB_REJECTED)
    not_failed["linkingState"] = "Succeeded"
    for endpoint in (extra, wrong_code, not_failed):
        assert not link_scenarios._is_identity_rotation_authorization_failure(endpoint=endpoint)
    assert link_scenarios._is_identity_rotation_authorization_failure(endpoint=_rotation_endpoint(message=_HUB_REJECTED))

    detached = HttpResponseError("(IdentityRotationUpdateFailed) Rotation failed. (LinkFailed) " + _HUB_REJECTED)
    attributed = HttpResponseError("(LinkingFailed) Failed. (IdentityRotationUpdateFailed) " + _HUB_REJECTED)
    rolled_back = _rotation_endpoint("Succeeded", "UserAssigned")
    assert not link_scenarios._is_identity_rotation_authorization_failure(error=detached, endpoint=rolled_back)
    assert link_scenarios._is_identity_rotation_authorization_failure(error=attributed, endpoint=rolled_back)


@pytest.mark.parametrize("outbound_user", [False, True])
def test_hub_rotation_recovery_reissues_same_update_after_grants_are_visible(monkeypatch, outbound_user):
    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    scenario = Mock()
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    roles = [{"id": "role"}]
    namespace = _rotation_namespace()
    if outbound_user:
        namespace["identity"]["userAssignedIdentities"] = {UAMI_ID: {"principalId": "namespace-user"}}
        namespace["identity"]["type"] = "SystemAssigned, UserAssigned"
        namespace["properties"]["outboundIdentity"] = {"type": "UserAssigned", "userAssignedIdentity": UAMI_ID}
    responses = [
        _output(namespace),
        _rotation_rejection(),
        _output(_rotation_endpoint()),
        _output(namespace),
        _output({"identity": {"principalId": "hub-sami"}}),
        *[_output(roles) for _ in range(6)],
        _output(None),
        _output(_rotation_endpoint("Succeeded", "SystemAssigned")),
    ]
    scenario.cmd.side_effect = responses

    result = link_scenarios._update_hub_to_sami_with_recovery(
        scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
    )

    assert result["linkingState"] == "Succeeded"
    assert clock.sleeps == [30]
    commands = _commands(scenario)
    assert _bounded_update_timeouts(scenario, update_cmd) == [600, 570]
    assert update_cmd not in commands
    assert any("role assignment list" in command and "hub-sami" in command for command in commands)
    outbound = "namespace-user" if outbound_user else "namespace-principal"
    assert sum(f"--assignee-object-id {outbound} " in command for command in commands) == 4


def test_hub_rotation_current_wrapper_requires_exact_rotation_attribution():
    from types import SimpleNamespace
    from azure.core.exceptions import HttpResponseError

    message = link_scenarios._HUB_ROTATION_CURRENT_MESSAGE
    endpoint = _rotation_endpoint(message=message)
    assert link_scenarios._is_identity_rotation_authorization_failure(endpoint=endpoint)
    chained = HttpResponseError("(LinkingFailed) Failed. (IdentityRotationUpdateFailed) " + message)
    chained.error = SimpleNamespace(code="IdentityRotationUpdateFailed")
    rolled_back = _rotation_endpoint("Succeeded", "UserAssigned")
    assert link_scenarios._is_identity_rotation_authorization_failure(error=chained, endpoint=rolled_back)
    for invalid in (message.replace("[400913]", "[400914]"), message + " Another failure.", message.replace("Hub", "DPS")):
        assert not link_scenarios._is_identity_rotation_authorization_failure(
            endpoint=_rotation_endpoint(message=invalid),
        )
    assert not link_scenarios._is_identity_rotation_authorization_failure(
        endpoint=_rotation_endpoint(code="LinkInitiateFailed", message=message),
    )
    endpoint["error"] = {"code": "OtherFailure", "message": "different failure"}
    assert not link_scenarios._is_identity_rotation_authorization_failure(error=chained, endpoint=endpoint)
    mixed = HttpResponseError("(OtherFailure) Failed.\n(IdentityRotationUpdateFailed) " + message)
    assert not link_scenarios._is_identity_rotation_authorization_failure(error=mixed, endpoint=rolled_back)


@pytest.mark.parametrize("route", ["asyncOperationStatuses", "operationStatuses"])
@pytest.mark.parametrize("message", [_HUB_REJECTED, link_scenarios._HUB_ROTATION_CURRENT_MESSAGE])
def test_hub_rotation_requires_real_sdk_terminal_rejection(mocked_response, route, message):
    from azure.mgmt.core.polling.arm_polling import ARMPolling

    status_url = f"https://management.azure.com/subscriptions/sub/providers/Microsoft.DeviceRegistry/locations/eastus/{route}/op"
    mocked_response.add(
        "PUT", "https://management.azure.com" + NS_ID, status=201,
        json={"properties": {"provisioningState": "Accepted"}}, headers={"Azure-AsyncOperation": status_url},
    )
    mocked_response.add("GET", status_url, json=_rotation_rejection(message).response.json())
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    with DeviceRegistryMgmtClient(credential, "sub", retry_total=0, polling_interval=0) as client:
        with pytest.raises(HttpResponseError) as raised:
            client.namespaces.begin_create_or_replace("rg", "ns", {"location": "eastus"}, polling=ARMPolling(0)).result()
    assert link_scenarios._current_rotation_rejection(raised.value, NS_ID, "secondary")
    assert link_scenarios._is_identity_rotation_authorization_failure(
        error=raised.value, endpoint=_rotation_endpoint("Succeeded", "UserAssigned"),
    )
    assert not link_scenarios._current_rotation_rejection(raised.value, NS_ID.replace("/sub/", "/other/"), "secondary")
    assert not link_scenarios._current_rotation_rejection(raised.value, NS_ID, "other")


@pytest.mark.parametrize("invalid", ["transport", "status", "method", "route", "mixed-detail"])
def test_hub_rotation_rejects_unproven_current_attempt(invalid):
    from azure.core.exceptions import ServiceResponseError

    error = _rotation_rejection()
    if invalid == "transport":
        error.__cause__ = ServiceResponseError("Response lost")
    elif invalid == "status":
        error.status_code = 400
    elif invalid == "method":
        error.response.request.method = "PUT"
    elif invalid == "route":
        error.response.request.url = "https://management.azure.com" + NS_ID
    else:
        body = error.response.json()
        body["error"]["details"].append({"code": "OtherFailure", "message": "Unrelated."})
        error.response.json = lambda: body
    assert not link_scenarios._current_rotation_rejection(error, NS_ID, "secondary")


@pytest.mark.parametrize("late_stage", ["baseline", "sleep", "terminal-success"])
def test_hub_rotation_deadline_rejects_oversleep_and_late_success(monkeypatch, late_stage):
    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", lambda _: setattr(clock, "now", 600.4))
    monkeypatch.setattr(link_scenarios, "_assert_hub_sami_rotation_grants", lambda *_: None)

    def terminal(*_args, **_kwargs):
        if late_stage == "terminal-success":
            clock.now = 600
            return _rotation_endpoint("Succeeded", "SystemAssigned")
        return _rotation_endpoint()

    monkeypatch.setattr(link_scenarios, "_wait_for_link_terminal", terminal)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(_rotation_namespace()), _rotation_rejection() if late_stage == "sleep" else _output(None),
    ]
    if late_stage == "baseline":
        def slow_baseline(_command):
            clock.now = 600
            return _output(_rotation_namespace())
        scenario.cmd.side_effect = slow_baseline
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    with pytest.raises(AssertionError, match="budget exhausted"):
        link_scenarios._update_hub_to_sami_with_recovery(
            scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
        )
    assert _bounded_update_timeouts(scenario, update_cmd) == ([] if late_stage == "baseline" else [600])


def test_hub_rotation_recovery_retries_chained_hub_rejection_after_identity_rollback(monkeypatch):
    from azure.cli.core.azclierror import AzureResponseError

    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    service_error = _rotation_rejection(_HUB_REJECTED)
    product_error = AzureResponseError(
        "Link target, type, inbound identity or settings changed; recovery stopped."
    )
    product_error.__cause__ = service_error
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    roles = [{"id": "role"}]
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(_rotation_namespace()),
        product_error,
        _output(_rotation_endpoint("Succeeded", "UserAssigned")),
        _output(_rotation_namespace()),
        _output({"identity": {"principalId": "hub-sami"}}),
        *[_output(roles) for _ in range(6)],
        _output(None),
        _output(_rotation_endpoint("Succeeded", "SystemAssigned")),
    ]

    result = link_scenarios._update_hub_to_sami_with_recovery(
        scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
    )

    assert result["inboundCallerIdentity"]["type"] == "SystemAssigned"
    assert clock.sleeps == [30]
    assert _bounded_update_timeouts(scenario, update_cmd) == [600, 570]


def test_hub_rotation_recovery_never_resubmits_after_its_budget(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    waits = []

    def terminal(*_, timeout, **__):
        waits.append(timeout)
        clock.now += 250  # Each observation (and synchronous update) consumes budget.
        return _rotation_endpoint()

    monkeypatch.setattr(link_scenarios, "_wait_for_link_terminal", terminal)
    monkeypatch.setattr(link_scenarios, "_assert_hub_sami_rotation_grants", lambda *_: None)
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(_rotation_namespace()), _rotation_rejection(), _rotation_rejection(), _rotation_rejection(),
    ]

    with pytest.raises(AssertionError, match="budget exhausted"):
        link_scenarios._update_hub_to_sami_with_recovery(
            scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
        )

    assert all(timeout > 0 for timeout in waits)
    assert clock.now <= link_scenarios._HUB_IDENTITY_ROTATION_BUDGET_SECONDS + 250
    timeouts = _bounded_update_timeouts(scenario, update_cmd)
    assert len(timeouts) == 3 and timeouts[0] == 600
    # Every synchronous mutation is capped by the budget remaining when it is submitted.
    assert all(0 < later < earlier for earlier, later in zip(timeouts, timeouts[1:]))
    assert clock.sleeps == [30, 60]


def test_hub_rotation_recovery_rejects_changed_target_before_retry(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    changed = _rotation_endpoint()
    changed["resourceId"] = HUB_ID + "-other"
    scenario = Mock()
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    scenario.cmd.side_effect = [_output(_rotation_namespace()), _rotation_rejection(), _output(changed)]

    with pytest.raises(AssertionError, match="resourceId"):
        link_scenarios._update_hub_to_sami_with_recovery(
            scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
        )

    assert _commands(scenario) == [
        "iot adr ns show -n ns -g rg",
        update_cmd + " --timeout 600",
        "iot adr ns link hub show --ns ns -g rg -n secondary",
    ]


@pytest.mark.parametrize("failure", ["uncertain", "drift", "keyerror", "success"])
def test_hub_rotation_never_uses_stale_failure_to_replay_an_unproven_write(monkeypatch, failure):
    from azure.core.exceptions import ServiceResponseError

    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    error = {
        "uncertain": AzureResponseError("Outcome unknown"),
        "drift": AzureResponseError("Settings changed; recovery stopped"),
        "keyerror": KeyError("unexpected"),
        "success": None,
    }[failure]
    if failure == "uncertain":
        error.__cause__ = ServiceResponseError("Connection lost")
    scenario = Mock()
    scenario.cmd.side_effect = [
        _output(_rotation_namespace()), error or _output(None), _output(_rotation_endpoint()),
    ]
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    with pytest.raises(type(error) if error else AssertionError) as raised:
        link_scenarios._update_hub_to_sami_with_recovery(
            scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
        )
    if error:
        assert raised.value is error
    assert _bounded_update_timeouts(scenario, update_cmd) == [600]
    assert not clock.sleeps


@pytest.mark.parametrize("state,identity", [("Failed", "UserAssigned"), ("Succeeded", "SystemAssigned")])
def test_hub_rotation_preserves_pre_submit_settings_on_retry_and_success(monkeypatch, state, identity):
    clock = Clock()
    monkeypatch.setattr(link_scenarios, "monotonic", clock)
    monkeypatch.setattr(link_scenarios, "sleep", clock.sleep)
    baseline = _rotation_namespace()
    baseline["properties"]["messaging"]["endpoints"]["secondary"]["provisioning"] = {"allocationWeight": 2}
    changed = _rotation_endpoint(state, identity)
    changed["provisioning"] = {"allocationWeight": 3}
    scenario = Mock()
    scenario.cmd.side_effect = [_output(baseline), _rotation_rejection(), _output(changed)]
    update_cmd = "iot adr ns link hub update --ns ns -g rg -n secondary --system-assigned-mi"
    with pytest.raises(AssertionError, match="endpoint settings changed"):
        link_scenarios._update_hub_to_sami_with_recovery(
            scenario, update_cmd, "ns", "rg", "secondary", HUB_ID, UAMI_ID,
        )
    assert _bounded_update_timeouts(scenario, update_cmd) == [600]
    assert not clock.sleeps


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
    monkeypatch.setattr("azext_iot.adr.rbac.LinkRbacManager", manager)
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

    def command(text, **_):
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
    grant_deleted = False

    def command(text, expect_failure=False, **_):
        nonlocal grant_deleted
        events.append(text)
        if "linked-hub" in text:
            raise AssertionError("The namespace-linked DPS Hub list is read-only")
        if text.startswith("iot adr ns identity show "):
            return _output({"type": "SystemAssigned", "principalId": "namespace-system"})
        if text.startswith("iot adr ns show "):
            return _output({"id": NS_ID, "identity": {"type": "SystemAssigned", "principalId": "namespace-system"}})
        if text.startswith("role assignment list "):
            if "--role 'IoT Hub Data Contributor'" in text:
                assert "--assignee-object-id dps-user" in text
                assert f"--scope '{HUB_ID}'" in text
                return _output([{"id": "owned-grant", "scope": HUB_ID, "principalId": "dps-user"}]
                               if "hub ready" in events and not grant_deleted else [])
            assert "--assignee-object-id namespace-system" in text
            assert "--role 'Azure Device Registry Administrator'" in text
            assert f"--scope '{NS_ID}'" in text
            return _output([{"id": "self-role"}] if "dps ready" in events else [])
        if text == "role assignment delete --ids owned-grant":
            grant_deleted = True
            return _output(None)
        if text.startswith("iot adr ns link hub update "):
            grant_deleted = False
            return _output(None)
        if text.startswith("iot dps show "):
            return _output({"id": DPS_ID, "properties": {"iotHubs": registered_hubs}, "identity": {
                "principalId": "dps-system", "userAssignedIdentities": {UAMI_ID: {"principalId": "dps-user"}},
            }})
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
            if expect_failure:
                return _output({})
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
        "1 registry device. Delete these resources before deleting the namespace."
    ))
    original.status_code = 409
    with pytest.raises(AzureResponseError) as caught:
        NamespaceProvider._raise_if_namespace_not_empty(original, "ns")
    translated = _sdk_error(caught.value)
    assert readiness._http_error(translated)[1] is None
    scenario = Mock()
    scenario.cmd.side_effect = [
        _missing("device"), _missing("ca"), _output({}), translated,
        _missing("device"), _missing("ca"), _output({}), _output([]), _output([]), _output(None),
        _missing("device"), _missing("ca"), _missing("namespace"),
    ]
    _cleanup(scenario, Clock())
    assert sum(" delete " in cmd for cmd in _commands(scenario)) == 2
