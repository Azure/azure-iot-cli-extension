# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.settings import DynamoSettings
from azext_iot.tests.generators import generate_generic_id
from typing import List, Tuple, Optional, Dict, Any
from knack.log import get_logger

logger = get_logger(__name__)


cli = EmbeddedCLI()


REQUIRED_TEST_ENV_VARS = ["azext_iot_testrg"]
settings = DynamoSettings(req_env_set=REQUIRED_TEST_ENV_VARS)

ACCOUNT_RG = settings.env.azext_iot_testrg
VALID_IDENTITY_MAP = {"system": 1, "user": 1}
DEFAULT_ADU_RBAC_SLEEP_SEC = 105

# Manifest v4 will work with deviceUpdateModel;[1|2] but v5 only with deviceUpdateModel;2
ADU_CLIENT_DTMI = "dtmi:azure:iot:deviceUpdateModel;2"


def generate_hub_id() -> str:
    return f"test-hub-{generate_generic_id()}"[:23]


def tags_to_dict(tags: str) -> dict:
    result = {}
    split_tags = tags.split()
    for tag in split_tags:
        kvp = tag.split("=")
        result[kvp[0]] = kvp[1]
    return result


@pytest.fixture(scope="module")
def provisioned_iothubs_module(request) -> Optional[dict]:
    result = _iothub_provisioner(request)
    yield result
    if result:
        _iothub_removal(result)


@pytest.fixture
def provisioned_iothubs(request) -> Optional[dict]:
    result = _iothub_provisioner(request)
    yield result
    if result:
        _iothub_removal(result)


def _iothub_provisioner(request) -> Optional[dict]:
    acct_marker = request.node.get_closest_marker("hub_infrastructure")
    if acct_marker:
        desired_instance_count = acct_marker.kwargs.get("instance_count")
        if desired_instance_count:
            hub_id_map = {}
            hub_names = []
            for _ in range(desired_instance_count):
                target_name = generate_hub_id()
                create_result = cli.invoke(f"iot hub create -g {ACCOUNT_RG} -n {target_name}")
                if not create_result.success():
                    raise RuntimeError(f"Failed to provision iot hub resource {target_name}.")
                create_result = create_result.as_json()
                hub_id_map[create_result["id"]] = create_result
                hub_names.append(target_name)
            return hub_id_map


def _iothub_removal(hub_id_map: Dict[str, Any]):
    for target_id in hub_id_map:
        target_name = target_id.split("/")[-1]
        delete_result = cli.invoke(f"iot hub delete -g {ACCOUNT_RG} -n {target_name}")
        if not delete_result.success():
            logger.error(f"Failed to delete iot hub resource {target_name}.")
