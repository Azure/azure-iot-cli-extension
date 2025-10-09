# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock, patch

import pytest
from azure.cli.core.azclierror import MutuallyExclusiveArgumentError

from azext_iot.adr.common import (
    DEFAULT_NS_POLICY_CERT_KEY_TYPE,
    DEFAULT_NS_POLICY_NAME,
    DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS,
    IdentityType,
)


@pytest.mark.parametrize("enable_credential_policy", [False, True])
@pytest.mark.parametrize("policy_name", [None, "test-policy"])
@pytest.mark.parametrize("cert_key_type", [None, DEFAULT_NS_POLICY_CERT_KEY_TYPE])
@pytest.mark.parametrize("cert_validity_days", [None, 30])
@pytest.mark.parametrize("cert_subject", [None, "CN=TestSubject"])
def test_create_namespace(
    fixture_namespace_provider,
    fixture_credential_provider,
    fixture_policy_provider,
    mock_poller,
    cert_key_type,
    cert_validity_days,
    cert_subject,
    policy_name,
    enable_credential_policy,
):
    namespace_name = "test-namespace"
    resource_group_name = "test-rg"
    location = "eastus"
    tags = None

    fixture_credential_provider.create = Mock(return_value={"id": "credential-id"})
    fixture_policy_provider.create = Mock(return_value={"id": "policy-id"})

    # Check if we should create credential policy
    should_create_credential_policy = any(
        [
            enable_credential_policy,
            policy_name,
            cert_key_type,
            cert_subject,
            cert_validity_days,
        ]
    )

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
            "location": location,
            "identity": {"principalId": "test-principal-id", "type": "SystemAssigned"},
            "resourceGroup": resource_group_name,
        }
        namespace_poller = mock_poller(mock_namespace_result)
        fixture_namespace_provider.client.namespaces.begin_create_or_replace.return_value = namespace_poller
        credential_poller = mock_poller({"id": "credential-id"})
        fixture_namespace_provider.client.credentials.begin_create_or_update.return_value = credential_poller
        fallback_location = location

        # Test parameter validation
        if enable_credential_policy is False and any([
            policy_name is not None,
            cert_key_type is not None,
            cert_validity_days is not None,
            cert_subject is not None,
        ]):
            with pytest.raises(MutuallyExclusiveArgumentError):
                fixture_namespace_provider.create(
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=location,
                    tags=tags,
                    enable_credential_policy=enable_credential_policy,
                    policy_name=policy_name,
                    certificate_key_type=cert_key_type,
                    certificate_subject=cert_subject,
                    certificate_validity_days=cert_validity_days,
                )
        else:
            result = fixture_namespace_provider.create(
                namespace_name=namespace_name,
                resource_group_name=resource_group_name,
                location=location,
                tags=tags,
                enable_credential_policy=enable_credential_policy,
                policy_name=policy_name,
                certificate_key_type=cert_key_type,
                certificate_subject=cert_subject,
                certificate_validity_days=cert_validity_days,
            )

            assert result["name"] == namespace_name
            assert result["resourceGroup"] == resource_group_name

            fixture_namespace_provider.client.namespaces.begin_create_or_replace.assert_called_once()
            call_args = fixture_namespace_provider.client.namespaces.begin_create_or_replace.call_args

            assert call_args[1]["resource_group_name"] == resource_group_name
            assert call_args[1]["namespace_name"] == namespace_name

            expected_resource = {
                "location": fallback_location,
                "identity": {"type": IdentityType.system_assigned.value},
            }
            assert call_args[1]["resource"]["location"] == expected_resource["location"]
            assert call_args[1]["resource"]["identity"] == expected_resource["identity"]

            should_create_credential_policy = any(
                [enable_credential_policy, policy_name, cert_key_type, cert_subject, cert_validity_days]
            )

            if should_create_credential_policy:
                fixture_credential_provider.create.assert_called_once_with(
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=fallback_location,
                )
                expected_policy_name = policy_name if policy_name is not None else DEFAULT_NS_POLICY_NAME
                expected_cert_key_type = cert_key_type if cert_key_type is not None else DEFAULT_NS_POLICY_CERT_KEY_TYPE
                expected_cert_validity_days = (
                    cert_validity_days if cert_validity_days is not None else DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS
                )

                fixture_policy_provider.create.assert_called_once_with(
                    policy_name=expected_policy_name,
                    namespace_name=namespace_name,
                    resource_group_name=resource_group_name,
                    location=fallback_location,
                    certificate_key_type=expected_cert_key_type,
                    certificate_subject=cert_subject,
                    certificate_validity_days=expected_cert_validity_days,
                )
            else:
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
