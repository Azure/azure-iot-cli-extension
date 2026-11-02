# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Integration tests for IoT Hub certificate management commands.

Covers: iot hub certificate list, show, create, update, generate-verification-code, verify, delete.
These are CRUD-only tests — no device connections, avoiding the flaky CA propagation timing.
"""

import os
from shlex import quote
from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.test_utils import certificate_fingerprints, create_certificate


CERT_NAME = "test-root-cert"


class TestIoTHubCertificates(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubCertificates, self).__init__(test_case)
        self._cert_files = []

    def tearDown(self):
        for f in self._cert_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        super(TestIoTHubCertificates, self).tearDown()

    def test_hub_certificate_lifecycle_int(self):
        """Test the full certificate management lifecycle: list, create, verify, delete."""
        output_dir = os.getcwd()

        # Create a root CA certificate
        root_cert = create_certificate(
            subject=CERT_NAME, valid_days=1, cert_output_dir=output_dir
        )
        root_cert_file = f"{CERT_NAME}-cert.pem"
        root_key_file = f"{CERT_NAME}-key.pem"
        self._cert_files.extend([root_cert_file, root_key_file])

        # Clean up if the certificate already exists from a prior run
        certs_result = self.cmd(
            "iot hub certificate list --hub-name {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()

        if any(cert["name"] == CERT_NAME for cert in certs_result["value"]):
            self.cmd(
                "iot hub certificate delete --hub-name {} -g {} -n {} -e *".format(
                    self.entity_name, self.entity_rg, CERT_NAME
                )
            )

        # Create certificate on the hub
        create_result = self.cmd(
            "iot hub certificate create --hub-name {} -g {} -n {} -p {}".format(
                self.entity_name, self.entity_rg, CERT_NAME, root_cert_file
            )
        ).get_output_in_json()
        assert create_result["name"] == CERT_NAME

        # List and verify our certificate appears
        list_result = self.cmd(
            "iot hub certificate list --hub-name {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()
        cert_names = [c["name"] for c in list_result["value"]]
        assert CERT_NAME in cert_names

        shown = self.cmd(
            f"iot hub certificate show --hub-name {self.entity_name} -g {self.entity_rg} -n {CERT_NAME}"
        ).get_output_in_json()
        assert shown["id"] == create_result["id"]
        assert shown["properties"]["thumbprint"].upper() in certificate_fingerprints(root_cert["certificate"])
        replacement_name = f"{CERT_NAME}-replacement"
        replacement_file = f"{replacement_name}-cert.pem"
        self._cert_files.extend([replacement_file, f"{replacement_name}-key.pem"])
        root_cert = create_certificate(replacement_name, 1, output_dir)
        updated = self.cmd(
            f"iot hub certificate update --hub-name {self.entity_name} -g {self.entity_rg} -n {CERT_NAME} "
            f"--path {quote(replacement_file)} --etag {quote(shown['etag'])}"
        ).get_output_in_json()
        readback = self.cmd(
            f"iot hub certificate show --hub-name {self.entity_name} -g {self.entity_rg} -n {CERT_NAME}"
        ).get_output_in_json()
        assert readback["id"] == shown["id"]
        assert readback["properties"]["thumbprint"] == updated["properties"]["thumbprint"]
        assert readback["properties"]["thumbprint"] != shown["properties"]["thumbprint"]
        assert readback["properties"]["thumbprint"].upper() in certificate_fingerprints(root_cert["certificate"])

        # Generate verification code
        verification_result = self.cmd(
            "iot hub certificate generate-verification-code --hub-name {} -g {} -n {} -e *".format(
                self.entity_name, self.entity_rg, CERT_NAME
            )
        ).get_output_in_json()
        verification_code = verification_result["properties"]["verificationCode"]
        assert verification_code

        # Create verification certificate signed by the root CA
        create_certificate(
            subject=verification_code,
            valid_days=1,
            cert_output_dir=output_dir,
            cert_object=root_cert,
        )
        verification_cert_file = f"{verification_code}-cert.pem"
        verification_key_file = f"{verification_code}-key.pem"
        self._cert_files.extend([verification_cert_file, verification_key_file])

        # Verify the certificate
        verify_result = self.cmd(
            "iot hub certificate verify --hub-name {} -g {} -n {} -p {} -e *".format(
                self.entity_name, self.entity_rg, CERT_NAME, verification_cert_file
            )
        ).get_output_in_json()
        assert verify_result["properties"]["isVerified"] is True

        # Delete the certificate
        self.cmd(
            "iot hub certificate delete --hub-name {} -g {} -n {} -e *".format(
                self.entity_name, self.entity_rg, CERT_NAME
            )
        )

        # Verify deletion
        list_after_delete = self.cmd(
            "iot hub certificate list --hub-name {} -g {}".format(
                self.entity_name, self.entity_rg
            )
        ).get_output_in_json()
        cert_names_after = [c["name"] for c in list_after_delete["value"]]
        assert CERT_NAME not in cert_names_after
