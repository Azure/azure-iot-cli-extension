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
    TEST_ENDORSEMENT_KEY
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

def test_dps_enrollment_tpm_lifecycle(provisioned_iot_dps_module):
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

    attestation_type = AttestationType.tpm.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()[0]
        device_id = generate_names()[0]

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} "
                f"--endorsement-key {TEST_ENDORSEMENT_KEY} --provisioning-status {EntityStatusType.enabled.value} --device-id {device_id} --initial-twin-tags \"{generic_dict}\" --initial-twin-properties \"{generic_dict}\" --device-information \"{generic_dict}\" --allocation-policy {AllocationType.static.value} --iot-hubs {hub_hostname}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()

        assert enrollment["attestation"]["type"] == attestation_type
        assert enrollment["registrationId"] == enrollment_id
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["deviceId"] == device_id
        assert enrollment["allocationPolicy"] == AllocationType.static.value
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["tags"] == generic_dict
        assert enrollment["optionalDeviceInformation"] == generic_dict
        assert enrollment["initialTwin"]["properties"]["desired"] == generic_dict
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] == True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] == True

        etag = enrollment["etag"]

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["registrationId"] for e in enrollment_list]

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_show["registrationId"] == enrollment_id
        assert enrollment_show["attestation"]["type"] == attestation_type
        assert enrollment_show["attestation"][attestation_type]

        update_enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} "
                f"--provisioning-status {EntityStatusType.disabled.value} --etag {etag} --info \"\"",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()

        assert update_enrollment["attestation"]["type"] == attestation_type
        assert update_enrollment["registrationId"] == enrollment_id
        assert update_enrollment["provisioningStatus"] == EntityStatusType.disabled.value
        assert update_enrollment["deviceId"] == device_id
        assert update_enrollment["allocationPolicy"] == AllocationType.static.value
        assert update_enrollment["iotHubs"] == [hub_hostname]
        assert update_enrollment["initialTwin"]["tags"]
        assert update_enrollment["optionalDeviceInformation"]
        assert update_enrollment["initialTwin"]["properties"]["desired"]

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        )

def test_dps_enrollment_x509_lifecycle(provisioned_iot_dps_module):
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
    attestation_type = AttestationType.x509.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()[0]
        device_id = generate_names()[0]

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --cp {cert_path} --scp {cert_path}"
                f" --provisioning-status {EntityStatusType.enabled.value} --device-id {device_id}"
                f" --initial-twin-tags \"{generic_dict}\" --initial-twin-properties \"{generic_dict}\" "
                f" --allocation-policy {AllocationType.hashed.value} --iot-hubs {hub_hostname}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        ).as_json()

        etag = enrollment["etag"]

        assert enrollment["attestation"]["type"] == attestation_type
        assert enrollment["registrationId"] == enrollment_id
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["deviceId"] == device_id
        assert enrollment["allocationPolicy"] == AllocationType.hashed.value
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["tags"] == generic_dict
        assert enrollment["initialTwin"]["properties"]["desired"] == generic_dict
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] == True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] == True

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["registrationId"] for e in enrollment_list]

        show_enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert show_enrollment["registrationId"] == enrollment_id

        update_enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}"
                f" --provisioning-status {EntityStatusType.disabled.value} --etag {etag} --info \"{generic_dict}\" --rc",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        ).as_json()

        assert update_enrollment["attestation"]["type"] == attestation_type
        assert update_enrollment["registrationId"] == enrollment_id
        assert update_enrollment["provisioningStatus"] == EntityStatusType.disabled.value
        assert update_enrollment["deviceId"] == device_id
        assert update_enrollment["allocationPolicy"] == AllocationType.hashed.value
        assert update_enrollment["iotHubs"] == [hub_hostname]
        assert update_enrollment["initialTwin"]["tags"]
        assert update_enrollment["initialTwin"]["properties"]["desired"]
        assert update_enrollment["optionalDeviceInformation"] == generic_dict
        assert update_enrollment["attestation"]["x509"]["clientCertificates"]["primary"] is None

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        )

def test_dps_enrollment_symmetrickey_lifecycle(provisioned_iot_dps_module):
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

    attestation_type = AttestationType.symmetricKey.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id, enrollment_id2 = generate_names(count=2)
        primary_key = generate_key()
        secondary_key = generate_key()
        device_id = generate_names()[0]

        # Use provided keys
        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --pk {primary_key} --sk {secondary_key}"
                f" --provisioning-status {EntityStatusType.enabled.value} --device-id {device_id}"
                f" --initial-twin-tags \"{generic_dict}\" --initial-twin-properties \"{generic_dict}\" --device-information \"{generic_dict}\""
                f" --allocation-policy {AllocationType.geolatency.value.lower()} --rp {ReprovisionType.reprovisionandresetdata.value} --iot-hubs {hub_hostname} --edge-enabled",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()

        etag = enrollment["etag"]

        assert enrollment["attestation"]["type"] == attestation_type
        assert enrollment["registrationId"] == enrollment_id
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["deviceId"] == device_id
        assert enrollment["allocationPolicy"] == AllocationType.geolatency.value
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["tags"] == generic_dict
        assert enrollment["optionalDeviceInformation"] == generic_dict
        assert enrollment["initialTwin"]["properties"]["desired"] == generic_dict
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] == False
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] == True
        assert enrollment["capabilities"]["iotEdge"] == True

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["registrationId"] for e in enrollment_list]

        show_enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()
        assert show_enrollment["registrationId"] == enrollment_id

        update_enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}"
                f" --provisioning-status {EntityStatusType.disabled.value} --etag {etag} --edge-enabled False"
                f" --allocation-policy {AllocationType.custom.value} --webhook-url {WEBHOOK_URL} --api-version {API_VERSION}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        ).as_json()

        assert update_enrollment["attestation"]["type"] == attestation_type
        assert update_enrollment["registrationId"] == enrollment_id
        assert update_enrollment["provisioningStatus"] == EntityStatusType.disabled.value
        assert update_enrollment["deviceId"] == device_id
        assert update_enrollment["allocationPolicy"] == AllocationType.custom.value
        assert update_enrollment["customAllocationDefinition"]["webhookUrl"] == WEBHOOK_URL
        assert update_enrollment["customAllocationDefinition"]["apiVersion"] == API_VERSION
        assert update_enrollment["iotHubs"] == None
        assert update_enrollment["initialTwin"]["tags"]
        assert update_enrollment["initialTwin"]["properties"]["desired"]
        assert update_enrollment["optionalDeviceInformation"] == generic_dict
        assert update_enrollment["capabilities"]["iotEdge"] == False

        # Use service generated keys
        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id2} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --allocation-policy {AllocationType.custom.value} --webhook-url {WEBHOOK_URL} --api-version {API_VERSION}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            )
        ).as_json()

        assert enrollment["attestation"]["type"] == attestation_type
        assert enrollment["registrationId"] == enrollment_id2
        assert enrollment["allocationPolicy"] == AllocationType.custom.value
        assert enrollment["customAllocationDefinition"]["webhookUrl"] == WEBHOOK_URL
        assert enrollment["customAllocationDefinition"]["apiVersion"] == API_VERSION

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        )
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2}",
                auth_type=auth_phase,
                dps_cstring=dps_cstring
            ),
        )

