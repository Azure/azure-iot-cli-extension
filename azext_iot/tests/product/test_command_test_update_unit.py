# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import unittest
import mock
from knack.util import CLIError
from azext_iot.product.test.command_tests import update
from azext_iot.product.shared import BadgeType, AttestationType


class TestTestUpdateUnit(unittest.TestCase):
    def __init__(self, test_case):
        self.test_id = "3beb0e67-33d0-4896-b69b-91c7b7ce8fab"
        super(TestTestUpdateUnit, self).__init__(test_case)

    def test_update_with_x509_and_no_certificate_fails(self):
        with self.assertRaises(CLIError) as context:
            update(
                self, test_id=self.test_id, attestation_type=AttestationType.x509.value
            )

        self.assertEqual(
            "If attestation type is x509, certificate path is required",
            str(context.exception),
        )

    def test_update_with_tpm_and_no_endorsement_key_fails(self):
        with self.assertRaises(CLIError) as context:
            update(
                self, test_id=self.test_id, attestation_type=AttestationType.tpm.value
            )

        self.assertEqual(
            "If attestation type is tpm, endorsement key is required",
            str(context.exception),
        )

    def test_update_with_pnp_and_no_models_fails(self):
        with self.assertRaises(CLIError) as context:
            update(self, test_id=self.test_id, badge_type=BadgeType.Pnp.value)

        self.assertEqual(
            "If badge type is Pnp, models is required", str(context.exception)
        )

    def test_edge_module_without_connection_string_fails(self):
        with self.assertRaises(CLIError) as context:
            update(
                self,
                test_id=self.test_id,
                attestation_type=AttestationType.connectionString.value,
                badge_type=BadgeType.IotEdgeCompatible.value,
            )

        self.assertEqual(
            "Connection string is required for Edge Compatible modules testing",
            str(context.exception),
        )

    def test_connection_string_for_pnp_fails(self):
        with self.assertRaises(CLIError) as context:
            update(
                self,
                test_id=self.test_id,
                attestation_type=AttestationType.connectionString.value,
                badge_type=BadgeType.Pnp.value,
                models="./stuff",
            )

        self.assertEqual(
            "Connection string is only available for Edge Compatible modules testing",
            str(context.exception),
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.product.test.command_tests._create_from_file")
    def test_update_from_file(self, mock_from_file, mock_sdk_update):
        mock_file_data = {"mock": "data"}
        mock_from_file.return_value = mock_file_data
        update(self, test_id=self.test_id, configuration_file="somefile")
        mock_from_file.assert_called_with("somefile")
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=False,
            body=mock_file_data,
            raw=True,
        )

    @mock.patch("azext_iot.product.test.command_tests._read_certificate_from_file")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test")
    def test_update_symmetric_key_to_cert(
        self, mock_from_get, mock_sdk_update, mock_read_certificate
    ):
        mock_read_certificate.return_value = "MockBase64String"
        mock_test_data = {
            "certificationBadgeConfigurations": [{"type": "IotDevice"}],
            "deviceType": "DevKit",
            "id": self.test_id,
            "productId": "product_1234",
            "provisioningConfiguration": {
                "deviceConnectionString": None,
                "deviceId": "device_1234",
                "dpsRegistrationId": "DPS_1234",
                "region": "region_1",
                "symmetricKeyEnrollmentInformation": {
                    "primaryKey": "primary_key",
                    "registrationId": "registration_1234",
                    "scopeId": "scope_1",
                    "secondaryKey": "secondary_key",
                },
                "tpmEnrollmentInformation": None,
                "type": "SymmetricKey",
                "x509EnrollmentInformation": None,
            },
            "validationType": "Certification",
        }
        return_data = mock.Mock()
        return_data.response.json.return_value = mock_test_data

        mock_from_get.return_value = return_data
        update(
            self,
            test_id=self.test_id,
            attestation_type=AttestationType.x509.value,
            certificate_path="mycertificate.cer",
        )
        mock_read_certificate.assert_called_with("mycertificate.cer")
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=True,
            raw=True,
            body={
                "certificationBadgeConfigurations": [{"type": "IotDevice"}],
                "deviceType": "DevKit",
                "id": self.test_id,
                "productId": "product_1234",
                "provisioningConfiguration": {
                    "dpsRegistrationId": "DPS_1234",
                    "type": AttestationType.x509.value,
                    "x509EnrollmentInformation": {
                        "base64EncodedX509Certificate": "MockBase64String"
                    },
                },
                "validationType": "Certification",
            },
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test")
    def test_update_symmetric_key_to_tpm(self, mock_from_get, mock_sdk_update):
        mock_test_data = {
            "certificationBadgeConfigurations": [{"type": "IotDevice"}],
            "deviceType": "DevKit",
            "id": self.test_id,
            "productId": "product_1234",
            "provisioningConfiguration": {
                "deviceConnectionString": None,
                "deviceId": "device_1234",
                "dpsRegistrationId": "DPS_1234",
                "region": "region_1",
                "symmetricKeyEnrollmentInformation": {
                    "primaryKey": "primary_key",
                    "registrationId": "registration_1234",
                    "scopeId": "scope_1",
                    "secondaryKey": "secondary_key",
                },
                "tpmEnrollmentInformation": None,
                "type": "SymmetricKey",
                "x509EnrollmentInformation": None,
            },
            "validationType": "Certification",
        }
        return_data = mock.Mock()
        return_data.response.json.return_value = mock_test_data

        mock_from_get.return_value = return_data
        update(
            self,
            test_id=self.test_id,
            attestation_type=AttestationType.tpm.value,
            endorsement_key="endorsement_key",
        )
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=True,
            raw=True,
            body={
                "certificationBadgeConfigurations": [{"type": "IotDevice"}],
                "deviceType": "DevKit",
                "id": self.test_id,
                "productId": "product_1234",
                "provisioningConfiguration": {
                    "dpsRegistrationId": "DPS_1234",
                    "type": AttestationType.tpm.value,
                    "tpmEnrollmentInformation": {"endorsementKey": "endorsement_key"},
                },
                "validationType": "Certification",
            },
        )

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test")
    def test_update_symmetric_key_to_symmetric_key(
        self, mock_from_get, mock_sdk_update
    ):
        mock_test_data = {
            "certificationBadgeConfigurations": [{"type": "IotDevice"}],
            "deviceType": "DevKit",
            "id": self.test_id,
            "productId": "product_1234",
            "provisioningConfiguration": {
                "deviceConnectionString": None,
                "deviceId": "device_1234",
                "dpsRegistrationId": "DPS_1234",
                "region": "region_1",
                "symmetricKeyEnrollmentInformation": {
                    "primaryKey": "primary_key",
                    "registrationId": "registration_1234",
                    "scopeId": "scope_1",
                    "secondaryKey": "secondary_key",
                },
                "tpmEnrollmentInformation": None,
                "type": "SymmetricKey",
                "x509EnrollmentInformation": None,
            },
            "validationType": "Certification",
        }
        return_data = mock.Mock()
        return_data.response.json.return_value = mock_test_data

        mock_from_get.return_value = return_data
        update(
            self,
            test_id=self.test_id,
            attestation_type=AttestationType.symmetricKey.value,
        )
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=True,
            raw=True,
            body={
                "certificationBadgeConfigurations": [{"type": "IotDevice"}],
                "deviceType": "DevKit",
                "id": self.test_id,
                "productId": "product_1234",
                "provisioningConfiguration": {
                    "dpsRegistrationId": "DPS_1234",
                    "type": AttestationType.symmetricKey.value,
                    "symmetricKeyEnrollmentInformation": {},
                },
                "validationType": "Certification",
            },
        )

    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test")
    def test_update_iotdevice_to_pnp(
        self, mock_from_get, mock_sdk_update, mock_process_models
    ):
        mock_process_models.return_value = [
            '{"@id":"model1"}',
            '{"@id":"model2"}',
            '{"@id":"model3"}',
        ]
        mock_test_data = {
            "certificationBadgeConfigurations": [{"type": "IotDevice"}],
            "deviceType": "DevKit",
            "id": self.test_id,
            "productId": "product_1234",
            "provisioningConfiguration": {
                "deviceConnectionString": None,
                "deviceId": "device_1234",
                "dpsRegistrationId": "DPS_1234",
                "region": "region_1",
                "symmetricKeyEnrollmentInformation": {
                    "primaryKey": "primary_key",
                    "registrationId": "registration_1234",
                    "scopeId": "scope_1",
                    "secondaryKey": "secondary_key",
                },
                "tpmEnrollmentInformation": None,
                "type": "SymmetricKey",
                "x509EnrollmentInformation": None,
            },
            "validationType": "Certification",
        }
        return_data = mock.Mock()
        return_data.response.json.return_value = mock_test_data

        mock_from_get.return_value = return_data
        update(
            self,
            test_id=self.test_id,
            badge_type=BadgeType.Pnp.value,
            models="model_folder",
        )
        mock_process_models.assert_called_with("model_folder")
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=False,
            raw=True,
            body={
                "certificationBadgeConfigurations": [
                    {
                        "type": BadgeType.Pnp.value,
                        "digitalTwinModelDefinitions": [
                            '{"@id":"model1"}',
                            '{"@id":"model2"}',
                            '{"@id":"model3"}',
                        ],
                    }
                ],
                "deviceType": "DevKit",
                "id": self.test_id,
                "productId": "product_1234",
                "provisioningConfiguration": {
                    "deviceConnectionString": None,
                    "deviceId": "device_1234",
                    "dpsRegistrationId": "DPS_1234",
                    "region": "region_1",
                    "symmetricKeyEnrollmentInformation": {
                        "primaryKey": "primary_key",
                        "registrationId": "registration_1234",
                        "scopeId": "scope_1",
                        "secondaryKey": "secondary_key",
                    },
                    "tpmEnrollmentInformation": None,
                    "type": "SymmetricKey",
                    "x509EnrollmentInformation": None,
                },
                "validationType": "Certification",
            },
        )

    @mock.patch("azext_iot.product.test.command_tests._process_models_directory")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.update_device_test")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test")
    def test_update_pnp_to_iotdevice(
        self, mock_from_get, mock_sdk_update, mock_process_models
    ):
        mock_test_data = {
            "certificationBadgeConfigurations": [
                {
                    "type": BadgeType.Pnp.value,
                    "digitalTwinModelDefinitions": [
                        '{"@id":"model1"}',
                        '{"@id":"model2"}',
                        '{"@id":"model3"}',
                    ],
                }
            ],
            "deviceType": "DevKit",
            "id": self.test_id,
            "productId": "product_1234",
            "provisioningConfiguration": {
                "deviceConnectionString": None,
                "deviceId": "device_1234",
                "dpsRegistrationId": "DPS_1234",
                "region": "region_1",
                "symmetricKeyEnrollmentInformation": {
                    "primaryKey": "primary_key",
                    "registrationId": "registration_1234",
                    "scopeId": "scope_1",
                    "secondaryKey": "secondary_key",
                },
                "tpmEnrollmentInformation": None,
                "type": "SymmetricKey",
                "x509EnrollmentInformation": None,
            },
            "validationType": "Certification",
        }
        return_data = mock.Mock()
        return_data.response.json.return_value = mock_test_data

        mock_from_get.return_value = return_data
        update(self, test_id=self.test_id, badge_type=BadgeType.IotDevice.value)
        mock_process_models.assert_not_called()
        mock_sdk_update.assert_called_with(
            device_test_id=self.test_id,
            generate_provisioning_configuration=False,
            raw=True,
            body={
                "certificationBadgeConfigurations": [
                    {"type": BadgeType.IotDevice.value, }
                ],
                "deviceType": "DevKit",
                "id": self.test_id,
                "productId": "product_1234",
                "provisioningConfiguration": {
                    "deviceConnectionString": None,
                    "deviceId": "device_1234",
                    "dpsRegistrationId": "DPS_1234",
                    "region": "region_1",
                    "symmetricKeyEnrollmentInformation": {
                        "primaryKey": "primary_key",
                        "registrationId": "registration_1234",
                        "scopeId": "scope_1",
                        "secondaryKey": "secondary_key",
                    },
                    "tpmEnrollmentInformation": None,
                    "type": "SymmetricKey",
                    "x509EnrollmentInformation": None,
                },
                "validationType": "Certification",
            },
        )
