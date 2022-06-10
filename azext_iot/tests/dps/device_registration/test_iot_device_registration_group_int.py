# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from azext_iot.common.shared import EntityStatusType
from azext_iot.tests.dps import DATAPLANE_AUTH_TYPES, IoTDPSLiveScenarioTest
from azext_iot.tests.dps.device_registration import compare_registrations
from azext_iot.tests.dps.test_utils import create_certificate

CERT_ENDING = "-cert.pem"
KEY_ENDING = "-key.pem"
ROOT_CERT_NAME = "aziotcli-root"
DEVICE_CERT_NAME = "aziotcli-device"


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
            self.check_hub_device(device_id1, "sas")

            # Recreate with group primary key, and use different provisioning host
            provisioning_host = f"{self.entity_dps_name}.azure-devices-provisioning.net"
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --group-id {} --registration-id {} --key {} "
                    "--ck --host {}".format(
                        self.entity_dps_name,
                        self.entity_rg,
                        group_id,
                        device_id1,
                        keys["primaryKey"],
                        provisioning_host
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

            # Use id scope - compute_key should work without login; group id is not needed
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} --key {} "
                    "--ck".format(
                        self.id_scope, device_id1, keys["primaryKey"]
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

            # Recreate with computed device key (and id scope); group id is not needed for the registration
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
                    "iot device registration create --id-scope {} --registration-id {} --key {}".format(
                        self.id_scope, device_id1, device_key
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
            self.check_hub_device(device_id1, "sas", key=device_key)

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
            self.check_hub_device(device_id2, "sas")

            # Can re-register a first device within the same enrollment group using a different key
            device1_registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} --key {} --ck".format(
                        self.entity_dps_name, self.entity_rg, device_id1, keys["secondaryKey"]
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
                    "iot device registration create --dps-name {} -g {} --registration-id {} --key {}".format(
                        self.entity_dps_name, self.entity_rg, device_id1, keys["primaryKey"]
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

    def test_dps_device_registration_x509_lifecycle(self):
        device_thumbprint = self._prepare_x509_certificates_for_dps()
        hub_host_name = f"{self.entity_hub_name}.azure-devices.net"

        for auth_phase in DATAPLANE_AUTH_TYPES:
            group_id = self.generate_enrollment_names(group=True)[0]

            # Enrollment needs to be created
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--cp {} --kp {}".format(
                        self.entity_dps_name,
                        self.entity_rg,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING,
                        DEVICE_CERT_NAME + KEY_ENDING
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            # Create enrollment group
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group create --group-id {} -g {} --dps-name {} --cp {}".format(
                        group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                        ROOT_CERT_NAME + CERT_ENDING
                    ),
                    auth_type=auth_phase
                ),
            )

            # Need to specify file - cannot retrieve need info from service
            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {}".format(
                        self.entity_dps_name, self.entity_rg, DEVICE_CERT_NAME
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
                        self.entity_dps_name,
                        self.entity_rg,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --dps-name {} -g {} --registration-id {} "
                    "--kp {}".format(
                        self.entity_dps_name,
                        self.entity_rg,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + KEY_ENDING
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
                        self.entity_dps_name,
                        self.entity_rg,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING,
                        DEVICE_CERT_NAME + KEY_ENDING
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
                        self.entity_dps_name,
                        self.entity_rg,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING,
                        DEVICE_CERT_NAME + KEY_ENDING
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", DEVICE_CERT_NAME),
                    self.check("registrationState.registrationId", DEVICE_CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )
            self.check_hub_device(DEVICE_CERT_NAME, "selfSigned", thumbprint=device_thumbprint)

            # Use id scope and host
            provisioning_host = f"{self.entity_dps_name}.azure-devices-provisioning.net"
            registration = self.cmd(
                self.set_cmd_auth_type(
                    "iot device registration create --id-scope {} --registration-id {} "
                    "--cp {} --kp {} --host {}".format(
                        self.id_scope,
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING,
                        DEVICE_CERT_NAME + KEY_ENDING,
                        provisioning_host
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", DEVICE_CERT_NAME),
                    self.check("registrationState.registrationId", DEVICE_CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            ).get_output_in_json()["registrationState"]

            # Check registration from service side
            service_side = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group registration show --dps-name {} -g {} --rid {}".format(
                        self.entity_dps_name, self.entity_rg, DEVICE_CERT_NAME
                    ),
                    auth_type=auth_phase
                ),
            ).get_output_in_json()
            compare_registrations(registration, service_side)

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
                        DEVICE_CERT_NAME,
                        DEVICE_CERT_NAME + CERT_ENDING,
                        DEVICE_CERT_NAME + KEY_ENDING,
                        "{payload}"
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.exists("operationId"),
                    self.check("registrationState.assignedHub", hub_host_name),
                    self.check("registrationState.deviceId", DEVICE_CERT_NAME),
                    self.check("registrationState.registrationId", DEVICE_CERT_NAME),
                    self.check("registrationState.substatus", "initialAssignment"),
                    self.check("status", "assigned"),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment-group delete --group-id {} -g {} --dps-name {}".format(
                        group_id,
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

    def _prepare_x509_certificates_for_dps(self):
        # Create root and device certificates
        output_dir = os.getcwd()
        root_cert_obj = create_certificate(
            subject=ROOT_CERT_NAME, valid_days=1, cert_output_dir=output_dir
        )
        device_thumbprint = create_certificate(
            subject=DEVICE_CERT_NAME,
            valid_days=1,
            cert_output_dir=output_dir,
            cert_object=root_cert_obj,
            chain_cert=True
        )['thumbprint']
        for cert_name in [ROOT_CERT_NAME, DEVICE_CERT_NAME]:
            self.tracked_certs.append(cert_name + CERT_ENDING)
            self.tracked_certs.append(cert_name + KEY_ENDING)

        # Upload root certifcate and get verification code
        self.cmd(
            "iot dps certificate create --dps-name {} -g {} -n {} -p {}".format(
                self.entity_dps_name,
                self.entity_rg,
                ROOT_CERT_NAME,
                ROOT_CERT_NAME + CERT_ENDING
            )
        )

        verification_code = self.cmd(
            "iot dps certificate generate-verification-code --dps-name {} -g {} -n {} -e *".format(
                self.entity_dps_name,
                self.entity_rg,
                ROOT_CERT_NAME
            )
        ).get_output_in_json()["properties"]["verificationCode"]

        # Create verification certificate and upload
        create_certificate(
            subject=verification_code,
            valid_days=1,
            cert_output_dir=output_dir,
            cert_object=root_cert_obj,
        )
        self.tracked_certs.append(verification_code + CERT_ENDING)
        self.tracked_certs.append(verification_code + KEY_ENDING)
        self.cmd(
            "iot dps certificate verify --dps-name {} -g {} -n {} -p {} -e *".format(
                self.entity_dps_name,
                self.entity_rg,
                ROOT_CERT_NAME,
                verification_code + CERT_ENDING
            )
        )
        return device_thumbprint
