# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.common.shared import EntityStatusType, AttestationType
from azext_iot.tests.dps import (
    DATAPLANE_AUTH_TYPES,
    CERT_NAME,
    CERT_PATH,
    KEY_PATH,
    SECONDARY_CERT_NAME,
    SECONDARY_CERT_PATH,
    SECONDARY_KEY_PATH,
    IoTDPSLiveScenarioTest
)
from azext_iot.tests.dps.device_registration import compare_registrations


class TestDPSDeviceRegistrationsIndividual(IoTDPSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDeviceRegistrationsIndividual, self).__init__(test_case, cert_only=False)
        self.id_scope = self.get_dps_id_scope()

    def test_dps_device_registration_symmetrickey_lifecycle(self):
        attestation_type = AttestationType.symmetricKey.value
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
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

            # Enrollment with no device id; deviceId becomes enrollmentId
            keys = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]

            # Defaults to primary key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Manually input primary key and id scope
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} --key {}".format(
                        self.id_scope, enrollment_id, keys["primaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Unauthorized
            bad_key = keys["primaryKey"].replace(keys["primaryKey"][0], "")
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} --key {}".format(
                        self.id_scope, enrollment_id, bad_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Try secondary key
            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, keys["secondaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Check registration from service side
            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(registration, service_side)

            # Delete registration to change the device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            )

            # Enrollment with device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} -g {} --dps-name {} --device-id {}".format(
                        enrollment_id,
                        self.entity_rg,
                        self.entity_dps_name,
                        device_id
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
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Try with payload
            self.kwargs["payload"] = json.dumps(
                {"Thermostat": {"$metadata": {}}}
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --payload '{}'".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, "{payload}"
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

    def test_dps_device_registration_x509_lifecycle(self):
        # Create the second test cert - have the same subject but a different file name
        self.create_test_cert(subject=CERT_NAME, cert_only=False, alt_name=SECONDARY_CERT_NAME)
        self.tracked_certs.append(SECONDARY_CERT_PATH)
        self.tracked_certs.append(SECONDARY_KEY_PATH)

        attestation_type = AttestationType.x509.value
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
        for auth_phase in DATAPLANE_AUTH_TYPES:
            # For some reason, enrollment_id must be the subject of the cert to get the device to register
            device_id = self.generate_device_names()[0]

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Enrollment with no device id; deviceId becomes enrollmentId
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --cp {} --scp {}".format(
                        CERT_NAME,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        CERT_PATH,
                        SECONDARY_CERT_PATH
                    ),
                    auth_type=auth_phase
                ),
            )

            # Need to specify file - cannot retrieve need info from service
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Need to specify both files
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--cp {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME, CERT_PATH
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--kp {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME, KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Swap files
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--kp {} --cp {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME, CERT_PATH, KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Normal registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME, CERT_PATH, KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", CERT_NAME),
                    self.check("registrationState.registrationId", CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Use id scope
            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.id_scope, CERT_NAME, CERT_PATH, KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", CERT_NAME),
                    self.check("registrationState.registrationId", CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Check registration from service side
            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(registration, service_side)

            # Delete registration to change the device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME
                    ),
                    auth_type=auth_phase
                ),
            )

            # Enrollment with device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} -g {} --dps-name {} --device-id {}".format(
                        CERT_NAME,
                        self.entity_rg,
                        self.entity_dps_name,
                        device_id
                    ),
                    auth_type=auth_phase
                ),
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.entity_dps_name, self.entity_rg, CERT_NAME, CERT_PATH, KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Try with payload
            self.kwargs["payload"] = json.dumps(
                {"Thermostat": {"$metadata": {}}}
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--cp {} --kp {} --payload '{}'".format(
                        self.entity_dps_name,
                        self.entity_rg,
                        CERT_NAME,
                        CERT_PATH,
                        KEY_PATH,
                        "{payload}"
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Try secondary cert
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.id_scope, CERT_NAME, SECONDARY_CERT_PATH, SECONDARY_KEY_PATH
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", CERT_NAME),
                    self.check("registrationState.registrationId", CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete --enrollment-id {} -g {} --dps-name {}".format(
                        CERT_NAME,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            )

    def test_dps_device_registration_unlinked_hub(self):
        # Unlink hub
        self.cmd(
            "iot dps linked-hub delete --dps-name {} -g {} --linked-hub {}".format(
                self.entity_dps_name,
                self.entity_rg,
                self.entity_hub_name
            )
        )

        attestation_type = AttestationType.symmetricKey.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id = self.generate_enrollment_names()[0]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            )

            # registration throws error
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Can see registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("etag"),
                    self.exists("lastUpdatedDateTimeUtc"),
                    self.check("registrationId", enrollment_id),
                    self.check("status", "failed"),
                ],
            )

    def test_dps_device_registration_disabled_enrollment(self):
        attestation_type = AttestationType.symmetricKey.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id = self.generate_enrollment_names()[0]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --provisioning-status {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        EntityStatusType.disabled.value
                    ),
                    auth_type=auth_phase
                ),
            )

            # Registration throws error
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Can see registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("etag"),
                    self.exists("lastUpdatedDateTimeUtc"),
                    self.check("registrationId", enrollment_id),
                    self.check("status", "disabled"),
                ],
            )
