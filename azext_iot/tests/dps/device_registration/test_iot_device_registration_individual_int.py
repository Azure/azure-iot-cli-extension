# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from typing import Dict
from azext_iot.common.shared import EntityStatusType, AttestationType
from azext_iot.dps.common import MAX_REGISTRATION_ASSIGNMENT_RETRIES
from azext_iot.tests.dps import (
    DATAPLANE_AUTH_TYPES,
    IoTDPSLiveScenarioTest
)


class TestDPSDeviceRegistrationsIndividual(IoTDPSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDeviceRegistrationsIndividual, self).__init__(test_case)
        self.id_scope = self.get_dps_id_scope()

    def test_dps_device_registration_symmetrickey_lifecycle(self):
        attestation_type = AttestationType.symmetricKey.value
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id1, enrollment_id2 = self.generate_enrollment_names(count=2)
            device_id = self.generate_device_names()[0]

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Enrollment with no device id; deviceId becomes enrollmentId
            secondary_key = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {}".format(
                        enrollment_id1,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]["secondaryKey"]

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(enrollment_id1, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id1),
                    self.check("registrationState.registrationId", enrollment_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("assignedHub", registration["assignedHub"]),
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("deviceId", registration["deviceId"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                ],
            )

            # Recreate registration, yeilds different substatus
            # Use of --wait in create will result in the same result as operation show
            operation_result = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --wait".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id1),
                    self.check("registrationState.registrationId", enrollment_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "reprovisionedToInitialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()
            self._wait_for_assignment(enrollment_id1, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1, operation_result["operationId"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_result["operationId"]),
                    self.check("registrationState", operation_result["registrationState"]),
                    self.check("status", operation_result["status"]),
                ],
            ).get_output_in_json()["registrationState"]

            # Cannot use secondary key when device registration was created with primary key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Enrollment with device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update --enrollment-id {} -g {} --dps-name {} --device-id {}".format(
                        enrollment_id1,
                        self.entity_rg,
                        self.entity_dps_name,
                        device_id
                    ),
                    auth_type=auth_phase
                ),
            )

            # Nothing changes until you create again (after deleting the registration)
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("assignedHub", registration["assignedHub"]),
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("deviceId", registration["deviceId"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                ],
            )

            # Delete registration to change the device id
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration delete --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(enrollment_id1, auth_phase)

            # Initial Assignment because changed device id
            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id),
                    self.check("registrationState.registrationId", enrollment_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("assignedHub", registration["assignedHub"]),
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("deviceId", registration["deviceId"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                ],
            )

            # Check registration from service side
            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            self._compare_registrations(registration, service_side)

            # Cannot use compute key for individual enrollment
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --ck".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id1
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Create second enrollment to use secondary key (cannot create registration with secondary key
            # once a registration with the primary key was created)
            secondary_key = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {}".format(
                        enrollment_id2,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]["secondaryKey"]

            # Register device with enrollment key and id scope
            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} --key {}".format(
                        self.id_scope, enrollment_id2, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(enrollment_id2, auth_phase, secondary_key)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --id-scope {} --registration-id {} --operation-id {} "
                    "--key {}".format(
                        self.id_scope, enrollment_id2, operation_id, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", enrollment_id2),
                    self.check("registrationState.registrationId", enrollment_id2),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --id-scope {} --registration-id {} --key {}".format(
                        self.id_scope, enrollment_id2, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("assignedHub", registration["assignedHub"]),
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("deviceId", registration["deviceId"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                ],
            )

            # Cannot use primary key here - default is primary key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id2
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id2, operation_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id2
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
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

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(enrollment_id, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --registration-id {} --operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.errorCode", 401001),
                    self.check("registrationState.errorMessage", "IoTHub not found."),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.status", "failed"),
                    self.check("status", "failed"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("createdDateTimeUtc", registration["createdDateTimeUtc"]),
                    self.check("errorCode", registration["errorCode"]),
                    self.check("errorMessage", registration["errorMessage"]),
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
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

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", ""),
                    self.exists("registrationState.etag"),
                    self.exists("registrationState.lastUpdatedDateTimeUtc"),
                    self.check("registrationState.registrationId", enrollment_id),
                    self.check("registrationState.status", "disabled"),
                    self.check("status", "disabled"),
                ],
            ).get_output_in_json()["registrationState"]

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
                    self.check("etag", registration["etag"]),
                    self.check("lastUpdatedDateTimeUtc", registration["lastUpdatedDateTimeUtc"]),
                    self.check("payload", registration["payload"]),
                    self.check("registrationId", registration["registrationId"]),
                    self.check("status", registration["status"]),
                    self.check("substatus", registration["substatus"]),
                ],
            )

    def _wait_for_assignment(self, enrollment_id: str, auth_phase: str, key: str = None):
        """
        Wait for the device registration to be assigned to a hub.
        Usually not needed, but here in case the service is slow.
        """
        status = "assigning"
        command = "iot device registration show --dps-name {} -g {} --registration-id {}".format(
            self.entity_dps_name, self.entity_rg, enrollment_id
        )
        if key:
            command += f" --key {key}"
        retries = 0
        while status == "assigning" and retries < MAX_REGISTRATION_ASSIGNMENT_RETRIES:
            status = self.cmd(
                self.set_cmd_auth_type(
                    command,
                    auth_type=auth_phase
                )
            ).get_output_in_json()["status"]
            sleep(1)

    def _compare_registrations(self, device_side: Dict[str, str], service_side: Dict[str, str]):
        """Compare the registration information from the device and the service clients."""
        assert device_side["assignedHub"] == service_side["assignedHub"]
        assert device_side["createdDateTimeUtc"].rstrip("+00:00") in service_side["createdDateTimeUtc"]
        assert device_side["deviceId"] == service_side["deviceId"]
        assert device_side["etag"] == service_side["etag"]
        assert device_side["lastUpdatedDateTimeUtc"].rstrip("+00:00") in service_side["lastUpdatedDateTimeUtc"]
        assert device_side["registrationId"] == service_side["registrationId"]
        assert device_side["status"] == service_side["status"]
        assert device_side["substatus"] == service_side["substatus"]