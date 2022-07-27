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


class TestDPSEnrollments(IoTDPSLiveScenarioTest):
    def __init__(self, test_method):
        super(TestDPSEnrollments, self).__init__(test_method)

    def test_dps_enrollment_tpm_lifecycle(self):
        attestation_type = AttestationType.tpm.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id = self.generate_enrollment_names()[0]
            device_id = self.generate_device_names()[0]

            enrollment = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --endorsement-key {}"
                    " --provisioning-status {} --device-id {} --initial-twin-tags {}"
                    " --initial-twin-properties {} --device-information {} "
                    "--allocation-policy {} --iot-hubs {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        TEST_ENDORSEMENT_KEY,
                        EntityStatusType.enabled.value,
                        device_id,
                        '"{generic_dict}"',
                        '"{generic_dict}"',
                        '"{generic_dict}"',
                        AllocationType.static.value,
                        self.hub_host_name,
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.enabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", AllocationType.static.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.check("initialTwin.tags", self.kwargs["generic_dict"]),
                    self.check("optionalDeviceInformation", self.kwargs["generic_dict"]),
                    self.check(
                        "initialTwin.properties.desired", self.kwargs["generic_dict"]
                    ),
                    self.exists("reprovisionPolicy"),
                    self.check("reprovisionPolicy.migrateDeviceData", True),
                    self.check("reprovisionPolicy.updateHubAssignment", True),
                ],
            ).get_output_in_json()
            etag = enrollment["etag"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment list -g {} --dps-name {}".format(
                        self.entity_rg, self.entity_dps_name
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("length(@)", 1),
                    self.check("[0].registrationId", enrollment_id),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[self.check("registrationId", enrollment_id)],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment show -g {} --dps-name {} --enrollment-id {} --show-keys".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("registrationId", enrollment_id),
                    self.check("attestation.type", attestation_type),
                    self.exists("attestation.{}".format(attestation_type)),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
                    " --provisioning-status {} --etag {} --info {}".format(
                        self.entity_rg,
                        self.entity_dps_name,
                        enrollment_id,
                        EntityStatusType.disabled.value,
                        etag,
                        '""'
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.disabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", AllocationType.static.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.exists("initialTwin.tags"),
                    self.exists("initialTwin.properties.desired"),
                    self.exists("optionalDeviceInformation"),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            )

    def test_dps_enrollment_x509_lifecycle(self):
        attestation_type = AttestationType.x509.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id = self.generate_enrollment_names()[0]
            device_id = self.generate_device_names()[0]

            etag = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --cp {} --scp {}"
                    " --provisioning-status {} --device-id {}"
                    " --initial-twin-tags {} --initial-twin-properties {}"
                    " --allocation-policy {} --iot-hubs {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        CERT_PATH,
                        CERT_PATH,
                        EntityStatusType.enabled.value,
                        device_id,
                        '"{generic_dict}"',
                        '"{generic_dict}"',
                        AllocationType.hashed.value,
                        self.hub_host_name,
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.enabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", AllocationType.hashed.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.check("initialTwin.tags", self.kwargs["generic_dict"]),
                    self.check(
                        "initialTwin.properties.desired", self.kwargs["generic_dict"]
                    ),
                    self.exists("reprovisionPolicy"),
                    self.check("reprovisionPolicy.migrateDeviceData", True),
                    self.check("reprovisionPolicy.updateHubAssignment", True),
                ],
            ).get_output_in_json()["etag"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment list -g {} --dps-name {}".format(self.entity_rg, self.entity_dps_name),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("length(@)", 1),
                    self.check("[0].registrationId", enrollment_id),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[self.check("registrationId", enrollment_id)],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
                    " --provisioning-status {} --etag {} --info {} --rc".format(
                        self.entity_rg,
                        self.entity_dps_name,
                        enrollment_id,
                        EntityStatusType.disabled.value,
                        etag,
                        '"{generic_dict}"',
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.disabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", AllocationType.hashed.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.exists("initialTwin.tags"),
                    self.exists("initialTwin.properties.desired"),
                    self.check("optionalDeviceInformation", self.kwargs["generic_dict"]),
                    self.check("attestation.type.x509.clientCertificates.primary", None),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            )

    def test_dps_enrollment_symmetrickey_lifecycle(self):
        attestation_type = AttestationType.symmetricKey.value
        for auth_phase in DATAPLANE_AUTH_TYPES:
            enrollment_id, enrollment_id2 = self.generate_enrollment_names(count=2)
            primary_key = generate_key()
            secondary_key = generate_key()
            device_id = self.generate_enrollment_names()[0]

            # Use provided keys
            etag = self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --pk {} --sk {}"
                    " --provisioning-status {} --device-id {}"
                    " --initial-twin-tags {} --initial-twin-properties {} --device-information {}"
                    " --allocation-policy {} --rp {} --iot-hubs {} --edge-enabled".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        primary_key,
                        secondary_key,
                        EntityStatusType.enabled.value,
                        device_id,
                        '"{generic_dict}"',
                        '"{generic_dict}"',
                        '"{generic_dict}"',
                        AllocationType.geolatency.value.lower(),
                        ReprovisionType.reprovisionandresetdata.value,
                        self.hub_host_name,
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.enabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", AllocationType.geolatency.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.check("initialTwin.tags", self.kwargs["generic_dict"]),
                    self.check("optionalDeviceInformation", self.kwargs["generic_dict"]),
                    self.check(
                        "initialTwin.properties.desired", self.kwargs["generic_dict"]
                    ),
                    self.exists("reprovisionPolicy"),
                    self.check("reprovisionPolicy.migrateDeviceData", False),
                    self.check("reprovisionPolicy.updateHubAssignment", True),
                    self.check("capabilities.iotEdge", True),
                ],
            ).get_output_in_json()["etag"]

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment list -g {} --dps-name {}".format(self.entity_rg, self.entity_dps_name),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("length(@)", 1),
                    self.check("[0].registrationId", enrollment_id),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
                checks=[self.check("registrationId", enrollment_id)],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
                    " --provisioning-status {} --etag {} --edge-enabled False"
                    " --allocation-policy {} --webhook-url {} --api-version {}".format(
                        self.entity_rg,
                        self.entity_dps_name,
                        enrollment_id,
                        EntityStatusType.disabled.value,
                        etag,
                        AllocationType.custom.value,
                        WEBHOOK_URL,
                        API_VERSION,
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id),
                    self.check("provisioningStatus", EntityStatusType.disabled.value),
                    self.check("deviceId", device_id),
                    self.check("allocationPolicy", "custom"),
                    self.check("customAllocationDefinition.webhookUrl", WEBHOOK_URL),
                    self.check("customAllocationDefinition.apiVersion", API_VERSION),
                    self.check("iotHubs", None),
                    self.exists("initialTwin.tags"),
                    self.exists("initialTwin.properties.desired"),
                    self.check("attestation.symmetricKey.primaryKey", primary_key),
                    self.check("capabilities.iotEdge", False),
                ],
            )

            # Use service generated keys
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --allocation-policy {} --webhook-url {} --api-version {}".format(
                        enrollment_id2,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        AllocationType.custom.value,
                        WEBHOOK_URL,
                        API_VERSION,
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("attestation.type", attestation_type),
                    self.check("registrationId", enrollment_id2),
                    self.check("allocationPolicy", "custom"),
                    self.check("customAllocationDefinition.webhookUrl", WEBHOOK_URL),
                    self.check("customAllocationDefinition.apiVersion", API_VERSION),
                ],
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            )
            self.cmd(
                self.set_cmd_auth_type(
                    "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id2
                    ),
                    auth_type=auth_phase
                ),
            )
