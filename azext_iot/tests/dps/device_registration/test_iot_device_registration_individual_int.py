# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.common.shared import EntityStatusType, AttestationType
from azext_iot.tests.dps import (
    DATAPLANE_AUTH_TYPES,
    IoTDPSLiveScenarioTest
)
from azext_iot.tests.dps.device_registration import compare_registrations
from azext_iot.tests.helpers import CERT_ENDING, KEY_ENDING


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
            self.check_hub_device(enrollment_id, "sas")

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

            # Try different provisioning host
            provisioning_host = f"{self.entity_dps_name}.azure-devices-provisioning.net"
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} --key {} --host {}".format(
                        self.id_scope, enrollment_id, keys["primaryKey"], provisioning_host
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
            self.check_hub_device(device_id, "sas")
            # Note that the old device registration still exists in hub
            self.check_hub_device(enrollment_id, "sas")

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
        # Create two test certs - have the same subject but a different file name
        cert_name = self.generate_device_names()[0]
        cert_path = cert_name + CERT_ENDING
        key_path = cert_name + KEY_ENDING
        first_thumbprint = self.create_test_cert(cert_name, False)

        second_cert_name = self.generate_device_names()[0]
        second_cert_path = second_cert_name + CERT_ENDING
        second_key_path = second_cert_name + KEY_ENDING
        secondary_thumprint = self.create_test_cert(cert_name, False, file_prefix=second_cert_name)

        attestation_type = AttestationType.x509.value
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
        for auth_phase in DATAPLANE_AUTH_TYPES:
            # For some reason, enrollment_id must be the subject of the cert to get the device to register
            device_id = self.generate_device_names()[0]

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, cert_name
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
                        cert_name,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        cert_path,
                        second_cert_path
                    ),
                    auth_type=auth_phase
                ),
            )

            # Need to specify file - cannot retrieve need info from service
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, cert_name
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
                        self.entity_dps_name, self.entity_rg, cert_name, cert_path, key_path
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", cert_name),
                    self.check("registrationState.registrationId", cert_name),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )
            self.check_hub_device(cert_name, "selfSigned", thumbprint=first_thumbprint)

            # Use id scope and different host
            provisioning_host = f"{self.entity_dps_name}.azure-devices-provisioning.net"
            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} "
                    "--cp {} --kp {} --host {}".format(
                        self.id_scope, cert_name, cert_path, key_path, provisioning_host
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", cert_name),
                    self.check("registrationState.registrationId", cert_name),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Check registration from service side
            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, cert_name
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(registration, service_side)

            # Delete registration to change the device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, cert_name
                    ),
                    auth_type=auth_phase
                ),
            )

            # Enrollment with device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} -g {} --dps-name {} --device-id {}".format(
                        cert_name,
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
                        self.entity_dps_name, self.entity_rg, cert_name, cert_path, key_path
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", cert_name),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )
            self.check_hub_device(device_id, "selfSigned", thumbprint=first_thumbprint)
            # Note that the old registration will still exist in hub
            self.check_hub_device(cert_name, "selfSigned", thumbprint=first_thumbprint)

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
                        cert_name,
                        cert_path,
                        key_path,
                        "{payload}"
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", cert_name),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Try secondary cert
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.id_scope, cert_name, second_cert_path, second_key_path
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", cert_name),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )
            self.check_hub_device(device_id, "selfSigned", thumbprint=secondary_thumprint)

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete --enrollment-id {} -g {} --dps-name {}".format(
                        cert_name,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            )

    def test_dps_device_registration_unlinked_hub(self):
        # Unlink hub - use hub host name until min version is 2.32
        self.cmd(
            "iot dps linked-hub delete --dps-name {} -g {} --linked-hub {}".format(
                self.entity_dps_name,
                self.entity_rg,
                self.hub_host_name
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
