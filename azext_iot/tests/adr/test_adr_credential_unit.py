# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import AzureResponseError, ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

# ==================== Create ====================


def test_create_credential_namespace_missing_location(fixture_credential_provider):
    """Create raises when parent namespace has no location to inherit."""
    fixture_credential_provider.client.namespaces.get.return_value = {}

    with pytest.raises(AzureResponseError):
        fixture_credential_provider.create(
            namespace_name="test-namespace", resource_group_name="test-rg", location=None,
        )


@pytest.mark.parametrize(
    "namespace_name, resource_group_name, tags, location",
    [
        ("test-namespace", "test-rg", None, None),
        ("test-namespace", "test-rg", {"env": "test", "team": "devops"}, None),
        ("another-ns", "another-rg", {"project": "iot"}, None),
        ("test-namespace", "test-rg", None, "westus"),
        ("test-namespace", "test-rg", {"env": "test"}, "eastus"),
    ],
)
def test_create_credential(
    fixture_credential_provider, mock_poller, namespace_name, resource_group_name, tags, location
):
    """Credential creation with various parameter combinations."""
    expected = {"name": "default", "location": "eastus"}
    ns_location = "namespace_location"
    fixture_credential_provider.client.credentials.begin_create_or_update.return_value = mock_poller(
        expected
    )
    fixture_credential_provider.client.namespaces.get.return_value = {"location": ns_location}

    result = fixture_credential_provider.create(
        namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags,
    )

    assert result == expected

    if location:
        fixture_credential_provider.client.namespaces.get.assert_not_called()
    else:
        fixture_credential_provider.client.namespaces.get.assert_called_once_with(
            resource_group_name=resource_group_name, namespace_name=namespace_name,
        )

    kw = fixture_credential_provider.client.credentials.begin_create_or_update.call_args[1]
    assert kw["resource_group_name"] == resource_group_name
    assert kw["namespace_name"] == namespace_name
    assert kw["resource"]["location"] == (location or ns_location)
    if tags:
        assert kw["resource"]["tags"] == tags


# ==================== Show ====================


def test_show_credential(fixture_credential_provider):
    """Show returns the serialized credential."""
    expected = {"name": "default", "location": "eastus", "properties": {"status": "active"}}
    fixture_credential_provider.client.namespaces.get.return_value = Mock()
    fixture_credential_provider.client.credentials.get.return_value = expected

    result = fixture_credential_provider.show(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected
    fixture_credential_provider.client.credentials.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace",
    )


# ==================== Error Scenarios ====================


@pytest.mark.parametrize(
    "ns_exists, expected_exception",
    [(True, ResourceNotFoundError), (False, HttpResponseError)],
    ids=["credential-missing", "namespace-missing"],
)
def test_show_credential_not_found(fixture_credential_provider, ns_exists, expected_exception):
    """Show raises appropriate error when credential or namespace is missing."""
    ns_name, rg = "test-namespace", "test-rg"
    http_404 = HttpResponseError(response=Mock(status_code=404))

    if ns_exists:
        fixture_credential_provider.client.namespaces.get.return_value = Mock()
        fixture_credential_provider.client.credentials.get.side_effect = http_404
    else:
        fixture_credential_provider.client.namespaces.get.side_effect = http_404

    with pytest.raises(expected_exception) as exc_info:
        fixture_credential_provider.show(namespace_name=ns_name, resource_group_name=rg)

    if ns_exists:
        assert f"No credential found for namespace '{ns_name}'" in str(exc_info.value)
        fixture_credential_provider.client.credentials.get.assert_called_once()
    else:
        assert exc_info.value.response.status_code == 404
        fixture_credential_provider.client.credentials.get.assert_not_called()


def test_show_credential_reraises_non_404(fixture_credential_provider):
    """Show re-raises HttpResponseError when status code is not 404."""
    fixture_credential_provider.client.namespaces.get.return_value = Mock()
    fixture_credential_provider.client.credentials.get.side_effect = HttpResponseError(
        response=Mock(status_code=500)
    )

    with pytest.raises(HttpResponseError) as exc_info:
        fixture_credential_provider.show(namespace_name="test-namespace", resource_group_name="test-rg")

    assert exc_info.value.response.status_code == 500


# ==================== Delete ====================


def test_delete_credential(fixture_credential_provider, mock_poller):
    """Delete triggers begin_delete LRO and returns the result."""
    sentinel = Mock()
    fixture_credential_provider.client.credentials.begin_delete.return_value = mock_poller(sentinel)

    result = fixture_credential_provider.delete(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == sentinel
    fixture_credential_provider.client.credentials.begin_delete.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace",
    )


# ==================== Synchronize ====================


def test_synchronize_credential(fixture_credential_provider, mock_poller):
    """Synchronize triggers LRO and prints success message."""
    sentinel = Mock()
    poller = mock_poller(sentinel)
    fixture_credential_provider.client.credentials.begin_synchronize.return_value = poller

    with patch("azext_iot.adr.providers.credential.console.print") as mock_print:
        result = fixture_credential_provider.synchronize(
            namespace_name="test-namespace", resource_group_name="test-rg",
        )

    assert result == sentinel
    fixture_credential_provider.client.credentials.begin_synchronize.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace",
    )
    mock_print.assert_called_once_with(
        "Successfully synchronized credentials for namespace 'test-namespace'", style="green",
    )


def test_synchronize_credential_swallows_false_positive(fixture_credential_provider):
    """Synchronize swallows HttpResponseError with status 200 (ARMPolling false positive)."""
    from azure.core.exceptions import HttpResponseError

    mock_response = Mock()
    mock_response.status_code = 200
    error = HttpResponseError(response=mock_response, message="Operation returned an invalid status 'OK'")

    poller = Mock()
    poller.done.return_value = True
    # wait_for_terminal_state calls poller.result() which we need to raise
    poller.result.side_effect = error
    fixture_credential_provider.client.credentials.begin_synchronize.return_value = poller

    with patch("azext_iot.adr.providers.credential.console.print") as mock_print:
        result = fixture_credential_provider.synchronize(
            namespace_name="test-namespace", resource_group_name="test-rg",
        )

    assert result is None
    mock_print.assert_called_once_with(
        "Successfully synchronized credentials for namespace 'test-namespace'", style="green",
    )


def test_synchronize_credential_raises_real_error(fixture_credential_provider):
    """Synchronize re-raises HttpResponseError with non-200 status codes."""
    from azure.core.exceptions import HttpResponseError

    mock_response = Mock()
    mock_response.status_code = 500
    error = HttpResponseError(response=mock_response, message="Internal Server Error")

    poller = Mock()
    poller.done.return_value = True
    poller.result.side_effect = error
    fixture_credential_provider.client.credentials.begin_synchronize.return_value = poller

    with pytest.raises(HttpResponseError):
        fixture_credential_provider.synchronize(
            namespace_name="test-namespace", resource_group_name="test-rg",
        )
