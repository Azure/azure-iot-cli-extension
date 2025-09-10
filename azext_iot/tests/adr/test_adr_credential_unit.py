# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch


@pytest.mark.parametrize(
    "namespace_name, resource_group_name, location, tags",
    [
        ("test-namespace", "test-rg", "eastus", None),
        ("test-namespace", "test-rg", None, {"env": "test", "team": "devops"}),
        ("another-ns", "another-rg", "westus", {"project": "iot"}),
    ],
)
def test_create_credential(
    fixture_credential_provider, mock_poller, namespace_name, resource_group_name, location, tags
):
    """Test successful credential creation."""
    mock_credential_result = Mock()
    poller = mock_poller(mock_credential_result)
    fixture_credential_provider.client.credentials.begin_create_or_update.return_value = poller

    if not location:
        mock_namespace_location = "namespace_location"
        mock_namespace = {"location": mock_namespace_location}
        fixture_credential_provider.client.namespaces.get.return_value = mock_namespace

        result = fixture_credential_provider.create(
            namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags
        )
        # Verify namespace get for location
        fixture_credential_provider.client.namespaces.get.assert_called_once_with(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )
        expected_location = mock_namespace_location
    else:
        result = fixture_credential_provider.create(
            namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags
        )
        expected_location = location

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
