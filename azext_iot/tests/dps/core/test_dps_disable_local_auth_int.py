# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.common.shared import AuthenticationTypeDataplane
from azext_iot.tests.dps import DATAPLANE_AUTH_TYPES
from azext_iot.tests.dps.conftest import ENTITY_RG, generate_dps_id
from azext_iot.tests.helpers import set_cmd_auth_type

cli = EmbeddedCLI()


@pytest.fixture
def created_dps_name():
    name = generate_dps_id()
    yield name
    cli.invoke(f"iot dps delete --name {name} --resource-group {ENTITY_RG}")


def test_dps_create_disable_local_auth(created_dps_name):
    dps = cli.invoke(
        f"iot dps create --name {created_dps_name} --resource-group {ENTITY_RG} --disable-local-auth true"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True

    dps = cli.invoke(
        f"iot dps show --name {created_dps_name} --resource-group {ENTITY_RG}"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True


def test_dps_update_disable_local_auth(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module["name"]
    dps_rg = provisioned_iot_dps_no_hub_module["resourceGroup"]

    # The property is absent until explicitly set.
    dps = cli.invoke(f"iot dps show --name {dps_name} --resource-group {dps_rg}").as_json()
    assert dps["properties"].get("disableLocalAuth") is not True

    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True

    # An unrelated generic update must not reset the setting.
    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --tags testtag=value"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is True
    assert dps["tags"]["testtag"] == "value"

    dps = cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    ).as_json()
    assert dps["properties"]["disableLocalAuth"] is False


def test_dps_disable_local_auth_dataplane(provisioned_iot_dps_no_hub_module):
    dps_name = provisioned_iot_dps_no_hub_module["name"]
    dps_rg = provisioned_iot_dps_no_hub_module["resourceGroup"]
    dps_cstring = provisioned_iot_dps_no_hub_module["connectionString"]
    enrollment_list = f"iot dps enrollment list --dps-name {dps_name} -g {dps_rg}"

    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()

    cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth true"
    )

    # Only auth type login is allowed.
    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success() is (auth_phase == AuthenticationTypeDataplane.login.value)

    cli.invoke(
        f"iot dps update --name {dps_name} --resource-group {dps_rg} --disable-local-auth false"
    )

    for auth_phase in DATAPLANE_AUTH_TYPES:
        assert cli.invoke(
            set_cmd_auth_type(enrollment_list, auth_type=auth_phase, cstring=dps_cstring)
        ).success()
