# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.base import (
    ADRProvider,
    _retry_after_seconds,
    parse_json_object,
)


@pytest.mark.parametrize("input_location", ["location", None])
def test_ensure_location(fixture_adr_provider, fixture_cmd, input_location):
    resource_group = "test-resource-group"
    fallback_location = "resource-group-location"

    if input_location is None:
        with patch("azure.cli.core.commands.client_factory.get_mgmt_service_client") as mock_get_client:
            mock_resource_client = Mock()
            mock_rg = Mock()
            mock_rg.location = fallback_location
            mock_resource_client.resource_groups.get.return_value = mock_rg
            mock_get_client.return_value = mock_resource_client

            result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, input_location)

            assert result == fallback_location
            mock_get_client.assert_called_once()
            mock_resource_client.resource_groups.get.assert_called_once_with(resource_group)
    else:
        result = fixture_adr_provider._ensure_location(fixture_cmd.cli_ctx, resource_group, input_location)
        assert result == input_location


def test_parse_json_object_rejects_unsupported_and_missing_properties():
    with pytest.raises(InvalidArgumentValueError, match="unsupported"):
        parse_json_object(
            {"known": 1, "unknown": 2},
            "--body",
            allowed_keys=frozenset({"known"}),
        )
    with pytest.raises(RequiredArgumentMissingError, match="required"):
        parse_json_object(
            {"required": None},
            "--body",
            required_keys=frozenset({"required"}),
        )


def test_provider_initialization(fixture_cmd):
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client

        provider = ADRProvider(fixture_cmd)

        assert provider.cmd == fixture_cmd
        assert provider.client == mock_client
        mock_factory.assert_called_once_with(fixture_cmd.cli_ctx)


def _fake_time():
    now = [0]
    sleeps = []

    def clock():
        return now[0]

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    return clock, sleeper, sleeps


@pytest.mark.parametrize("error,detail", [
    ({"code": "OnlyCode"}, "OnlyCode"), ({"message": "Only message"}, "Only message"),
    ({"code": None, "message": "useful"}, "useful"), ({}, ""), (None, ""),
    ("invalid", ""), ({"code": 3, "message": []}, ""), ({"code": "  ", "message": None}, ""),
])
@pytest.mark.parametrize("source", ["resource-status response", "Location-status response", "initial operation response"])
def test_partial_failure_details_and_provenance(fixture_adr_provider, error, detail, source):
    body = {"id": "/subscriptions/sub/resourceGroups/rg/resource", "properties": {"error": error}}
    response = SimpleNamespace(headers={"x-ms-correlation-request-id": "observed", "Authorization": "secret-sentinel"})
    message = fixture_adr_provider._format_failure("Failed", body, response, source)
    assert "provisioningState='Failed'" in message
    assert f"Correlation ID from the {source}: observed" in message
    assert "Resource: /subscriptions/sub/resourceGroups/rg/resource" in message
    assert "Activity Log" in message
    assert ("did not include a detailed error" in message) == (not detail)
    if detail:
        assert detail in message
    assert "None" not in message
    assert "secret-sentinel" not in message
    fixture_adr_provider.client.send_request.assert_not_called()


def test_unusable_properties_error_does_not_hide_top_level_detail():
    assert ADRProvider._extract_failure_detail(
        {"properties": {"error": {"code": None}}, "error": {"code": "Useful"}}
    ) == "Useful"


@pytest.mark.parametrize(
    "body,expected",
    [
        (None, ""),
        ({"properties": {"provisioning": {"endpoints": ["unexpected"]}}}, ""),
        (
            {"properties": {"provisioning": {"endpoints": {
                "raw": "invalid", "bad-status": {"status": "Failed"}, "bad-error": {"error": "invalid"},
            }}}},
            "",
        ),
        (
            {"properties": {"provisioning": {"endpoints": {
                "endpoint": {"provisioningStatus": {"error": {"message": "status error"}}},
            }}}},
            "endpoint 'endpoint': status error",
        ),
        (
            {"properties": {"messaging": {"endpoints": {
                "endpoint": {"error": {"message": "endpoint error"}},
            }}}},
            "endpoint 'endpoint': endpoint error",
        ),
        (
            {"properties": {"provisioning": {"endpoints": {
                "endpoint": {"linkingError": {"message": "linking error"}},
            }}}},
            "endpoint 'endpoint': linking error",
        ),
        (
            {"properties": {"provisioning": {"endpoints": {
                "endpoint": {"provisioningStatus": {"status": "Failed"}},
            }}}},
            "endpoint 'endpoint' is in a 'Failed' state",
        ),
        (
            {"properties": {"messaging": {"endpoints": {
                "endpoint": {"linkingState": "failed"},
            }}}},
            "endpoint 'endpoint' is in a 'Failed' state",
        ),
        ({"properties": {"error": {"code": "BadLink", "message": "failed"}}}, "BadLink: failed"),
        ({"error": {"message": "root failure"}}, "root failure"),
    ],
)
def test_extract_failure_detail(body, expected):
    assert ADRProvider._extract_failure_detail(body) == expected


_TWO_FAILED_ENDPOINTS = {
    "id": "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/ns",
    "properties": {
        "provisioningState": "Failed",
        "messaging": {"endpoints": {"primary-hub": {
            "linkingState": "Failed",
            "linkingError": {"code": "LinkInitiateFailed", "message": "stale hub failure"},
        }}},
        "provisioning": {"endpoints": {
            "other-dps": {"linkingState": "Failed", "linkingError": {"message": "other dps failure"}},
            "primary-dps": {"linkingState": "Failed", "linkingError": {"code": "LinkOrphaned", "message": "orphaned"}},
        }},
    },
}


@pytest.mark.parametrize(
    "target,expected",
    [
        (None, "endpoint 'other-dps': other dps failure"),
        (("provisioning", "primary-dps"), "endpoint 'primary-dps': LinkOrphaned: orphaned"),
        (("provisioning", "missing"), ""),
        (("management", "primary-dps"), ""),
    ],
)
def test_extract_failure_detail_reports_only_the_target_endpoint(target, expected):
    assert ADRProvider._extract_failure_detail(_TWO_FAILED_ENDPOINTS, target) == expected


def test_extract_failure_detail_target_falls_back_to_resource_error_not_other_endpoints():
    body = {**_TWO_FAILED_ENDPOINTS, "error": {"code": "NamespaceFailed", "message": "root"}}

    assert ADRProvider._extract_failure_detail(body, ("provisioning", "missing")) == "NamespaceFailed: root"


def test_await_terminal_formats_failure_for_the_target_endpoint(fixture_adr_provider):
    poller = SimpleNamespace(done=Mock(return_value=True), result=Mock(return_value=_TWO_FAILED_ENDPOINTS))

    with pytest.raises(AzureResponseError) as raised:
        fixture_adr_provider._await_terminal(poller, failure_target=("provisioning", "primary-dps"))

    assert "endpoint 'primary-dps': LinkOrphaned: orphaned." in str(raised.value)
    assert "primary-hub" not in str(raised.value)
    assert raised.value.body is _TWO_FAILED_ENDPOINTS


def test_format_failure_includes_authorization_guidance_and_correlation_id(fixture_adr_provider):
    body = {
        "properties": {
            "provisioning": {
                "endpoints": {
                    "endpoint": {
                        "error": {
                            "message": "Managed identity is not authorized"
                        }
                    }
                }
            }
        }
    }
    response = SimpleNamespace(headers={"x-ms-correlation-request-id": "correlation-id"})

    message = fixture_adr_provider._format_failure("Failed", body, response)

    assert "Managed identity is not authorized." in message
    assert "Role assignments visible in ARM may not yet be effective" in message
    assert "use link update, not link add" in message
    assert "Update reruns RBAC preflight" in message
    assert "roles are incomplete" not in message
    assert "exact remediation commands" not in message
    assert "\naz iot" not in message
    assert "Correlation ID from the resource-status response: correlation-id." in message


@pytest.mark.parametrize(
    "body,response",
    [
        ({"error": {"message": "Already failed."}}, SimpleNamespace(headers=None)),
        ({}, SimpleNamespace(headers={})),
    ],
)
def test_format_failure_uses_activity_log_fallback(fixture_adr_provider, body, response):
    message = fixture_adr_provider._format_failure("Canceled", body, response)

    assert "Check Azure Activity Log for this resource around the operation time" in message
    assert "Correlation id:" not in message


@pytest.mark.parametrize(
    "headers,fallback,expected",
    [
        ({"Retry-After": "45"}, 2, 30),
        ({"retry-after": "invalid"}, 7, 7),
        ({"ReTrY-AfTeR": 3}, 7, 3),
        ({"Retry-After": 0}, 4, 4),
    ],
)
def test_retry_after_is_case_insensitive_integer_and_capped(headers, fallback, expected):
    assert _retry_after_seconds(SimpleNamespace(headers=headers), fallback=fallback) == expected


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_await_terminal_uses_sdk_poller_without_resource_get(fixture_adr_provider, method):
    result = {"method": method, "status": "complete"}
    poller = SimpleNamespace(
        done=Mock(side_effect=[False, True]),
        result=Mock(return_value=result),
    )
    clock, sleeper, sleeps = _fake_time()

    assert fixture_adr_provider._await_terminal(
        poller, wait_sec=2, timeout_sec=10, clock=clock, sleeper=sleeper,
    ) is result

    assert sleeps == [2]
    assert poller.done.call_count == 2
    poller.result.assert_called_once_with()
    fixture_adr_provider.client.send_request.assert_not_called()


def test_await_terminal_timeout_never_calls_result(fixture_adr_provider):
    poller = SimpleNamespace(done=Mock(return_value=False), result=Mock())
    clock, sleeper, sleeps = _fake_time()

    with pytest.raises(AzureResponseError, match="Timed out waiting"):
        fixture_adr_provider._await_terminal(
            poller, wait_sec=2, timeout_sec=3, clock=clock, sleeper=sleeper,
        )

    assert sleeps == [2, 1]
    poller.result.assert_not_called()
    fixture_adr_provider.client.send_request.assert_not_called()


def test_await_terminal_propagates_deadline_guard_message(fixture_adr_provider):
    poller = SimpleNamespace(done=Mock(return_value=False), result=Mock())

    def expired():
        raise AzureResponseError("outer budget expired")

    with pytest.raises(AzureResponseError, match="outer budget expired"):
        fixture_adr_provider._await_terminal(poller, deadline_guard=expired)

    poller.done.assert_not_called()
    poller.result.assert_not_called()


def test_await_terminal_deadline_guard_replaces_default_budget(fixture_adr_provider):
    poller = SimpleNamespace(done=Mock(side_effect=[False, False, True]), result=Mock(return_value="done"))
    clock, sleeper, sleeps = _fake_time()

    assert fixture_adr_provider._await_terminal(
        poller, wait_sec=5, timeout_sec=1, clock=clock, sleeper=sleeper, deadline_guard=lambda: 100,
    ) == "done"
    assert sleeps == [5, 5]


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_no_wait_returns_before_sdk_polling(fixture_adr_provider, method):
    poller = SimpleNamespace(done=Mock(), result=Mock(), method=method)
    fixture_adr_provider._await_terminal = Mock()

    assert fixture_adr_provider._wait(poller, "Working...", no_wait=True) is poller
    fixture_adr_provider._await_terminal.assert_not_called()
    fixture_adr_provider.client.send_request.assert_not_called()
    poller.result.assert_not_called()


def test_resolve_location_rejects_parent_without_location(fixture_adr_provider):
    fixture_adr_provider.client.namespaces.get.return_value = {}

    with pytest.raises(AzureResponseError, match="does not contain a location"):
        fixture_adr_provider._resolve_location("namespace", "rg")


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unrelated"),
        HttpResponseError(message="ParentResourceNotFound", response=None),
        HttpResponseError(message="OtherNotFound", response=None),
    ],
)
def test_raise_if_parent_not_found_reraises_other_errors(fixture_adr_provider, error):
    if isinstance(error, HttpResponseError):
        error.status_code = 500 if "ParentResourceNotFound" in str(error) else 404

    with pytest.raises(type(error)) as raised:
        fixture_adr_provider._raise_if_parent_not_found(error, "friendly message")
    assert raised.value is error


def test_raise_if_parent_not_found_translates_matching_error(fixture_adr_provider):
    error = HttpResponseError(message="ParentResourceNotFound", response=None)
    error.status_code = 404

    with pytest.raises(ResourceNotFoundError, match="friendly message"):
        fixture_adr_provider._raise_if_parent_not_found(error, "friendly message")
