# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from typing import Dict, Optional
import os

import pytest
from knack.log import get_logger

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.helpers import assign_role_assignment
from azext_iot.tests.settings import (
    DynamoSettings,
    ENV_SET_TEST_IOTHUB_REQUIRED,
    ENV_SET_TEST_IOTHUB_OPTIONAL,
    ENV_SET_TEST_IOTDPS_OPTIONAL,
)

logger = get_logger(__name__)
HUB_USER_ROLE = "IoT Hub Data Contributor"
DPS_USER_ROLE = "Device Provisioning Service Data Contributor"
cli = EmbeddedCLI()

# Test Environment Variables
settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_REQUIRED,
    opt_env_set=list(set(ENV_SET_TEST_IOTHUB_OPTIONAL + ENV_SET_TEST_IOTDPS_OPTIONAL))
)
ENTITY_RG = settings.env.azext_iot_testrg
MAX_RBAC_ASSIGNMENT_TRIES = settings.env.azext_iot_rbac_max_tries if settings.env.azext_iot_rbac_max_tries else 10


def generate_hub_id() -> str:
    return f"aziotclitest-hub-{generate_generic_id()}"[:35]


def generate_dps_id() -> str:
    return f"aziotclitest-dps-{generate_generic_id()}"[:35]


def assign_iot_dps_dataplane_rbac_role(target_dps):
    account = cli.invoke("account show").as_json()
    user = account["user"]
    if user["name"] is None:
        raise Exception("User not found")
    assign_role_assignment(
        role=DPS_USER_ROLE,
        scope=target_dps["id"],
        assignee=user["name"],
        max_tries=MAX_RBAC_ASSIGNMENT_TRIES
    )


# IoT DPS fixtures
@pytest.fixture(scope="module")
def provisioned_iot_dps_module(provisioned_only_iot_hubs_session) -> dict:
    result = _iot_dps_provisioner(provisioned_only_iot_hubs_session)
    yield result
    if result:
        _iot_dps_removal(result)


@pytest.fixture(scope="module")
def provisioned_iot_dps_no_hub_module() -> dict:
    result = _iot_dps_provisioner()
    yield result
    if result:
        _iot_dps_removal(result)


def _iot_dps_provisioner(iot_hub: Optional[Dict] = None) -> dict:
    """Create a device provisioning service for testing purposes."""
    dps_name = settings.env.azext_iot_testdps or generate_dps_id()

    dps_list = cli.invoke(
        'iot dps list -g "{}"'.format(ENTITY_RG)
    ).as_json()

    # Check if the generated name is already used
    target_dps = None
    for dps in dps_list:
        if dps["name"] == dps_name:
            target_dps = dps
            break

    # Create the min version dps and assign the correct roles
    if not target_dps:
        if settings.env.azext_iot_testdps:
            logger.error(f"DPS {dps_name} specified in pytest settings not found. DPS will be created")

        base_command = f"iot dps create --name {dps_name} --resource-group {ENTITY_RG}"
        if iot_hub:
            base_command += f" --tags hubname={iot_hub['name']}"
        target_dps = cli.invoke(base_command).as_json()

    assign_iot_dps_dataplane_rbac_role(target_dps)

    # Add link between dps and first iot hub
    hub_host_name = None
    if iot_hub:
        target_hub = iot_hub
        linked_hubs = cli.invoke(
            "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
        ).as_json()
        hub_host_name = "{}.azure-devices.net".format(target_hub["name"])

        if hub_host_name not in [hub["name"] for hub in linked_hubs]:
            cli.invoke(
                f"iot dps linked-hub create --dps-name {dps_name} -g {ENTITY_RG} "
                f"--connection-string {target_hub['connectionString']}"
            )
    elif settings.env.azext_iot_testdps:
        # Ensure 0 linked hubs
        linked_hubs = cli.invoke(
            "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
        ).as_json()
        for hub in linked_hubs:
            cli.invoke(
                f"iot dps linked-hub delete --dps-name {dps_name} -g {ENTITY_RG} --linked-hub {hub['name']}"
            )
    else:
        # time passed if hub was not linked
        sleep(30)

    return {
        "name": dps_name,
        "resourceGroup": ENTITY_RG,
        "dps": target_dps,
        "connectionString": get_dps_cstring(dps_name, ENTITY_RG),
        "hubHostName": hub_host_name,
        "hubConnectionString": iot_hub["connectionString"] if iot_hub else None,
        "certificates": []
    }


def get_dps_cstring(dps_name: str, dps_rg: str, policy: str = "provisioningserviceowner") -> str:
    return cli.invoke(
        "iot dps connection-string show -n {} -g {} --policy-name {}".format(
            dps_name, dps_rg, policy
        )
    ).as_json()["connectionString"]


def _iot_dps_removal(dps):
    for cert in dps["certificates"]:
        if os.path.exists(cert):
            try:
                os.remove(cert)
            except OSError as e:
                logger.error(f"Failed to remove {cert}. {e}")
    if not settings.env.azext_iot_testdps:
        cli.invoke(
            "iot dps delete --name {} --resource-group {}".format(
                dps["name"], dps["resourceGroup"]
            )
        )


# IoT Hub fixtures for DPS
@pytest.fixture(scope="session")
def provisioned_only_iot_hubs_session() -> dict:
    result = _iot_hubs_provisioner()
    yield result
    if result:
        _iot_hubs_removal(result)


def _iot_hubs_provisioner():
    """Note that this will create min iot hub for a dps test."""
    name = settings.env.azext_iot_testdps_hub or generate_hub_id()
    hub_list = cli.invoke(
        'iot hub list -g "{}"'.format(ENTITY_RG)
    ).as_json()

    # Check if the generated name is already used
    target_hub = None
    for hub in hub_list:
        if hub["name"] == name:
            target_hub = hub
            break

    # Create the min version dps and assign the correct roles
    if not target_hub:
        if settings.env.azext_iot_testdps_hub:
            logger.error(f"Hub {name} specified in pytest settings not found. DPS will be created")

        base_create_command = f"iot hub create -n {name} -g {ENTITY_RG} --sku S1"
        target_hub = cli.invoke(base_create_command).as_json()

    return {
        "hub": target_hub,
        "name": name,
        "rg": ENTITY_RG,
        "connectionString": _get_hub_connection_string(name, ENTITY_RG),
    }


def _get_hub_connection_string(name, rg, policy="iothubowner"):
    return cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            name, rg, policy
        )
    ).as_json()["connectionString"]


def _iot_hubs_removal(hub_result):
    if not settings.env.azext_iot_testdps_hub:
        name = hub_result["name"]
        delete_result = cli.invoke(f"iot hub delete -n {name} -g {ENTITY_RG}")
        if not delete_result.success():
            logger.error(f"Failed to delete iot hub resource {name}.")
