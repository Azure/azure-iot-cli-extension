# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import os
from ..generators import generate_generic_id
from ..settings import DynamoSettings
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.embedded_cli import EmbeddedCLI


MOCK_RESOURCE_TAGS = "a=b c=d"
MOCK_RESOURCE_TAGS_DICT = {"a": "b", "c": "d"}
MOCK_DEAD_LETTER_SECRET = (
    "https://accountname.blob.core.windows.net/containerName?sasToken"
)


def generate_resource_id():
    return "dt{}".format(generate_generic_id())


class DTLiveScenarioTest(LiveScenarioTest):
    role_map = {
        "owner": "Azure Digital Twins Data Owner",
        "reader": "Azure Digital Twins Data Reader",
    }

    def __init__(self, test_scenario):
        assert test_scenario

        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        super(DTLiveScenarioTest, self).__init__(test_scenario)
        self.settings = DynamoSettings(
            opt_env_set=["azext_iot_testrg", "azext_dt_resource_location"]
        )
        self.embedded_cli = EmbeddedCLI()
        self._bootup_scenario()

    def _bootup_scenario(self):
        self._is_provider_registered()
        self._init_basic_env_vars()

    def _is_provider_registered(self):
        result = self.cmd(
            "provider show --namespace 'Microsoft.DigitalTwins' --query 'registrationState'"
        )
        if '"registered"' in result.output.lower():
            return

        pytest.skip(
            "Microsoft.DigitalTwins provider not registered. "
            "Run 'az provider register --namespace Microsoft.DigitalTwins'"
        )

    def _init_basic_env_vars(self):
        self._location = self.settings.env.azext_dt_resource_location
        if not self._location:
            self._location = "westus2"

        self._rg = self.settings.env.azext_iot_testrg
        if not self._rg:
            pytest.skip(
                "Digital Twins CLI tests requires at least 'azext_iot_testrg' for resource deployment."
            )

        self._rg_loc = self.embedded_cli.invoke(
            "group show --name {}".format(self._rg)
        ).as_json()["location"]

    @property
    def current_user(self):
        return self.embedded_cli.invoke("account show").as_json()["user"]["name"]

    @property
    def current_subscription(self):
        return self.embedded_cli.invoke("account show").as_json()["id"]

    @property
    def dt_location(self):
        return self._location

    @dt_location.setter
    def dt_location(self, value):
        self._location = value

    @property
    def dt_resource_group(self):
        return self._rg

    @dt_resource_group.setter
    def dt_resource_group(self, value):
        self._rg = value

    @property
    def dt_resource_group_loc(self):
        return self._rg_loc
