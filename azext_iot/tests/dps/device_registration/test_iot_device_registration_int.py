# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Opt-in live coverage for DPS 2026-11-02 device registration."""

import os

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI


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


def test_register_and_issue_certificate_contract():
    values = _required_environment(
        "azext_iot_dps_device_name",
        "azext_iot_dps_device_resource_group",
        "azext_iot_dps_device_id_scope",
        "azext_iot_dps_device_registration_id",
        "azext_iot_dps_device_csr_path",
    )
    result = cli.invoke(
        "iot device registration create "
        f"--dps-name '{values['azext_iot_dps_device_name']}' "
        f"--resource-group '{values['azext_iot_dps_device_resource_group']}' "
        f"--id-scope '{values['azext_iot_dps_device_id_scope']}' "
        f"--registration-id '{values['azext_iot_dps_device_registration_id']}' "
        f"--csr '{values['azext_iot_dps_device_csr_path']}'"
    ).as_json()

    assert result["operationId"]
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
        f"--operation-id '{result['operationId']}'"
    ).as_json()
    assert followed["operationId"] == result["operationId"]
    assert followed["status"] in {"assigned", "failed"}
