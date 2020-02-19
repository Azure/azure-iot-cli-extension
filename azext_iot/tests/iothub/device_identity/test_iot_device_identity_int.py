# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from ... import IoTLiveScenarioTest
from ...settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg
LIVE_HUB_CS = settings.env.azext_iot_testhub_cs


class TestIoTDeviceIdentity(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTDeviceIdentity, self).__init__(
            test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS
        )

        pass
