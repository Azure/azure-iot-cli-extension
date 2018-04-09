# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

import os
from azure.cli.testsdk import ResourceGroupPreparer, ScenarioTest

LIVE_HUB = os.environ.get('azext_iot_testhub')


# These tests are primarily testing the mode 2 login mechanism for commands which works with a connection string.
class TestIoTHub(ScenarioTest):
    @ResourceGroupPreparer()
    def test_iot_hub(self, resource_group, resource_group_location):
        # device_id = self.create_random_name(prefix='test-device-cs-', length=32)

        hub = 'iot-hub-for-test'
        rg = resource_group
        loc = resource_group_location

        # Test 'az iot hub create'
        self.cmd('iot hub create -n {} -g {} --sku S1 --partition-count 4'.format(hub, resource_group),
                 checks=[self.check('resourceGroup', rg),
                         self.check('location', loc),
                         self.check('name', hub),
                         self.check('sku.name', 'S1'),
                         self.check('properties.eventHubEndpoints.events.partitionCount', '4')])
