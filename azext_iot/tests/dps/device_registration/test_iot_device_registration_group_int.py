# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from azext_iot.common.shared import EntityStatusType
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


class TestDPSDeviceRegistrationsGroup(IoTDPSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSDeviceRegistrationsGroup, self).__init__(test_case, cert_only=False)
        self.id_scope = self.get_dps_id_scope()

    def test_dps_device_registration_symmetrickey_lifecycle(self):
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
        for auth_phase in DATAPLANE_AUTH_TYPES:
            group_id = self.generate_enrollment_names(count=1, group=True)[0]
            device_id1, device_id2 = self.generate_device_names(count=2)

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
            keys = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group create --group-id {} -g {} --dps-name {}".format(
                        group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()["attestation"]["symmetricKey"]

            # Defaults to group primary key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Recreate with group primary key, recreate yeilds different substatus
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} "
                    "--ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, keys["primaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Use id scope - compute_key should work without login
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --group-id {} --registration-id {} --key {} "
                    "--ck".format(
                        self.id_scope, group_id, device_id1, keys["primaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
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

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --group-id {} --registration-id {} --key {}".format(
                        self.id_scope, group_id, device_id1, device_key
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            # Can register a second device within the same enrollment group
            device2_registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id2
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id2),
                    self.check("registrationState.registrationId", device_id2),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Can re-register a first device within the same enrollment group using a different key
            device1_registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, keys["secondaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Check for both registration from service side
            service_side_registrations = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration list --dps-name {} -g {} --group-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            assert len(service_side_registrations) == 2

            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, device_id1
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(device1_registration, service_side)

            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, device_id2
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(device2_registration, service_side)

            # Cannot use group key as device key
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, keys["primaryKey"]
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Try with payload
            self.kwargs["payload"] = json.dumps(
                {"Thermostat": {"$metadata": {}}}
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} "
                    "--payload '{}'".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id1, "{payload}"
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", device_id1),
                    self.check("registrationState.registrationId", device_id1),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

    # def test_dps_device_registration_x509_lifecycle(self):
    #     # Create the second test cert
    #     self.create_test_cert(subject=SECONDARY_CERT_NAME, cert_only=False)

    #     hub_host_name = f"{self.entity_hub_name}.azure-devices.net"
    #     for auth_phase in DATAPLANE_AUTH_TYPES:
    #         group_id = self.generate_enrollment_names(count=1, group=True)[0]
    #         # For some reason, device_id must be the subject of the cert to get the device to register

    #         # Enrollment needs to be created
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
    #                     self.entity_dps_name, self.entity_rg, group_id, SECONDARY_CERT_NAME
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             expect_failure=True
    #         )

    #         # Regular enrollment group
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot dps enrollment-group create --group-id {} -g {} --dps-name {} --cp {} --scp {}".format(
    #                     group_id,
    #                     self.entity_rg,
    #                     self.entity_dps_name,
    #                     CERT_PATH,
    #                     SECONDARY_CERT_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #         )

    #         # Need to specify file - cannot retrieve need info from service
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME, group_id
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             expect_failure=True
    #         )

    #         # Need to specify both files
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {} "
    #                 "--cp {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME, group_id, CERT_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             expect_failure=True
    #         )

    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {} "
    #                 "--kp {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME, group_id, KEY_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             expect_failure=True
    #         )

    #         # Swap files
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {} "
    #                 "--kp {} --cp {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME, group_id, CERT_PATH, KEY_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             expect_failure=True
    #         )

    #         # Input files correctly
    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {} "
    #                 "--cp {} --kp {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME, group_id, CERT_PATH, KEY_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             checks=[
    #                 self.exists("operationId"),
    #                 self.check("registrationState.assignedHub", hub_host_name),
    #                 self.check("registrationState.deviceId", CERT_NAME),
    #                 self.check("registrationState.registrationId", CERT_NAME),
    #                 self.check("registrationState.substatus", "initialAssignment"),
    #                 self.check("status", "assigned"),
    #             ],
    #         )

    #         # Use id scope
    #         device1_registration = self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --id-scope {} --registration-id {} --group-id {} "
    #                 "--cp {} --kp {}".format(
    #                     self.id_scope, CERT_NAME, group_id, CERT_PATH, KEY_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             checks=[
    #                 self.exists("operationId"),
    #                 self.check("registrationState.assignedHub", hub_host_name),
    #                 self.check("registrationState.deviceId", CERT_NAME),
    #                 self.check("registrationState.registrationId", CERT_NAME),
    #                 self.check("registrationState.substatus", "initialAssignment"),
    #                 self.check("status", "assigned"),
    #             ],
    #         ).get_output_in_json()["registrationState"]

    #         # Register using secondary cert file
    #         device2_registration = self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --dps-name {} -g {} --registration-id {} --group-id {} "
    #                 "--cp {} --kp {}".format(
    #                     self.entity_dps_name,
    #                     self.entity_rg,
    #                     SECONDARY_CERT_NAME,
    #                     group_id,
    #                     SECONDARY_CERT_PATH,
    #                     SECONDARY_KEY_PATH
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             checks=[
    #                 self.exists("operationId"),
    #                 self.check("registrationState.assignedHub", hub_host_name),
    #                 self.check("registrationState.deviceId", SECONDARY_CERT_NAME),
    #                 self.check("registrationState.registrationId", SECONDARY_CERT_NAME),
    #                 self.check("registrationState.substatus", "initialAssignment"),
    #                 self.check("status", "assigned"),
    #             ],
    #         ).get_output_in_json()["registrationState"]

    #         # Check service side
    #         service_side_registrations = self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot dps enrollment-group registration list --dps-name {} -g {} --group-id {}".format(
    #                     self.entity_dps_name, self.entity_rg, group_id
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #         ).get_output_in_json()
    #         assert len(service_side_registrations) == 2

    #         service_side = self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
    #                     self.entity_dps_name, self.entity_rg, CERT_NAME
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #         ).get_output_in_json()
    #         compare_registrations(device1_registration, service_side)

    #         service_side = self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
    #                     self.entity_dps_name, self.entity_rg, SECONDARY_CERT_NAME
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #         ).get_output_in_json()
    #         compare_registrations(device2_registration, service_side)

    #         # Try with payload
    #         self.kwargs["payload"] = json.dumps(
    #             {"Thermostat": {"$metadata": {}}}
    #         )

    #         self.cmd(
    #             self.set_cmd_auth_type(
    #                 "iot device registration create --id-scope {} --registration-id {} --group-id {} "
    #                 "--cp {} --kp {} --payload '{}'".format(
    #                     self.id_scope,
    #                     CERT_NAME,
    #                     group_id,
    #                     CERT_PATH,
    #                     KEY_PATH,
    #                     "{payload}"
    #                 ),
    #                 auth_type=auth_phase
    #             ),
    #             checks=[
    #                 self.exists("operationId"),
    #                 self.check("registrationState.assignedHub", hub_host_name),
    #                 self.check("registrationState.deviceId", CERT_NAME),
    #                 self.check("registrationState.registrationId", CERT_NAME),
    #                 self.check("registrationState.substatus", "initialAssignment"),
    #                 self.check("status", "assigned"),
    #             ],
    #         )

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

            # registration throws error
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Can see registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration show --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, device_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("etag"),
                    self.exists("lastUpdatedDateTimeUtc"),
                    self.check("registrationId", device_id),
                    self.check("status", "failed"),
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

            # Registration throws error
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, group_id, device_id
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Can see registration
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment registration show --dps-name {} -g {} --enrollment-id {}".format(
                        self.entity_dps_name, self.entity_rg, device_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("etag"),
                    self.exists("lastUpdatedDateTimeUtc"),
                    self.check("registrationId", device_id),
                    self.check("status", "disabled"),
                ],
            )
