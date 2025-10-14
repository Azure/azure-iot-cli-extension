# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.common import DEFAULT_NS_POLICY_CERT_KEY_TYPE, DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS


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
            "cert_key_type": None,
            "cert_subject": None,
            "cert_validity_days": None,
            "tags": None,
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
            "cert_key_type": None,
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


@pytest.mark.parametrize("cert_key_type", [None, "ECC"])
@pytest.mark.parametrize("cert_validity_days", [None, 30])
@pytest.mark.parametrize("cert_subject", [None, "test"])
def test_create_policy_certificate_validation(
    fixture_policy_provider,
    mock_poller,
    cert_key_type,
    cert_validity_days,
    cert_subject,
):
    """Test certificate parameter validation - defaults are provided when parameters are specified."""
    # Mock successful creation
    mock_policy_result = Mock()
    poller = mock_poller(mock_policy_result)
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = poller

    # Mock namespace.get to return location
    mock_namespace = {"location": "eastus"}
    fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

    result = fixture_policy_provider.create(
        policy_name="cert-test-policy",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        certificate_key_type=cert_key_type,
        certificate_subject=cert_subject,
        certificate_validity_days=cert_validity_days,
    )

    assert result == mock_policy_result

    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args
    resource = call_args[1]["resource"]

    # Verify certificate configuration
    if any([cert_subject is not None, cert_key_type is not None, cert_validity_days is not None]):
        assert "properties" in resource
        assert "certificate" in resource["properties"]
        cert_config = resource["properties"]["certificate"]

        # Check CA configuration
        assert "certificateAuthorityConfiguration" in cert_config
        ca_config = cert_config["certificateAuthorityConfiguration"]

        # Key type should default if None
        expected_key_type = cert_key_type if cert_key_type is not None else DEFAULT_NS_POLICY_CERT_KEY_TYPE
        assert ca_config["keyType"] == expected_key_type

        if cert_subject:
            assert ca_config["subject"] == cert_subject

        # Check leaf certificate configuration
        assert "leafCertificateConfiguration" in cert_config
        leaf_config = cert_config["leafCertificateConfiguration"]
        # Validity should default if None
        expected_validity = (
            cert_validity_days if cert_validity_days is not None else DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS
        )
        assert leaf_config["validityPeriodInDays"] == expected_validity
    else:
        # empty properties object for service defaults (no user input)
        assert resource["properties"] == {}


@pytest.mark.parametrize("tags", [None, {"env": "test"}])
@pytest.mark.parametrize("cert_validity_days", [None, 20])
def test_update_policy(fixture_policy_provider, mock_poller, tags, cert_validity_days):
    """Test successful policy update."""
    # Mock existing policy from show()
    existing_policy_name = "test-policy"
    namespace_name = "test-namespace"
    rg = "test-rg"
    existing_policy = {
        "name": existing_policy_name,
        "location": "location",
        "tags": {"existing": "tag"},
        "properties": {"certificate": {"leafCertificateConfiguration": {"validityPeriodInDays": 30}}},
    }

    # Mock show call
    fixture_policy_provider.client.namespaces.get.return_value = Mock()
    fixture_policy_provider.client.policies.get.return_value = existing_policy

    # Mock create_or_update call
    mock_update_result = Mock()
    poller = mock_poller(mock_update_result)
    fixture_policy_provider.client.policies.begin_create_or_update.return_value = poller

    result = fixture_policy_provider.update(
        policy_name=existing_policy_name,
        namespace_name=namespace_name,
        resource_group_name=rg,
        tags=tags,
        certificate_validity_days=cert_validity_days,
    )

    assert result == mock_update_result

    # Verify policy get was called
    fixture_policy_provider.client.policies.get.assert_called_once_with(
        resource_group_name=rg, namespace_name=namespace_name, policy_name=existing_policy_name
    )

    # Verify begin_create_or_update was called
    fixture_policy_provider.client.policies.begin_create_or_update.assert_called_once()

    call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args
    assert call_args[1]["resource_group_name"] == rg
    assert call_args[1]["namespace_name"] == namespace_name
    assert call_args[1]["policy_name"] == existing_policy_name

    resource = call_args[1]["resource"]

    # Verify only provided properties were changed
    assert resource["tags"] == (tags if tags else existing_policy["tags"])
    expected_validity = (
        cert_validity_days
        if cert_validity_days
        else existing_policy["properties"]["certificate"]["leafCertificateConfiguration"]["validityPeriodInDays"]
    )
    assert (
        resource["properties"]["certificate"]["leafCertificateConfiguration"]["validityPeriodInDays"]
        == expected_validity
    )


@pytest.mark.parametrize("namespace_exists", [True, False])
def test_update_policy_error_scenarios(fixture_policy_provider, namespace_exists):
    """Test policy update error scenarios: namespace missing or credentials missing during show."""
    _test_namespace_or_credential_not_found_error(
        fixture_policy_provider,
        operation_method="update",
        operation_kwargs={
            "policy_name": "test-policy",
            "namespace_name": "test-namespace",
            "resource_group_name": "test-rg",
            "tags": {"test": "tag"},
        },
        namespace_exists=namespace_exists,
    )


@pytest.mark.parametrize("namespace_exists", [True, False])
def test_show_policy_error_scenarios(fixture_policy_provider, namespace_exists):
    """Test policy show error scenarios: namespace missing or credentials missing."""
    _test_namespace_or_credential_not_found_error(
        fixture_policy_provider,
        operation_method="show",
        operation_kwargs={
            "policy_name": "test-policy",
            "namespace_name": "test-namespace",
            "resource_group_name": "test-rg",
        },
        namespace_exists=namespace_exists,
    )


@pytest.mark.parametrize("namespace_exists", [True, False])
def test_list_policy_error_scenarios(fixture_policy_provider, namespace_exists):
    """Test policy list error scenarios: namespace missing or credentials missing."""
    _test_namespace_or_credential_not_found_error(
        fixture_policy_provider,
        operation_method="list",
        operation_kwargs={"namespace_name": "test-namespace", "resource_group_name": "test-rg"},
        namespace_exists=namespace_exists,
    )


def _test_namespace_or_credential_not_found_error(
    fixture_policy_provider,
    operation_method,
    operation_kwargs,
    namespace_exists=True,
):
    """
    Common test helper for namespace/credential not found errors during policy commands.

    Args:
        fixture_policy_provider: The policy provider fixture
        operation_method: String name of the method to test (e.g., "show", "list", "update")
        operation_kwargs: Dict of kwargs to pass to the operation method
        namespace_exists: Whether namespace exists (True) or not (False)
    """
    # Setup common test data
    test_namespace = operation_kwargs.get("namespace_name", "test-namespace")
    test_rg = operation_kwargs.get("resource_group_name", "test-rg")

    # HTTP 404 mock
    mock_404_response = Mock()
    mock_404_response.status_code = 404
    http_404_error = HttpResponseError(response=mock_404_response)

    if namespace_exists:
        # Mock namespace exists
        mock_namespace = Mock()
        fixture_policy_provider.client.namespaces.get.return_value = mock_namespace

        # Mock credential not found (ParentResourceNotFound)
        class MockParentResourceNotFoundError(HttpResponseError):
            def __str__(self):
                return "ParentResourceNotFound"

        parent_error = MockParentResourceNotFoundError(response=mock_404_response)

        # Set up the appropriate client method to raise parent error
        if operation_method == "list":
            fixture_policy_provider.client.policies.list_by_resource_group.side_effect = parent_error
        else:  # show or update (both use get)
            fixture_policy_provider.client.policies.get.side_effect = parent_error

        expected_exception = ResourceNotFoundError
        expected_error_substring = f"No credential exists on namespace '{test_namespace}'"
    else:
        # Mock namespace doesn't exist
        fixture_policy_provider.client.namespaces.get.side_effect = http_404_error
        expected_exception = HttpResponseError
        expected_error_substring = None

    # Execute the operation and verify it raises the expected exception
    provider_method = getattr(fixture_policy_provider, operation_method)
    with pytest.raises(expected_exception) as exc_info:
        provider_method(**operation_kwargs)

    # Verify error message content
    if expected_error_substring:
        assert expected_error_substring in str(exc_info.value)
    else:
        assert exc_info.value.response.status_code == 404

    # Verify namespace get was called
    fixture_policy_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name=test_rg, namespace_name=test_namespace
    )

    # Verify policy operations based on namespace existence
    if namespace_exists:
        if operation_method == "list":
            fixture_policy_provider.client.policies.list_by_resource_group.assert_called_once_with(
                resource_group_name=test_rg, namespace_name=test_namespace
            )
        else:  # show or update
            fixture_policy_provider.client.policies.get.assert_called_once_with(
                resource_group_name=test_rg,
                namespace_name=test_namespace,
                policy_name=operation_kwargs.get("policy_name"),
            )
    else:
        # When namespace doesn't exist, policy methods shouldn't be called
        fixture_policy_provider.client.policies.get.assert_not_called()
        fixture_policy_provider.client.policies.list_by_resource_group.assert_not_called()

    # For update, also verify that begin_create_or_update wasn't called
    if operation_method == "update":
        fixture_policy_provider.client.policies.begin_create_or_update.assert_not_called()
