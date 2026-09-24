# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from shlex import quote

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_names
from azext_iot.tests.helpers import invoke_checked

cli = EmbeddedCLI()


@pytest.mark.parametrize(("command", "create_options"), [
    pytest.param("enrollment", "--attestation-type symmetricKey", id="individual"),
    pytest.param("enrollment-group", "", id="group"),
])
def test_dps_device_type_reference_round_trip(provisioned_csr_issuance, command, create_options):
    dps = provisioned_csr_issuance["dps"]
    enrollment_id = generate_names()
    reference = f"urn:example:thing-model:{enrollment_id}:1"
    resource_scope = (
        f"--dps-name {quote(dps['name'])} "
        f"-g {quote(dps['resourceGroup'])} "
        "--auth-type login"
    )
    enrollment_scope = f"{resource_scope} --enrollment-id {enrollment_id}"
    target = f"iot dps {command}"
    create_options = f" {create_options}" if create_options else ""
    enrollment_created = False

    try:
        create_result = invoke_checked(
            cli,
            f"{target} create {enrollment_scope}{create_options} "
            f"--device-type-ref {quote(reference)}",
            description=f"Create semantic-reference DPS {command}",
        )
        enrollment_created = True
        created = create_result.as_json()
        assert created["deviceTypeRefs"] == [reference]

        shown = invoke_checked(
            cli,
            f"{target} show {enrollment_scope}",
            description=f"Show semantic-reference DPS {command}",
        ).as_json()
        assert shown["deviceTypeRefs"] == [reference]

        invoke_checked(
            cli,
            f"{target} update {enrollment_scope} --remove-device-type-ref",
            description=f"Remove semantic-reference from DPS {command}",
        )
        shown = invoke_checked(
            cli,
            f"{target} show {enrollment_scope}",
            description=f"Show cleared semantic-reference DPS {command}",
        ).as_json()
        assert shown.get("deviceTypeRefs") in (None, [])
    finally:
        if enrollment_created:
            invoke_checked(
                cli,
                f"{target} delete {enrollment_scope}",
                description=f"Delete semantic-reference DPS {command}",
            )
