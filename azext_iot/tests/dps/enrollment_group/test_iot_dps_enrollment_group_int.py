# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import BadRequestError
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import EntityStatusType, AttestationType, AllocationType, ReprovisionType
from azext_iot.common.utility import generate_key
from azext_iot.tests.dps import (
    API_VERSION,
    DATAPLANE_AUTH_TYPES,
    WEBHOOK_URL,
    clean_dps_dataplane,
)
from azext_iot.tests.helpers import CERT_ENDING, create_test_cert, set_cmd_auth_type
from azext_iot.tests.generators import generate_generic_id, generate_names

cli = EmbeddedCLI()


def test_dps_enrollment_group_x509_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    clean_dps_dataplane(cli, dps_cstring)

    cert_name = generate_names()
    cert_path = cert_name + CERT_ENDING
    create_test_cert(tracked_certs=provisioned_iot_dps_module["certificates"], subject=cert_name)
    for auth_phase in DATAPLANE_AUTH_TYPES:
        enrollment_id = generate_names()

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --enrollment-id {enrollment_id} -g {dps_rg} --dps-name {dps_name} "
                f"--cp {cert_path} --scp {cert_path} --provisioning-status {EntityStatusType.enabled.value} "
                f"--allocation-policy {AllocationType.geolatency.value} --iot-hubs {hub_hostname} --edge-enabled",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()

        etag = enrollment["etag"]
        assert enrollment["allocationPolicy"] == AllocationType.geolatency.value
        assert enrollment["attestation"]["type"] == AttestationType.x509.value
        assert enrollment["capabilities"]["iotEdge"] is True
        assert enrollment["enrollmentGroupId"] == enrollment_id
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] is True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] is True

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list]

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_show["enrollmentGroupId"] == enrollment_id
        assert enrollment_show["attestation"]["x509"]

        # TODO The warning is annoying - x509 with show keys should be a unit test instead
        # enrollment_show = cli.invoke(
        #     set_cmd_auth_type(
        #         f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} --show-keys",
        #         auth_type=auth_phase,
        #         cstring=dps_cstring
        #     ),
        # ).as_json()
        # assert enrollment_show["enrollmentGroupId"] == enrollment_id
        # assert enrollment_show["attestation"]["x509"]

        # Compute Device Key only works for symmetric key enrollment groups
        with pytest.raises(BadRequestError):
            cli.invoke(
                set_cmd_auth_type(
                    f"iot dps enrollment-group compute-device-key -g {dps_rg} --dps-name {dps_name} "
                    f"--enrollment-id {enrollment_id} --registration-id myarbitrarydeviceId",
                    auth_type=auth_phase,
                    cstring=dps_cstring
                ),
                capture_stderr=True
            )

        enrollment_update = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} "
                f"--provisioning-status {EntityStatusType.disabled.value} --rsc --etag {etag} "
                f"--rp {ReprovisionType.never.value} --allocation-policy {AllocationType.hashed.value} --edge-enabled False "
                f"--scp {cert_path}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()

        etag = enrollment["etag"]
        assert enrollment_update["allocationPolicy"] == AllocationType.hashed.value
        assert enrollment_update["attestation"]["type"] == AttestationType.x509.value
        assert enrollment_update["attestation"]["x509"]["clientCertificates"] is None
        assert enrollment_update["capabilities"]["iotEdge"] is False
        assert enrollment_update["enrollmentGroupId"] == enrollment_id
        assert enrollment_update["provisioningStatus"] == EntityStatusType.disabled.value
        assert enrollment_update["reprovisionPolicy"]
        assert enrollment_update["reprovisionPolicy"]["migrateDeviceData"] is False
        assert enrollment_update["reprovisionPolicy"]["updateHubAssignment"] is False

        etag = enrollment_update["etag"]

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group registration list -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert len(enrollment_list) == 0

        cert_name = generate_names()
        certificate_create = cli.invoke(
            f"iot dps certificate create -g {dps_rg} --dps-name {dps_name} --name {cert_name} --p {cert_path}"
        ).as_json()
        cert_etag = certificate_create["etag"]
        assert certificate_create["name"] == cert_name

        enrollment_update = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id} "
                f"--cn {cert_name} --etag {etag} --allocation-policy {AllocationType.custom.value} "
                f"--webhook-url {WEBHOOK_URL} --api-version {API_VERSION}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_update["allocationPolicy"] == AllocationType.custom.value
        assert enrollment_update["attestation"]["type"] == AttestationType.x509.value
        assert enrollment_update["attestation"]["x509"]["caReferences"]["primary"] == cert_name
        assert enrollment_update["attestation"]["x509"]["caReferences"]["secondary"] is None
        assert enrollment_update["customAllocationDefinition"]["webhookUrl"] == WEBHOOK_URL
        assert enrollment_update["customAllocationDefinition"]["apiVersion"] == API_VERSION
        assert enrollment_update["enrollmentGroupId"] == enrollment_id

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        cli.invoke(
            f"iot dps certificate delete -g {dps_rg} --dps-name {dps_name} --name {cert_name} --etag {cert_etag}"
        )


def test_dps_enrollment_group_symmetrickey_lifecycle(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    clean_dps_dataplane(cli, dps_cstring)
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

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create --enrollment-id {enrollment_id} -g {dps_rg} --dps-name {dps_name} "
                f"--pk {primary_key} --sk {secondary_key} --provisioning-status {EntityStatusType.enabled.value}"
                f" --initial-twin-tags \"{generic_dict}\" --initial-twin-properties \"{generic_dict}\" "
                f"--allocation-policy {AllocationType.geolatency.value} --rp {ReprovisionType.reprovisionandresetdata.value} "
                f"--iot-hubs {hub_hostname} --edge-enabled",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        etag = enrollment["etag"]

        assert enrollment["allocationPolicy"] == AllocationType.geolatency.value
        assert enrollment["attestation"]["symmetricKey"]["primaryKey"] == primary_key
        assert enrollment["capabilities"]["iotEdge"] is True
        assert enrollment["enrollmentGroupId"] == enrollment_id
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] is True
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["tags"] == generic_dict
        assert enrollment["initialTwin"]["properties"]["desired"] == generic_dict
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] is False

        enrollment_list = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list]

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_show["enrollmentGroupId"] == enrollment_id

        enrollment_update = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}"
                f" --provisioning-status {EntityStatusType.disabled.value} --etag {etag} --edge-enabled False"
                f" --allocation-policy {AllocationType.custom.value} --webhook-url {WEBHOOK_URL} --api-version {API_VERSION}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_update["allocationPolicy"] == AllocationType.custom.value
        assert enrollment_update["attestation"]["type"] == attestation_type
        assert enrollment_update["attestation"]["symmetricKey"]["primaryKey"] == primary_key
        assert enrollment_update["capabilities"]["iotEdge"] is False
        assert enrollment_update["customAllocationDefinition"]["webhookUrl"] == WEBHOOK_URL
        assert enrollment_update["customAllocationDefinition"]["apiVersion"] == API_VERSION
        assert enrollment_update["enrollmentGroupId"] == enrollment_id
        assert enrollment_update["iotHubs"] is None
        assert enrollment_update["initialTwin"]["tags"]
        assert enrollment_update["initialTwin"]["properties"]["desired"]
        assert enrollment_update["provisioningStatus"] == EntityStatusType.disabled.value

        # Use service generated keys
        enrollment2 = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        etag = enrollment2["etag"]
        assert enrollment2["enrollmentGroupId"] == enrollment_id2
        assert enrollment2["attestation"]["type"] == attestation_type

        enrollment_list2 = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group list -g {dps_rg} --dps-name {dps_name}",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()
        assert enrollment_id in [e["enrollmentGroupId"] for e in enrollment_list2]
        assert enrollment_id2 in [e["enrollmentGroupId"] for e in enrollment_list2]

        enrollment_show = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment_show["enrollmentGroupId"] == enrollment_id2
        assert enrollment_show["attestation"]["type"] == attestation_type

        keys = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group show -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2} --show-keys",
                auth_type=auth_phase,
                cstring=dps_cstring
            )
        ).as_json()["attestation"]["symmetricKey"]

        # Compute Device Key tests
        online_device_key = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group compute-device-key -g {dps_rg} --dps-name {dps_name} "
                f"--enrollment-id {enrollment_id2} --registration-id myarbitrarydeviceId",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).output

        offline_device_key = cli.invoke(
            f"iot dps enrollment-group compute-device-key --key \"{keys['primaryKey']}\" "
            "--registration-id myarbitrarydeviceId".format()
        ).output
        assert offline_device_key == online_device_key

        # Compute Device Key uses primary key
        offline_device_key = cli.invoke(
            f"iot dps enrollment-group compute-device-key --key \"{keys['secondaryKey']}\" "
            "--registration-id myarbitrarydeviceId"
        ).output
        assert offline_device_key != online_device_key

        enrollment_update = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group update -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2}"
                f" --pk \"{keys['secondaryKey']}\" --sk \"{keys['primaryKey']}\" --etag {etag}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        etag = enrollment_update["etag"]
        assert enrollment_update["enrollmentGroupId"] == enrollment_id2
        assert enrollment_update["attestation"]["type"] == attestation_type

        online_device_key = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group compute-device-key -g {dps_rg} --dps-name {dps_name} "
                f"--enrollment-id {enrollment_id2} --registration-id myarbitrarydeviceId",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).output
        assert offline_device_key == online_device_key

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id2}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )


def test_dps_enrollment_twin_array(provisioned_iot_dps_module):
    dps_name = provisioned_iot_dps_module['name']
    dps_rg = provisioned_iot_dps_module['resourceGroup']
    hub_hostname = provisioned_iot_dps_module['hubHostName']
    dps_cstring = provisioned_iot_dps_module["connectionString"]
    clean_dps_dataplane(cli, dps_cstring)
    base_enrollment_props = {
        "count": None,
        "metadata": None,
        "version": None,
    }
    generic_dict = {
        **base_enrollment_props,
        generate_generic_id(): generate_generic_id(),
        "key": "value",
    }
    twin_array_dict = {
        **base_enrollment_props,
        "values": [{"key1": "value1"}, {"key2": "value2"}],
    }

    attestation_type = AttestationType.x509.value
    cert_name = generate_names()
    cert_path = cert_name + CERT_ENDING
    create_test_cert(tracked_certs=provisioned_iot_dps_module["certificates"], subject=cert_name)
    for auth_phase in DATAPLANE_AUTH_TYPES:
        # test twin array in enrollment
        device_id = generate_names()
        enrollment_id = generate_names()

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment create --enrollment-id {enrollment_id} --attestation-type {attestation_type}"
                f" -g {dps_rg} --dps-name {dps_name} --cp {cert_path} --scp {cert_path}"
                f" --provisioning-status {EntityStatusType.enabled.value} --device-id {device_id}"
                f" --initial-twin-tags \"{generic_dict}\" --initial-twin-properties \"{twin_array_dict}\" "
                f"--device-information \"{generic_dict}\" --allocation-policy {AllocationType.hashed.value} "
                f"--iot-hubs {hub_hostname}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment["attestation"]["type"] == AttestationType.x509.value
        assert enrollment["allocationPolicy"] == AllocationType.hashed.value
        assert enrollment["deviceId"] == device_id
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["tags"] == generic_dict
        assert enrollment["initialTwin"]["properties"]["desired"] == twin_array_dict
        assert enrollment["optionalDeviceInformation"] == generic_dict
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["registrationId"] == enrollment_id
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] is True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] is True

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )

        # test twin array in enrollment group
        enrollment_group_id = generate_names()

        enrollment = cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group create -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_group_id}"
                f" --cp {cert_path} --scp {cert_path} --provisioning-status {EntityStatusType.enabled.value} "
                f"--allocation-policy {AllocationType.geolatency.value} --iot-hubs {hub_hostname} --edge-enabled "
                f"--props \"{twin_array_dict}\"",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        ).as_json()
        assert enrollment["attestation"]["type"] == AttestationType.x509.value
        assert enrollment["allocationPolicy"] == AllocationType.geolatency.value
        assert enrollment["capabilities"]["iotEdge"] is True
        assert enrollment["enrollmentGroupId"] == enrollment_group_id
        assert enrollment["iotHubs"] == [hub_hostname]
        assert enrollment["initialTwin"]["properties"]["desired"] == twin_array_dict
        assert enrollment["provisioningStatus"] == EntityStatusType.enabled.value
        assert enrollment["reprovisionPolicy"]
        assert enrollment["reprovisionPolicy"]["migrateDeviceData"] is True
        assert enrollment["reprovisionPolicy"]["updateHubAssignment"] is True

        cli.invoke(
            set_cmd_auth_type(
                f"iot dps enrollment-group delete -g {dps_rg} --dps-name {dps_name} --enrollment-id {enrollment_group_id}",
                auth_type=auth_phase,
                cstring=dps_cstring
            ),
        )
