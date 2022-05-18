# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from typing import Dict
from azext_iot.common.shared import EntityStatusType
from azext_iot.dps.common import MAX_REGISTRATION_ASSIGNMENT_RETRIES
from azext_iot.tests.dps import (
    DATAPLANE_AUTH_TYPES,
    IoTDPSLiveScenarioTest
)


class TestDPSDeviceRegistrationsGroup(IoTDPSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDeviceRegistrationsGroup, self).__init__(test_case)
        self.id_scope = self.get_dps_id_scope()

    def test_dps_device_registration_symmetrickey_lifecycle(self):
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
        for auth_phase in DATAPLANE_AUTH_TYPES:
            group_id = self.generate_enrollment_names(count=1, group=True)[0]
            device_id1, device_id2, device_id3 = self.generate_device_names(count=3)

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Regular enrollment group
            symmetric_keys = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group create --group-id {} -g {} --dps-name {}".format(
                        group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]
            primary_key = symmetric_keys["primaryKey"]
            secondary_key = symmetric_keys["secondaryKey"]

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(group_id, device_id1, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1
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

            # Recreate with group primary key, recreate yeilds different substatus
            # Use of --wait in create will result in the same result as operation show
            operation_result = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} "
                    "--ck --wait".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, primary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "reprovisionedToInitialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--operation-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, operation_result["operationId"], primary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_result["operationId"]),
                    self.check("registrationState", operation_result["registrationState"]),
                    self.check("status", operation_result["status"]),
                ],
            )

            # Recreate with computed device key (and id scope)
            device_key = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group compute-device-key --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1
                    ),
                    auth_type=auth_phase
                )
            ).get_output_in_json()

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --group-id {} --registration-id {} --key {}".format(
                        self.id_scope, group_id, device_id1, device_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(group_id, device_id1, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --id-scope {} --group-id {} --registration-id {} "
                    "--operation-id {} --key {}".format(
                        self.id_scope, group_id, device_id1, operation_id, device_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "reprovisionedToInitialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --id-scope {} --group-id {} --registration-id {} --key {}".format(
                        self.id_scope, group_id, device_id1, device_key
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

            # Can register a second device within the same enrollment group
            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id2
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(group_id, device_id2, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id2, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id2),
                    self.check("registrationState.registrationId", device_id2),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id2
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

            # Can register a third device within the same enrollment group using a different key
            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id3, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(group_id, device_id3, auth_phase, key=secondary_key)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--operation-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id3, operation_id, secondary_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id3),
                    self.check("registrationState.registrationId", device_id3),
                    self.check("registrationState.status", "assigned"),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id3, secondary_key
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

            # Cannot use primary key for third device
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id3, primary_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id3, primary_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Check for both registration from service side
            service_side_registrations = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration list --dps-name {} -g {} --group-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            assert len(service_side_registrations) == 3

            for device_id in [device_id1, device_id2, device_id3]:
                show_command = "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                    self.entity_dps_name, self.entity_rg, group_id, device_id
                )
                if device_id == device_id3:
                    show_command += f" --key {secondary_key} --ck"
                device_side = self.cmd(
                    self.set_cmd_auth_type(
                        show_command,
                        auth_type=auth_phase
                    ),
                ).get_output_in_json()

                service_side = self.cmd(
                    self.set_cmd_auth_type(
                        "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
                            self.entity_dps_name, self.entity_rg, device_id
                        ),
                        auth_type=auth_phase
                    ),
                ).get_output_in_json()
                self._compare_registrations(device_side, service_side)

            # Cannot use group key as device key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, primary_key
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Delete registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration delete --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, device_id2
                    ),
                    auth_type=auth_phase
                ),
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id2
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

        for auth_phase in DATAPLANE_AUTH_TYPES:
            group_id = self.generate_enrollment_names(group=True)[0]
            device_id = self.generate_device_names()[0]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group create --group-id {} -g {} --dps-name {}".format(
                        group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            )

            operation_id = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState", None),
                    self.check("status", "assigning"),
                ],
            ).get_output_in_json()["operationId"]
            self._wait_for_assignment(group_id, device_id, auth_phase)

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration operation show --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--operation-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id, operation_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", operation_id),
                    self.check("registrationState.errorCode", 401001),
                    self.check("registrationState.errorMessage", "IoTHub not found."),
                    self.check("registrationState.registrationId", device_id),
                    self.check("registrationState.status", "failed"),
                    self.check("status", "failed"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
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
        for auth_phase in DATAPLANE_AUTH_TYPES:
            group_id = self.generate_enrollment_names(count=1, group=True)[0]
            device_id = self.generate_device_names()[0]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group create --group-id {} -g {} --dps-name {} --provisioning-status {}".format(
                        group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                        EntityStatusType.disabled.value
                    ),
                    auth_type=auth_phase
                ),
            )

            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("operationId", ""),
                    self.check("registrationState.deviceId", None),
                    self.exists("registrationState.etag"),
                    self.exists("registrationState.lastUpdatedDateTimeUtc"),
                    self.check("registrationState.registrationId", device_id),
                    self.check("registrationState.status", "disabled"),
                    self.check("status", "disabled"),
                ],
            ).get_output_in_json()["registrationState"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
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

    def _wait_for_assignment(self, group_id: str, registration_id: str, auth_phase: str, key: str = None):
        """
        Wait for the device registration to be assigned to a hub.
        Usually not needed, but here in case the service is slow.
        """
        status = "assigning"
        command = "iot device registration show --dps-name {} -g {} --group-id {} --registration-id {}".format(
            self.entity_dps_name, self.entity_rg, group_id, registration_id
        )
        if key:
            command += f" --key {key} --ck"
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
