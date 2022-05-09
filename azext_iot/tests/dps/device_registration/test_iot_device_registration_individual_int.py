# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.shared import EntityStatusType, AttestationType, AllocationType, ReprovisionType
from azext_iot.common.utility import generate_key
from azext_iot.tests.dps import (
    API_VERSION,
    CERT_PATH,
    DATAPLANE_AUTH_TYPES,
    WEBHOOK_URL,
    TEST_ENDORSEMENT_KEY,
    IoTDPSLiveScenarioTest
)

# Todo: test ideas
# regular test pattern
# regular test pattern with enrollment key
# delete registration and see what happens (in show and operation show)
# device id effects -
# bad enrollment (doesnt exist) -
# no linked hub
# disabled enrollment - create gives different outcome
# specified iot hub in enrollment
# does endorsement key affect this?


class TestDPSDeviceRegistrationsIndividual(IoTDPSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDeviceRegistrationsIndividual, self).__init__(test_case)

    def test_dps_device_registration_symmetrickey_lifecycle(self):
        attestation_type = AttestationType.symmetricKey.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id = self.generate_enrollment_names()[0]
            device_id = self.generate_device_names()[0]

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Normal enrollment group
            enrollment_key = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --device-id {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        device_id
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]["secondaryKey"]

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json().get("operationId")

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.exists("registrationState.assignedHub", self.entity_hub_name),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json().get("registrationState")

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("assignedHub", registration["assignedHub"]),
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("deviceId", registration["deviceId"]),
                    # self.check("errorCode", registration["errorCode"]),
                    # self.check("errorMessage", registration["errorMessage"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", , registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                    # self.check("symmetricKey", registration["symmetricKey"]),
                    # self.check("tpm", registration["tpm"]),
                    # self.check("x509", registration["x509"]),
                ],
            ).get_output_in_json()

            # Register device with enrollment key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, enrollment_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, enrollment_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                ],
            )

            # No device id in enrollment group; deviceId becomes enrollmentId
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json().get("operationId")

            operation = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("assignedHub"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()

            # Disabled enrollment
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --provisioning-state {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        EntityStatusType.disabled.value
                    ),
                    auth_type=auth_phase
                ),
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("assignedHub"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, enrollment_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                ],
            )

            # Delete registration
            self.cmd(
                self.set_cmd_auth_type(
                    "dps enrollment registration delete --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("assignedHub"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("assignedHub"),
                    self.exists("registrationState"),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()

    def test_dps_device_registration_unlinked_hub(self):
        pass
