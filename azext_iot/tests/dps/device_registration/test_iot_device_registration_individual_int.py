# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import EntityStatusType, AttestationType
from azext_iot.tests.dps import (
    DATAPLANE_AUTH_TYPES,
    clean_dps_dataplane
)
from azext_iot.tests.dps.device_registration import compare_registrations, check_hub_device
from azext_iot.tests.helpers import CERT_ENDING, KEY_ENDING, create_test_cert, set_cmd_auth_type
from azext_iot.tests.generators import generate_names

cli = EmbeddedCLI()


def test_dps_device_registration_symmetrickey_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    hub_cstring = provisioned_iot_dps_module["hubConnectionString"]
    id_scope = provisioned_iot_dps_module["dps"]["properties"]["idScope"]
    clean_dps_dataplane(cli, dps_cstring)

    attestation_type = AttestationType.symmetricKey.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id, device_id = generate_names(count=2)

        # Enrollment needs to be created
        enrollment_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert enrollment_result.success() is False

        # Enrollment with no device id; deviceId becomes enrollmentId
        keys = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" --dps-name {dps_name} -g {dps_rg}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()["attestation"]["symmetricKey"]

        # Defaults to primary key
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == enrollment_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, enrollment_id, "sas", hub_cstring)

        # Manually input primary key and id scope
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {enrollment_id} "
                f"--key {keys['primaryKey']}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == enrollment_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Try different provisioning host
        provisioning_host = f"{dps_name}.azure-devices-provisioning.net"
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {enrollment_id} "
                f"--key {keys['primaryKey']} --host {provisioning_host}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == enrollment_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Unauthorized
        bad_key = keys["primaryKey"].replace(keys["primaryKey"][0], "")
        bad_registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {enrollment_id} --key {bad_key}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        assert bad_registration.success() is False

        # Try secondary key
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {enrollment_id} "
                f"--key {keys['secondaryKey']}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        registration_state = registration["registrationState"]
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == enrollment_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Check registration from service side
        service_state = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration show --dps-name {dps_name} -g {dps_rg} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        compare_registrations(registration_state, service_state)

        # Delete registration to change the device id
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration delete --dps-name {dps_name} -g {dps_rg} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        # Enrollment with device id
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment update --enrollment-id {enrollment_id} --dps-name {dps_name} -g {dps_rg} "
                f"--device-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id, "sas", hub_cstring)
        # Note that the old device registration still exists in hub
        check_hub_device(cli, enrollment_id, "sas", hub_cstring)

        # Try with payload
        payload = {"Thermostat": {"$metadata": {}}}

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {enrollment_id} "
                f"--payload '{payload}'",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id
        assert registration["registrationState"]["registrationId"] == enrollment_id
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"


def test_dps_device_registration_x509_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    hub_cstring = provisioned_iot_dps_module["hubConnectionString"]
    id_scope = provisioned_iot_dps_module["dps"]["properties"]["idScope"]
    tracked_certs = provisioned_iot_dps_module["certificates"]
    clean_dps_dataplane(cli, dps_cstring)

    # Create two test certs - have the same subject but a different file name
    cert_name = generate_names()
    cert_path = cert_name + CERT_ENDING
    key_path = cert_name + KEY_ENDING
    first_thumbprint = create_test_cert(tracked_certs=tracked_certs, subject=cert_name, cert_only=False)

    second_cert_name = generate_names()
    second_cert_path = second_cert_name + CERT_ENDING
    second_key_path = second_cert_name + KEY_ENDING
    secondary_thumprint = create_test_cert(
        tracked_certs=tracked_certs, subject=cert_name, cert_only=False, file_prefix=second_cert_name
    )

    attestation_type = AttestationType.x509.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        # For some reason, enrollment_id must be the subject of the cert to get the device to register
        device_id = generate_names()

        # Enrollment needs to be created
        enrollment_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {cert_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert enrollment_result.success() is False

        # Enrollment with no device id; deviceId becomes enrollmentId
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {cert_name} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --cp {cert_path} --scp {second_cert_path}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        # Need to specify file - cannot retrieve need info from service
        enrollment_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {cert_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert enrollment_result.success() is False

        # Normal registration
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {cert_name} "
                f"--cp {cert_path} --kp {key_path}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == cert_name
        assert registration["registrationState"]["registrationId"] == cert_name
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, cert_name, "selfSigned", hub_cstring, thumbprint=first_thumbprint)

        # Use id scope and different host
        provisioning_host = f"{dps_name}.azure-devices-provisioning.net"
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {cert_name} "
                f"--cp {cert_path} --kp {key_path} --host {provisioning_host}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        registration_state = registration["registrationState"]
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == cert_name
        assert registration["registrationState"]["registrationId"] == cert_name
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Check registration from service side
        service_state = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration show --dps-name {dps_name} -g {dps_rg} --enrollment-id {cert_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        compare_registrations(registration_state, service_state)

        # Delete registration to change the device id
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration delete --dps-name {dps_name} -g {dps_rg} --enrollment-id {cert_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        # Enrollment with device id
        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment update --enrollment-id {cert_name} --dps-name {dps_name} -g {dps_rg} "
                f"--device-id {device_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {cert_name} "
                f"--cp {cert_path} --kp {key_path}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()

        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id
        assert registration["registrationState"]["registrationId"] == cert_name
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id, "selfSigned", hub_cstring, thumbprint=first_thumbprint)
        # Note that the old registration will still exist in hub
        check_hub_device(cli, cert_name, "selfSigned", hub_cstring, thumbprint=first_thumbprint)

        # Try with payload
        payload = {"Thermostat": {"$metadata": {}}}

        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --dps-name {dps_name} -g {dps_rg} --registration-id {cert_name} "
                f"--cp {cert_path} --kp {key_path} --payload '{payload}'",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id
        assert registration["registrationState"]["registrationId"] == cert_name
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"

        # Try secondary cert
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create --id-scope {id_scope} --registration-id {cert_name} "
                f"--cp {second_cert_path} --kp {second_key_path}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert registration["operationId"]
        assert registration["registrationState"]["assignedHub"] == hub_hostname
        assert registration["registrationState"]["deviceId"] == device_id
        assert registration["registrationState"]["registrationId"] == cert_name
        assert registration["registrationState"]["substatus"] == "initialAssignment"
        assert registration["status"] == "assigned"
        check_hub_device(cli, device_id, "selfSigned", hub_cstring, thumbprint=secondary_thumprint)

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete --dps-name {dps_name} -g {dps_rg} --enrollment-id {cert_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )


def test_dps_device_registration_unlinked_hub(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module['name']
    dps_rg = provisioned_iot_dps_no_hub_module['resourceGroup']
    dps_cstring = provisioned_iot_dps_no_hub_module["connectionString"]
    clean_dps_dataplane(cli, dps_cstring)

    attestation_type = AttestationType.symmetricKey.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()

        # TODO: seems transient - as in permissions are there but sometimes the login fails
        result = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        if not result.success():
            raise AssertionError(f"Failed to create enrollment with attestation-type {attestation_type}")

        # registration throws error
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create -g {dps_rg} --dps-name {dps_name} --registration-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert registration_result.success() is False

        # Can see registration
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert registration["etag"]
        assert registration["lastUpdatedDateTimeUtc"]
        assert registration["registrationId"] == enrollment_id
        assert registration["status"] == "failed"


def test_dps_device_registration_disabled_enrollment(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    clean_dps_dataplane(cli, dps_cstring)

    attestation_type = AttestationType.symmetricKey.value
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()

        result = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --provisioning-status {EntityStatusType.disabled.value}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
        if not result.success():
            raise AssertionError(f"Failed to create enrollment with attestation-type {attestation_type}")

        # registration throws error
        registration_result = cli.invoke(
            set_cmd_auth_type(
                f"iot device registration create -g {dps_rg} --dps-name {dps_name} --registration-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        )
        assert registration_result.success() is False

        # Can see registration
        registration = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment registration show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert registration["etag"]
        assert registration["lastUpdatedDateTimeUtc"]
        assert registration["registrationId"] == enrollment_id
        assert registration["status"] == "disabled"
