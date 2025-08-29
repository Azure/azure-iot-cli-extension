# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.common import IdentityType


@pytest.mark.parametrize(
    (
        "namespace_name, resource_group_name, location, tags, no_credential, "
        "no_policy, policy_name, cert_key_type, cert_subject, cert_validity_days"
    ),
    [
        ("test-namespace", "test-rg", "eastus", None, False, False, None, None, None, None),
        ("test-namespace", "test-rg", None, {"env": "test"}, False, False, None, "RSA", "CN=test", 365),
        ("test-namespace", "test-rg", "westus", None, True, True, "test-policy", None, None, None),
    ],
)
def test_create_namespace(
    fixture_namespace_provider,
    fixture_cmd,
    namespace_name,
    resource_group_name,
    location,
    tags,
    no_credential,
        no_policy,
        policy_name,
        cert_key_type,
        cert_subject,
        cert_validity_days,
    ):
        """Test successful namespace creation."""
        mock_namespace_result = {
            "id": (
                f"/subscriptions/test-sub/resourceGroups/{resource_group_name}/"
                f"providers/Microsoft.DeviceRegistry/namespaces/{namespace_name}"
            ),
            "name": namespace_name,
            "type": "Microsoft.DeviceRegistry/namespaces",
            "location": location or "eastus",
            "identity": {"principalId": "test-principal-id", "type": "SystemAssigned"},
            "resourceGroup": resource_group_name,
        }

        # Set up the mock namespace result properly
        mock_poller = Mock()
        mock_poller.result.return_value = mock_namespace_result
        fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = mock_poller

        # Mock credential and policy providers
        with patch("azext_iot.adr.providers.credential.CredentialProvider") as mock_credential_provider_class, patch(
            "azext_iot.adr.providers.policy.PolicyProvider"
        ) as mock_policy_provider_class:

            mock_credential_provider = Mock()
            mock_policy_provider = Mock()

            mock_credential_provider_class.return_value = mock_credential_provider
            mock_policy_provider_class.return_value = mock_policy_provider

            # Mock location fallback if needed
            if not location:
                with patch.object(
                    fixture_namespace_provider, "_ensure_location", return_value="eastus"
                ) as mock_location:
                    result = fixture_namespace_provider.create(
                        namespace_name=namespace_name,
                        resource_group_name=resource_group_name,
                        location=location,
                        tags=tags,
                        no_credential=no_credential,
                        no_policy=no_policy,
                        policy_name=policy_name,
                        certificate_key_type=cert_key_type,
                        certificate_subject=cert_subject,
                        certificate_validity_days=cert_validity_days,
                    )
                    # Verify location fallback was called
                    mock_location.assert_called_once()
            else:
                result = fixture_namespace_provider.create(
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=location,
                    tags=tags,
                    no_credential=no_credential,
                    no_policy=no_policy,
                    policy_name=policy_name,
                    certificate_key_type=cert_key_type,
                    certificate_subject=cert_subject,
                    certificate_validity_days=cert_validity_days,
                )
        assert result["name"] == namespace_name
        assert result["resourceGroup"] == resource_group_name

        # Verify namespace creation call
        fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_called_once()
        call_args = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args

        assert call_args[1]["resource_group_name"] == resource_group_name
        assert call_args[1]["namespace_name"] == namespace_name

        expected_resource = {"location": location or "eastus", "identity": {"type": IdentityType.system_assigned.value}}
        if tags:
            expected_resource["tags"] = tags

        assert call_args[1]["resource"]["location"] == expected_resource["location"]
        assert call_args[1]["resource"]["identity"] == expected_resource["identity"]

        # Verify credential and policy creation based on flags
        if not no_credential:
            mock_credential_provider.create.assert_called_once_with(
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
                location=location or "eastus",
            )
        else:
            mock_credential_provider.create.assert_not_called()

        if not no_credential and not no_policy:
            mock_policy_provider.create.assert_called_once()
        else:
            mock_policy_provider.create.assert_not_called()


def test_show_namespace(fixture_namespace_provider):
    """Test successful namespace show."""
    expected_namespace = {"name": "test-namespace", "location": "eastus"}
    fixture_namespace_provider.client.namespaces.get.return_value = expected_namespace

    result = fixture_namespace_provider.show(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected_namespace
    fixture_namespace_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


def test_delete_namespace(fixture_namespace_provider):
    """Test successful namespace deletion."""
    fixture_namespace_provider.client.namespaces.begin_delete.return_value = Mock()

    result = fixture_namespace_provider.delete(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result is not None
    fixture_namespace_provider.client.namespaces.begin_delete.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


def test_list_namespaces_by_resource_group(fixture_namespace_provider):
    """Test successful namespace listing by resource group."""
    expected_namespaces = [
        {"name": "namespace1", "location": "eastus"},
        {"name": "namespace2", "location": "westus"},
    ]
    fixture_namespace_provider.client.namespaces.list_by_resource_group.return_value = expected_namespaces

    result = fixture_namespace_provider.list(resource_group_name="test-rg")

    assert result == expected_namespaces
    fixture_namespace_provider.client.namespaces.list_by_resource_group.assert_called_once_with(
        resource_group_name="test-rg"
    )


def test_list_namespaces_by_subscription(fixture_namespace_provider):
    """Test successful namespace listing by subscription."""
    expected_namespaces = [
        {"name": "namespace1", "location": "eastus"},
        {"name": "namespace2", "location": "westus"},
    ]
    fixture_namespace_provider.client.namespaces.list_by_subscription.return_value = expected_namespaces

    result = fixture_namespace_provider.list()

    assert result == expected_namespaces
    fixture_namespace_provider.client.namespaces.list_by_subscription.assert_called_once()


@pytest.mark.parametrize(
    "namespace_name, resource_group_name, tags",
    [
        ("test-namespace", "test-rg", {"env": "production"}),
        ("prod-namespace", "prod-rg", {"team": "platform", "env": "prod"}),
        ("update-namespace", "update-rg", None),  # Test with no tags
    ],
)
def test_update_namespace(fixture_namespace_provider, namespace_name, resource_group_name, tags):
    """Test successful namespace update."""
    mock_update_result = Mock()
    fixture_namespace_provider.client.namespaces.begin_update.return_value = mock_update_result

    result = fixture_namespace_provider.update(
        namespace_name=namespace_name, resource_group_name=resource_group_name, tags=tags
    )

    assert result == mock_update_result
    fixture_namespace_provider.client.namespaces.begin_update.assert_called_once()

    call_args = fixture_namespace_provider.client.namespaces.begin_update.call_args
    assert call_args[1]["resource_group_name"] == resource_group_name
    assert call_args[1]["namespace_name"] == namespace_name

    properties = call_args[1]["properties"]
    if tags is not None:
        assert properties["tags"] == tags
    else:
        # Should be empty dict when no tags provided
        assert properties == {}
