# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import EntityStatusType, AttestationType, AllocationType, ReprovisionType
from azext_iot.common.utility import generate_key
from azext_iot.tests.dps import (
    API_VERSION,
    CERT_NAME,
    DATAPLANE_AUTH_TYPES,
    WEBHOOK_URL,
)
from azext_iot.tests.helpers import CERT_ENDING, KEY_ENDING
from azext_iot.tests.generators import generate_generic_id

cli = EmbeddedCLI()

def generate_names(count=1):
    return [generate_generic_id()[:48] for _ in range(count)]


def create_test_cert(tracked_certs, subject=CERT_NAME, cert_only=True, file_prefix=None):
    output_dir = os.getcwd()
    thumbprint = create_self_signed_certificate(
        subject=subject,
        valid_days=1,
        cert_output_dir=output_dir,
        cert_only=cert_only,
        file_prefix=file_prefix,
        sha_version=256,
    )["thumbprint"]
    tracked_certs.append(subject + CERT_ENDING)
    if not cert_only:
        tracked_certs.append(subject + KEY_ENDING)
    return thumbprint


def set_cmd_auth_type(command: str, auth_type: str, dps_cstring: str) -> str:
    if auth_type not in DATAPLANE_AUTH_TYPES:
        raise RuntimeError(f"auth_type of: {auth_type} is unsupported.")

    # cstring takes precedence
    if auth_type == "cstring":
        return f"{command} --login {dps_cstring}"

    return f"{command} --auth-type {auth_type}"


def test_dps_enrollment_group_x509_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring=provisioned_iot_dps_module["connectionString"]

    generic_dict = {
        generate_generic_id(): generate_generic_id(),
        "key": "value",
        "count": None,
        "metadata": None,
        "version": None,
    }

    cert_name = generate_names()[0]
    cert_path = cert_name + CERT_ENDING
    create_test_cert(tracked_certs=provisioned_iot_dps_module["certificates"], subject=cert_name)
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()[0]

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --enrollment-id {enrollment_id} -g {dps_rg} --dps-name {dps_name}"
                f" --cp {cert_path} --scp {cert_path} --provisioning-status {EntityStatusType.enabled.value} --allocation-policy {AllocationType.geolatency.value}"
                f" --iot-hubs {hub_hostname} --edge-enabled",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()

        etag = enrollment["etag"]
        assert enrollment["enrollmentGroupId"] == enrollment_id
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] == True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] == True
        assert enrollment["allocationPolicy"] == AllocationType.geolatency.value
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["capabilities"]["iotEdge"] == True

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list]

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_show["enrollmentGroupId"] == enrollment_id

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} --show-keys",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_show["enrollmentGroupId"] == enrollment_id
        assert enrollment_show["attestation"]["x509"]

        # Compute Device Key only works for symmetric key enrollment groups
        failure_command = cli.invoke(
            set_cmd_auth_type(
                f"az iot dps enrollment-group compute-device-key -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} "
                "--registration-id myarbitrarydeviceId",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        )
        assert failure_command.success() == False

        etag = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group update  -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}"
                " --provisioning-status {EntityStatusType.disabled.value} --rsc --etag {etag} --rp {ReprovisionType.never.value} --allocation-policy {AllocationType.hashed.value}"
                " --edge-enabled False --scp {cert_path}".format(
                    self.entity_rg,
                    self.entity_dps_name,
                    enrollment_id,
                    EntityStatusType.disabled.value,
                    etag,
                    ReprovisionType.never.value,
                    AllocationType.hashed.value,
                    cert_path,
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("attestation.type", AttestationType.x509.value),
                self.check("enrollmentGroupId", enrollment_id),
                self.check("provisioningStatus", EntityStatusType.disabled.value),
                self.check("attestation.type.x509.clientCertificates.secondary", None),
                self.exists("reprovisionPolicy"),
                self.check("allocationPolicy", AllocationType.hashed.value),
                self.check("reprovisionPolicy.migrateDeviceData", False),
                self.check("reprovisionPolicy.updateHubAssignment", False),
                self.check("capabilities.iotEdge", False),
            ],
        ).as_json()["etag"]

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group registration list -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id
                ),
                auth_type=auth_phase
            ),
            checks=[self.check("length(@)", 0)],
        )

        cert_name = self.create_random_name("certificate-for-test", length=48)
        cert_etag = cli.invoke(
            "iot dps certificate create -g {} --dps-name {} --name {} --p {}".format(
                self.entity_rg, self.entity_dps_name, cert_name, cert_path
            ),
            checks=[self.check("name", cert_name)],
        ).as_json()["etag"]

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}"
                " --cn {} --etag {} --allocation-policy {} --webhook-url {} --api-version {}".format(
                    self.entity_rg,
                    self.entity_dps_name,
                    enrollment_id,
                    cert_name,
                    etag,
                    AllocationType.custom.value,
                    WEBHOOK_URL,
                    API_VERSION,
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("attestation.type", AttestationType.x509.value),
                self.check("enrollmentGroupId", enrollment_id),
                self.check("allocationPolicy", "custom"),
                self.check("customAllocationDefinition.webhookUrl", WEBHOOK_URL),
                self.check("customAllocationDefinition.apiVersion", API_VERSION),
                self.check("attestation.x509.caReferences.primary", cert_name),
                self.check("attestation.x509.caReferences.secondary", None),
            ],
        )

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id
                ),
                auth_type=auth_phase
            ),
        )

        cli.invoke(
            "iot dps certificate delete -g {} --dps-name {} --name {} --etag {}".format(
                self.entity_rg, self.entity_dps_name, cert_name, cert_etag
            ),
        )

def test_dps_enrollment_group_symmetrickey_lifecycle(self):
    attestation_type = AttestationType.symmetricKey.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id, enrollment_id2 = self.generate_enrollment_names(count=2, group=True)
        primary_key = generate_key()
        secondary_key = generate_key()

        etag = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group create --enrollment-id {}"
                " -g {} --dps-name {} --pk {} --sk {} --provisioning-status {}"
                " --initial-twin-tags {} --initial-twin-properties {}"
                " --allocation-policy {} --rp {} --iot-hubs {} --edge-enabled".format(
                    enrollment_id,
                    self.entity_rg,
                    self.entity_dps_name,
                    primary_key,
                    secondary_key,
                    EntityStatusType.enabled.value,
                    '"{generic_dict}"',
                    '"{generic_dict}"',
                    AllocationType.geolatency.value,
                    ReprovisionType.reprovisionandresetdata.value,
                    self.hub_host_name,
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id),
                self.check("provisioningStatus", EntityStatusType.enabled.value),
                self.check("allocationPolicy", AllocationType.geolatency.value),
                self.check("iotHubs", self.hub_host_name.split()),
                self.check("initialTwin.tags", self.kwargs["generic_dict"]),
                self.check(
                    "initialTwin.properties.desired", self.kwargs["generic_dict"]
                ),
                self.exists("reprovisionPolicy"),
                self.check("reprovisionPolicy.migrateDeviceData", False),
                self.check("reprovisionPolicy.updateHubAssignment", True),
                self.check("capabilities.iotEdge", True),
            ],
        ).as_json()["etag"]

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group list -g {} --dps-name {}".format(self.entity_rg, self.entity_dps_name),
                auth_type=auth_phase
            ),
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list]

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id
                ),
                auth_type=auth_phase
            ),
            checks=[self.check("enrollmentGroupId", enrollment_id)],
        )

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}"
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
                self.check("enrollmentGroupId", enrollment_id),
                self.check("provisioningStatus", EntityStatusType.disabled.value),
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
        etag = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group create -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id2),
                self.check("attestation.type", attestation_type),
            ],
        ).as_json()["etag"]

        enrollment_list2 = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group list -g {} --dps-name {}".format(self.entity_rg, self.entity_dps_name),
                auth_type=auth_phase
            )
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list2]
        assert enrollment_id2 in [e["enrollmentGroupId"] for e in enrollment_list2]

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
            checks=[self.check("enrollmentGroupId", enrollment_id2)],
        )

        keys = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {} --show-keys".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id2),
                self.exists("attestation.symmetricKey"),
            ],
        ).as_json()["attestation"]["symmetricKey"]

        # Compute Device Key tests
        online_device_key = cli.invoke(
            set_cmd_auth_type(
                'az iot dps enrollment-group compute-device-key -g {} --dps-name {} --enrollment-id {} '
                "--registration-id myarbitrarydeviceId".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
        ).output

        offline_device_key = cli.invoke(
            'az iot dps enrollment-group compute-device-key --key "{}" '
            "--registration-id myarbitrarydeviceId".format(keys["primaryKey"])
        ).output
        assert offline_device_key == online_device_key

        # Compute Device Key uses primary key
        offline_device_key = cli.invoke(
            'az iot dps enrollment-group compute-device-key --key "{}" '
            "--registration-id myarbitrarydeviceId".format(keys["secondaryKey"])
        ).output
        assert offline_device_key != online_device_key

        etag = cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}"
                " --pk {} --sk {} --etag {}".format(
                    self.entity_rg,
                    self.entity_dps_name,
                    enrollment_id2,
                    keys["secondaryKey"],
                    keys["primaryKey"],
                    etag
                ),
                auth_type=auth_phase
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id2),
                self.check("attestation.type", attestation_type),
            ],
        ).as_json()["etag"]

        online_device_key = cli.invoke(
            set_cmd_auth_type(
                'az iot dps enrollment-group compute-device-key -g {} --dps-name {} --enrollment-id {} '
                "--registration-id myarbitrarydeviceId".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
        ).output
        assert offline_device_key == online_device_key

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id2
                ),
                auth_type=auth_phase
            ),
        )

        cli.invoke(
            set_cmd_auth_type(
                "iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}".format(
                    self.entity_rg, self.entity_dps_name, enrollment_id
                ),
                auth_type=auth_phase
            ),
        )

def test_dps_enrollment_twin_array(self):
        attestation_type = AttestationType.x509.value
        cert_name = self.generate_device_names()[0]
        cert_path = cert_name + CERT_ENDING
        self.create_test_cert(subject=cert_name)
        for auth_phase in DATAPLANE_AUTH_TYPES:
            # test twin array in enrollment
            device_id = self.generate_device_names()[0]
            enrollment_id = self.generate_enrollment_names()[0]

            cli.invoke(
                set_cmd_auth_type(
                    "iot dps enrollment create --enrollment-id {} --attestation-type {}"
                    " -g {} --dps-name {} --cp {} --scp {}"
                    " --provisioning-status {} --device-id {}"
                    " --initial-twin-tags {} --initial-twin-properties {} --device-information {}"
                    " --allocation-policy {} --iot-hubs {}".format(
                        enrollment_id,
                        attestation_type,
                        self.entity_rg,
                        self.entity_dps_name,
                        cert_path,
                        cert_path,
                        EntityStatusType.enabled.value,
                        device_id,
                        '"{generic_dict}"',
                        '"{twin_array_dict}"',
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
                    self.check("optionalDeviceInformation", self.kwargs["generic_dict"]),
                    self.check(
                        "initialTwin.properties.desired", self.kwargs["twin_array_dict"]
                    ),
                    self.exists("reprovisionPolicy"),
                    self.check("reprovisionPolicy.migrateDeviceData", True),
                    self.check("reprovisionPolicy.updateHubAssignment", True),
                ],
            )

            cli.invoke(
                set_cmd_auth_type(
                    "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_id
                    ),
                    auth_type=auth_phase
                ),
            )

            # test twin array in enrollment group
            enrollment_group_id = self.generate_enrollment_names(group=True)[0]

            cli.invoke(
                set_cmd_auth_type(
                    "iot dps enrollment-group create --enrollment-id {} -g {} --dps-name {}"
                    " --cp {} --scp {} --provisioning-status {} --allocation-policy {}"
                    " --iot-hubs {} --edge-enabled --props {}".format(
                        enrollment_group_id,
                        self.entity_rg,
                        self.entity_dps_name,
                        cert_path,
                        cert_path,
                        EntityStatusType.enabled.value,
                        AllocationType.geolatency.value,
                        self.hub_host_name,
                        '"{twin_array_dict}"',
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("enrollmentGroupId", enrollment_group_id),
                    self.check("provisioningStatus", EntityStatusType.enabled.value),
                    self.exists("reprovisionPolicy"),
                    self.check("allocationPolicy", AllocationType.geolatency.value),
                    self.check("iotHubs", self.hub_host_name.split()),
                    self.check(
                        "initialTwin.properties.desired", self.kwargs["twin_array_dict"]
                    ),
                    self.check("reprovisionPolicy.migrateDeviceData", True),
                    self.check("reprovisionPolicy.updateHubAssignment", True),
                    self.check("capabilities.iotEdge", True),
                ],
            )

            cli.invoke(
                set_cmd_auth_type(
                    "iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}".format(
                        self.entity_rg, self.entity_dps_name, enrollment_group_id
                    ),
                    auth_type=auth_phase
                ),
            )
