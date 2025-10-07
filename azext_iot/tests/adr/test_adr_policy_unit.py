# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock

from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError


@pytest.mark.parametrize(
    "test_params",
    [
        {
            "policy_name": "policy",
            "namespace_name": "namespace",
            "resource_group_name": "rg",
            "cert_key_type": "ECC",
            "cert_subject": "test",
            "cert_validity_days": 30,
            "tags": {"example": "tag"},
            "location": None,
        },
        {
            "policy_name": "policy",
            "namespace_name": "namespace",
            "resource_group_name": "rg",
            "cert_key_type": "RSA",
            "cert_subject": None,
            "cert_validity_days": None,
            "tags": None,
            "location": None,
        },
        {
            "policy_name": "policy",
            "namespace_name": "namespace",
            "resource_group_name": "rg",
            "cert_key_type": None,
            "cert_subject": "test",
            "cert_validity_days": None,
            "tags": {"example": "tag"},
            "location": None,
        },
        {
            "policy_name": "policy",
            "namespace_name": "namespace",
            "resource_group_name": "rg",
            "cert_key_type": "ECC",
            "cert_subject": "test",
            "cert_validity_days": 30,
            "tags": {"example": "tag"},
            "location": "westus",
        },
        {
            "policy_name": "policy",
            "namespace_name": "namespace",
            "resource_group_name": "rg",
            "cert_key_type": "RSA",
            "cert_subject": None,
            "cert_validity_days": None,
            "tags": None,
            "location": "eastus",
        },
    ],
)
def test_create_policy(
    fixture_policy_provider,
    mock_poller,
    test_params,
):
    """Test successful policy creation with various parameter combinations."""
    mock_policy_result = Mock()
    poller = mock_poller(mock_policy_result)
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = poller

    # Mock namespace.get to return location
    mock_namespace_location = "namespace_location"
    mock_namespace = {"location": mock_namespace_location}
    fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

    result = fixture_policy_provider.create(
        policy_name=test_params["policy_name"],
        namespace_name=test_params["namespace_name"],
        resource_group_name=test_params["resource_group_name"],
        location=test_params["location"],
        tags=test_params["tags"],
        certificate_key_type=test_params["cert_key_type"],
        certificate_subject=test_params["cert_subject"],
        certificate_validity_days=test_params["cert_validity_days"],
    )

    if test_params["location"]:
        # Verify namespace get was NOT called when location is provided
        fixture_policy_provider.client.namespaces.get.assert_not_called()
        expected_location = test_params["location"]
    else:
        # Verify namespace get for location
        fixture_policy_provider.client.namespaces.get.assert_called_once_with(
            resource_group_name=test_params["resource_group_name"], namespace_name=test_params["namespace_name"]
        )
        expected_location = mock_namespace_location

    assert result == mock_policy_result

    # Verify client call
    fixture_policy_provider.client.policies.begin_create_or_update.assert_called_once()
    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args

    assert call_args[1]["resource_group_name"] == test_params["resource_group_name"]
    assert call_args[1]["namespace_name"] == test_params["namespace_name"]
    assert call_args[1]["policy_name"] == test_params["policy_name"]

    # Verify resource structure
    resource = call_args[1]["resource"]
    # Verify the policy was created with the correct location
    assert resource["location"] == expected_location

    if test_params["tags"]:
        assert resource["tags"] == test_params["tags"]
    else:
        assert "tags" not in resource

    # Verify certificate configuration
    cert_key_type = test_params["cert_key_type"]
    cert_subject = test_params["cert_subject"]
    cert_validity_days = test_params["cert_validity_days"]

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

    # Mock successful namespace check
    mock_namespace = Mock()
    fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

    fixture_policy_provider.client.policies.get.return_value = expected_policy

    result = fixture_policy_provider.show(
        policy_name="test-policy", namespace_name="test-namespace", resource_group_name="test-rg"
    )

    assert result == expected_policy

    # Verify namespace and policy calls were made
    fixture_policy_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )
    fixture_policy_provider.client.policies.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace", policy_name="test-policy"
    )


def test_list_policies_by_resource_group(fixture_policy_provider):
    """Test successful policy listing by resource group."""
    expected_policies = [{"name": "policy1", "location": "eastus"}, {"name": "policy2", "location": "westus"}]
    mock_policies_iterator = Mock()
    mock_policies_iterator.__iter__ = Mock(return_value=iter(expected_policies))
    fixture_policy_provider.client.policies.list_by_resource_group.return_value = mock_policies_iterator

    # Mock successful namespace check
    mock_namespace = Mock()
    fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

    result = fixture_policy_provider.list(namespace_name="test-namespace", resource_group_name="test-rg")

    assert result == expected_policies

    # Verify namespace and policy list calls were made
    fixture_policy_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
    )
    fixture_policy_provider.client.policies.list_by_resource_group.assert_called_once_with(
        resource_group_name="test-rg", namespace_name="test-namespace"
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
    "cert_params",
    [
        {"cert_key_type": "RSA", "cert_subject": None, "cert_validity_days": None},
        {"cert_key_type": None, "cert_subject": "test", "cert_validity_days": None},
        {"cert_key_type": "ECC", "cert_subject": "test", "cert_validity_days": None},
        {"cert_key_type": None, "cert_subject": None, "cert_validity_days": 30},
        {"cert_key_type": "RSA", "cert_subject": "test", "cert_validity_days": 30},
    ],
)
def test_certificate_configuration_combinations(
    fixture_policy_provider,
    cert_params,
):
    """Test various certificate configuration combinations."""
    mock_policy_result = Mock()
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = mock_policy_result

    # Mock namespace.get to return location
    mock_namespace = {"location": "eastus"}
    fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

    fixture_policy_provider.create(
        policy_name="cert-test-policy",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        certificate_key_type=cert_params["cert_key_type"],
        certificate_subject=cert_params["cert_subject"],
        certificate_validity_days=cert_params["cert_validity_days"],
    )

    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args
    resource = call_args[1]["resource"]

    # Extract cert params for easier reading
    cert_key_type = cert_params["cert_key_type"]
    cert_subject = cert_params["cert_subject"]
    cert_validity_days = cert_params["cert_validity_days"]

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
    "update_params",
    [
        {"tags": None, "cert_subject": None, "cert_validity_days": None},
        {"tags": {"env": "test"}, "cert_subject": "test", "cert_validity_days": None},
        {"tags": {"env": "prod", "team": "ops"}, "cert_subject": None, "cert_validity_days": 30},
        {"tags": None, "cert_subject": "test", "cert_validity_days": 30},
    ],
)
def test_update_policy(fixture_policy_provider, mock_poller, update_params):
    """Test successful policy update."""
    mock_update_result = Mock()
    poller = mock_poller(mock_update_result)
    fixture_policy_provider.client.policies.begin_update.return_value = poller

    # Extract params for easier reading
    tags = update_params["tags"]
    cert_subject = update_params["cert_subject"]
    cert_validity_days = update_params["cert_validity_days"]

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


@pytest.mark.parametrize(
    "namespace_exists, expected_exception",
    [
        (True, ResourceNotFoundError),
        (False, HttpResponseError),
    ],
)
def test_show_policy_error_scenarios(fixture_policy_provider, namespace_exists, expected_exception):
    """Test policy show error scenarios: namespace missing or credentials missing."""
    test_namespace = "test-namespace"
    test_rg = "test-rg"
    test_policy = "test-policy"

    # HTTP 404 mock
    mock_404_response = Mock()
    mock_404_response.status_code = 404
    http_404_error = HttpResponseError(response=mock_404_response)

    if namespace_exists:
        # Mock namespace exists
        mock_namespace = Mock()
        fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

        # ParentResourceNotFound (credentials don't exist)
        class MockParentResourceNotFoundError(HttpResponseError):
            def __str__(self):
                return "ParentResourceNotFound"

        parent_error = MockParentResourceNotFoundError(response=mock_404_response)
        fixture_policy_provider.client.policies.get.side_effect = parent_error
    else:
        # Mock namespace doesn't exist
        fixture_policy_provider.client.namespaces.get.side_effect = http_404_error

    with pytest.raises(expected_exception) as exc_info:
        fixture_policy_provider.show(
            policy_name=test_policy, namespace_name=test_namespace, resource_group_name=test_rg
        )

    error_message = str(exc_info.value)
    if namespace_exists:
        assert f"No credential exists on namespace '{test_namespace}'" in error_message
        fixture_policy_provider.client.policies.get.assert_called_once_with(
            resource_group_name=test_rg, namespace_name=test_namespace, policy_name=test_policy
        )
    else:
        assert exc_info.value.response.status_code == 404
        fixture_policy_provider.client.policies.get.assert_not_called()

    # Namespace get should always be called
    fixture_policy_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name=test_rg, namespace_name=test_namespace
    )


@pytest.mark.parametrize(
    "namespace_exists, expected_exception",
    [
        (True, ResourceNotFoundError),
        (False, HttpResponseError),
    ],
)
def test_list_policy_error_scenarios(fixture_policy_provider, namespace_exists, expected_exception):
    """Test policy list error scenarios: namespace missing or credentials missing."""
    test_namespace = "test-namespace"
    test_rg = "test-rg"

    # HTTP 404 mock
    mock_404_response = Mock()
    mock_404_response.status_code = 404
    http_404_error = HttpResponseError(response=mock_404_response)

    if namespace_exists:
        # Mock namespace exists
        mock_namespace = Mock()
        fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

        # ParentResourceNotFound (credentials don't exist)
        class MockParentResourceNotFoundError(HttpResponseError):
            def __str__(self):
                return "ParentResourceNotFound error message"

        parent_error = MockParentResourceNotFoundError(response=mock_404_response)
        fixture_policy_provider.client.policies.list_by_resource_group.side_effect = parent_error
    else:
        # Mock namespace doesn't exist
        fixture_policy_provider.client.namespaces.get.side_effect = http_404_error

    with pytest.raises(expected_exception) as exc_info:
        fixture_policy_provider.list(namespace_name=test_namespace, resource_group_name=test_rg)

    error_message = str(exc_info.value)
    if namespace_exists:
        assert f"No credential exists on namespace '{test_namespace}'" in error_message
        fixture_policy_provider.client.policies.list_by_resource_group.assert_called_once_with(
            resource_group_name=test_rg, namespace_name=test_namespace
        )
    else:
        assert exc_info.value.response.status_code == 404
        fixture_policy_provider.client.policies.list_by_resource_group.assert_not_called()

    # Namespace get should always be called
    fixture_policy_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name=test_rg, namespace_name=test_namespace
    )
