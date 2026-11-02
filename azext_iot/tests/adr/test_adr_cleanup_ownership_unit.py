# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
import responses
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ServiceRequestError
from azure.core.pipeline import Pipeline
from azure.core.pipeline.policies import RetryPolicy
from azure.core.pipeline.transport import HttpRequest, RequestsTransport
from knack.util import CLIError
from requests.exceptions import ConnectionError as RequestsConnectionError

from azext_iot.tests.adr._helpers import ADRFullInfraHelper, is_resource_not_found_error, LINK_ROLE_IDS, READER_ROLE


def _http_error(status=None, code=None):
    error = HttpResponseError(message="ResourceNotFound (404): misleading text")
    error.status_code = status
    if code:
        error.error = SimpleNamespace(code=code)
    return error


@pytest.mark.parametrize("outcome", ["created", "uncertain", "conflict", "foreign", "binding-changed"])
def test_owned_identity_cleanup_tracks_only_its_native_rg_reader(mocker, outcome):
    helper = ADRFullInfraHelper()
    principal = "11111111-2222-3333-4444-555555555555"
    resource = ("identity", "owned", "rg")
    result = Mock()
    result.get_output_in_json.return_value = {"principalId": principal}
    helper.cmd = Mock(side_effect=[_http_error(404, "ResourceNotFound"), result])
    helper.create_owned_resource("identity create -n owned -g rg", kind="identity", name="owned", resource_group="rg")
    assert helper._owned_principals[resource] == principal
    group = "/subscriptions/sub/resourceGroups/rg"
    role = {
        "id": group + "/providers/Microsoft.Authorization/roleAssignments/role-id",
        "name": "role-id", "scope": group, "principalId": principal if outcome != "foreign" else "someone-else",
        "principalType": "ServicePrincipal",
        "roleDefinitionId": "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/"
        + LINK_ROLE_IDS[READER_ROLE],
    }
    request = HttpRequest("PUT", "https://management.azure.com" + role["id"])
    request.set_json_body({"properties": {key: role[key] for key in ("principalId", "principalType", "roleDefinitionId")}})
    send = mocker.patch.object(RequestsTransport, "send", return_value=SimpleNamespace(
        status_code=409 if outcome == "conflict" else 201,
    ))
    if outcome == "uncertain":
        send.side_effect = ServiceRequestError("response lost")
        with pytest.raises(ServiceRequestError), helper.record_group_reader_assignments():
            RequestsTransport().send(request)
    else:
        with helper.record_group_reader_assignments():
            RequestsTransport().send(request)
    mocker.patch("azext_iot.tests.adr._helpers.time.sleep")
    roles = [dict(role), {**role, "id": role["id"] + "-preexisting", "name": "preexisting"}]
    if outcome == "binding-changed":
        roles[0]["principalId"] = "replacement"
    commands = []

    def command(text):
        commands.append(text)
        output = Mock()
        if text.startswith("role assignment list"):
            output.get_output_in_json.return_value = list(roles)
        elif text.startswith("role assignment delete"):
            assert role["id"] in text and "-preexisting" not in text
            roles.pop(0)
        return output

    helper.cmd = Mock(side_effect=command)
    mocker.patch.object(helper, "_resource_is_absent", return_value=False)
    if outcome == "binding-changed":
        with pytest.raises(AssertionError, match="binding changed"):
            helper._delete_owned_resource(*resource)
        assert not any(" delete " in command for command in commands)
    else:
        helper._delete_owned_resource(*resource)
        deletes = [command for command in commands if " delete " in command]
        assert deletes[-1] == "identity delete -n owned -g rg"
        assert len(deletes) == (1 if outcome in {"conflict", "foreign"} else 2)
    assert roles[-1]["name"] == "preexisting"


@responses.activate
@pytest.mark.parametrize("status", [429, 503])
def test_reader_recorder_preserves_sdk_retry_and_rejects_another_request(status):
    helper = ADRFullInfraHelper()
    principal = "11111111-2222-3333-4444-555555555555"
    helper._owned_principals = {("identity", "owned", "rg"): principal}
    path = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Authorization/roleAssignments/role-id"
    url = "https://management.azure.com" + path
    body = {"properties": {
        "principalId": principal, "principalType": "ServicePrincipal",
        "roleDefinitionId": "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/"
        + LINK_ROLE_IDS[READER_ROLE],
    }}
    responses.add("PUT", url, status=status, json={})
    responses.add("PUT", url, status=201, json={})
    with helper.record_group_reader_assignments():
        with Pipeline(transport=RequestsTransport(), policies=[RetryPolicy(retry_total=1, retry_backoff_factor=0)]) as pipeline:
            request = HttpRequest("PUT", url)
            request.set_json_body(body)
            assert pipeline.run(request).http_response.status_code == 201
            other = HttpRequest("PUT", url)
            other.set_json_body(body)
            with pytest.raises(AssertionError, match="different request"):
                pipeline.run(other)
    assert len(responses.calls) == 2
    assert len(helper._owned_group_readers) == 1
    assert helper._owned_group_readers[path.casefold()]["statuses"] == [status, 201]


@responses.activate
@pytest.mark.parametrize("statuses,reconcile", [
    ((503, 403), True),
    ((408, 403), True),
    ((None, 403), True),
    ((503, 429, 403), True),
    ((429, 403), False),
])
def test_reader_cleanup_reconciles_earlier_uncertain_attempt_after_rejected_retry(mocker, statuses, reconcile):
    helper = ADRFullInfraHelper()
    principal = "11111111-2222-3333-4444-555555555555"
    resource = ("identity", "owned", "rg")
    helper._owned_principals = {resource: principal}
    group = "/subscriptions/sub/resourceGroups/rg"
    role = {
        "id": group + "/providers/Microsoft.Authorization/roleAssignments/role-id",
        "name": "role-id", "scope": group, "principalId": principal,
        "principalType": "ServicePrincipal",
        "roleDefinitionId": "/subscriptions/sub/providers/Microsoft.Authorization/roleDefinitions/"
        + LINK_ROLE_IDS[READER_ROLE],
    }
    url = "https://management.azure.com" + role["id"]
    for status in statuses:
        if status is None:
            responses.add("PUT", url, body=RequestsConnectionError("response lost"))
        else:
            responses.add("PUT", url, status=status, json={})
    with helper.record_group_reader_assignments():
        with Pipeline(transport=RequestsTransport(), policies=[RetryPolicy(retry_total=2, retry_backoff_factor=0)]) as pipeline:
            request = HttpRequest("PUT", url)
            request.set_json_body({"properties": {
                key: role[key] for key in ("principalId", "principalType", "roleDefinitionId")
            }})
            assert pipeline.run(request).http_response.status_code == 403
    assert len(responses.calls) == len(statuses)
    roles = [role]

    def command(text):
        if text.startswith("role assignment delete"):
            roles.clear()
        return SimpleNamespace(get_output_in_json=lambda: list(roles))

    helper.cmd = Mock(side_effect=command)
    mocker.patch.object(helper, "_resource_is_absent", return_value=False)
    helper._delete_owned_resource(*resource)
    lookup = (
        f"role assignment list --scope {group} --assignee-object-id {principal} "
        "--fill-principal-name false --subscription sub"
    )
    expected = [
        call(lookup), call(f"role assignment delete --ids {role['id']} --subscription sub"), call(lookup),
    ] if reconcile else []
    assert helper.cmd.call_args_list == [*expected, call("identity delete -n owned -g rg")]
    assert not helper._owned_group_readers


def _assert_lookup_cannot_claim_resource(error, expected_type=None):
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=error)
    with pytest.raises(expected_type or type(error)) as raised:
        helper.create_owned_resource(
            "iot hub create -n target -g rg", kind="hub", name="target", resource_group="rg",
        )
    if expected_type is None:
        assert raised.value is error
    assert not getattr(helper, "_owned_resources", {})
    helper.cmd.assert_called_once_with("iot hub show -n target -g rg")


@pytest.mark.parametrize("status", [403, 502])
@pytest.mark.parametrize("source", ["direct", "response", "cause", "context"])
def test_denied_or_failed_lookup_never_claims_ownership(status, source):
    error = _http_error(status, "ResourceNotFound")
    if source == "response":
        error.status_code = None
        error.response = SimpleNamespace(status_code=status)
    elif source in {"cause", "context"}:
        wrapped = CLIError("ResourceNotFound (404)")
        setattr(wrapped, f"__{source}__", error)
        error = wrapped
    assert not is_resource_not_found_error(error)
    _assert_lookup_cannot_claim_resource(error)


@pytest.mark.parametrize("status", [None, 404])
@pytest.mark.parametrize("code", ["AuthorizationFailed", "InvalidResourceType"])
@pytest.mark.parametrize("source", ["direct", "object", "dict"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_structured_non_absence_codes_override_not_found_text(status, code, source, wrapped):
    error = _http_error(status)
    if source == "direct":
        error.code = code
    elif source == "object":
        error.error = SimpleNamespace(code=code)
    else:
        error.error = {"code": code}
    if wrapped:
        outer = CLIError("ResourceNotFound (404)")
        outer.__cause__ = error
        error = outer
    _assert_lookup_cannot_claim_resource(error)


@pytest.mark.parametrize("status", [None, 404])
@pytest.mark.parametrize("code", ["ResourceNotFound", "ParentResourceNotFound", "ResourceGroupNotFound"])
def test_structured_not_found_is_recognized(status, code):
    assert is_resource_not_found_error(_http_error(status, code))


@pytest.mark.parametrize("code", [404002, "404002"])
@pytest.mark.parametrize("status", [None, 404, 403, 502])
@pytest.mark.parametrize("source", ["direct", "object", "dict", "response", "wrapped"])
def test_hub_numeric_absence_requires_http_confirmation(code, status, source):
    error = _http_error(status)
    if source == "direct":
        error.code = code
    elif source == "dict":
        error.error = {"code": code}
    else:
        error.error = SimpleNamespace(code=code)
    if source == "response":
        error.status_code = None
        error.response = SimpleNamespace(status_code=status)
    elif source == "wrapped":
        outer = CLIError("IoT Hub request failed.")
        outer.__cause__ = error
        error = outer
    if status == 404:
        assert is_resource_not_found_error(error)
    else:
        _assert_lookup_cannot_claim_resource(error)


def _hub_absence_error():
    detail = {"code": 404002, "httpStatusCode": 404, "message": "IotHub 'hub' not found."}
    return CLIError(f"Not Found({json.dumps(detail)})")


def test_canonical_hub_absence_allows_owned_creation_and_cleanup():
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=[_hub_absence_error(), Mock()])
    command = "iot hub create -n target -g rg"
    helper.create_owned_resource(command, kind="hub", name="target", resource_group="rg")
    assert helper.cmd.call_args_list == [call("iot hub show -n target -g rg"), call(command)]
    assert helper._owned_resources == {("hub", "target", "rg"): None}

    helper.cmd = Mock(side_effect=_hub_absence_error())
    helper.cleanup_full_infra()
    helper.cmd.assert_called_once_with("iot hub show -n target -g rg")
    assert not helper._owned_resources


@pytest.mark.parametrize(
    "payload",
    [
        '{"code":404002,"httpStatusCode":403}',
        '{"code":404002,"httpStatusCode":502}',
        '{"code":404002}',
        '{"httpStatusCode":404}',
        '{"code":"AuthorizationFailed","httpStatusCode":404}',
        '{"code":404001,"httpStatusCode":404}',
        '{"code":404002.0,"httpStatusCode":404}',
        '{"code":404002,"httpStatusCode":null}',
        '{"code":404002,"httpStatusCode":"404"}',
        '{"code":404002,"httpStatusCode":404',
        'null',
        '[]',
    ],
)
def test_malformed_or_conflicting_hub_payload_cannot_claim_absence(payload):
    _assert_lookup_cannot_claim_resource(CLIError(f"Not Found({payload})"))


@pytest.mark.parametrize("source", ["status", "code", "cause", "context"])
def test_canonical_hub_absence_respects_authoritative_conflicts(source):
    error = _hub_absence_error()
    if source == "status":
        error.status_code = 403
    elif source == "code":
        error.code = "AuthorizationFailed"
    elif source == "cause":
        error.__cause__ = _http_error(502)
    else:
        error.__context__ = _http_error(403)
        assert is_resource_not_found_error(error)
        return
    _assert_lookup_cannot_claim_resource(error)


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("ResourceNotFound (404)"),
        ServiceRequestError("ResourceNotFound (404)"),
        ClientAuthenticationError("ResourceNotFound (404)"),
        CLIError("AuthorizationFailed: ResourceNotFound 404"),
        CLIError("ServiceUnavailable at /resources/404"),
        CLIError("Required configuration could not be found."),
    ],
)
def test_unexpected_authentication_transport_and_text_errors_do_not_claim_ownership(error):
    _assert_lookup_cannot_claim_resource(error)


@pytest.mark.parametrize("status", [None, 404])
def test_authentication_failure_cannot_be_resource_absence(status):
    error = ClientAuthenticationError("ResourceNotFound (404)")
    error.status_code = status
    wrapped = CLIError("ResourceNotFound (404)")
    wrapped.__cause__ = error
    _assert_lookup_cannot_claim_resource(wrapped)


@pytest.mark.parametrize(
    "message",
    [
        "(ResourceNotFound) Resource is absent.\nCode: ResourceNotFound",
        "ResourceNotFound: Resource is absent.",
        "ResourceGroupNotFound: Group is absent.",
        "An IotHub 'hub' under resource group 'rg' was not found.",
    ],
)
def test_canonical_cli_absence_messages_are_retained(message):
    assert is_resource_not_found_error(CLIError(message))


@pytest.mark.parametrize("status", [403, 502])
def test_cli_missing_exit_cannot_hide_a_denied_or_failed_request(status):
    error = SystemExit(3)
    error.__cause__ = _http_error(status)
    _assert_lookup_cannot_claim_resource(error, AssertionError)


def test_explicit_cause_conflicts_fail_closed_but_unrelated_cleanup_context_does_not():
    error = _http_error(404, "ResourceNotFound")
    error.__context__ = _http_error(403, "AuthorizationFailed")
    assert is_resource_not_found_error(error)
    error.__cause__ = error.__context__
    assert not is_resource_not_found_error(error)


def test_cyclic_cause_is_not_accepted_as_absence():
    error = CLIError("ResourceNotFound (404)")
    error.__cause__ = error
    assert not is_resource_not_found_error(error)


def test_cleanup_retry_retains_only_failed_owned_resources():
    helper = ADRFullInfraHelper()
    namespace = ("namespace", "owned-ns", "rg")
    hub = ("hub", "owned-hub", "rg")
    helper._owned_resources = dict.fromkeys([namespace, hub])

    def invoke(command):
        if command == "iot adr ns delete -n owned-ns -g rg --yes":
            raise CLIError("namespace deletion failed")
        return Mock()

    helper.cmd = Mock(side_effect=invoke)
    with pytest.raises(AssertionError, match="namespace deletion failed"):
        helper.cleanup_full_infra()
    assert helper._owned_resources == {namespace: None}
    assert call("iot hub delete -n owned-hub -g rg") in helper.cmd.call_args_list

    helper.cmd = Mock()
    helper.cleanup_full_infra()
    assert helper.cmd.call_args_list == [
        call("iot adr ns show -n owned-ns -g rg"),
        call("iot adr ns delete -n owned-ns -g rg --yes"),
    ]
    assert not helper._owned_resources


def test_cleanup_failure_retains_ownership_without_replacing_primary_error():
    helper = ADRFullInfraHelper()
    resource = ("hub", "owned-hub", "rg")
    helper._owned_resources = {resource: None}
    helper.cmd = Mock(side_effect=_http_error(403, "AuthorizationFailed"))
    primary = RuntimeError("original test failure")
    with pytest.raises(RuntimeError) as raised:
        try:
            raise primary
        finally:
            helper.cleanup_full_infra()
    assert raised.value is primary
    assert helper._owned_resources == {resource: None}

    helper.cmd = Mock(side_effect=_http_error(404, "ResourceNotFound"))
    helper.cleanup_full_infra()
    helper.cmd.assert_called_once_with("iot hub show -n owned-hub -g rg")
    assert not helper._owned_resources


def test_namespace_cleanup_failure_is_recorded_for_a_later_retry():
    helper = ADRFullInfraHelper()
    helper.cmd = Mock(side_effect=_http_error(502))
    with pytest.raises(AssertionError, match="ADR cleanup failed"):
        helper.cleanup_namespace("owned-ns", "rg")
    assert helper._owned_resources == {("namespace", "owned-ns", "rg"): None}


@pytest.fixture(params=list(ADRFullInfraHelper._RESOURCE_COMMANDS))
def owned_cleanup(request):
    kind = request.param
    helper = ADRFullInfraHelper()
    resource = (kind, "owned", "rg")
    helper._owned_resources = {resource: None}
    command = helper._RESOURCE_COMMANDS[kind]
    confirmation = " --yes" if kind in {"namespace", } else ""
    commands = [
        call(f"{command} show -n owned -g rg"),
        call(f"{command} delete -n owned -g rg{confirmation}"),
    ]
    helper.cmd = Mock()
    return helper, resource, commands


@pytest.mark.parametrize("source", ["sdk", "wrapped", "cli", "exit"])
def test_delete_race_to_confirmed_absence_releases_ownership(owned_cleanup, source):
    helper, _, commands = owned_cleanup
    error = _http_error(404, "ResourceNotFound")
    if source in {"wrapped", "exit"}:
        outer = CLIError("ResourceNotFound (404)") if source == "wrapped" else SystemExit(3)
        outer.__cause__ = error
        error = outer
    elif source == "cli":
        error = CLIError("(ResourceNotFound) Resource was deleted after SHOW.")
    helper.cmd.side_effect = [Mock(), error]

    helper.cleanup_full_infra()

    assert helper.cmd.call_args_list == commands
    assert not helper._owned_resources
    helper.cmd.reset_mock()
    helper.cleanup_full_infra()
    helper.cmd.assert_not_called()


@pytest.mark.parametrize(
    "status,code",
    [(403, "ResourceNotFound"), (502, "ResourceNotFound"),
     (404, "InvalidResourceType"), (404, "AuthorizationFailed")],
)
def test_other_delete_failures_retain_exact_ownership_for_retry(owned_cleanup, status, code):
    helper, resource, commands = owned_cleanup
    error = _http_error(status, code)
    helper.cmd.side_effect = [Mock(), error]

    with pytest.raises(AssertionError, match="ADR cleanup failed") as raised:
        helper.cleanup_full_infra()
    assert raised.value.__cause__ is error
    assert helper.cmd.call_args_list == commands
    assert helper._owned_resources == {resource: None}

    helper.cmd.reset_mock(side_effect=True)
    helper.cleanup_full_infra()
    assert helper.cmd.call_args_list == commands
    assert not helper._owned_resources


@pytest.mark.parametrize("exit_code", [2, 3])
def test_delete_exit_cannot_hide_denial_or_release_ownership(owned_cleanup, exit_code):
    helper, resource, commands = owned_cleanup
    error = SystemExit(exit_code)
    error.__cause__ = _http_error(403, "ResourceNotFound")
    helper.cmd.side_effect = [Mock(), error]

    with pytest.raises(AssertionError, match=f"delete exited with code {exit_code}") as raised:
        helper.cleanup_full_infra()
    assert raised.value.__cause__.__cause__ is error
    assert helper.cmd.call_args_list == commands
    assert helper._owned_resources == {resource: None}

    helper.cmd.reset_mock(side_effect=True)
    helper.cleanup_full_infra()
    assert helper.cmd.call_args_list == commands
    assert not helper._owned_resources


def test_delete_race_preserves_primary_failure_without_retaining_absent_resource(owned_cleanup, caplog):
    helper, _, commands = owned_cleanup
    primary = _http_error(403, "AuthorizationFailed")
    helper.cmd.side_effect = [Mock(), _http_error(404, "ResourceNotFound")]

    with pytest.raises(HttpResponseError) as raised:
        try:
            raise primary
        finally:
            helper.cleanup_full_infra()

    assert raised.value is primary
    assert helper.cmd.call_args_list == commands
    assert not helper._owned_resources
    assert "Cleanup failed" not in caplog.text
