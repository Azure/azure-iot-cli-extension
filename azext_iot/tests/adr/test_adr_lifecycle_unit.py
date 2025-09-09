# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import Mock, patch
from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.adr.providers.credential import CredentialProvider
from azext_iot.adr.providers.policy import PolicyProvider
from azext_iot.tests.generators import generate_names


class TestADRIntegration(object):
    """Integration tests for ADR certificate management workflow."""

    @pytest.fixture()
    def fixture_cmd(self):
        mock_cmd = Mock()
        mock_cmd.cli_ctx = Mock()
        return mock_cmd

    @pytest.fixture()
    def fixture_adr_client(self):
        """Mock ADR client with all necessary operations."""
        mock_client = Mock()

        # Mock namespaces operations
        mock_client.namespaces.begin_create_or_replace.return_value.result.return_value = {
            "id": "/subscriptions/test-sub/resourceGroups/test-rg/providers/Microsoft.DeviceRegistry/namespaces/test-namespace",
            "name": "test-namespace",
            "location": "eastus",
            "identity": {"principalId": "test-principal-id", "type": "SystemAssigned"},
        }
        mock_client.namespaces.get.return_value = {"name": "test-namespace", "location": "eastus"}
        mock_client.namespaces.begin_delete.return_value = Mock()
        mock_client.namespaces.list_by_resource_group.return_value = []

        # Mock credentials operations
        mock_credential_lro = Mock()
        mock_credential_lro.result.return_value = {"name": "default", "location": "eastus"}
        mock_client.credentials.begin_create_or_update.return_value = mock_credential_lro
        mock_client.credentials.get.return_value = {"name": "default", "properties": {"status": "active"}}
        mock_client.credentials.begin_delete.return_value = Mock()
        mock_client.credentials.begin_synchronize.return_value = Mock()

        # Mock policies operations
        mock_policy_lro = Mock()
        mock_policy_lro.result.return_value = {"name": "test-policy", "location": "eastus"}
        mock_client.policies.begin_create_or_update.return_value = mock_policy_lro
        mock_client.policies.get.return_value = {
            "name": "test-policy",
            "properties": {"certificate": {"status": "active"}},
        }
        mock_client.policies.begin_delete.return_value = Mock()
        mock_client.policies.list_by_resource_group.return_value = []

        return mock_client

    def test_complete_adr_namespace_creation_workflow(
        self, fixture_cmd, fixture_adr_client, fixture_credential_provider, fixture_policy_provider
    ):
        """Test complete ADR namespace creation, with credential and policy"""
        namespace_name = generate_names("test-namespace-")
        rg_name = generate_names("test-rg-")
        policy_name = generate_names("test-policy-")
        subscription_id = generate_names("test-sub-")
        principal_id = generate_names("test-principal-")
        credential_id = generate_names("credential-")
        policy_id = generate_names("policy-")
        location = "eastus"
        certificate_subject = "CN=test.example.com"
        test_tag_value = generate_names("integration-")
        cert_validity = 30
        cert_key_type = "ECC"

        fixture_credential_provider.create = Mock(return_value={"id": credential_id})
        fixture_policy_provider.create = Mock(return_value={"id": policy_id})

        # Update the mock to return the expected namespace name
        fixture_adr_client.namespaces.begin_create_or_replace.return_value.result.return_value = {
            "id": (
                f"/subscriptions/{subscription_id}/resourceGroups/{rg_name}/"
                f"providers/Microsoft.DeviceRegistry/namespaces/{namespace_name}"
            ),
            "name": namespace_name,
            "location": location,
            "identity": {"principalId": principal_id, "type": "SystemAssigned"},
            "resourceGroup": rg_name,
        }
        with patch(
            "azext_iot.adr.providers.credential.CredentialProvider", return_value=fixture_credential_provider
        ), patch("azext_iot.adr.providers.policy.PolicyProvider", return_value=fixture_policy_provider), patch(
            "azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client
        ):

            namespace_provider = NamespaceProvider(fixture_cmd)

            # Create namespace with default credential and policy
            result = namespace_provider.create(
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
                tags={"test": test_tag_value},
                no_credential=False,
                no_policy=False,
                policy_name=policy_name,
                certificate_key_type=cert_key_type,
                certificate_subject=certificate_subject,
                certificate_validity_days=cert_validity,
            )

            # Assert namespace creation
            assert result["name"] == namespace_name
            fixture_adr_client.namespaces.begin_create_or_replace.assert_called_once()

            # Verify namespace resource structure
            create_call = fixture_adr_client.namespaces.begin_create_or_replace.call_args
            namespace_resource = create_call[1]["resource"]
            assert namespace_resource["location"] == location
            assert namespace_resource["tags"]["test"] == test_tag_value

            # Ensure system assigned identity
            assert namespace_resource["identity"]["type"] == "SystemAssigned"

            # Assert credential and policy providers were called
            fixture_credential_provider.create.assert_called_once_with(
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
            )

            fixture_policy_provider.create.assert_called_once_with(
                policy_name=policy_name,
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
                certificate_key_type=cert_key_type,
                certificate_subject=certificate_subject,
                certificate_validity_days=cert_validity,
            )

    def test_adr_credential_lifecycle(self, fixture_cmd, fixture_adr_client):
        """Test complete credential lifecycle: create, show, sync, delete."""
        namespace_name = generate_names("test-namespace-")
        rg_name = generate_names("test-rg-")
        location = "eastus"
        lifecycle_tag_value = generate_names("lifecycle-")

        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            credential_provider = CredentialProvider(fixture_cmd)

            # Test create
            create_result = credential_provider.create(
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
                tags={"lifecycle": lifecycle_tag_value},
            )
            assert create_result["name"] == "default"
            fixture_adr_client.credentials.begin_create_or_update.assert_called_once()

            # Test show
            show_result = credential_provider.show(namespace_name, rg_name)
            assert show_result["properties"]["status"] == "active"
            fixture_adr_client.credentials.get.assert_called_once()

            # Test sync
            sync_result = credential_provider.synchronize(namespace_name, rg_name)
            assert sync_result is not None
            fixture_adr_client.credentials.begin_synchronize.assert_called_once()

            # Test delete
            delete_result = credential_provider.delete(namespace_name, rg_name)
            assert delete_result is not None
            fixture_adr_client.credentials.begin_delete.assert_called_once()

    def test_adr_policy_lifecycle(self, fixture_cmd, fixture_adr_client):
        """Test complete policy lifecycle: create, show, list, delete."""
        policy_name = generate_names("lifecycle-policy-")
        namespace_name = generate_names("test-namespace-")
        rg_name = generate_names("test-rg-")
        location = "eastus"
        certificate_subject = "CN=lifecycle.test.com"

        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            policy_provider = PolicyProvider(fixture_cmd)

            # Test create with certificate configuration
            create_result = policy_provider.create(
                policy_name=policy_name,
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
                certificate_key_type="RSA",
                certificate_subject=certificate_subject,
                certificate_validity_days=365,
            )
            assert create_result["name"] == "test-policy"
            fixture_adr_client.policies.begin_create_or_update.assert_called_once()

            # Verify certificate configuration was passed
            create_call = fixture_adr_client.policies.begin_create_or_update.call_args
            policy_resource = create_call[1]["resource"]
            assert "properties" in policy_resource
            assert "certificate" in policy_resource["properties"]

            # Test show
            show_result = policy_provider.show(policy_name, namespace_name, rg_name)
            assert show_result["properties"]["certificate"]["status"] == "active"
            fixture_adr_client.policies.get.assert_called_once()

            # Test list
            list_result = policy_provider.list(namespace_name, rg_name)
            assert isinstance(list_result, list)
            fixture_adr_client.policies.list_by_resource_group.assert_called_once()

            # Test delete
            delete_result = policy_provider.delete(policy_name, namespace_name, rg_name)
            assert delete_result is not None
            fixture_adr_client.policies.begin_delete.assert_called_once()

    @pytest.mark.parametrize(
        "no_credential, no_policy, expected_credentials_calls, expected_policies_calls",
        [
            (False, False, 1, 1),  # credential and policy
            (False, True, 1, 0),  # only credential
            (True, False, 0, 0),  # no_credential disables credential and policy
            (True, True, 0, 0),  # both disabled
        ],
    )
    def test_adr_namespace_creation_options(
        self,
        fixture_cmd,
        fixture_adr_client,
        fixture_credential_provider,
        fixture_policy_provider,
        no_credential,
        no_policy,
        expected_credentials_calls,
        expected_policies_calls,
    ):
        """Test namespace creation with different credential and policy options."""
        namespace_name = generate_names("options-test-namespace-")
        rg_name = generate_names("options-test-rg-")
        location = "eastus"
        fixture_credential_provider.create = Mock(return_value={"id": "credential-id"})
        fixture_policy_provider.create = Mock(return_value={"id": "policy-id"})

        with patch(
            "azext_iot.adr.providers.credential.CredentialProvider", return_value=fixture_credential_provider
        ), patch("azext_iot.adr.providers.policy.PolicyProvider", return_value=fixture_policy_provider), patch(
            "azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client
        ):

            namespace_provider = NamespaceProvider(fixture_cmd)
            namespace_provider.create(
                namespace_name=namespace_name,
                resource_group_name=rg_name,
                location=location,
                no_credential=no_credential,
                no_policy=no_policy,
            )

            # Assert calls
            assert fixture_credential_provider.create.call_count == expected_credentials_calls
            assert fixture_policy_provider.create.call_count == expected_policies_calls
            # Namespace should always be created
            fixture_adr_client.namespaces.begin_create_or_replace.assert_called_once()

    def test_adr_certificate_configuration_validation(self, fixture_cmd, fixture_adr_client):
        """Test that certificate configurations are properly validated and passed through."""
        policy_name = generate_names("cert-validation-policy-")
        namespace_name = generate_names("cert-test-namespace-")
        rg_name = generate_names("cert-test-rg-")
        location = "eastus"

        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            policy_provider = PolicyProvider(fixture_cmd)

            # Test certificate configuration combinations
            test_cases = [
                {
                    "certificate_key_type": "ECC",
                    "certificate_subject": "CN=test.example.com",
                    "certificate_validity_days": 30,
                    "expected_ca_config": {"keyType": "ECC", "subject": "CN=test.example.com"},
                    "expected_leaf_config": {"validityPeriodInDays": 30},
                },
                {
                    "certificate_key_type": "ECC",
                    "certificate_subject": None,
                    "certificate_validity_days": None,
                    "expected_ca_config": {"keyType": "ECC"},
                    "expected_leaf_config": None,
                },
            ]

            for case in test_cases:
                policy_provider.create(
                    policy_name=policy_name,
                    namespace_name=namespace_name,
                    resource_group_name=rg_name,
                    location=location,
                    **{k: v for k, v in case.items() if k.startswith("certificate_")},
                )

                create_call = fixture_adr_client.policies.begin_create_or_update.call_args
                resource = create_call[1]["resource"]

                if case["expected_ca_config"] or case["expected_leaf_config"]:
                    assert "properties" in resource
                    cert_config = resource["properties"]["certificate"]

                    if case["expected_ca_config"]:
                        assert "certificateAuthorityConfiguration" in cert_config
                        assert cert_config["certificateAuthorityConfiguration"] == case["expected_ca_config"]

                    if case["expected_leaf_config"]:
                        assert "leafCertificateConfiguration" in cert_config
                        assert cert_config["leafCertificateConfiguration"] == case["expected_leaf_config"]

                # Reset for next test case
                fixture_adr_client.policies.begin_create_or_update.reset_mock()
