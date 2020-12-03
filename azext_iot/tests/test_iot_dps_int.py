# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.shared import EntityStatusType, AttestationType, AllocationType
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.common import embedded_cli
from azext_iot.common.utility import generate_key
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from .settings import Setting

# Set these to the proper IoT Hub DPS, IoT Hub and Resource Group for Integration Tests.
dps = os.environ.get("azext_iot_testdps")
rg = os.environ.get("azext_iot_testrg")
hub = os.environ.get("azext_iot_testhub")

if not all([dps, rg, hub]):
    raise ValueError(
        "Set azext_iot_testhub, azext_iot_testdps "
        "and azext_iot_testrg to run integration tests."
    )

cert_name = "test"
cert_path = cert_name + "-cert.pem"
test_endorsement_key = (
    "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1Q"
    "QsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3"
    "CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRI"
    "Dj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzB"
    "QQ1NpOJVhrsTrhyJzO7KNw=="
)
provisioning_status = EntityStatusType.enabled.value
provisioning_status_new = EntityStatusType.disabled.value


def _cleanup_enrollments(self, dps, rg):
    enrollments = self.cmd(
        "iot dps enrollment list --dps-name {} -g  {}".format(dps, rg)
    ).get_output_in_json()
    if len(enrollments) > 0:
        enrollment_ids = list(map(lambda x: x["registrationId"], enrollments))
        for id in enrollment_ids:
            self.cmd(
                "iot dps enrollment delete --dps-name {} -g {} --enrollment-id {}".format(
                    dps, rg, id
                )
            )

    enrollment_groups = self.cmd(
        "iot dps enrollment-group list --dps-name {} -g  {}".format(dps, rg)
    ).get_output_in_json()
    if len(enrollment_groups) > 0:
        enrollment_ids = list(map(lambda x: x["enrollmentGroupId"], enrollment_groups))
        for id in enrollment_ids:
            self.cmd(
                "iot dps enrollment-group delete --dps-name {} -g {} --enrollment-id {}".format(
                    dps, rg, id
                )
            )

    self.cmd(
        "iot dps enrollment list --dps-name {} -g  {}".format(dps, rg),
        checks=self.is_empty(),
    )
    self.cmd(
        "iot dps enrollment-group list --dps-name {} -g  {}".format(dps, rg),
        checks=self.is_empty(),
    )


def _ensure_dps_hub_link(self, dps, rg, hub):
    cli = embedded_cli.EmbeddedCLI()
    hubs = cli.invoke(
        "iot dps linked-hub list --dps-name {} -g {}".format(dps, rg)
    ).as_json()
    if not len(hubs) or not len(
        list(
            filter(
                lambda linked_hub: linked_hub["name"]
                == "{}.azure-devices.net".format(hub),
                hubs,
            )
        )
    ):
        discovery = IotHubDiscovery(self.cmd_shell)
        target_hub = discovery.get_target(hub, rg)
        cli.invoke(
            "iot dps linked-hub create --dps-name {} -g {} --connection-string {} --location {}".format(
                dps, rg, target_hub.get("cs"), target_hub.get("location")
            )
        )


class TestDPSEnrollments(LiveScenarioTest):
    def __init__(self, test_method):
        super(TestDPSEnrollments, self).__init__(test_method)
        self.cmd_shell = Setting()
        setattr(self.cmd_shell, "cli_ctx", self.cli_ctx)

        _ensure_dps_hub_link(self, dps, rg, hub)

        output_dir = os.getcwd()
        create_self_signed_certificate(cert_name, 200, output_dir, True)
        self.kwargs["generic_dict"] = {
            "count": None,
            "key": "value",
            "metadata": None,
            "version": None,
        }

        _cleanup_enrollments(self, dps, rg)

    def __del__(self):
        if os.path.exists(cert_path):
            os.remove(cert_path)

    def test_dps_compute_device_key(self):
        device_key = self.cmd(
            'az iot dps compute-device-key --key "{}" '
            "--registration-id myarbitrarydeviceId".format(test_endorsement_key)
        ).output
        device_key = device_key.strip("\"'\n")
        assert device_key == "cT/EXZvsplPEpT//p98Pc6sKh8mY3kYgSxavHwMkl7w="

    def test_dps_enrollment_tpm_lifecycle(self):
        enrollment_id = self.create_random_name("enrollment-for-test", length=48)
        device_id = self.create_random_name("device-id-for-test", length=48)
        attestation_type = AttestationType.tpm.value
        hub_host_name = "{}.azure-devices.net".format(hub)

        enrollment = self.cmd(
            "iot dps enrollment create --enrollment-id {} --attestation-type {}"
            " -g {} --dps-name {} --endorsement-key {}"
            " --provisioning-status {} --device-id {} --initial-twin-tags {}"
            " --initial-twin-properties {} --allocation-policy {} --iot-hubs {}".format(
                enrollment_id,
                attestation_type,
                rg,
                dps,
                test_endorsement_key,
                provisioning_status,
                device_id,
                '"{generic_dict}"',
                '"{generic_dict}"',
                AllocationType.static.value,
                hub_host_name,
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", AllocationType.static.value),
                self.check("iotHubs", hub_host_name.split()),
                self.check("initialTwin.tags", self.kwargs["generic_dict"]),
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
            "iot dps enrollment list -g {} --dps-name {}".format(rg, dps),
            checks=[
                self.check("length(@)", 1),
                self.check("[0].registrationId", enrollment_id),
            ],
        )

        self.cmd(
            "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            ),
            checks=[self.check("registrationId", enrollment_id)],
        )

        self.cmd(
            "iot dps enrollment show -g {} --dps-name {} --enrollment-id {} --show-keys".format(
                rg, dps, enrollment_id
            ),
            checks=[
                self.check("registrationId", enrollment_id),
                self.check("attestation.type", attestation_type),
                self.exists("attestation.{}".format(attestation_type)),
            ],
        )

        self.cmd(
            "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
            " --provisioning-status {} --etag {}".format(
                rg, dps, enrollment_id, provisioning_status_new, etag
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status_new),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", AllocationType.static.value),
                self.check("iotHubs", hub_host_name.split()),
                self.exists("initialTwin.tags"),
                self.exists("initialTwin.properties.desired"),
            ],
        )

        self.cmd(
            "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            )
        )

    def test_dps_enrollment_x509_lifecycle(self):
        enrollment_id = self.create_random_name("enrollment-for-test", length=48)
        attestation_type = AttestationType.x509.value
        device_id = self.create_random_name("device-id-for-test", length=48)
        hub_host_name = "{}.azure-devices.net".format(hub)

        etag = self.cmd(
            "iot dps enrollment create --enrollment-id {} --attestation-type {}"
            " -g {} --dps-name {} --cp {} --scp {}"
            " --provisioning-status {} --device-id {}"
            " --initial-twin-tags {} --initial-twin-properties {}"
            " --allocation-policy {} --iot-hubs {}".format(
                enrollment_id,
                attestation_type,
                rg,
                dps,
                cert_path,
                cert_path,
                provisioning_status,
                device_id,
                '"{generic_dict}"',
                '"{generic_dict}"',
                AllocationType.hashed.value,
                hub_host_name,
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", AllocationType.hashed.value),
                self.check("iotHubs", hub_host_name.split()),
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
            "iot dps enrollment list -g {} --dps-name {}".format(rg, dps),
            checks=[
                self.check("length(@)", 1),
                self.check("[0].registrationId", enrollment_id),
            ],
        )

        self.cmd(
            "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            ),
            checks=[self.check("registrationId", enrollment_id)],
        )

        self.cmd(
            "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
            " --provisioning-status {} --etag {} --rc".format(
                rg, dps, enrollment_id, provisioning_status_new, etag
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status_new),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", AllocationType.hashed.value),
                self.check("iotHubs", hub_host_name.split()),
                self.exists("initialTwin.tags"),
                self.exists("initialTwin.properties.desired"),
                self.check("attestation.type.x509.clientCertificates.primary", None),
            ],
        )

        self.cmd(
            "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            )
        )

    def test_dps_enrollment_symmetrickey_lifecycle(self):
        enrollment_id = self.create_random_name("enrollment-for-test", length=48)
        enrollment_id2 = self.create_random_name("enrollment-for-test", length=48)
        attestation_type = AttestationType.symmetricKey.value
        primary_key = generate_key()
        secondary_key = generate_key()
        device_id = self.create_random_name("device-id-for-test", length=48)
        reprovisionPolicy_reprovisionandresetdata = "reprovisionandresetdata"
        hub_host_name = "{}.azure-devices.net".format(hub)
        webhook_url = "https://www.test.test"
        api_version = "2019-03-31"

        etag = self.cmd(
            "iot dps enrollment create --enrollment-id {} --attestation-type {}"
            " -g {} --dps-name {} --pk {} --sk {}"
            " --provisioning-status {} --device-id {}"
            " --initial-twin-tags {} --initial-twin-properties {}"
            " --allocation-policy {} --rp {} --iot-hubs {} --edge-enabled".format(
                enrollment_id,
                attestation_type,
                rg,
                dps,
                primary_key,
                secondary_key,
                provisioning_status,
                device_id,
                '"{generic_dict}"',
                '"{generic_dict}"',
                AllocationType.geolatency.value,
                reprovisionPolicy_reprovisionandresetdata,
                hub_host_name,
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", "geoLatency"),
                # self.check("iotHubs", hub_host_name.split()),
                self.check("initialTwin.tags", self.kwargs["generic_dict"]),
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
            "iot dps enrollment list -g {} --dps-name {}".format(rg, dps),
            checks=[
                self.check("length(@)", 1),
                self.check("[0].registrationId", enrollment_id),
            ],
        )

        self.cmd(
            "iot dps enrollment show -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            ),
            checks=[self.check("registrationId", enrollment_id)],
        )

        self.cmd(
            "iot dps enrollment update -g {} --dps-name {} --enrollment-id {}"
            " --provisioning-status {} --etag {} --edge-enabled False"
            " --allocation-policy {} --webhook-url {} --api-version {}".format(
                rg,
                dps,
                enrollment_id,
                provisioning_status_new,
                etag,
                AllocationType.custom.value,
                webhook_url,
                api_version,
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id),
                self.check("provisioningStatus", provisioning_status_new),
                self.check("deviceId", device_id),
                self.check("allocationPolicy", "custom"),
                self.check("customAllocationDefinition.webhookUrl", webhook_url),
                self.check("customAllocationDefinition.apiVersion", api_version),
                # self.check("iotHubs", hub_host_name.split()),
                self.exists("initialTwin.tags"),
                self.exists("initialTwin.properties.desired"),
                self.check("attestation.symmetricKey.primaryKey", primary_key),
                self.check("capabilities.iotEdge", False),
            ],
        )

        self.cmd(
            "iot dps enrollment create --enrollment-id {} --attestation-type {}"
            " -g {} --dps-name {} --allocation-policy {} --webhook-url {} --api-version {}".format(
                enrollment_id2,
                attestation_type,
                rg,
                dps,
                AllocationType.custom.value,
                webhook_url,
                api_version,
            ),
            checks=[
                self.check("attestation.type", attestation_type),
                self.check("registrationId", enrollment_id2),
                self.check("allocationPolicy", "custom"),
                self.check("customAllocationDefinition.webhookUrl", webhook_url),
                self.check("customAllocationDefinition.apiVersion", api_version),
            ],
        )

        self.cmd(
            "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            )
        )
        self.cmd(
            "iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id2
            )
        )

    def test_dps_enrollment_group_lifecycle(self):
        enrollment_id = self.create_random_name("enrollment-for-test", length=48)
        reprovisionPolicy_never = "never"
        hub_host_name = "{}.azure-devices.net".format(hub)
        webhook_url = "https://www.test.test"
        api_version = "2019-03-31"
        etag = self.cmd(
            "iot dps enrollment-group create --enrollment-id {} -g {} --dps-name {}"
            " --cp {} --scp {} --provisioning-status {} --allocation-policy {}"
            " --iot-hubs {} --edge-enabled".format(
                enrollment_id,
                rg,
                dps,
                cert_path,
                cert_path,
                provisioning_status,
                "geoLatency",
                hub_host_name,
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id),
                self.check("provisioningStatus", provisioning_status),
                self.exists("reprovisionPolicy"),
                self.check("allocationPolicy", "geoLatency"),
                self.check("iotHubs", hub_host_name.split()),
                self.check("reprovisionPolicy.migrateDeviceData", True),
                self.check("reprovisionPolicy.updateHubAssignment", True),
                self.check("capabilities.iotEdge", True),
            ],
        ).get_output_in_json()["etag"]

        self.cmd(
            "iot dps enrollment-group list -g {} --dps-name {}".format(rg, dps),
            checks=[
                self.check("length(@)", 1),
                self.check("[0].enrollmentGroupId", enrollment_id),
            ],
        )

        self.cmd(
            "iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            ),
            checks=[self.check("enrollmentGroupId", enrollment_id)],
        )

        self.cmd(
            "iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {} --show-keys".format(
                rg, dps, enrollment_id
            ),
            checks=[
                self.check("enrollmentGroupId", enrollment_id),
                self.exists("attestation.x509"),
            ],
        )

        etag = self.cmd(
            "iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}"
            " --provisioning-status {} --rsc --etag {} --rp {} --allocation-policy {}"
            " --edge-enabled False --scp {}".format(
                rg,
                dps,
                enrollment_id,
                provisioning_status_new,
                etag,
                reprovisionPolicy_never,
                AllocationType.hashed.value,
                cert_path,
            ),
            checks=[
                self.check("attestation.type", AttestationType.x509.value),
                self.check("enrollmentGroupId", enrollment_id),
                self.check("provisioningStatus", provisioning_status_new),
                self.check("attestation.type.x509.clientCertificates.secondary", None),
                self.exists("reprovisionPolicy"),
                self.check("allocationPolicy", AllocationType.hashed.value),
                self.check("reprovisionPolicy.migrateDeviceData", False),
                self.check("reprovisionPolicy.updateHubAssignment", False),
                self.check("capabilities.iotEdge", False),
            ],
        ).get_output_in_json()["etag"]

        self.cmd(
            "iot dps registration list -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            ),
            checks=[self.check("length(@)", 0)],
        )

        cert_name = self.create_random_name("certificate-for-test", length=48)
        cert_etag = self.cmd(
            "iot dps certificate create -g {} --dps-name {} --name {} --p {}".format(
                rg, dps, cert_name, cert_path
            ),
            checks=[self.check("name", cert_name)],
        ).get_output_in_json()["etag"]

        self.cmd(
            "iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}"
            " --cn {} --etag {} --allocation-policy {} --webhook-url {} --api-version {}".format(
                rg,
                dps,
                enrollment_id,
                cert_name,
                etag,
                AllocationType.custom.value,
                webhook_url,
                api_version,
            ),
            checks=[
                self.check("attestation.type", AttestationType.x509.value),
                self.check("enrollmentGroupId", enrollment_id),
                self.check("allocationPolicy", "custom"),
                self.check("customAllocationDefinition.webhookUrl", webhook_url),
                self.check("customAllocationDefinition.apiVersion", api_version),
                self.check("attestation.x509.caReferences.primary", cert_name),
                self.check("attestation.x509.caReferences.secondary", None),
            ],
        )

        self.cmd(
            "iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}".format(
                rg, dps, enrollment_id
            )
        )

        self.cmd(
            "iot dps certificate delete -g {} --dps-name {} --name {} --etag {}".format(
                rg, dps, cert_name, cert_etag
            )
        )
