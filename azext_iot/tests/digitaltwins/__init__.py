# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import os
from ..generators import generate_generic_id
from azure.cli.testsdk import LiveScenarioTest

MOCK_RESOURCE_TAGS = "a=b;c=d"
MOCK_ENDPOINT_TAGS = "key0=value0;key1=value1;"


def generate_resource_id():
    return "dt{}".format(generate_generic_id())


def generate_group_id():
    return "group{}".format(generate_generic_id())


class DTLiveScenarioTest(LiveScenarioTest):
    group_location = "westus2"
    group_names = []
    dt_location_default = "eastus2euap"

    role_map = {
        "owner": "Azure Digital Twins Owner (Preview)",
        "reader": "Azure Digital Twins Reader (Preview)",
    }

    def __init__(self, test_scenario, group_names):
        assert test_scenario
        assert group_names

        os.environ["AZURE_CORE_COLLECT_TELEMETRY"] = "no"
        super(DTLiveScenarioTest, self).__init__(test_scenario)
        DTLiveScenarioTest.handle = self

        DTLiveScenarioTest.group_names = group_names
        self._bootup_scenario()

    def _bootup_scenario(self):
        self._is_provider_registered()
        for group_name in self.group_names:
            self.cmd("group create -n {} -l {}".format(group_name, self.group_location))

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

    @property
    def dt_location(self):
        return self.dt_location_default

    @dt_location.setter
    def dt_location(self, value):
        self.dt_location_default = value

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        target_groups = DTLiveScenarioTest.group_names
        # Ensure clean-up after ourselves.
        for group in target_groups:
            try:
                cls.handle.cmd("group delete -n {} -y --no-wait".format(group))
            except:
                pass
