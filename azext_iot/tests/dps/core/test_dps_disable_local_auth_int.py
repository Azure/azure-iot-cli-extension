# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.dps import DATAPLANE_AUTH_TYPES
from azext_iot.tests.helpers import set_cmd_auth_type

cli = EmbeddedCLI()


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
    assert cli.invoke(enable_local_auth).success()
    try:
        yield provisioned_iot_dps_local_auth_module
    finally:
        assert cli.invoke(disable_local_auth).success()


def test_dps_create_disable_local_auth(provisioned_iot_dps_local_auth_module):
    dps_name = provisioned_iot_dps_local_auth_module["name"]
    dps_rg = provisioned_iot_dps_local_auth_module["resourceGroup"]

    assert provisioned_iot_dps_local_auth_module["dps"]["properties"]["disableLocalAuth"] is True
    dps = cli.invoke(f"iot dps show --name {dps_name} --resource-group {dps_rg}").as_json()
    assert dps["properties"]["disableLocalAuth"] is True


def test_dps_update_disable_local_auth(local_auth_dps):
    dps_name = local_auth_dps["name"]
    dps_rg = local_auth_dps["resourceGroup"]

    # The fixture normalizes the resource to local authentication enabled.
    dps = cli.invoke(f"iot dps show --name {dps_name} --resource-group {dps_rg}").as_json()
    assert dps["properties"].get("disableLocalAuth") is not True

    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True

    # An unrelated generic update must not reset the setting.
    tags = dict(local_auth_dps["dps"]["tags"])
    tags["testtag"] = "value"
    tag_arguments = " ".join(f"{key}={value}" for key, value in tags.items())
    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --tags {tag_arguments}"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True
    assert dps["tags"] == tags

    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is False


def test_dps_disable_local_auth_dataplane(local_auth_dps):
    dps_name = local_auth_dps["name"]
    dps_rg = local_auth_dps["resourceGroup"]
    dps_cstring = local_auth_dps["connectionString"]
    enrollment_list = f"iot dps enrollment list --dps-name {dps_name} -g {dps_rg}"

    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()

    assert cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    ).success()

    # Only auth type login is allowed.
    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success() is (auth_phase == AuthenticationTypeDataplane.login.value)

    assert cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    ).success()

    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()
