# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.common import IdentityType
from azext_iot.tests.generators import generate_names


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
    fixture_credential_provider,
    fixture_policy_provider,
    mock_poller,
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
    fixture_credential_provider.create = Mock(return_value={"id": "credential-id"})
    fixture_policy_provider.create = Mock(return_value={"id": "policy-id"})

    with patch(
        "azext_iot.adr.providers.credential.CredentialProvider", return_value=fixture_credential_provider
    ), patch("azext_iot.adr.providers.policy.PolicyProvider", return_value=fixture_policy_provider):

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
        namespace_poller = mock_poller(mock_namespace_result)
        fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = namespace_poller

        # Mock credential and policy creation pollers
        credential_poller = mock_poller({"id": "credential-id"})
        fixture_namespace_provider.client.credentials.begin_create_or_update.return_value = credential_poller

        # Mock location fallback if needed
        if not location:
            fallback_location = generate_names("test-location-")
            with patch.object(
                fixture_namespace_provider, "_ensure_location", return_value=fallback_location
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
            fallback_location = location  # Use the provided location
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

        expected_resource = {"location": fallback_location, "identity": {"type": IdentityType.system_assigned.value}}
        if tags:
            expected_resource["tags"] = tags

        assert call_args[1]["resource"]["location"] == expected_resource["location"]
        assert call_args[1]["resource"]["identity"] == expected_resource["identity"]

        # Verify credential and policy creation based on flags
        if not no_credential:
            # Should call credential create
            fixture_credential_provider.create.assert_called_once_with(
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
            )

            if not no_policy:
                # Should call policy create
                fixture_policy_provider.create.assert_called_once_with(
                    policy_name=policy_name,
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    certificate_key_type=cert_key_type,
                    certificate_subject=cert_subject,
                    certificate_validity_days=cert_validity_days,
                )
            else:
                # Should not call policy create
                fixture_policy_provider.create.assert_not_called()
        else:
            # Should not call credential or policy create
            fixture_credential_provider.create.assert_not_called()
            fixture_policy_provider.create.assert_not_called()


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
def test_update_namespace(fixture_namespace_provider, mock_poller, namespace_name, resource_group_name, tags):
    """Test successful namespace update."""
    mock_update_result = Mock()
    poller = mock_poller(mock_update_result)
    fixture_namespace_provider.client.namespaces.begin_update.return_value = poller

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
