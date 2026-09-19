# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Deadline registration and self-contained, receipt-owned certificate issuance."""

from shlex import quote

import pytest

from azext_iot.tests.dps._csr import temporary_csr
from azext_iot.tests.dps._csr_issuance import enrollment, invoke
from azext_iot.tests.dps._registry_assertions import assert_registry_registration
from azext_iot.tests.generators import generate_names


@pytest.mark.parametrize("timeout", [None, 180], ids=["default", "deadline"])
@pytest.mark.timeout(2700)
def test_register_without_csr_deadline_contract(provisioned_csr_issuance, timeout):
    resource = provisioned_csr_issuance
    dps = resource["dps"]
    enrollment_id = generate_names()
    command = (
        f"iot device registration create --dps-name {dps['name']} -g {dps['resourceGroup']} "
        f"--registration-id {enrollment_id} --auth-type login"
    )
    if timeout is not None:
        command += f" --timeout {timeout}"
    with enrollment(resource, enrollment_id, certificate=False) as ownership:
        ownership.before_submit()
        result = invoke(command).as_json()
        ownership.record_result(result)
        assert result["operationId"]
        assert result["status"] == "assigned"
        assert result["registrationState"]["registrationId"] == enrollment_id
        assert result["registrationState"]["deviceId"] == enrollment_id
        assert result["registrationState"]["assignedHub"] in ownership.intent["assigned_hubs"]
        assert result["registrationState"]["substatus"] == "initialAssignment"
        assert_registry_registration(resource, ownership, certificate=False)


@pytest.mark.parametrize("timeout", [None, 180], ids=["default", "deadline"])
@pytest.mark.timeout(2700)
def test_register_and_issue_certificate_contract(provisioned_csr_issuance, tmp_path, timeout):
    resource = provisioned_csr_issuance
    dps = resource["dps"]
    registration_id = generate_names()
    context = (
        f"--dps-name {dps['name']} -g {dps['resourceGroup']} "
        f"--id-scope {dps['dps']['properties']['idScope']} --registration-id {registration_id} --auth-type login"
    )
    with temporary_csr(tmp_path, registration_id) as csr, enrollment(resource, registration_id) as ownership:
        command = f"iot device registration create {context} --csr {quote(str(csr))}"
        if timeout is not None:
            command += f" --timeout {timeout}"
        ownership.before_submit()
        result = invoke(command).as_json()
        ownership.record_result(result)

        assert result["operationId"]
        assert result["status"] == "assigned"
        state = result["registrationState"]
        assert state["registrationId"] == registration_id
        assert state["deviceId"] == registration_id
        properties = resource["hub"]["hub"]["properties"]
        assert state["assignedHub"] in {properties["hostName"], properties["deviceHostName"]}
        assert state["connectionProfile"] in {"Classic", "MqttV5"}
        assert state["issuedCertificateChain"]
        assert state["registryDeviceExternalId"]

        followed = invoke(
            f"iot device registration operation-status {context} --operation-id {quote(result['operationId'])}"
        ).as_json()
        ownership.record_result(followed)
        assert followed["operationId"] == result["operationId"]
        assert followed["status"] == "assigned"
        assert followed["registrationState"]["registrationId"] == registration_id
        assert_registry_registration(resource, ownership, certificate=True)
