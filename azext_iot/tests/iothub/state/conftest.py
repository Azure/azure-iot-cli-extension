# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings
from azext_iot.tests.generators import generate_generic_id
from typing import  Optional, TypeVar
from knack.log import get_logger

logger = get_logger(__name__)
SubRequest = TypeVar('SubRequest')
Mark = TypeVar('Mark')


MAX_RBAC_ASSIGNMENT_TRIES = 10
USER_ROLE = "IoT Hub Data Contributor"


cli = EmbeddedCLI()
REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)
RG = settings.env.azext_iot_testrg


def generate_hub_id() -> str:
    return f"test-hub-{generate_generic_id()}"[:23]


def tags_to_dict(tags: str) -> dict:
    result = {}
    split_tags = tags.split()
    for tag in split_tags:
        kvp = tag.split("=")
        result[kvp[0]] = kvp[1]
    return result


def get_closest_marker(request: SubRequest) -> Mark:
    for item in request.session.items:
        if item.get_closest_marker("hub_infrastructure"):
            return item.get_closest_marker("hub_infrastructure")
    return request.node.get_closest_marker("hub_infrastructure")


@pytest.fixture(scope="module")
def provisioned_iothubs_module(request) -> Optional[dict]:
    result = _iot_hub_provisioner(request)
    _assign_dataplane_rbac_role(result)
    yield result
    if result:
        _iot_hub_removal(result)


@pytest.fixture
def provisioned_iothubs(request) -> Optional[dict]:
    result = _iot_hub_provisioner(request)
    _assign_dataplane_rbac_role(result)
    yield result
    if result:
        _iot_hub_removal(result)


def _iot_hub_provisioner(request, provisioned_user_identity=None):
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
        desired_sys_identity = hub_marker.kwargs.get("sys_identity")
        desired_user_identity = hub_marker.kwargs.get("user_identity")
        desired_storage = hub_marker.kwargs.get("storage")
        desired_count = hub_marker.kwargs.get("count", 1)

    print("number of hubs to provision")

    hub_results = []
    for _ in range(desired_count):
        name = generate_hub_id()
        base_create_command = f"iot hub create -n {name} -g {RG} --sku S1"
        if desired_sys_identity:
            base_create_command += " --mi-system-assigned"
        if desired_user_identity and provisioned_user_identity:
            user_identity_id = provisioned_user_identity["id"]
            base_create_command += f" --mi-user-assigned {user_identity_id}"
        if desired_tags:
            base_create_command = base_create_command + f" --tags {desired_tags}"
        if desired_location:
            base_create_command = base_create_command + f" -l {desired_location}"

        hub_obj = cli.invoke(base_create_command).as_json()
        hub_results.append({
            "hub": hub_obj,
            "name": name,
            "rg": RG,
            "connectionString": _get_connection_string(name, RG)
        })
    return hub_results


def _assign_dataplane_rbac_role(hub_results):
    for hub in hub_results:
        target_hub_id = hub["hub"]["id"]
        account = cli.invoke("account show").as_json()
        user = account["user"]

        if user["name"] is None:
            raise Exception("User not found")

        tries = 0
        while tries < MAX_RBAC_ASSIGNMENT_TRIES:
            role_assignments = _get_role_assignments(target_hub_id, USER_ROLE)
            role_assignment_principal_names = [assignment["principalName"] for assignment in role_assignments]
            if user["name"] in role_assignment_principal_names:
                break
            # else assign IoT Hub Data Contributor role to current user and check again
            cli.invoke(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    user["name"], USER_ROLE, target_hub_id
                )
            )
            sleep(10)

        if tries == MAX_RBAC_ASSIGNMENT_TRIES:
            raise Exception(
                "Reached max ({}) number of tries to assign RBAC role. Please re-run the test later "
                "or with more max number of tries.".format(MAX_RBAC_ASSIGNMENT_TRIES)
            )


def _get_connection_string(name, rg, policy="iothubowner"):
    return cli.invoke(
        "iot hub connection-string show -n {} -g {} --policy-name {}".format(
            name, rg, policy
        )
    ).as_json()["connectionString"]


def _get_role_assignments(scope, role):
    return cli.invoke(
        'role assignment list --scope "{}" --role "{}"'.format(
            scope, role
        )
    ).as_json()

def _iot_hub_removal(hub_result):
    for hub in hub_result:
        name = hub["name"]
        delete_result = cli.invoke(f"iot hub delete -n {name} -g {RG}")
        if not delete_result.success():
            logger.error(f"Failed to delete iot hub resource {name}.")
