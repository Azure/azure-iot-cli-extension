# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr.conftest import (
    CUSTOM_CERT_KEY_TYPE,
    CUSTOM_CERT_SUBJECT,
    CUSTOM_CERT_VALIDITY_DAYS,
    CUSTOM_POLICY_NAME,
    TEST_RG,
    generate_adr_namespace_name,
    generate_device_id,
    generate_dps_name,
    generate_enrollment_group_id,
    generate_hub_name,
    generate_identity_name,
)

logger = get_logger(__name__)

TEST_LOCATION = "westus"


@pytest.mark.usefixtures("set_cwd")
class TestADRCertificateManagementLifecycle(CaptureOutputLiveScenarioTest):

    def __init__(self, test_case):
        super(TestADRCertificateManagementLifecycle, self).__init__(test_case)

    def assign_role(self, assignee_id, role, scope, assignee_type="auto"):
        try:
            # Check if role assignment already exists
            # For object ID checks, we can use either --assignee or --assignee-object-id
            existing_assignment = self.cmd(
                f"role assignment list --assignee '{assignee_id}' --scope '{scope}' --role '{role}'"
            ).get_output_in_json()

            if existing_assignment:
                print(f"Role '{role}' already assigned to {assignee_id} on scope")
                return existing_assignment[0].get("id", "existing")

            # Create the role assignment
            if assignee_type == "auto":
                # Let Azure CLI auto-detect the assignee type
                assignment = self.cmd(
                    f"role assignment create --assignee '{assignee_id}' --role '{role}' --scope '{scope}'"
                ).get_output_in_json()
            else:
                # When specifying assignee type, use --assignee-object-id instead of --assignee
                assignment = self.cmd(
                    f"role assignment create --assignee-object-id '{assignee_id}' --role '{role}' "
                    f"--scope '{scope}' --assignee-principal-type '{assignee_type}'"
                ).get_output_in_json()

            assignment_id = assignment.get("id", "unknown")
            print(f"Assigned role '{role}' to {assignee_id}: {assignment_id}")
            return assignment_id

        except Exception as e:
            logger.warning(f"Failed to assign role '{role}' to {assignee_id}: {e}")
            return None

    def assign_hub_rp_contributor_role(self, subscription_id, resource_group_name):
        hub_rp_object_id = "0aab4033-4ad9-4b0b-9934-542334eceffb"
        rg_scope = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}"

        try:
            # Use the consolidated role assignment method
            assignment_id = self.assign_role(
                assignee_id=hub_rp_object_id, role="Contributor", scope=rg_scope, assignee_type="ServicePrincipal"
            )

            if assignment_id:
                print(f"IoT Hub RP contributor role assignment: {assignment_id}")
            else:
                logger.warning("Failed to assign IoT Hub RP contributor role")

        except Exception as e:
            logger.warning(f"Failed to assign IoT Hub RP contributor role: {e}")

    def assign_adr_roles_to_identity(self, identity_principal_id, scope_resource_id):
        for role in ["Azure Device Registry Contributor", "Azure Device Registry Onboarding"]:
            print(f"Assigning {role} to UAMI: {identity_principal_id}")
            self.assign_role(
                assignee_id=identity_principal_id,
                role=role,
                scope=scope_resource_id,
            )

    def test_adr_certificate_management_lifecycle(self):
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()
        hub_name = generate_hub_name()
        dps_name = generate_dps_name()
        identity_name = generate_identity_name()
        device_id = generate_device_id()
        enrollment_group_id = generate_enrollment_group_id()

        try:
            # Create user assigned identity
            identity = self.cmd(
                f"identity create -n {identity_name} -g {rg} --location {TEST_LOCATION}"
            ).get_output_in_json()
            identity_resource_id = identity["id"]
            identity_principal_id = identity["principalId"]

            # Get current subscription ID for role creation
            subscription_info = self.cmd("account show").get_output_in_json()
            subscription_id = subscription_info["id"]

            # Assign IoT Hub RP contributor access to resource group (required for ADR integration)
            self.assign_hub_rp_contributor_role(subscription_id, rg)

            # Create ADR namespace with credential and policy
            namespace = self.cmd(
                f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION} --enable-credential-policy"
            ).get_output_in_json()
            adr_resource_id = namespace["id"]

            assert namespace["name"] == namespace_name
            assert namespace["properties"]["provisioningState"] == "Succeeded"
            assert namespace["location"] == TEST_LOCATION.lower()

            # Validate system-assigned identity was created for the namespace
            assert namespace["identity"]["type"] == "SystemAssigned"
            assert "principalId" in namespace["identity"]
            assert "tenantId" in namespace["identity"]

            # Assign built-in ADR roles to identity for ADR access
            self.assign_adr_roles_to_identity(identity_principal_id, adr_resource_id)

            # Delete default policy
            self.cmd(f"iot adr ns policy delete --ns {namespace_name} -g {rg} --policy-name default -y")

            # Create custom credential policy for this test
            custom_policy = self.cmd(
                f"iot adr ns policy create --ns {namespace_name} -g {rg} "
                f"--policy-name {CUSTOM_POLICY_NAME} "
                f"--cert-subject '{CUSTOM_CERT_SUBJECT}' "
                f"--cert-validity-days {CUSTOM_CERT_VALIDITY_DAYS} "
                f"--cert-key-type {CUSTOM_CERT_KEY_TYPE}"
            ).get_output_in_json()

            assert custom_policy["name"] == CUSTOM_POLICY_NAME
            assert (
                custom_policy["properties"]["certificate"]["leafCertificateConfiguration"]["validityPeriodInDays"]
                == CUSTOM_CERT_VALIDITY_DAYS
            )
            assert (
                custom_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]["keyType"]
                == CUSTOM_CERT_KEY_TYPE
            )
            assert custom_policy["properties"]["provisioningState"] == "Succeeded"
            assert custom_policy["location"] == TEST_LOCATION.lower()

            # Validate certificate authority configuration
            ca_config = custom_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert "subject" in ca_config

            # TODO: Re-enable when service issues are resolved
            # assert (
            #     custom_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]["subject"]
            #     == CUSTOM_CERT_SUBJECT
            # )

            # Create IoT Hub with ADR integration
            hub = self.cmd(
                f"iot hub create -n {hub_name} -g {rg} --sku GEN2 --location {TEST_LOCATION} "
                f"--mi-user-assigned {identity_resource_id} "
                f"--ns-resource-id {adr_resource_id} "
                f"--ns-identity-id {identity_resource_id}"
            ).get_output_in_json()

            assert hub["name"] == hub_name
            assert hub["properties"]["state"] == "Active"

            # Show IoT Hub properties
            hub_show = self.cmd(f"iot hub show -n {hub_name} -g {rg}").get_output_in_json()

            # Validate ADR integration is properly configured
            assert "deviceRegistry" in hub_show["properties"]
            adr_props = hub_show["properties"]["deviceRegistry"]
            assert adr_props["identityResourceId"] == identity_resource_id
            assert adr_props["namespaceResourceId"] == adr_resource_id

            # Validate user-assigned managed identity configuration
            assert hub_show["identity"]["type"] == "UserAssigned"
            assert identity_resource_id in hub_show["identity"]["userAssignedIdentities"]
            assert (
                hub_show["identity"]["userAssignedIdentities"][identity_resource_id]["principalId"]
                == identity_principal_id
            )

            # Create DPS with ADR integration
            dps = self.cmd(
                f"iot dps create --name {dps_name} -g {rg} --location {TEST_LOCATION} "
                f"--mi-user-assigned {identity_resource_id} "
                f"--ns-resource-id {adr_resource_id} "
                f"--ns-identity-id {identity_resource_id}"
            ).get_output_in_json()

            assert dps["name"] == dps_name
            assert dps["properties"]["state"] == "Active"

            # Link IoT Hub to DPS
            self.cmd(
                f"iot dps linked-hub create --dps-name {dps_name} -g {rg} --hub-name {hub_name}"
            ).get_output_in_json()

            # Show DPS properties
            dps_show = self.cmd(f"iot dps show --name {dps_name} -g {rg}").get_output_in_json()

            # Validate device registry namespace configuration
            assert "deviceRegistryNamespace" in dps_show["properties"]
            drn_props = dps_show["properties"]["deviceRegistryNamespace"]
            assert drn_props["authenticationType"] == "UserAssigned"
            assert drn_props["resourceId"] == adr_resource_id
            assert drn_props["selectedUserAssignedIdentityResourceId"] == identity_resource_id

            # Validate user-assigned managed identity configuration
            assert dps_show["identity"]["type"] == "UserAssigned"
            assert identity_resource_id in dps_show["identity"]["userAssignedIdentities"]
            assert (
                dps_show["identity"]["userAssignedIdentities"][identity_resource_id]["principalId"]
                == identity_principal_id
            )

            # Validate linked hubs are configured
            linked_hubs = dps_show["properties"]["iotHubs"]
            assert len(linked_hubs) > 0
            assert any(hub["name"] == f"{hub_name}.azure-devices.net" for hub in linked_hubs)

            # Create enrollment group with credential policy
            enrollment_group = self.cmd(
                f"iot dps enrollment-group create --dps-name {dps_name} -g {rg} "
                f"--enrollment-id {enrollment_group_id} "
                f"--credential-policy-name {CUSTOM_POLICY_NAME}"
            ).get_output_in_json()
            assert enrollment_group["enrollmentGroupId"] == enrollment_group_id

            # Show enrollment group
            enrollment_group_show = self.cmd(
                f"iot dps enrollment-group show --dps-name {dps_name} -g {rg} " f"--enrollment-id {enrollment_group_id}"
            ).get_output_in_json()
            assert enrollment_group_show["enrollmentGroupId"] == enrollment_group_id

            # Validate enrollment group credential policy reference
            assert enrollment_group_show["credentialPolicyName"] == CUSTOM_POLICY_NAME
            assert enrollment_group_show["attestation"]["type"] == "symmetricKey"

            # Create individual enrollment with credential policy
            individual_enrollment = self.cmd(
                f"iot dps enrollment create --dps-name {dps_name} -g {rg} "
                f"--enrollment-id {device_id} "
                f"--credential-policy-name {CUSTOM_POLICY_NAME} "
                f"--attestation-type symmetrickey"
            ).get_output_in_json()
            assert individual_enrollment["registrationId"] == device_id

            # Show individual enrollment
            individual_enrollment_show = self.cmd(
                f"iot dps enrollment show --dps-name {dps_name} -g {rg} " f"--enrollment-id {device_id}"
            ).get_output_in_json()
            assert individual_enrollment_show["registrationId"] == device_id

            # Validate individual enrollment credential policy reference
            assert individual_enrollment_show["credentialPolicyName"] == CUSTOM_POLICY_NAME
            assert individual_enrollment_show["attestation"]["type"] == "symmetricKey"
            assert individual_enrollment_show["provisioningStatus"] == "enabled"

            # Run ADR credential sync
            self.cmd(f"iot adr ns credential sync --ns {namespace_name} -g {rg}")

            # Validate that certificates were synchronized to the hub
            certificates = self.cmd(f"iot hub certificate list --hub-name {hub_name} -g {rg}").get_output_in_json()

            # Validate certificate sync results
            cert_list = certificates.get("value", [])
            assert len(cert_list) == 1

            custom_policy_resource_id = (
                f"/subscriptions/{subscription_id}/resourceGroups/{rg}/providers/"
                f"Microsoft.DeviceRegistry/namespaces/{namespace_name}/credentials/"
                f"default/policies/{CUSTOM_POLICY_NAME}"
            )

            # Find certificate by policy resource ID
            custom_policy_cert = None

            for cert in cert_list:
                if cert["properties"]["PolicyResourceId"] == custom_policy_resource_id:
                    custom_policy_cert = cert

            # Validate custom policy certificate properties
            assert custom_policy_cert is not None, "Custom policy certificate not found"
            cert_props = custom_policy_cert["properties"]
            assert cert_props["PolicyResourceId"] == custom_policy_resource_id

        finally:
            # Cleanup all resources

            # Delete DPS
            try:
                self.cmd(f"iot dps delete --name {dps_name} -g {rg}")
            except Exception as e:
                logger.warning(f"Failed to delete DPS {dps_name}: {e}")

            # Delete IoT Hub
            try:
                self.cmd(f"iot hub delete -n {hub_name} -g {rg}")
            except Exception as e:
                logger.warning(f"Failed to delete IoT Hub {hub_name}: {e}")

            # Delete ADR namespace
            try:
                self.cmd(f"iot adr ns delete -n {namespace_name} -g {rg} -y")
            except Exception as e:
                logger.warning(f"Failed to delete ADR namespace {namespace_name}: {e}")

            # Delete user assigned managed identity
            try:
                self.cmd(f"identity delete -n {identity_name} -g {rg}")
            except Exception as e:
                logger.warning(f"Failed to delete identity {identity_name}: {e}")
