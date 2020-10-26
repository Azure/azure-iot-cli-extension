# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.testsdk import LiveScenarioTest
import pytest


@pytest.mark.skipif(True, reason="Skipping AICS tests due to environment inconsistencies")
class AICSLiveScenarioTest(LiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario

        super(AICSLiveScenarioTest, self).__init__(test_scenario)
        AICSLiveScenarioTest.handle = self
        self.kwargs.update({"BASE_URL": "https://test.certsvc.trafficmanager.net"})
