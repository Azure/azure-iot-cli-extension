# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
from shlex import quote
from tempfile import TemporaryDirectory

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_names
from azext_iot.tests.helpers import invoke_checked
from azext_iot.tests.test_utils import create_certificate

cli = EmbeddedCLI()


@pytest.mark.parametrize("explicit_etag", [False, True], ids=["automatic", "explicit"])
def test_dps_certificate_verification_etag(provisioned_iot_dps_no_hub_module, explicit_etag):
    dps = provisioned_iot_dps_no_hub_module
    certificate_name = generate_names()
    scope = f"--dps-name {quote(dps['name'])} -g {quote(dps['resourceGroup'])} -n {certificate_name}"
    created = False
    with TemporaryDirectory() as directory:
        root = create_certificate(subject=certificate_name, valid_days=1, cert_output_dir=directory, file_prefix="root")
        root_path = quote(str(Path(directory) / "root-cert.pem"))
        proof_path = quote(str(Path(directory) / "proof-cert.pem"))
        try:
            result = invoke_checked(
                cli, f"iot dps certificate create {scope} --path {root_path}",
                description="Create owned DPS certificate",
            )
            created = True
            certificate = result.as_json()
            assert certificate["properties"]["isVerified"] is False
            etag_option = f" --etag {quote(certificate['etag'])}" if explicit_etag else ""
            generated = invoke_checked(
                cli, f"iot dps certificate generate-verification-code {scope}{etag_option}",
                description="Generate DPS certificate verification code",
            ).as_json()
            assert generated["properties"]["verificationCode"]
            create_certificate(
                subject=generated["properties"]["verificationCode"], valid_days=1,
                cert_output_dir=directory, file_prefix="proof", cert_object=root,
            )
            etag_option = f" --etag {quote(generated['etag'])}" if explicit_etag else ""
            verified = invoke_checked(
                cli, f"iot dps certificate verify {scope} --path {proof_path}{etag_option}",
                description="Verify owned DPS certificate",
            ).as_json()
            assert verified["properties"]["isVerified"] is True
            shown = invoke_checked(
                cli, f"iot dps certificate show {scope}", description="Read verified DPS certificate",
            ).as_json()
            assert shown["properties"]["isVerified"] is True
        finally:
            if created:
                invoke_checked(
                    cli, f"iot dps certificate delete {scope} --etag '*'",
                    description="Delete owned DPS certificate",
                )


@pytest.mark.parametrize(("command", "create_options"), [
    pytest.param("enrollment", "--attestation-type symmetricKey", id="individual"),
    pytest.param("enrollment-group", "", id="group"),
])
def test_dps_enrollment_inherited_allocation_with_hubs(provisioned_iot_dps_module, command, create_options):
    dps = provisioned_iot_dps_module
    enrollment_id = generate_names()
    host = dps["dps"]["properties"]["serviceOperationsHostName"]
    hub = dps["hubHostName"]
    scope = (
        f"--dps-name {quote(host)} -g {quote(dps['resourceGroup'])} "
        f"--enrollment-id {enrollment_id} --auth-type login"
    )
    target = f"iot dps {command}"
    created = False
    try:
        result = invoke_checked(
            cli, f"{target} create {scope} {create_options} --iot-hubs {quote(hub)}",
            description=f"Create DPS {command} with inherited allocation",
        )
        created = True
        enrollment = result.as_json()
        assert enrollment["iotHubs"] == [hub]
        assert enrollment.get("allocationPolicy") is None
        shown = invoke_checked(
            cli, f"{target} show {scope}", description=f"Read DPS {command} with inherited allocation",
        ).as_json()
        assert shown["iotHubs"] == [hub]
        assert shown.get("allocationPolicy") is None
        if command == "enrollment-group":
            key_names = {"primaryKey", "secondaryKey"}
            assert key_names.isdisjoint(enrollment["attestation"]["symmetricKey"])
            updated = invoke_checked(
                cli, f"{target} update {scope} --provisioning-status disabled",
                description="Update enrollment group with default key redaction",
            ).as_json()
            assert updated["provisioningStatus"] == "disabled"
            assert key_names.isdisjoint(updated["attestation"]["symmetricKey"])
            explicit_keys = invoke_checked(
                cli, f"{target} show {scope} --show-keys",
                description="Explicitly request enrollment-group keys",
            ).as_json()["attestation"]["symmetricKey"]
            assert all(explicit_keys.get(key) for key in key_names)
    finally:
        if created:
            invoke_checked(cli, f"{target} delete {scope}", description=f"Delete owned DPS {command}")
