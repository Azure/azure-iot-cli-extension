# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock


@pytest.mark.parametrize(
    "policy_name, namespace_name, resource_group_name, location, cert_key_type, cert_subject, cert_validity_days, tags",
    [
        ("policy", "namespace", "rg", "location", "ECC", "test", 30, {"example": "tag"}),
        ("policy", "namespace", "rg", None, "RSA", None, None, None),
        ("policy", "namespace", "rg", "location", None, "test", None, {"example": "tag"}),
    ],
)
def test_create_policy(
    fixture_policy_provider,
    mock_poller,
    policy_name,
    namespace_name,
    resource_group_name,
    location,
    cert_key_type,
    cert_subject,
    cert_validity_days,
    tags,
):
    """Test successful policy creation with various parameter combinations."""
    mock_policy_result = Mock()
    poller = mock_poller(mock_policy_result)
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = poller

    if not location:
        # Mock namespace.get to return location
        mock_namespace_location = "namespace_location"
        mock_namespace = {"location": mock_namespace_location}
        fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

        result = fixture_policy_provider.create(
            policy_name=policy_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            location=location,
            tags=tags,
            certificate_key_type=cert_key_type,
            certificate_subject=cert_subject,
            certificate_validity_days=cert_validity_days,
        )
        # Verify namespace get for location
        fixture_policy_provider.client.namespaces.get.assert_called_once_with(
            resource_group_name=resource_group_name, namespace_name=namespace_name
        )
        expected_location = mock_namespace_location
    else:
        # Act
        result = fixture_policy_provider.create(
            policy_name=policy_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            location=location,
            tags=tags,
            certificate_key_type=cert_key_type,
            certificate_subject=cert_subject,
            certificate_validity_days=cert_validity_days,
        )
        expected_location = location

    assert result == mock_policy_result

    # Verify client call
    fixture_policy_provider.client.policies.begin_create_or_update.assert_called_once()
    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args

    assert call_args[1]["resource_group_name"] == resource_group_name
    assert call_args[1]["namespace_name"] == namespace_name
    assert call_args[1]["policy_name"] == policy_name

    # Verify resource structure
    resource = call_args[1]["resource"]
    # Verify the policy was created with the correct location
    assert resource["location"] == expected_location

    if tags:
        assert resource["tags"] == tags
    else:
        assert "tags" not in resource

    # Verify certificate configuration
    if cert_key_type or cert_subject or cert_validity_days:
        assert "properties" in resource
        assert "certificate" in resource["properties"]
        cert_config = resource["properties"]["certificate"]

        # Check CA configuration
        if cert_key_type or cert_subject:
            assert "certificateAuthorityConfiguration" in cert_config
            ca_config = cert_config["certificateAuthorityConfiguration"]

            if cert_key_type:
                assert ca_config["keyType"] == cert_key_type
            if cert_subject:
                assert ca_config["subject"] == cert_subject

        # Check leaf certificate configuration
        if cert_validity_days:
            assert "leafCertificateConfiguration" in cert_config
            leaf_config = cert_config["leafCertificateConfiguration"]
            assert leaf_config["validityPeriodInDays"] == cert_validity_days
    else:
        # No certificate configuration should be present
        if "properties" in resource:
            assert "certificate" not in resource["properties"]


def test_show_policy(fixture_policy_provider):
    """Test successful policy show."""
    expected_policy = {
        "name": "test-policy",
        "location": "eastus",
        "properties": {"certificate": {"status": "active"}},
    }
    fixture_policy_provider.client.policies.get.return_value = expected_policy

    result = fixture_policy_provider.show(
        policy_name="test-policy", namespace_name="test-namespace", resource_group_name="test-rg"
    )

    assert result == expected_policy
    fixture_policy_provider.client.policies.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace", policy_name="test-policy"
    )


def test_list_policies_by_resource_group(fixture_policy_provider):
    """Test successful policy listing by resource group."""
    expected_policies = [{"name": "policy1", "location": "eastus"}, {"name": "policy2", "location": "westus"}]
    mock_policies_iterator = Mock()
    mock_policies_iterator.__iter__ = Mock(return_value=iter(expected_policies))
    fixture_policy_provider.client.policies.list_by_resource_group.return_value = mock_policies_iterator

    result = fixture_policy_provider.list(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected_policies
    fixture_policy_provider.client.policies.list_by_resource_group.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )


def test_list_policies_by_subscription(fixture_policy_provider):
    """Test successful policy listing by subscription."""
    expected_policies = [{"name": "policy1", "location": "eastus"}, {"name": "policy2", "location": "westus"}]
    mock_policies_iterator = Mock()
    mock_policies_iterator.__iter__ = Mock(return_value=iter(expected_policies))
    fixture_policy_provider.client.policies.list_by_subscription.return_value = mock_policies_iterator

    result = fixture_policy_provider.list(namespace_name="test-namespace")

    assert result == expected_policies
    fixture_policy_provider.client.policies.list_by_subscription.assert_called_once_with(
        namespace_name="test-namespace"
    )


def test_delete_policy(fixture_policy_provider, mock_poller):
    """Test successful policy deletion."""
    mock_delete_result = Mock()
    poller = mock_poller(mock_delete_result)
    fixture_policy_provider.client.policies.begin_delete.return_value = poller

    result = fixture_policy_provider.delete(
        policy_name="test-policy", namespace_name="test-namespace", resource_group_name="test-rg"
    )

    assert result == mock_delete_result
    fixture_policy_provider.client.policies.begin_delete.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace", policy_name="test-policy"
    )


@pytest.mark.parametrize(
    "cert_key_type, cert_subject, cert_validity_days",
    [
        ("RSA", None, None),
        (None, "test", None),
        ("ECC", "test", None),
        (None, None, 30),
        ("RSA", "test", 30),
    ],
)
def test_certificate_configuration_combinations(
    fixture_policy_provider,
    cert_key_type,
    cert_subject,
    cert_validity_days,
):
    """Test various certificate configuration combinations."""
    mock_policy_result = Mock()
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = mock_policy_result

    fixture_policy_provider.create(
        policy_name="cert-test-policy",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        location="eastus",
        certificate_key_type=cert_key_type,
        certificate_subject=cert_subject,
        certificate_validity_days=cert_validity_days,
    )

    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args
    resource = call_args[1]["resource"]

    # Verify certificate configuration
    if cert_key_type or cert_subject or cert_validity_days:
        assert "properties" in resource
        assert "certificate" in resource["properties"]
        cert_config = resource["properties"]["certificate"]

        # Check CA configuration
        if cert_key_type or cert_subject:
            assert "certificateAuthorityConfiguration" in cert_config
            ca_config = cert_config["certificateAuthorityConfiguration"]

            if cert_key_type:
                assert ca_config["keyType"] == cert_key_type
            if cert_subject:
                assert ca_config["subject"] == cert_subject

        # Check leaf certificate configuration
        if cert_validity_days:
            assert "leafCertificateConfiguration" in cert_config
            leaf_config = cert_config["leafCertificateConfiguration"]
            assert leaf_config["validityPeriodInDays"] == cert_validity_days
    else:
        # No certificate configuration should be present
        if "properties" in resource:
            assert "certificate" not in resource["properties"]


@pytest.mark.parametrize(
    "tags, cert_subject, cert_validity_days",
    [
        (None, None, None),
        ({"env": "test"}, "test", None),
        ({"env": "prod", "team": "ops"}, None, 30),
        (None, "test", 30),
    ],
)
def test_update_policy(fixture_policy_provider, mock_poller, tags, cert_subject, cert_validity_days):
    """Test successful policy update."""
    mock_update_result = Mock()
    poller = mock_poller(mock_update_result)
    fixture_policy_provider.client.policies.begin_update.return_value = poller

    result = fixture_policy_provider.update(
        policy_name="test-policy",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        tags=tags,
        certificate_subject=cert_subject,
        certificate_validity_days=cert_validity_days,
    )

    # If no changes, the method returns early with None
    if not tags and not cert_subject and not cert_validity_days:
        assert result is None
        fixture_policy_provider.client.policies.begin_update.assert_not_called()
        return

    assert result == mock_update_result
    fixture_policy_provider.client.policies.begin_update.assert_called_once()

    call_args = fixture_policy_provider.client.policies.begin_update.call_args
    assert call_args[1]["resource_group_name"] == "test-rg"
    assert call_args[1]["namespace_name"] == "test-namespace"
    assert call_args[1]["policy_name"] == "test-policy"

    properties = call_args[1]["properties"]

    # Verify tags
    if tags:
        assert "tags" in properties
        assert properties["tags"] == tags
    else:
        assert "tags" not in properties or properties["tags"] is None

    # Verify certificate configuration based on parameters
    if cert_subject or cert_validity_days:
        assert "properties" in properties
        cert_props = properties["properties"].get("certificate", {})

        if cert_subject:
            ca_config = cert_props.get("certificateAuthorityConfiguration", {})
            assert ca_config["subject"] == cert_subject

        if cert_validity_days:
            leaf_config = cert_props.get("leafCertificateConfiguration", {})
            assert leaf_config["validityPeriodInDays"] == cert_validity_days


def test_update_policy_no_changes(fixture_policy_provider):
    """Test policy update with no parameters returns early."""
    result = fixture_policy_provider.update(
        policy_name="test-policy",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
    )

    # Should return early without calling the client
    assert result is None
    fixture_policy_provider.client.policies.begin_update.assert_not_called()
