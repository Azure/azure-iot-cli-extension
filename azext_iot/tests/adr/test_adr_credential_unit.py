# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch

from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError


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
    """Test successful credential creation."""
    mock_credential_result = Mock()
    poller = mock_poller(mock_credential_result)
    fixture_credential_provider.client.credentials.begin_create_or_update.return_value = poller

    # Mock namespace.get to return location
    mock_namespace_location = "namespace_location"
    mock_namespace = {"location": mock_namespace_location}
    fixture_credential_provider.client.namespaces.get.return_value = mock_namespace

    result = fixture_credential_provider.create(
        namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags
    )

    if location:
        # Verify namespace get was NOT called when location is provided
        fixture_credential_provider.client.namespaces.get.assert_not_called()
        expected_location = location
    else:
        # Verify namespace get for location
        fixture_credential_provider.client.namespaces.get.assert_called_once_with(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )
        expected_location = mock_namespace_location

    assert result == mock_credential_result

    fixture_credential_provider.client.credentials.begin_create_or_update.assert_called_once()
    call_args = fixture_credential_provider.client.credentials.begin_create_or_update.call_args
    called_with = call_args[1]

    assert called_with["resource_group_name"] == resource_group_name
    assert called_with["namespace_name"] == namespace_name

    # Verify the credential was created with the correct location
    assert called_with["resource"]["location"] == expected_location
    if tags:
        assert called_with["resource"]["tags"] == tags


def test_show_credential(fixture_credential_provider):
    """Test successful credential show."""
    expected_credential = {"name": "default", "location": "eastus", "properties": {"status": "active"}}
    fixture_credential_provider.client.credentials.get.return_value = expected_credential

    result = fixture_credential_provider.show(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected_credential
    fixture_credential_provider.client.credentials.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


@pytest.mark.parametrize(
    "namespace_exists, expected_exception",
    [
        (True, ResourceNotFoundError),
        (False, HttpResponseError),
    ],
)
def test_show_credential_not_found(fixture_credential_provider, namespace_exists, expected_exception):
    """Test credential show when credential or namespace doesn't exist - covers both namespace exists/doesn't exist scenarios."""
    test_namespace = "test-namespace"
    test_rg = "test_rg"

    # HTTP 404 mock
    mock_404_response = Mock()
    mock_404_response.status_code = 404
    http_404_error = HttpResponseError(response=mock_404_response)

    if namespace_exists:
        # namespace get succeeds
        mock_namespace = Mock()
        fixture_credential_provider.client.namespaces.get.return_value = mock_namespace
        # credential returns 404
        fixture_credential_provider.client.credentials.get.side_effect = http_404_error
    else:
        # namespace returns 404
        fixture_credential_provider.client.namespaces.get.side_effect = http_404_error

    with pytest.raises(expected_exception) as exc_info:
        fixture_credential_provider.show(namespace_name=test_namespace, resource_group_name=test_rg)

    if namespace_exists:
        error_message = str(exc_info.value)
        assert f"No credential found for namespace '{test_namespace}'" in error_message
    else:
        assert exc_info.value.response.status_code == 404

    # Namespace get should always be called
    fixture_credential_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name=test_rg, namespace_name=test_namespace
    )

    # Credential get is only called if namespace exists
    if namespace_exists:
        fixture_credential_provider.client.credentials.get.assert_called_once_with(
            resource_group_name=test_rg, namespace_name=test_namespace
        )
    else:
        fixture_credential_provider.client.credentials.get.assert_not_called()


def test_delete_credential(fixture_credential_provider, mock_poller):
    """Test successful credential deletion."""
    mock_delete_result = Mock()
    poller = mock_poller(mock_delete_result)
    fixture_credential_provider.client.credentials.begin_delete.return_value = poller

    result = fixture_credential_provider.delete(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == mock_delete_result
    fixture_credential_provider.client.credentials.begin_delete.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


@pytest.mark.parametrize("status", ["Succeeded", "Failed"])
def test_synchronize_credential(fixture_credential_provider, mock_poller, status):
    """Test credential synchronization"""
    mock_sync_result = Mock()
    poller = mock_poller(mock_sync_result)
    poller.status = Mock(return_value=status)
    fixture_credential_provider.client.credentials.begin_synchronize.return_value = poller

    with patch("azext_iot.adr.providers.credential.console.print") as mock_console_print, patch(
        "azext_iot.adr.providers.credential.logger.warning"
    ) as mock_logger_warning:

        result = fixture_credential_provider.synchronize(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == mock_sync_result
    fixture_credential_provider.client.credentials.begin_synchronize.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )

    if status != "Succeeded":
        # Verify warning was logged
        mock_logger_warning.assert_called_once_with(f"Synchronization completed with a status of: '{status}'")
    else:
        # Verify success message was printed to console
        mock_console_print.assert_called_once_with(
            "Successfully synchronized credentials for namespace 'test-namespace'", style="green"
        )
