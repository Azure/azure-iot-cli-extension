# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.iothub.conftest import generate_hub_id, RG


cli = EmbeddedCLI()
logger = get_logger(__name__)


@pytest.fixture()
def provisioned_mqtt5_hub():
    name = generate_hub_id()
    try:
        hub_resource = cli.invoke(
            f"iot hub create -n {name} -g {RG} --sku S1 "
            "--connection-profile MqttV5 --yes",
            capture_stderr=True,
        )
        yield hub_resource.as_json()
    finally:
        cleanup = EmbeddedCLI().invoke(f"iot hub delete -n {name} -g {RG}")
        if not cleanup.success():
            logger.error(
                "Failed to clean up MQTT 5 integration-test Hub '%s': %s",
                name,
                cleanup.get_error(),
            )


def test_mqtt5_profile_lifecycle(provisioned_mqtt5_hub):
    hub_name = provisioned_mqtt5_hub["name"]
    hub = cli.invoke(
        f"iot hub show -n {hub_name} -g {RG}",
        capture_stderr=True,
    ).as_json()
    assert hub["properties"]["connectionProfile"].casefold() == "mqttv5"
    assert hub["properties"]["provisioningState"] == "Succeeded"
    assert hub["properties"]["state"] == "Active"
