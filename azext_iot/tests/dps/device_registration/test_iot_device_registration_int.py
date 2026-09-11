# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Deadline registration coverage, with opt-in certificate-issuance prerequisites."""

import os

import pytest
from azure.cli.core.azclierror import UnauthorizedError

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.utility import generate_key
from azext_iot.tests.dps.device_registration import check_hub_device
from azext_iot.tests.generators import generate_names


cli = EmbeddedCLI()


def _required_environment(*names):
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        pytest.skip(
            "Set these variables for DPS device 2026-11-02 integration "
            f"coverage: {', '.join(missing)}"
        )
    return values


@pytest.mark.parametrize("timeout", [None, 180], ids=["default", "deadline"])
def test_register_without_csr_deadline_contract(provisioned_iot_dps_module, timeout):
    dps_name = provisioned_iot_dps_module["name"]
    dps_rg = provisioned_iot_dps_module["resourceGroup"]
    enrollment_id = generate_names()
    enrollment = cli.invoke(
        f"iot dps enrollment create --dps-name {dps_name} -g {dps_rg} "
        f"--enrollment-id {enrollment_id} --attestation-type symmetricKey --auth-type login",
        capture_stderr=True,
    ).as_json()
    command = (
        f"iot device registration create --dps-name {dps_name} -g {dps_rg} "
        f"--registration-id {enrollment_id} --auth-type login"
    )
    if timeout is not None:
        command += f" --timeout {timeout}"
    try:
        result = cli.invoke(
            f"{command} --key {enrollment['attestation']['symmetricKey']['primaryKey']}",
            capture_stderr=True,
        ).as_json()
        assert result["operationId"]
        assert result["status"] == "assigned"
        assert result["registrationState"]["registrationId"] == enrollment_id
        assert result["registrationState"]["deviceId"] == enrollment_id
        assert result["registrationState"]["assignedHub"] == provisioned_iot_dps_module["hubHostName"]
        assert result["registrationState"]["substatus"] == "initialAssignment"
        check_hub_device(cli, enrollment_id, "sas", provisioned_iot_dps_module["iotHub"])
        with pytest.raises(UnauthorizedError):
            cli.invoke(f"{command} --key {generate_key()}", capture_stderr=True)
    finally:
        cli.invoke(
            f"iot dps enrollment delete --dps-name {dps_name} -g {dps_rg} "
            f"--enrollment-id {enrollment_id} --auth-type login",
            capture_stderr=True,
        )


@pytest.mark.parametrize("timeout", [None, 180], ids=["default", "deadline"])
def test_register_and_issue_certificate_contract(timeout):
    values = _required_environment(
        "azext_iot_dps_device_name",
        "azext_iot_dps_device_resource_group",
        "azext_iot_dps_device_id_scope",
        "azext_iot_dps_device_registration_id",
        "azext_iot_dps_device_csr_path",
    )
    command = (
        "iot device registration create "
        f"--dps-name '{values['azext_iot_dps_device_name']}' "
        f"--resource-group '{values['azext_iot_dps_device_resource_group']}' "
        f"--id-scope '{values['azext_iot_dps_device_id_scope']}' "
        f"--registration-id '{values['azext_iot_dps_device_registration_id']}' "
        f"--csr '{values['azext_iot_dps_device_csr_path']}' --auth-type login"
    )
    if timeout is not None:
        command += f" --timeout {timeout}"
    result = cli.invoke(command, capture_stderr=True).as_json()

    assert result["operationId"]
    assert result["status"] == "assigned"
    state = result.get("registrationState") or {}
    assert state.get("connectionProfile") in {"Classic", "MqttV5"}
    assert state.get("issuedCertificateChain")
    assert state.get("registryDeviceExternalId")

    followed = cli.invoke(
        "iot device registration operation-status "
        f"--dps-name '{values['azext_iot_dps_device_name']}' "
        f"--resource-group '{values['azext_iot_dps_device_resource_group']}' "
        f"--id-scope '{values['azext_iot_dps_device_id_scope']}' "
        f"--registration-id '{values['azext_iot_dps_device_registration_id']}' "
        f"--operation-id '{result['operationId']}' --auth-type login",
        capture_stderr=True,
    ).as_json()
    assert followed["operationId"] == result["operationId"]
    assert followed["status"] == "assigned"
