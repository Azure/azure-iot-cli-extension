# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import EntityStatusType
from azext_iot.tests.dps import DATAPLANE_AUTH_TYPES
from azext_iot.tests.dps.device_registration import check_hub_device, compare_registrations
from azext_iot.tests.generators import generate_generic_id, generate_names
from azext_iot.tests.helpers import CERT_ENDING, KEY_ENDING, set_cmd_auth_type
from azext_iot.tests.test_utils import create_certificate

cli = EmbeddedCLI()


def test_dps_device_registration_symmetrickey_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    hub_cstring = provisioned_iot_dps_module["hubConnectionString"]
    id_scope = provisioned_iot_dps_module["dps"]["properties"]["idScope"]

    for auth_phase in DATAPLANE_AUTH_TYPES:
        group_id, device_id1, device_id2 = generate_names(count=3)

        # Enrollment needs to be created
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id1}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        assert registration_result.success() is False

        # Regular enrollment group
        keys = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --group-id {group_id} --dps-name {dps_name} -g {dps_rg}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()["attestation"]["symmetricKey"]

        # Defaults to group primary key
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id1}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id1, "sas", hub_cstring)

        # Recreate with group primary key, and use different provisioning host
        provisioning_host = f"{dps_name}.azure-devices-provisioning.net"
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id1} --key {keys['primaryKey']} "
                f"--ck --host {provisioning_host}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Use id scope - compute_key should work without login; group id is not needed
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {device_id1} --key {keys['primaryKey']} "
                "--ck",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Recreate with computed device key (and id scope); group id is not needed for the registration
        device_key = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group compute-device-key --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id1}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {device_id1} --key {device_key}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id1, "sas", hub_cstring, key=device_key)

        # Can register a second device within the same enrollment group
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id2}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        device2_registration = registration["registrationState"]
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id2
        assert registration["registrationState"]["registrationId"] == device_id2
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id2, "sas", hub_cstring)

        # Can re-register a first device within the same enrollment group using a different key
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {device_id1} "
                f"--key {keys['secondaryKey']} --ck",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        device1_registration = registration["registrationState"]
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Check for both registration from service side
        service_side_registrations = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group registration list --dps-name {dps_name} -g {dps_rg} --group-id {group_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert len(service_side_registrations) == 2

        service_side = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group registration show --dps-name {dps_name} -g {dps_rg} --registration-id {device_id1}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        compare_registrations(device1_registration, service_side)

        service_side = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group registration show --dps-name {dps_name} -g {dps_rg} --registration-id {device_id2}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        compare_registrations(device2_registration, service_side)

        # Cannot use group key as device key
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {device_id1} "
                f"--key {keys['primaryKey']}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        assert registration_result.success() is False

        # Try with payload
        payload = {"Thermostat": {"$metadata": {}}}

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --group-id {group_id} "
                f"--registration-id {device_id1} "
                f"--payload '{payload}'",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        device1_registration = registration["registrationState"]
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id1
        assert registration["registrationState"]["registrationId"] == device_id1
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"


def test_dps_device_registration_x509_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    hub_cstring = provisioned_iot_dps_module["hubConnectionString"]
    id_scope = provisioned_iot_dps_module["dps"]["properties"]["idScope"]

    fake_pass = "pass1234"
    root_name, devices = _prepare_x509_certificates_for_dps(
        tracked_certs=provisioned_iot_dps_module["certificates"],
        dps_name=dps_name,
        dps_rg=dps_rg,
        device_passwords=[None, fake_pass]
    )

    for auth_phase in DATAPLANE_AUTH_TYPES:
        group_id = generate_names()

        # Enrollment needs to be created
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {devices[0][0]} "
                f"--cp {devices[0][0] + CERT_ENDING} --kp {devices[0][0] + KEY_ENDING}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert registration_result.success() is False

        # Create enrollment group
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --group-id {group_id} --dps-name {dps_name} -g {dps_rg} "
                f"--cp {root_name + CERT_ENDING}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        # Need to specify file - cannot retrieve need info from service
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {devices[0][0]}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        assert registration_result.success() is False

        # Normal registration
        registration_states = []
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {devices[0][0]} "
                f"--cp {devices[0][0] + CERT_ENDING} --kp {devices[0][0] + KEY_ENDING}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        registration_states.append(registration["registrationState"])
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == devices[0][0]
        assert registration["registrationState"]["registrationId"] == devices[0][0]
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, devices[0][0], "selfSigned", hub_cstring, thumbprint=devices[0][1])

        # Use id scope and host to register the second device with password
        provisioning_host = f"{dps_name}.azure-devices-provisioning.net"
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {devices[1][0]} "
                f"--cp {devices[1][0] + CERT_ENDING} --kp {devices[1][0] + KEY_ENDING} --host {provisioning_host} "
                f"--pass {fake_pass}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        registration_states.append(registration["registrationState"])
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == devices[1][0]
        assert registration["registrationState"]["registrationId"] == devices[1][0]
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, devices[1][0], "selfSigned", hub_cstring, thumbprint=devices[1][1])

        # Check registration from service side
        for i in range(len(devices)):
            service_side = cli.invoke(
                set_cmd_auth_type(
                    f"iot dps enrollment-group registration show --dps-name {dps_name} -g {dps_rg} --rid {devices[i][0]}",
                    auth_type=auth_phase,
                    cstring=dps_cstring
                ),
            ).as_json()
            compare_registrations(registration_states[i], service_side)

        # Try with payload
        payload = {"Thermostat": {"$metadata": {}}}

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {devices[0][0]} "
                f"--cp {devices[0][0] + CERT_ENDING} --kp {devices[0][0] + KEY_ENDING} --payload '{payload}'",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == devices[0][0]
        assert registration["registrationState"]["registrationId"] == devices[0][0]
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group delete --group-id {group_id} --dps-name {dps_name} -g {dps_rg}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )


def test_dps_device_registration_unlinked_hub(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module['name']
    dps_rg = provisioned_iot_dps_no_hub_module['resourceGroup']
    dps_cstring = provisioned_iot_dps_no_hub_module["connectionString"]

    for auth_phase in DATAPLANE_AUTH_TYPES:
        group_id, device_id = generate_names(count=2)

        result = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --group-id {group_id} -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        if not result.success():
            raise AssertionError(f"Failed to create enrollment group with attestation-type {auth_phase}")

        # registration throws error
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --group-id {group_id} -g {dps_rg} --dps-name {dps_name} "
                f"--registration-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert registration_result.success() is False

        # Can see registration
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group registration show -g {dps_rg} --dps-name {dps_name} --registration-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["etag"]
        assert registration["lastUpdatedDateTimeUtc"]
        assert registration["registrationId"] == device_id
        assert registration["status"] == "failed"


def test_dps_device_registration_disabled_enrollment(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    for auth_phase in DATAPLANE_AUTH_TYPES:
        group_id, device_id = generate_names(count=2)

        result = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --group-id {group_id} -g {dps_rg} --dps-name {dps_name} "
                f"--provisioning-status {EntityStatusType.disabled.value}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        if not result.success():
            raise AssertionError(f"Failed to create enrollment group with attestation-type {auth_phase}")

        # Registration throws error
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --group-id {group_id} -g {dps_rg} --dps-name {dps_name} "
                f"--registration-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        assert registration_result.success() is False

        # Can see registration
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration show -g {dps_rg} --dps-name {dps_name} --enrollment-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["etag"]
        assert registration["lastUpdatedDateTimeUtc"]
        assert registration["registrationId"] == device_id
        assert registration["status"] == "disabled"


def _prepare_x509_certificates_for_dps(tracked_certs, dps_name, dps_rg, device_passwords=[None]):
    # Create root and device certificates
    output_dir = os.getcwd()
    root_name = "root" + generate_generic_id()
    root_cert_obj = create_certificate(
        subject=root_name, valid_days=1, cert_output_dir=output_dir
    )
    devices = []
    device_names = generate_names(count=len(device_passwords))
    for d, device in enumerate(device_names):
        device_thumbprint = create_certificate(
            subject=device,
            valid_days=1,
            cert_output_dir=output_dir,
            cert_object=root_cert_obj,
            chain_cert=True,
            signing_password=device_passwords[d]
        )['thumbprint']
        devices.append((device, device_thumbprint))

    for cert_name in [root_name] + device_names:
        tracked_certs.append(cert_name + CERT_ENDING)
        tracked_certs.append(cert_name + KEY_ENDING)

    # Upload root certifcate and get verification code
    cli.invoke(
        f"iot dps certificate create --dps-name {dps_name} -g {dps_rg} -n {root_name} -p {root_name + CERT_ENDING}"
    )

    verification_code = cli.invoke(
        f"iot dps certificate generate-verification-code --dps-name {dps_name} -g {dps_rg} -n {root_name} -e *"
    ).as_json()["properties"]["verificationCode"]

    # Create verification certificate and upload
    create_certificate(
        subject=verification_code,
        valid_days=1,
        cert_output_dir=output_dir,
        cert_object=root_cert_obj,
    )
    tracked_certs.append(verification_code + CERT_ENDING)
    tracked_certs.append(verification_code + KEY_ENDING)

    cli.invoke(
        f"iot dps certificate verify --dps-name {dps_name} -g {dps_rg} -n {root_name} -p {verification_code + CERT_ENDING} -e *"
    )
    return (root_name, devices)
