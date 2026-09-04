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
    _poll_with_deadline,
    _retry_after_seconds,
    parse_json_object,
)


@pytest.mark.parametrize("input_location", ["location", None])
def test_ensure_location(fixture_adr_provider, fixture_cmd, input_location):
    """Test _ensure_location behavior with various input combinations."""
    resource_group = "test-resource-group"
    fallback_location = "resource-group-location"

    if input_location is None:
        # Mock the resource client when location lookup is needed
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
        # When location is provided, it should return immediately without any mocking needed
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
    """Test that ADRProvider initializes correctly."""
    with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
        mock_client = Mock()
        mock_factory.return_value = mock_client

        provider = ADRProvider(fixture_cmd)

        assert provider.cmd == fixture_cmd
        assert provider.client == mock_client
        mock_factory.assert_called_once_with(fixture_cmd.cli_ctx)


def _resource_poller(method="PATCH", location=None):
    poller = Mock()
    poller.done.return_value = False
    poller._polling_method._initial_response.http_request = Mock(
        url="https://management.azure.com/resource", method=method
    )
    poller._polling_method._initial_response.http_response.headers = (
        {"Location": location} if location else {}
    )
    poller._polling_method._initial_response.http_response.status_code = 202
    return poller


def _fake_time():
    now = [0]
    sleeps = []

    def clock():
        return now[0]

    def sleeper(delay):
        sleeps.append(delay)
        now[0] += delay

    return clock, sleeper, sleeps


def test_poll_provisioning_state_raises_4xx_immediately(
    fixture_adr_provider,
):
    response = Mock(status_code=400)
    response.raise_for_status.side_effect = RuntimeError("bad request")
    fixture_adr_provider.client.send_request.return_value = response

    with pytest.raises(RuntimeError, match="bad request"):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(), wait_sec=0
        )

    response.raise_for_status.assert_called_once_with()
    assert fixture_adr_provider.client.send_request.call_count == 1


@pytest.mark.parametrize(
    "response,expected_message",
    [
        (
            Mock(
                status_code=200,
                json=Mock(
                    return_value={
                        "properties": {"provisioningState": "Updating"}
                    }
                ),
            ),
            "last provisioningState='Updating'",
        ),
        (Mock(status_code=500), "Timed out waiting"),
    ],
)
def test_poll_provisioning_state_timeout_is_an_error(
    fixture_adr_provider,
    response,
    expected_message,
):
    fixture_adr_provider.client.send_request.return_value = response
    clock, sleeper, _ = _fake_time()

    with pytest.raises(AzureResponseError, match=expected_message):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(),
            wait_sec=1,
            timeout_sec=3,
            clock=clock,
            sleeper=sleeper,
        )

    assert fixture_adr_provider.client.send_request.call_count == 2


def test_await_terminal_uses_sdk_polling_when_workaround_is_disabled(
    fixture_adr_provider, monkeypatch, mocker
):
    poller = Mock()
    monkeypatch.setattr(
        "azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND",
        False,
    )
    wait = mocker.patch(
        "azext_iot.adr.providers.base.wait_for_terminal_state",
        return_value="complete",
    )

    assert fixture_adr_provider._await_terminal(poller, wait_sec=7) == "complete"
    wait.assert_called_once_with(poller, wait_sec=7)


def test_poller_initial_request_uses_public_poller_and_response_request():
    request = SimpleNamespace(
        url="https://management.azure.com/resource",
        method="patch",
    )
    polling_method = SimpleNamespace(
        _initial_response=SimpleNamespace(
            http_request=None,
            http_response=SimpleNamespace(request=request),
        )
    )
    poller = SimpleNamespace(
        _polling_method=None,
        polling_method=lambda: polling_method,
    )

    assert ADRProvider._poller_initial_request(poller) == (
        request.url,
        "PATCH",
    )


def test_poller_initial_request_handles_public_poller_failure():
    def raise_error():
        raise RuntimeError("unavailable")

    poller = SimpleNamespace(
        _polling_method=None,
        polling_method=raise_error,
    )

    assert ADRProvider._poller_initial_request(poller) == (None, None)


def test_poller_location_accepts_lowercase_header():
    poller = _resource_poller("POST")
    poller._polling_method._initial_response.http_response.headers = {
        "location": "https://management.azure.com/status"
    }

    assert (
        ADRProvider._poller_location(poller)
        == "https://management.azure.com/status"
    )


def test_poller_without_initial_http_response_is_not_async():
    poller = SimpleNamespace(
        _polling_method=SimpleNamespace(_initial_response=None)
    )

    assert not ADRProvider._poller_is_async(poller)


@pytest.mark.parametrize(
    "body,expected",
    [
        (None, ""),
        (
            {
                "properties": {
                    "provisioning": {"endpoints": ["unexpected"]}
                }
            },
            "",
        ),
        (
            {
                "properties": {
                    "provisioning": {
                        "endpoints": {
                            "raw": "invalid",
                            "bad-status": {"status": "Failed"},
                            "bad-error": {"error": "invalid"},
                        }
                    }
                }
            },
            "",
        ),
        (
            {
                "properties": {
                    "provisioning": {
                        "endpoints": {
                            "endpoint": {
                                "provisioningStatus": {
                                    "error": {"message": "status error"}
                                }
                            }
                        }
                    }
                }
            },
            "endpoint 'endpoint': status error",
        ),
        (
            {
                "properties": {
                    "messaging": {
                        "endpoints": {
                            "endpoint": {
                                "error": {"message": "endpoint error"}
                            }
                        }
                    }
                }
            },
            "endpoint 'endpoint': endpoint error",
        ),
        (
            {
                "properties": {
                    "updating": {
                        "endpoints": {
                            "endpoint": {
                                "linkingError": {
                                    "message": "linking error"
                                }
                            }
                        }
                    }
                }
            },
            "endpoint 'endpoint': linking error",
        ),
        (
            {
                "properties": {
                    "provisioning": {
                        "endpoints": {
                            "endpoint": {
                                "provisioningStatus": {"status": "Failed"}
                            }
                        }
                    }
                }
            },
            "endpoint 'endpoint' is in a 'Failed' state",
        ),
        (
            {
                "properties": {
                    "messaging": {
                        "endpoints": {
                            "endpoint": {"linkingState": "failed"}
                        }
                    }
                }
            },
            "endpoint 'endpoint' is in a 'Failed' state",
        ),
        (
            {
                "properties": {
                    "error": {"code": "BadLink", "message": "failed"}
                }
            },
            "BadLink: failed",
        ),
        ({"error": {"message": "root failure"}}, "root failure"),
    ],
)
def test_extract_failure_detail(body, expected):
    assert ADRProvider._extract_failure_detail(body) == expected


def test_format_failure_includes_authorization_guidance_and_correlation_id(
    fixture_adr_provider,
):
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
    response = SimpleNamespace(
        headers={"x-ms-correlation-request-id": "correlation-id"}
    )

    message = fixture_adr_provider._format_failure(
        "Failed", body, response
    )

    assert "Managed identity is not authorized." in message
    assert "automatic RBAC preflight" in message
    assert "exact remediation commands" in message
    assert "Correlation id: correlation-id." in message


@pytest.mark.parametrize(
    "body,response",
    [
        (
            {"error": {"message": "Already failed."}},
            SimpleNamespace(headers=None),
        ),
        ({}, SimpleNamespace(headers={})),
    ],
)
def test_format_failure_uses_activity_log_fallback(
    fixture_adr_provider,
    body,
    response,
):
    message = fixture_adr_provider._format_failure(
        "Canceled", body, response
    )

    assert "Inspect the service activity log" in message
    assert "Correlation id:" not in message


def test_poll_provisioning_state_falls_back_when_request_is_missing(
    fixture_adr_provider,
    mocker,
):
    poller = SimpleNamespace(done=lambda: False)
    wait = mocker.patch(
        "azext_iot.adr.providers.base.wait_for_terminal_state",
        return_value="complete",
    )

    assert (
        fixture_adr_provider._poll_provisioning_state(
            poller, wait_sec=7
        )
        == "complete"
    )
    wait.assert_called_once_with(poller, wait_sec=7)


def test_post_lro_polls_location_until_succeeded(fixture_adr_provider):
    result = {"status": "Succeeded", "value": "report"}
    fixture_adr_provider.client.send_request.side_effect = [
        Mock(status_code=404),
        Mock(
            status_code=202,
            json=Mock(return_value={"status": "Running"}),
        ),
        Mock(status_code=200, json=Mock(return_value=result)),
    ]

    assert fixture_adr_provider._poll_provisioning_state(
        _resource_poller("POST", location="https://management.azure.com/status"),
        wait_sec=0,
    ) == result
    assert all(
        call.args[0].url == "https://management.azure.com/status"
        for call in fixture_adr_provider.client.send_request.call_args_list
    )


def test_post_lro_ignores_sdk_done_state_for_accepted_response(
    fixture_adr_provider,
):
    poller = _resource_poller(
        "POST", location="https://management.azure.com/status"
    )
    poller.done.return_value = True
    poller.result.side_effect = RuntimeError("broken Azure-AsyncOperation poll")
    fixture_adr_provider.client.send_request.return_value = Mock(
        status_code=204
    )

    assert fixture_adr_provider._poll_provisioning_state(
        poller, wait_sec=0
    ) is None
    poller.done.assert_not_called()
    poller.result.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_inline_mutation_returns_poller_result(
    fixture_adr_provider, method
):
    poller = _resource_poller(method)
    poller._polling_method._initial_response.http_response.status_code = 200
    poller.result.return_value = {"status": "complete"}

    assert fixture_adr_provider._poll_provisioning_state(
        poller, wait_sec=0
    ) == {"status": "complete"}
    poller.result.assert_called_once_with()
    fixture_adr_provider.client.send_request.assert_not_called()


def test_post_lro_requires_location(fixture_adr_provider):
    with pytest.raises(AzureResponseError, match="without a Location header"):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller("POST"), wait_sec=0
        )


@pytest.mark.parametrize(
    "response",
    [
        Mock(status_code=204),
        Mock(status_code=200, json=Mock(side_effect=ValueError("empty"))),
    ],
)
def test_post_lro_accepts_empty_terminal_response(fixture_adr_provider, response):
    fixture_adr_provider.client.send_request.return_value = response

    assert fixture_adr_provider._poll_provisioning_state(
        _resource_poller("POST", location="https://management.azure.com/status"),
        wait_sec=0,
    ) is None


@pytest.mark.parametrize("status", ["Failed", "Canceled"])
def test_post_lro_raises_terminal_failure(fixture_adr_provider, status):
    fixture_adr_provider.client.send_request.return_value = Mock(
        status_code=200,
        headers={},
        json=Mock(return_value={"status": status, "error": {"message": "failed"}}),
    )

    with pytest.raises(AzureResponseError, match=status):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller("POST", location="https://management.azure.com/status"),
            wait_sec=0,
        )


def test_post_lro_raises_4xx_immediately(fixture_adr_provider):
    response = Mock(status_code=400)
    response.raise_for_status.side_effect = RuntimeError("bad request")
    fixture_adr_provider.client.send_request.return_value = response

    with pytest.raises(RuntimeError, match="bad request"):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller("POST", location="https://management.azure.com/status"),
            wait_sec=0,
        )


@pytest.mark.parametrize(
    "response,expected",
    [
        (Mock(status_code=500), "Timed out waiting"),
        (
            Mock(
                status_code=200,
                json=Mock(return_value={"status": "Running"}),
            ),
            "last status='Running'",
        ),
    ],
)
def test_post_lro_timeout_is_an_error(
    fixture_adr_provider, response, expected
):
    fixture_adr_provider.client.send_request.return_value = response
    clock, sleeper, _ = _fake_time()

    with pytest.raises(AzureResponseError, match=expected):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(
                "POST", location="https://management.azure.com/status"
            ),
            wait_sec=1,
            timeout_sec=3,
            clock=clock,
            sleeper=sleeper,
        )


def test_workaround_waiter_honors_initial_and_subsequent_retry_after(
    fixture_adr_provider,
):
    poller = _resource_poller()
    poller._polling_method._initial_response.http_response.headers = {
        "rEtRy-AfTeR": "2"
    }
    body = {"properties": {"provisioningState": "Succeeded"}}
    fixture_adr_provider.client.send_request.side_effect = [
        Mock(status_code=429, headers={"RETRY-AFTER": "4"}),
        Mock(status_code=200, headers={}, json=Mock(return_value=body)),
    ]
    clock, sleeper, sleeps = _fake_time()

    assert fixture_adr_provider._poll_provisioning_state(
        poller,
        timeout_sec=20,
        clock=clock,
        sleeper=sleeper,
    ) == body

    assert sleeps == [2, 4]


@pytest.mark.parametrize(
    "headers,fallback,expected",
    [
        ({"Retry-After": "45"}, 2, 30),
        ({"retry-after": "invalid"}, 7, 7),
        ({"ReTrY-AfTeR": 3}, 7, 3),
        ({"Retry-After": 0}, 4, 4),
    ],
)
def test_retry_after_is_case_insensitive_integer_and_capped(
    headers, fallback, expected
):
    assert (
        _retry_after_seconds(
            SimpleNamespace(headers=headers), fallback=fallback
        )
        == expected
    )


def test_deadline_waiter_clamps_sleep_to_remaining_time():
    clock, sleeper, sleeps = _fake_time()
    request = Mock()

    with pytest.raises(AzureResponseError, match="deadline"):
        _poll_with_deadline(
            request,
            Mock(),
            lambda: "deadline expired",
            initial_response=SimpleNamespace(
                headers={"Retry-After": "30"}
            ),
            timeout_sec=5,
            clock=clock,
            sleeper=sleeper,
        )

    assert sleeps == [5]
    request.assert_not_called()


def test_deadline_waiter_rejects_already_expired_deadline():
    request = Mock()

    with pytest.raises(AzureResponseError, match="already expired"):
        _poll_with_deadline(
            request,
            Mock(),
            lambda: "deadline already expired",
            timeout_sec=0,
            clock=lambda: 1,
            sleeper=Mock(),
        )

    request.assert_not_called()


@pytest.mark.parametrize("method", ["PATCH", "POST"])
def test_workaround_waiter_tolerates_unexpected_redirect_response(
    fixture_adr_provider, method
):
    body = (
        {"properties": {"provisioningState": "Succeeded"}}
        if method == "PATCH"
        else {"status": "Succeeded"}
    )
    fixture_adr_provider.client.send_request.side_effect = [
        Mock(status_code=302, headers={}),
        Mock(status_code=200, headers={}, json=Mock(return_value=body)),
    ]
    poller = _resource_poller(
        method,
        location=(
            "https://management.azure.com/status"
            if method == "POST"
            else None
        ),
    )

    assert fixture_adr_provider._poll_provisioning_state(
        poller, wait_sec=0
    ) == body


def test_no_wait_returns_before_workaround_polling(fixture_adr_provider):
    poller = Mock()
    fixture_adr_provider._await_terminal = Mock()

    assert (
        fixture_adr_provider._wait(
            poller, "Working...", no_wait=True
        )
        is poller
    )
    fixture_adr_provider._await_terminal.assert_not_called()


def test_resolve_location_rejects_parent_without_location(
    fixture_adr_provider,
):
    fixture_adr_provider.client.namespaces.get.return_value = {}

    with pytest.raises(AzureResponseError, match="does not contain a location"):
        fixture_adr_provider._resolve_location("namespace", "rg")


def test_poll_provisioning_state_treats_delete_404_as_success(
    fixture_adr_provider,
):
    fixture_adr_provider.client.send_request.return_value = Mock(
        status_code=404
    )

    assert (
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller("DELETE"), wait_sec=0
        )
        is None
    )


def test_poll_provisioning_state_retries_read_404_then_succeeds(
    fixture_adr_provider,
):
    body = {"properties": {"provisioningState": "Succeeded"}}
    fixture_adr_provider.client.send_request.side_effect = [
        Mock(status_code=404),
        Mock(status_code=200, json=Mock(return_value=body)),
    ]

    assert fixture_adr_provider._poll_provisioning_state(
        _resource_poller(), wait_sec=0
    ) == body
    assert fixture_adr_provider.client.send_request.call_count == 2


def test_poll_provisioning_state_accepts_resource_without_state(
    fixture_adr_provider,
):
    body = {"properties": {}}
    fixture_adr_provider.client.send_request.return_value = Mock(
        status_code=200,
        json=Mock(return_value=body),
    )

    assert fixture_adr_provider._poll_provisioning_state(
        _resource_poller(), wait_sec=0
    ) == body


@pytest.mark.parametrize("state", ["Failed", "Canceled"])
def test_poll_provisioning_state_raises_terminal_failure(
    fixture_adr_provider,
    state,
):
    body = {"properties": {"provisioningState": state}}
    fixture_adr_provider.client.send_request.return_value = Mock(
        status_code=200,
        headers={},
        json=Mock(return_value=body),
    )

    with pytest.raises(AzureResponseError, match=state):
        fixture_adr_provider._poll_provisioning_state(
            _resource_poller(), wait_sec=0
        )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unrelated"),
        HttpResponseError(message="ParentResourceNotFound", response=None),
        HttpResponseError(message="OtherNotFound", response=None),
    ],
)
def test_raise_if_parent_not_found_reraises_other_errors(
    fixture_adr_provider,
    error,
):
    if isinstance(error, HttpResponseError):
        error.status_code = (
            500 if "ParentResourceNotFound" in str(error) else 404
        )

    with pytest.raises(type(error)) as raised:
        fixture_adr_provider._raise_if_parent_not_found(
            error, "friendly message"
        )
    assert raised.value is error


def test_raise_if_parent_not_found_translates_matching_error(
    fixture_adr_provider,
):
    error = HttpResponseError(message="ParentResourceNotFound", response=None)
    error.status_code = 404

    with pytest.raises(ResourceNotFoundError, match="friendly message"):
        fixture_adr_provider._raise_if_parent_not_found(
            error, "friendly message"
        )
