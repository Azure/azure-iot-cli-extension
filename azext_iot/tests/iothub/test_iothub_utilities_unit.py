# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.sas_token_auth import SasTokenAuthentication
import pytest
from knack.cli import CLIError
from azext_iot.operations import hub as subject
from azext_iot.tests.generators import generate_generic_id


def generate_valid_cs(validate_pairs=[]):
    host_name = generate_generic_id()
    shared_access_key = generate_generic_id()
    cs = f"HostName={host_name};"
    input_pairs = dict((k, generate_generic_id()) for k in validate_pairs)
    policy = input_pairs["SharedAccessKeyName"] if "SharedAccessKeyName" in input_pairs else None

    for key, value in input_pairs.items():
        cs += "{}={};".format(
            key, value
        )

    cs = f"{cs}SharedAccessKey={shared_access_key}"
    uri = host_name
    if "DeviceId" in input_pairs:
        uri = f"{uri}/devices/{input_pairs['DeviceId']}"
    if "ModuleId" in input_pairs:
        uri = f"{uri}/modules/{input_pairs['ModuleId']}"

    return {
        "connection_string": cs,
        "uri": uri,
        "policy": policy,
        "key": shared_access_key
    }


class TestGenerateSasToken:
    @pytest.mark.parametrize(
        "duration, req",
        [
            (3600, generate_valid_cs(["DeviceId"])),
            (30, generate_valid_cs(["DeviceId"])),
            (60000, generate_valid_cs(["DeviceId"])),
            (3600, generate_valid_cs(["RepositoryId", "SharedAccessKeyName"])),
            (3600, generate_valid_cs(["SharedAccessKeyName"])),
            (3600, generate_valid_cs(["DeviceId"])),
            (3600, generate_valid_cs(["DeviceId", "ModuleId"])),
            (3600, generate_valid_cs(["Test", "DeviceId", "ModuleId"])),
            (3600, generate_valid_cs(["RepositoryId", "DeviceId", "ModuleId"])),
        ],
    )
    def test_generate_sas_token_from_cs(self, mocker, fixture_cmd, duration, req):
        patched_time = mocker.patch(
            "azext_iot.common.sas_token_auth.time"
        )
        patched_time.return_value = 0
        result = subject.iot_get_sas_token(
            cmd=fixture_cmd,
            connection_string=req["connection_string"],
            duration=duration
        )

        duration = duration if duration else 3600
        expected_sas = SasTokenAuthentication(
            req["uri"], req["policy"], req["key"], duration
        ).generate_sas_token()
        assert result["sas"] == expected_sas

    @pytest.mark.parametrize(
        "req",
        [
            (generate_valid_cs()),
            (generate_valid_cs(["ModuleId"])),
            (generate_valid_cs(["RepositoryId"])),
            (generate_valid_cs(["Test"]))
        ],
    )
    def test_generate_sas_token_from_cs_error(self, mocker, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_get_sas_token(
                cmd=fixture_cmd,
                connection_string=req["connection_string"],
            )
