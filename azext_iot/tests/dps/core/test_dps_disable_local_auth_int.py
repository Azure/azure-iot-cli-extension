# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re

import pytest
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.helpers import invoke_checked, set_cmd_auth_type

cli = EmbeddedCLI()
pytestmark = pytest.mark.dps_local_auth_toggle
AUTH_TYPES = (AuthenticationTypeDataplane.login.value, AuthenticationTypeDataplane.key.value, "cstring")


def _invoke(command):
    return invoke_checked(cli, command, description="Owned DPS local-auth coverage")


def _assert_service_sas_denied(command):
    with pytest.raises((CLIError, HttpResponseError)) as error:
        _invoke(command)
    diagnostic = str(error.value).lower()
    assert (
        getattr(error.value, "status_code", None) in (401, 403)
        or re.search(r"\b(?:unauthorized(?:access)?|forbidden)\b|(?:\(|http\s+)(?:401|403)\b", diagnostic)
    ), "Disabling DPS local auth must reject SAS authentication, not fail for an unrelated reason."


@pytest.fixture
def local_auth_dps(provisioned_iot_dps_local_auth_module):
    enable_local_auth = (
        "iot dps update --name {} --resource-group {} --disable-local-auth false".format(
            provisioned_iot_dps_local_auth_module["name"],
            provisioned_iot_dps_local_auth_module["resourceGroup"],
        )
    )
    disable_local_auth = (
        "iot dps update --name {} --resource-group {} --disable-local-auth true".format(
            provisioned_iot_dps_local_auth_module["name"],
            provisioned_iot_dps_local_auth_module["resourceGroup"],
        )
    )
    try:
        assert _invoke(enable_local_auth).success()
        yield provisioned_iot_dps_local_auth_module
    finally:
        assert _invoke(disable_local_auth).success()


def test_dps_create_disable_local_auth(provisioned_iot_dps_local_auth_module):
    dps_name = provisioned_iot_dps_local_auth_module["name"]
    dps_rg = provisioned_iot_dps_local_auth_module["resourceGroup"]

    assert provisioned_iot_dps_local_auth_module["dps"]["properties"]["disableLocalAuth"] is True
    dps = _invoke(f"iot dps show --name {dps_name} --resource-group {dps_rg}").as_json()
    assert dps["properties"]["disableLocalAuth"] is True


def test_dps_update_disable_local_auth(local_auth_dps):
    dps_name = local_auth_dps["name"]
    dps_rg = local_auth_dps["resourceGroup"]

    # The fixture normalizes the resource to local authentication enabled.
    dps = _invoke(f"iot dps show --name {dps_name} --resource-group {dps_rg}").as_json()
    assert dps["properties"].get("disableLocalAuth") is not True

    dps = _invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True

    # An unrelated generic update must not reset the setting.
    tags = dict(local_auth_dps["dps"]["tags"])
    tags["testtag"] = "value"
    tag_arguments = " ".join(f"{key}={value}" for key, value in tags.items())
    dps = _invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --tags {tag_arguments}"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True
    assert dps["tags"] == tags

    dps = _invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is False


def test_dps_disable_local_auth_dataplane(local_auth_dps):
    dps_name = local_auth_dps["name"]
    dps_rg = local_auth_dps["resourceGroup"]
    dps_cstring = local_auth_dps["connectionString"]
    enrollment_list = f"iot dps enrollment list --dps-name {dps_name} -g {dps_rg}"

    for auth_phase in AUTH_TYPES:
        assert _invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()

    assert _invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    ).success()

    # Only auth type login is allowed.
    for auth_phase in AUTH_TYPES:
        command = set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        if auth_phase == AuthenticationTypeDataplane.login.value:
            assert _invoke(command).success()
        else:
            _assert_service_sas_denied(command)

    assert _invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    ).success()

    for auth_phase in AUTH_TYPES:
        assert _invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()
