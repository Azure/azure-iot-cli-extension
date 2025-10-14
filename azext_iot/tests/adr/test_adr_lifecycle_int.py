# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger

from azext_iot.adr.common import DEFAULT_NS_POLICY_CERT_KEY_TYPE, DEFAULT_NS_POLICY_NAME, DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS
from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr.conftest import (
    CUSTOM_CERT_KEY_TYPE,
    CUSTOM_CERT_SUBJECT,
    CUSTOM_CERT_UPDATE_VALIDITY_DAYS,
    CUSTOM_CERT_VALIDITY_DAYS,
    CUSTOM_POLICY_NAME,
    TEST_RG,
    generate_adr_namespace_name,
)

logger = get_logger(__name__)

# TODO - change once service rolls out to more regions
TEST_LOCATION = "centraluseuap"


@pytest.mark.usefixtures("set_cwd")
class TestADRLifecycleIntegration(CaptureOutputLiveScenarioTest):

    def __init__(self, test_case):
        super(TestADRLifecycleIntegration, self).__init__(test_case)

    def test_adr_lifecycle(self):
        rg = TEST_RG
        namespace_name = generate_adr_namespace_name()

        try:
            # Create ADR namespace with no credentials
            namespace = self.cmd(
                f"iot adr ns create -n {namespace_name} -g {rg} --location {TEST_LOCATION}"
            ).get_output_in_json()

            assert namespace["name"] == namespace_name
            assert namespace["location"] == TEST_LOCATION
            assert namespace["properties"]["provisioningState"] == "Succeeded"

            # Show ADR namespace
            namespace_show = self.cmd(f"iot adr ns show -n {namespace_name} -g {rg}").get_output_in_json()

            assert namespace_show["name"] == namespace_name
            assert namespace_show["location"] == TEST_LOCATION
            assert namespace_show["properties"]["provisioningState"] == "Succeeded"

            # Verify no credential exists
            self.cmd(f"iot adr ns credential show --ns {namespace_name} -g {rg}", expect_failure=True)

            # Create credential for the namespace
            credential = self.cmd(f"iot adr ns credential create --ns {namespace_name} -g {rg}").get_output_in_json()

            assert credential["name"] == "default"
            assert credential["location"] == TEST_LOCATION
            assert credential["properties"]["provisioningState"] == "Succeeded"

            # Show credential
            credential_show = self.cmd(f"iot adr ns credential show --ns {namespace_name} -g {rg}").get_output_in_json()

            assert credential_show["name"] == "default"
            assert credential_show["location"] == TEST_LOCATION
            assert credential_show["properties"]["provisioningState"] == "Succeeded"

            # Create default credential policy
            # TODO - once service issue is resolved, remove extra default inputs besides name
            default_policy = self.cmd(
                f"iot adr ns policy create --ns {namespace_name} -g {rg} "
                f"--name {DEFAULT_NS_POLICY_NAME} "
                f"--cert-validity-days {DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS} "
                f"--cert-key-type {DEFAULT_NS_POLICY_CERT_KEY_TYPE}"
            ).get_output_in_json()
            assert default_policy["name"] == DEFAULT_NS_POLICY_NAME
            assert default_policy["properties"]["provisioningState"] == "Succeeded"
            leaf_config = default_policy["properties"]["certificate"]["leafCertificateConfiguration"]
            ca_config = default_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert leaf_config["validityPeriodInDays"] == DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS
            assert ca_config["keyType"] == DEFAULT_NS_POLICY_CERT_KEY_TYPE

            # Show default credential policy
            default_policy_show = self.cmd(
                f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name default"
            ).get_output_in_json()

            assert default_policy_show["name"] == "default"
            assert default_policy_show["properties"]["provisioningState"] == "Succeeded"
            leaf_config = default_policy_show["properties"]["certificate"]["leafCertificateConfiguration"]
            ca_config = default_policy_show["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert leaf_config["validityPeriodInDays"] == DEFAULT_NS_POLICY_CERT_VALIDITY_DAYS
            assert ca_config["keyType"] == DEFAULT_NS_POLICY_CERT_KEY_TYPE

            # Create custom credential policy
            custom_policy = self.cmd(
                f"iot adr ns policy create --ns {namespace_name} -g {rg} "
                f"--policy-name {CUSTOM_POLICY_NAME} "
                f"--cert-subject '{CUSTOM_CERT_SUBJECT}' "
                f"--cert-validity-days {CUSTOM_CERT_VALIDITY_DAYS} "
                f"--cert-key-type {CUSTOM_CERT_KEY_TYPE}"
            ).get_output_in_json()

            assert custom_policy["name"] == CUSTOM_POLICY_NAME
            assert custom_policy["location"] == TEST_LOCATION
            assert custom_policy["properties"]["provisioningState"] == "Succeeded"
            leaf_config = custom_policy["properties"]["certificate"]["leafCertificateConfiguration"]
            ca_config = custom_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert leaf_config["validityPeriodInDays"] == CUSTOM_CERT_VALIDITY_DAYS
            assert ca_config["keyType"] == CUSTOM_CERT_KEY_TYPE
            # TODO - cert subject not respected
            # assert ca_config["subject"] == CUSTOM_CERT_SUBJECT

            # Show custom credential policy
            custom_policy_show = self.cmd(
                f"iot adr ns policy show --ns {namespace_name} -g {rg} --policy-name {CUSTOM_POLICY_NAME}"
            ).get_output_in_json()

            assert custom_policy_show["name"] == CUSTOM_POLICY_NAME
            assert custom_policy_show["location"] == TEST_LOCATION
            leaf_config = custom_policy_show["properties"]["certificate"]["leafCertificateConfiguration"]
            ca_config = custom_policy_show["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert leaf_config["validityPeriodInDays"] == CUSTOM_CERT_VALIDITY_DAYS
            assert ca_config["keyType"] == CUSTOM_CERT_KEY_TYPE
            # TODO - cert subject not respected
            # assert ca_config["subject"] == CUSTOM_CERT_SUBJECT

            # TODO - service currently only supports validity period updates
            # Update custom credential policy
            updated_policy = self.cmd(
                f"iot adr ns policy update --ns {namespace_name} -g {rg} "
                f"--policy-name {CUSTOM_POLICY_NAME} "
                f"--cert-validity-days {CUSTOM_CERT_UPDATE_VALIDITY_DAYS}"
            ).get_output_in_json()
            assert updated_policy["properties"]["provisioningState"] == "Succeeded"
            leaf_config = updated_policy["properties"]["certificate"]["leafCertificateConfiguration"]
            ca_config = updated_policy["properties"]["certificate"]["certificateAuthorityConfiguration"]
            assert leaf_config["validityPeriodInDays"] == CUSTOM_CERT_UPDATE_VALIDITY_DAYS

            # List ADR credential policies
            policies = self.cmd(f"iot adr ns policy list --ns {namespace_name} -g {rg}").get_output_in_json()

            assert isinstance(policies, list)
            assert len(policies) == 2  # Should have default + custom
            policy_names = [p["name"] for p in policies]
            assert "default" in policy_names
            assert CUSTOM_POLICY_NAME in policy_names

            # Verify credential still exists
            credentials = self.cmd(f"iot adr ns credential show --ns {namespace_name} -g {rg}").get_output_in_json()

            assert credentials["name"] == "default"
            assert credentials["properties"]["provisioningState"] == "Succeeded"

            # Delete policies
            self.cmd(f"iot adr ns policy delete --ns {namespace_name} -g {rg} --policy-name {CUSTOM_POLICY_NAME} -y")
            self.cmd(f"iot adr ns policy delete --ns {namespace_name} -g {rg} --policy-name {DEFAULT_NS_POLICY_NAME} -y")

            # Verify all policies were deleted
            policies_after = self.cmd(f"iot adr ns policy list --ns {namespace_name} -g {rg}").get_output_in_json()

            assert isinstance(policies_after, list)
            assert len(policies_after) == 0

            # Delete the credential
            self.cmd(f"iot adr ns credential delete --ns {namespace_name} -g {rg} -y")

            # Verify credentials are deleted (expect failure)
            self.cmd(f"iot adr ns credential show --ns {namespace_name} -g {rg}", expect_failure=True)

        finally:
            # Cleanup
            try:
                self.cmd(f"iot adr ns delete -n {namespace_name} -g {rg} -y")
            except Exception as e:
                logger.warning(f"Cleanup failed: {e}")
