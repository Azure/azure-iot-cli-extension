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
from azext_iot.adr.providers.rbac import RbacProvider


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
        mock_client.credentials.begin_create_or_update.return_value = {"name": "default", "location": "eastus"}
        mock_client.credentials.get.return_value = {"name": "default", "properties": {"status": "active"}}
        mock_client.credentials.begin_delete.return_value = Mock()
        mock_client.credentials.begin_synchronize.return_value = Mock()

        # Mock policies operations
        mock_client.policies.begin_create_or_update.return_value = {"name": "test-policy", "location": "eastus"}
        mock_client.policies.get.return_value = {
            "name": "test-policy",
            "properties": {"certificate": {"status": "active"}},
        }
        mock_client.policies.begin_delete.return_value = Mock()
        mock_client.policies.list_by_resource_group.return_value = []

        return mock_client

    @pytest.fixture()
    def fixture_rbac_cli(self):
        """Mock EmbeddedCLI for RBAC operations."""
        mock_cli = Mock()

        # Mock successful operations
        mock_operation = Mock()
        mock_operation.success.return_value = True
        mock_operation.as_json.return_value = {"id": "test-id", "principalId": "test-principal"}
        mock_operation.get_error.return_value = ""

        mock_cli.invoke.return_value = mock_operation
        return mock_cli

    def test_complete_adr_namespace_creation_workflow(self, fixture_cmd, fixture_adr_client, fixture_rbac_cli):
        """Test complete ADR namespace creation including credentials, policies, and RBAC."""
        namespace_name = "integration-test-namespace"

        # Update the mock to return the expected namespace name
        fixture_adr_client.namespaces.begin_create_or_replace.return_value.result.return_value = {
            "id": (
                "/subscriptions/test-sub/resourceGroups/integration-test-rg/"
                f"providers/Microsoft.DeviceRegistry/namespaces/{namespace_name}"
            ),
            "name": namespace_name,
            "location": "eastus",
            "identity": {"principalId": "test-principal-id", "type": "SystemAssigned"},
            "resourceGroup": "integration-test-rg",
        }

        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client), patch(
            "azext_iot.adr.providers.rbac.EmbeddedCLI", return_value=fixture_rbac_cli
        ), patch("azext_iot.adr.providers.rbac.get_subscription_id", return_value="test-subscription"):

            namespace_provider = NamespaceProvider(fixture_cmd)

            # Create namespace with default credential and policy
            result = namespace_provider.create(
                namespace_name=namespace_name,
                resource_group_name="integration-test-rg",
                location="eastus",
                tags={"test": "integration"},
                no_credential=False,
                no_policy=False,
                policy_name="integration-policy",
                certificate_key_type="RSA",
                certificate_subject="CN=integration.test.com",
                certificate_validity_days=365,
            )

            # Assert namespace creation
            assert result["name"] == namespace_name
            fixture_adr_client.namespaces.begin_create_or_replace.assert_called_once()

            # Verify namespace resource structure
            create_call = fixture_adr_client.namespaces.begin_create_or_replace.call_args
            namespace_resource = create_call[1]["resource"]
            assert namespace_resource["location"] == "eastus"
            assert namespace_resource["tags"]["test"] == "integration"

            # Ensure system assigned identity
            assert namespace_resource["identity"]["type"] == "SystemAssigned"

            # Assert credential creation was called
            fixture_adr_client.credentials.begin_create_or_update.assert_called_once()

            # Assert policy creation was called
            fixture_adr_client.policies.begin_create_or_update.assert_called_once()

            # TODO - better checks for RBAC lifecycle
            assert fixture_rbac_cli.invoke.call_count >= 1  # At least some RBAC calls were made

    def test_adr_credential_lifecycle(self, fixture_cmd, fixture_adr_client):
        """Test complete credential lifecycle: create, show, sync, delete."""
        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            credential_provider = CredentialProvider(fixture_cmd)

            # Test create
            create_result = credential_provider.create(
                namespace_name="test-namespace",
                resource_group_name="test-rg",
                location="eastus",
                tags={"lifecycle": "test"},
            )
            assert create_result["name"] == "default"
            fixture_adr_client.credentials.begin_create_or_update.assert_called_once()

            # Test show
            show_result = credential_provider.show("test-namespace", "test-rg")
            assert show_result["properties"]["status"] == "active"
            fixture_adr_client.credentials.get.assert_called_once()

            # Test sync
            sync_result = credential_provider.synchronize("test-namespace", "test-rg")
            assert sync_result is not None
            fixture_adr_client.credentials.begin_synchronize.assert_called_once()

            # Test delete
            delete_result = credential_provider.delete("test-namespace", "test-rg")
            assert delete_result is not None
            fixture_adr_client.credentials.begin_delete.assert_called_once()

    def test_adr_policy_lifecycle(self, fixture_cmd, fixture_adr_client):
        """Test complete policy lifecycle: create, show, list, delete."""
        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            policy_provider = PolicyProvider(fixture_cmd)

            # Test create with certificate configuration
            create_result = policy_provider.create(
                policy_name="lifecycle-policy",
                namespace_name="test-namespace",
                resource_group_name="test-rg",
                location="eastus",
                certificate_key_type="RSA",
                certificate_subject="CN=lifecycle.test.com",
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
            show_result = policy_provider.show("lifecycle-policy", "test-namespace", "test-rg")
            assert show_result["properties"]["certificate"]["status"] == "active"
            fixture_adr_client.policies.get.assert_called_once()

            # Test list
            list_result = policy_provider.list("test-namespace", "test-rg")
            assert isinstance(list_result, list)
            fixture_adr_client.policies.list_by_resource_group.assert_called_once()

            # Test delete
            delete_result = policy_provider.delete("lifecycle-policy", "test-namespace", "test-rg")
            assert delete_result is not None
            fixture_adr_client.policies.begin_delete.assert_called_once()

    def test_adr_rbac_configuration(self, fixture_cmd, fixture_rbac_cli):
        """Test ADR RBAC configuration workflow."""
        namespace = {
            "id": "/subscriptions/test-sub/resourceGroups/test-rg/providers/Microsoft.DeviceRegistry/namespaces/rbac-test",
            "name": "rbac-test",
            "location": "eastus",
            "resourceGroup": "test-rg",
            "identity": {"principalId": "namespace-principal-id"},
        }

        # Mock successful role and identity operations
        mock_role_list_operation = Mock()
        mock_role_list_operation.success.return_value = True
        mock_role_list_operation.as_json.return_value = [
            {"id": "custom-role-id", "name": "ADR Integration Role"}
        ]  # Return as list

        mock_role_create_operation = Mock()
        mock_role_create_operation.success.return_value = True
        mock_role_create_operation.as_json.return_value = {"id": "custom-role-id", "name": "ADR Integration Role"}

        mock_identity_operation = Mock()
        mock_identity_operation.success.return_value = True
        mock_identity_operation.as_json.return_value = {"principalId": "user-identity-principal"}

        def cli_side_effect(command):
            if "role definition list" in command:
                return mock_role_list_operation
            elif "role definition" in command and "create" in command:
                return mock_role_create_operation
            elif "identity create" in command:
                return mock_identity_operation
            else:
                # Role assignments
                mock_assign_op = Mock()
                mock_assign_op.success.return_value = True
                return mock_assign_op

        fixture_rbac_cli.invoke.side_effect = cli_side_effect

        with patch("azext_iot.adr.providers.rbac.get_subscription_id", return_value="test-subscription"):
            rbac_provider = RbacProvider(fixture_cmd)
            rbac_provider.cli = fixture_rbac_cli

            # Act
            rbac_provider.configure_adr_user_identity_and_rbac(namespace)

            # Assert
            # Should have called: role definition operations, identity create, and multiple role assignments
            assert fixture_rbac_cli.invoke.call_count >= 6

            # Verify role definition creation/update
            role_calls = [call for call in fixture_rbac_cli.invoke.call_args_list if "role definition" in call[0][0]]
            assert len(role_calls) >= 1

            # Verify identity creation
            identity_calls = [
                call for call in fixture_rbac_cli.invoke.call_args_list if "identity create" in call[0][0]
            ]
            assert len(identity_calls) == 1

            # Verify role assignments
            assignment_calls = [
                call for call in fixture_rbac_cli.invoke.call_args_list if "role assignment create" in call[0][0]
            ]
            assert len(assignment_calls) >= 4  # Custom role + Contributor role for user identity + IoT Hub RP

    @pytest.mark.parametrize(
        "no_credential, no_policy, expected_credential_calls, expected_policy_calls",
        [
            (False, False, 1, 1),  # Both enabled
            (True, False, 0, 0),  # Only credential disabled (policy depends on credential)
            (False, True, 1, 0),  # Only policy disabled
            (True, True, 0, 0),  # Both disabled
        ],
    )
    def test_adr_namespace_creation_options(
        self,
        fixture_cmd,
        fixture_adr_client,
        fixture_rbac_cli,
        no_credential,
        no_policy,
        expected_credential_calls,
        expected_policy_calls,
    ):
        """Test namespace creation with different credential and policy options."""
        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client), patch(
            "azext_iot.adr.providers.rbac.EmbeddedCLI", return_value=fixture_rbac_cli
        ), patch("azext_iot.adr.providers.rbac.get_subscription_id", return_value="test-subscription"):

            namespace_provider = NamespaceProvider(fixture_cmd)
            namespace_provider.create(
                namespace_name="options-test-namespace",
                resource_group_name="options-test-rg",
                location="eastus",
                no_credential=no_credential,
                no_policy=no_policy,
            )

            # Assert calls
            assert fixture_adr_client.credentials.begin_create_or_update.call_count == expected_credential_calls
            assert fixture_adr_client.policies.begin_create_or_update.call_count == expected_policy_calls
            # Namespace should always be created
            fixture_adr_client.namespaces.begin_create_or_replace.assert_called_once()

    def test_adr_certificate_configuration_validation(self, fixture_cmd, fixture_adr_client):
        """Test that certificate configurations are properly validated and passed through."""
        with patch("azext_iot.adr.providers.base.adr_service_factory", return_value=fixture_adr_client):
            policy_provider = PolicyProvider(fixture_cmd)

            # Test certificate configuration combinations
            test_cases = [
                {
                    "certificate_key_type": "RSA",
                    "certificate_subject": "CN=test.example.com",
                    "certificate_validity_days": 365,
                    "expected_ca_config": {"keyType": "RSA", "subject": "CN=test.example.com"},
                    "expected_leaf_config": {"validityPeriodInDays": 365},
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
                    policy_name="cert-validation-policy",
                    namespace_name="cert-test-namespace",
                    resource_group_name="cert-test-rg",
                    location="eastus",
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
