# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.policy import PolicyProvider


class TestPolicyProvider(object):
    """Test PolicyProvider class methods."""

    @pytest.fixture()
    def fixture_cmd(self):
        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()
        return mock_cmd

    @pytest.fixture()
    def fixture_policy_provider(self, fixture_cmd):
        with patch("azext_iot.adr.providers.base.adr_service_factory") as mock_factory:
            mock_client = Mock()
            mock_factory.return_value = mock_client
            provider = PolicyProvider(fixture_cmd)
            provider.client = mock_client
            return provider

    @pytest.mark.parametrize(
        "policy_name, namespace_name, resource_group_name, location, tags, cert_key_type, cert_subject, cert_validity_days",
        [
            ("test-policy", "test-namespace", "test-rg", "eastus", None, None, None, None),
            (
                "prod-policy",
                "prod-namespace",
                "prod-rg",
                None,
                {"env": "production"},
                "RSA",
                "CN=prod.example.com",
                365,
            ),
            (
                "dev-policy",
                "dev-namespace",
                "dev-rg",
                "westus",
                {"env": "dev", "team": "qa"},
                "ECC",
                "CN=dev.example.com",
                180,
            ),
            ("cert-policy", "cert-namespace", "cert-rg", "centralus", None, "RSA", None, 730),
            (
                "subject-policy",
                "subject-namespace",
                "subject-rg",
                "southcentralus",
                None,
                None,
                "CN=subject.example.com",
                None,
            ),
        ],
    )
    def test_create_policy(
        self,
        fixture_policy_provider,
        policy_name,
        namespace_name,
        resource_group_name,
        location,
        tags,
        cert_key_type,
        cert_subject,
        cert_validity_days,
    ):
        """Test successful policy creation with various parameter combinations."""
        mock_policy_result = Mock()
        fixture_policy_provider.client.policies.begin_create_or_update.return_value = mock_policy_result

        if not location:
            with patch.object(fixture_policy_provider, "_ensure_location", return_value="eastus") as mock_location:
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
                # Assert location fallback was called
                mock_location.assert_called_once()
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

        assert result == mock_policy_result

        # Verify client call
        fixture_policy_provider.client.policies.begin_create_or_update.assert_called_once()
        call_args = fixture_policy_provider.client.policies.begin_create_or_update.call_args

        assert call_args[1]["resource_group_name"] == resource_group_name
        assert call_args[1]["namespace_name"] == namespace_name
        assert call_args[1]["policy_name"] == policy_name

        # Verify resource structure
        resource = call_args[1]["resource"]
        expected_location = location or "eastus"
        assert resource["location"] == expected_location

        if tags:
            assert resource["tags"] == tags
        else:
            assert "tags" not in resource

        # Verify certificate configuration
        has_cert_config = cert_key_type or cert_subject or cert_validity_days
        if has_cert_config:
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

    def test_show_policy(self, fixture_policy_provider):
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

    def test_list_policies_by_resource_group(self, fixture_policy_provider):
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

    def test_list_policies_by_subscription(self, fixture_policy_provider):
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

    def test_delete_policy(self, fixture_policy_provider):
        """Test successful policy deletion."""
        mock_delete_result = Mock()
        fixture_policy_provider.client.policies.begin_delete.return_value = mock_delete_result

        result = fixture_policy_provider.delete(
            policy_name="test-policy", namespace_name="test-namespace", resource_group_name="test-rg"
        )

        assert result == mock_delete_result
        fixture_policy_provider.client.policies.begin_delete.assert_called_once_with(
            resource_group_name="test-rg", namespace_name="test-namespace", policy_name="test-policy"
        )

    @pytest.mark.parametrize(
        "cert_key_type, cert_subject, cert_validity_days, expected_ca_config, expected_leaf_config",
        [
            ("RSA", None, None, {"keyType": "RSA"}, None),
            (None, "CN=test", None, {"subject": "CN=test"}, None),
            ("ECC", "CN=test", None, {"keyType": "ECC", "subject": "CN=test"}, None),
            (None, None, 365, None, {"validityPeriodInDays": 365}),
            ("RSA", "CN=test", 365, {"keyType": "RSA", "subject": "CN=test"}, {"validityPeriodInDays": 365}),
        ],
    )
    def test_certificate_configuration_combinations(
        self,
        fixture_policy_provider,
        cert_key_type,
        cert_subject,
        cert_validity_days,
        expected_ca_config,
        expected_leaf_config,
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

        if expected_ca_config or expected_leaf_config:
            assert "properties" in resource
            assert "certificate" in resource["properties"]
            cert_config = resource["properties"]["certificate"]

            if expected_ca_config:
                assert "certificateAuthorityConfiguration" in cert_config
                ca_config = cert_config["certificateAuthorityConfiguration"]
                assert ca_config == expected_ca_config
            else:
                assert "certificateAuthorityConfiguration" not in cert_config

            if expected_leaf_config:
                assert "leafCertificateConfiguration" in cert_config
                leaf_config = cert_config["leafCertificateConfiguration"]
                assert leaf_config == expected_leaf_config
            else:
                assert "leafCertificateConfiguration" not in cert_config

    @pytest.mark.parametrize(
        "cert_key_type, cert_subject, cert_validity_days",
        [
            ("RSA", None, None),
            (None, "CN=updated.example.com", None),
            (None, None, 730),
            ("ECC", "CN=updated.example.com", 365),
        ],
    )
    def test_update_policy(self, fixture_policy_provider, cert_key_type, cert_subject, cert_validity_days):
        """Test successful policy update."""
        mock_update_result = Mock()
        fixture_policy_provider.client.policies.begin_update.return_value = mock_update_result

        result = fixture_policy_provider.update(
            policy_name="test-policy",
            namespace_name="test-namespace",
            resource_group_name="test-rg",
            certificate_key_type=cert_key_type,
            certificate_subject=cert_subject,
            certificate_validity_days=cert_validity_days,
        )

        assert result == mock_update_result
        fixture_policy_provider.client.policies.begin_update.assert_called_once()

        call_args = fixture_policy_provider.client.policies.begin_update.call_args
        assert call_args[1]["resource_group_name"] == "test-rg"
        assert call_args[1]["namespace_name"] == "test-namespace"
        assert call_args[1]["policy_name"] == "test-policy"

        properties = call_args[1]["properties"]

        # Verify certificate configuration based on parameters
        if cert_key_type or cert_subject or cert_validity_days:
            assert "properties" in properties
            cert_props = properties["properties"].get("certificate", {})

            if cert_key_type or cert_subject:
                ca_config = cert_props.get("certificateAuthorityConfiguration", {})
                if cert_key_type:
                    assert ca_config["keyType"] == cert_key_type
                if cert_subject:
                    assert ca_config["subject"] == cert_subject

            if cert_validity_days:
                leaf_config = cert_props.get("leafCertificateConfiguration", {})
                assert leaf_config["validityPeriodInDays"] == cert_validity_days
