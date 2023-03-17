# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from typing import Optional, List
import os

import pytest
from knack.log import get_logger

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.certops import create_self_signed_certificate
from azext_iot.tests.helpers import assign_role_assignment, clean_up_iothub_device_config, get_closest_marker, get_agent_public_ip
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_REQUIRED, ENV_SET_TEST_IOTHUB_OPTIONAL, ENV_SET_TEST_IOTDPS_OPTIONAL

logger = get_logger(__name__)
MAX_RBAC_ASSIGNMENT_TRIES = 10
HUB_USER_ROLE = "IoT Hub Data Contributor"
DPS_USER_ROLE = "Device Provisioning Service Data Contributor"
cli = EmbeddedCLI()
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

def generate_names(count=1):
    return [generate_generic_id()[:48] for _ in range(count)]


def generate_hub_depenency_id() -> str:
    return f"aziotclitest{generate_generic_id()}"[:24]


def assign_iot_hub_dataplane_rbac_role(hub_results):
    """Add IoT Hub Data Contributor role to current user"""
    for hub in hub_results:
        # Only add dataplane roles to the hubs that were not created mid test
        if hub.get("hub"):
            target_hub_id = hub["hub"]["id"]
            account = cli.invoke("account show").as_json()
            user = account["user"]

            if user["name"] is None:
                raise Exception("User not found")

            assign_role_assignment(
                assignee=user["name"],
                scope=target_hub_id,
                role=HUB_USER_ROLE,
                max_tries=MAX_RBAC_ASSIGNMENT_TRIES
            )

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


@pytest.fixture()
def fixture_provision_existing_hub_role(request):
    if settings.env.azext_iot_testhub:
        # Assign Data Contributor role
        account = cli.invoke("account show").as_json()
        user = account["user"]

        target_hub = cli.invoke(
            "iot hub show -n {} -g {}".format(settings.env.azext_iot_testhub, ENTITY_RG)
        ).as_json()

        assign_role_assignment(
            assignee=user["name"],
            scope=target_hub["id"],
            role=HUB_USER_ROLE,
            max_tries=MAX_RBAC_ASSIGNMENT_TRIES
        )
    yield


# IoT DPS fixtures
@pytest.fixture(scope="module")
def provisioned_iot_dps_module(request, provisioned_only_iot_hubs_session) -> dict:
    result = _iot_dps_provisioner(request, provisioned_only_iot_hubs_session)
    yield result
    if result:
        _iot_dps_removal(result)


def _iot_dps_provisioner(request, iot_hubs = None):
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
            logger.info(f"DPS {dps['name']} found.")
            break

    # Create the min version dps and assign the correct roles
    if not target_dps:
        if settings.env.azext_iot_testdps:
            logger.error(f"DPS {dps_name} specified in pytest settings not found. DPS will be created")

        base_command = f"iot dps create --name {dps_name} --resource-group {ENTITY_RG}"
        if iot_hubs:
            base_command += f" --tags hubname={iot_hubs[0]['name']}"
        target_dps = cli.invoke(base_command).as_json()
        logger.info(f"DPS {dps['name']} created.")

    assign_iot_dps_dataplane_rbac_role(target_dps)

    # Add link between dps and first iot hub
    target_hub = iot_hubs[0]
    linked_hubs = cli.invoke(
        "iot dps linked-hub list --dps-name {} -g {}".format(dps_name, ENTITY_RG)
    ).as_json()
    hub_host_name = "{}.azure-devices.net".format(target_hub["name"])

    if hub_host_name not in [hub["name"] for hub in linked_hubs]:
        cli.invoke(
            f"iot dps linked-hub create --dps-name {dps_name} -g {ENTITY_RG} "
            f"--connection-string {target_hub['connectionString']} --location {target_hub['hub']['location']}"
        )

    return {
        "name": dps_name,
        "resourceGroup": ENTITY_RG,
        "dps": target_dps,
        "connectionString": get_dps_cstring(dps_name, ENTITY_RG),
        "hubHostName": hub_host_name,
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
    if not settings.env.azext_iot_testdps_hub:
        cli.invoke(
            "iot hub delete --name {} --resource-group {}".format(
                dps["name"], dps["resourceGroup"]
            )
        )
        logger.info(f"DPS {dps['name']} deleted.")


# IoT Hub fixtures
@pytest.fixture(scope="session")
def provisioned_only_iot_hubs_session(request) -> dict:
    result = _iot_hubs_provisioner(request)
    yield result
    if result:
        _iot_hubs_removal(result)


def _iot_hubs_provisioner(request, provisioned_user_identity=None, provisioned_storage=None):
    hub_marker = get_closest_marker(request)
    desired_location = None
    desired_tags = None
    desired_sys_identity = False
    desired_user_identity = False
    desired_storage = None
    desired_count = 1

    if hub_marker:
        desired_location = hub_marker.kwargs.get("location")
        desired_tags = hub_marker.kwargs.get("desired_tags")
        desired_sys_identity = hub_marker.kwargs.get("sys_identity", False)
        desired_user_identity = hub_marker.kwargs.get("user_identity", False)
        desired_storage = hub_marker.kwargs.get("storage")
        desired_count = hub_marker.kwargs.get("count", 1)

    hub_results = []
    for _ in range(desired_count):
        name = generate_hub_id()
        base_create_command = f"iot hub create -n {name} -g {ENTITY_RG} --sku S1"
        if desired_sys_identity:
            base_create_command += " --mi-system-assigned"
        if desired_user_identity and provisioned_user_identity:
            user_identity_id = provisioned_user_identity["id"]
            base_create_command += f" --mi-user-assigned {user_identity_id}"
        if desired_tags:
            base_create_command += f" --tags {desired_tags}"
        if desired_location:
            base_create_command += f" -l {desired_location}"
        if desired_storage and provisioned_storage:
            storage_cstring = provisioned_storage["connectionString"]
            base_create_command += f" --fcs {storage_cstring} --fc fileupload"

        hub_obj = cli.invoke(base_create_command).as_json()
        hub_results.append({
            "hub": hub_obj,
            "name": name,
            "rg": ENTITY_RG,
            "connectionString": _get_hub_connection_string(name, ENTITY_RG),
            "storage": provisioned_storage
        })
    return hub_results


def _get_hub_connection_string(name, rg, policy="iothubowner"):
    return cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            name, rg, policy
        )
    ).as_json()["connectionString"]


def _iot_hubs_removal(hub_result):
    for hub in hub_result:
        name = hub["name"]
        delete_result = cli.invoke(f"iot hub delete -n {name} -g {ENTITY_RG}")
        if not delete_result.success():
            logger.error(f"Failed to delete iot hub resource {name}.")
