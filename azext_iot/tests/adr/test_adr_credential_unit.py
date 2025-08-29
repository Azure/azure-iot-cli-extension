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
def test_create_credential(fixture_credential_provider, namespace_name, resource_group_name, location, tags):
    """Test successful credential creation."""
    mock_credential_result = Mock()
    fixture_credential_provider.client.credentials.begin_create_or_update.return_value = mock_credential_result

    if not location:
        with patch.object(fixture_credential_provider, "_ensure_location", return_value="eastus") as mock_location:
            result = fixture_credential_provider.create(
                namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags
            )
            mock_location.assert_called_once()
    else:
        result = fixture_credential_provider.create(
            namespace_name=namespace_name, resource_group_name=resource_group_name, location=location, tags=tags
        )

    assert result == mock_credential_result

    fixture_credential_provider.client.credentials.begin_create_or_update.assert_called_once()
    call_args = fixture_credential_provider.client.credentials.begin_create_or_update.call_args
    called_with = call_args[1]

    assert called_with["resource_group_name"] == resource_group_name
    assert called_with["namespace_name"] == namespace_name

    expected_resource = {"location": location or "eastus"}
    if tags:
        expected_resource["tags"] = tags

    assert called_with["resource"]["location"] == expected_resource["location"]
    if tags:
        assert called_with["resource"]["tags"] == expected_resource["tags"]


def test_show_credential(fixture_credential_provider):
    """Test successful credential show."""
    expected_credential = {"name": "default", "location": "eastus", "properties": {"status": "active"}}
    fixture_credential_provider.client.credentials.get.return_value = expected_credential

    result = fixture_credential_provider.show(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected_credential
    fixture_credential_provider.client.credentials.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


def test_delete_credential(fixture_credential_provider):
    """Test successful credential deletion."""
    mock_delete_result = Mock()
    fixture_credential_provider.client.credentials.begin_delete.return_value = mock_delete_result

    result = fixture_credential_provider.delete(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == mock_delete_result
    fixture_credential_provider.client.credentials.begin_delete.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


def test_synchronize_credential(fixture_credential_provider):
    """Test successful credential synchronization."""
    mock_sync_result = Mock()
    fixture_credential_provider.client.credentials.begin_synchronize.return_value = mock_sync_result

    result = fixture_credential_provider.synchronize(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == mock_sync_result
    fixture_credential_provider.client.credentials.begin_synchronize.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )
