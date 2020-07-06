# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.testsdk import LiveScenarioTest


class PNPLiveScenarioTest(LiveScenarioTest):
    def __init__(self, test_scenario):
        assert test_scenario

        super(PNPLiveScenarioTest, self).__init__(test_scenario)
        PNPLiveScenarioTest.handle = self
