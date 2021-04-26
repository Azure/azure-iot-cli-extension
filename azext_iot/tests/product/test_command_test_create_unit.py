# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import unittest
import mock
from knack.util import CLIError
from azext_iot.product.test.command_tests import create, _process_models_directory as process_models
from azext_iot.product.shared import BadgeType, AttestationType, DeviceType, ValidationType


class TestTestCreateUnit(unittest.TestCase):
    def __init__(self, test_case):
        super(TestTestCreateUnit, self).__init__(test_case)

    def test_create_with_no_parameters_fails(self):
        with self.assertRaises(CLIError):
            create(self)

    def test_create_with_x509_and_no_certificate_fails(self):
        with self.assertRaises(CLIError) as context:
            create(self, attestation_type=AttestationType.x509.value)

        self.assertEqual(
            "If attestation type is x509, certificate path is required",
            str(context.exception),
        )

    def test_create_with_tpm_and_no_endorsement_key_fails(self):
        with self.assertRaises(CLIError) as context:
            create(self, attestation_type=AttestationType.tpm.value)

        self.assertEqual(
            "If attestation type is TPM, endorsement key is required",
            str(context.exception),
        )

    def test_edge_module_without_connection_string_fails(self):
        with self.assertRaises(CLIError) as context:
            create(
                self,
                attestation_type=AttestationType.connectionString.value,
                badge_type=BadgeType.IotEdgeCompatible.value,
            )

        self.assertEqual(
            "Connection string is required for Edge Compatible modules testing",
            str(context.exception),
        )

    def test_connection_string_for_pnp_fails(self):
        with self.assertRaises(CLIError) as context:
            create(
                self,
                attestation_type=AttestationType.connectionString.value,
                badge_type=BadgeType.Pnp.value,
                models="./stuff",
            )

        self.assertEqual(
            "Connection string is only available for Edge Compatible modules testing",
            str(context.exception),
        )

    def test_connection_string_for_iot_device_fails(self):
        with self.assertRaises(CLIError) as context:
            create(self, attestation_type=AttestationType.connectionString.value)

        self.assertEqual(
            "Connection string is only available for Edge Compatible modules testing",
            str(context.exception),
        )

    def test_create_with_pnp_and_no_models_fails(self):
        with self.assertRaises(CLIError) as context:
            create(self, badge_type=BadgeType.Pnp.value)

        self.assertEqual(
            "If badge type is Pnp, models is required", str(context.exception)
        )

    def test_create_with_missing_device_type_fails(self):
        with self.assertRaises(CLIError) as context:
            create(
                self,
                attestation_type=AttestationType.symmetricKey.value,
                badge_type=BadgeType.Pnp.value,
                models="models_folder",
            )

        self.assertEqual(
            "If configuration file is not specified, attestation and device definition parameters must be specified",
            str(context.exception),
        )

    def test_create_certification_with_missing_product_id_fails(self):
        with self.assertRaises(CLIError) as context:
            create(
                self,
                attestation_type=AttestationType.symmetricKey.value,
                device_type=DeviceType.DevKit.value,
                badge_type=BadgeType.Pnp.value,
                models="models_folder",
                validation_type=ValidationType.certification.value
            )
        self.assertEqual(
            "Product Id is required for validation type Certification",
            str(context.exception),
        )

    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test")
    def test_create_with_default_badge_type_doesnt_check_models(
        self, mock_service, mock_process_models
    ):
        create(
            self,
            attestation_type=AttestationType.symmetricKey.value,
            device_type=DeviceType.DevKit.value,
            models="models_folder",
        )

        mock_process_models.assert_not_called()
        mock_service.assert_called_with(
            generate_provisioning_configuration=True,
            body={
                "validationType": "Test",
                "productId": None,
                "deviceType": "DevKit",
                "provisioningConfiguration": {
                    "type": "SymmetricKey",
                    "symmetricKeyEnrollmentInformation": {},
                },
                "certificationBadgeConfigurations": [{"type": "IotDevice"}],
            },
        )

    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test")
    def test_create_with_pnp_badge_type_checks_models(
        self, mock_service, mock_process_models
    ):
        mock_process_models.return_value = [
            '{"@id":"model1"}',
            '{"@id":"model2"}',
            '{"@id":"model3"}',
        ]
        create(
            self,
            attestation_type=AttestationType.symmetricKey.value,
            device_type=DeviceType.DevKit.value,
            models="models_folder",
            badge_type=BadgeType.Pnp.value,
        )

        mock_process_models.assert_called_with("models_folder")
        mock_service.assert_called_with(
            generate_provisioning_configuration=True,
            body={
                "validationType": "Test",
                "productId": None,
                "deviceType": "DevKit",
                "provisioningConfiguration": {
                    "type": "SymmetricKey",
                    "symmetricKeyEnrollmentInformation": {},
                },
                "certificationBadgeConfigurations": [
                    {
                        "type": "Pnp",
                        "digitalTwinModelDefinitions": [
                            '{"@id":"model1"}',
                            '{"@id":"model2"}',
                            '{"@id":"model3"}',
                        ],
                    }
                ],
            },
        )

    @mock.patch("azext_iot.product.test.command_tests._read_certificate_from_file")
    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test")
    def test_create_with_cert_auth_reads_cert_file(
        self, mock_service, mock_process_models, mock_read_certificate
    ):
        mock_read_certificate.return_value = "MockBase64String"
        mock_process_models.return_value = [
            '{"@id":"model1"}',
            '{"@id":"model2"}',
            '{"@id":"model3"}',
        ]
        create(
            self,
            attestation_type=AttestationType.x509.value,
            device_type=DeviceType.DevKit.value,
            models="models_folder",
            badge_type=BadgeType.Pnp.value,
            certificate_path="mycertificate.cer",
            product_id="ABC123",
            validation_type=ValidationType.certification.value
        )

        mock_read_certificate.assert_called_with("mycertificate.cer")
        mock_process_models.assert_called_with("models_folder")
        mock_service.assert_called_with(
            generate_provisioning_configuration=True,
            body={
                "validationType": "Certification",
                "productId": "ABC123",
                "deviceType": "DevKit",
                "provisioningConfiguration": {
                    "type": "X509",
                    "x509EnrollmentInformation": {
                        "base64EncodedX509Certificate": "MockBase64String"
                    },
                },
                "certificationBadgeConfigurations": [
                    {
                        "type": "Pnp",
                        "digitalTwinModelDefinitions": [
                            '{"@id":"model1"}',
                            '{"@id":"model2"}',
                            '{"@id":"model3"}',
                        ],
                    }
                ],
            },
        )

    @mock.patch("azext_iot.product.test.command_tests._read_certificate_from_file")
    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test")
    def test_create_with_tpm(
        self, mock_service, mock_process_models, mock_read_certificate
    ):
        mock_process_models.return_value = [
            '{"@id":"model1"}',
            '{"@id":"model2"}',
            '{"@id":"model3"}',
        ]
        create(
            self,
            attestation_type=AttestationType.tpm.value,
            endorsement_key="12345",
            device_type=DeviceType.DevKit.value,
            models="models_folder",
            badge_type=BadgeType.Pnp.value,
            certificate_path="mycertificate.cer",
        )

        mock_read_certificate.assert_not_called()
        mock_process_models.assert_called_with("models_folder")
        mock_service.assert_called_with(
            generate_provisioning_configuration=True,
            body={
                "validationType": "Test",
                "productId": None,
                "deviceType": "DevKit",
                "provisioningConfiguration": {
                    "type": "TPM",
                    "tpmEnrollmentInformation": {"endorsementKey": "12345"},
                },
                "certificationBadgeConfigurations": [
                    {
                        "type": "Pnp",
                        "digitalTwinModelDefinitions": [
                            '{"@id":"model1"}',
                            '{"@id":"model2"}',
                            '{"@id":"model3"}',
                        ],
                    }
                ],
            },
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test")
    @mock.patch("azext_iot.product.test.command_tests._create_from_file")
    def test_create_with_configuration_file(self, mock_from_file, mock_sdk_create):
        mock_file_data = {"mock": "data"}
        mock_from_file.return_value = mock_file_data
        create(self, configuration_file="somefile")
        mock_from_file.assert_called_with("somefile")
        mock_sdk_create.assert_called_with(generate_provisioning_configuration=True, body=mock_file_data)

    @mock.patch("os.scandir")
    @mock.patch("os.path.isfile")
    @mock.patch("azext_iot.common.utility.read_file_content")
    def test_process_models_directory_as_file(self, mock_file_content, mock_is_file, mock_scan_tree):
        mock_file_content.return_value = {"id": "my file"}
        mock_is_file.return_value = True

        results = process_models("myPath.dtdl")

        self.assertEqual(len(results), 1)
        mock_scan_tree.assert_not_called()

        results = process_models("myPath.json")

        self.assertEqual(len(results), 1)
        mock_scan_tree.assert_not_called()
