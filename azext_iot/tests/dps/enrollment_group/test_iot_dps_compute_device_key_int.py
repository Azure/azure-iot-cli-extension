# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.dps import TEST_ENDORSEMENT_KEY


class TestDPSComputeDeviceKey(CaptureOutputLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDPSComputeDeviceKey, self).__init__(test_case)

    def test_dps_compute_device_key(self):
        offline_device_key = self.cmd(
            'az iot dps enrollment-group compute-device-key --key "{}" '
            "--registration-id myarbitrarydeviceId".format(TEST_ENDORSEMENT_KEY)
        ).output
        offline_device_key = offline_device_key.strip("\"'\n")
        assert offline_device_key == "cT/EXZvsplPEpT//p98Pc6sKh8mY3kYgSxavHwMkl7w="
