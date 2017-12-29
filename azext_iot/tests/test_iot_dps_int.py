# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

from azure.cli.testsdk import ScenarioTest, ResourceGroupPreparer, ResourceGroupPreparer

#from ._test_utils import _create_test_cert, _delete_test_cert
import random


class IoTDpsTest(ScenarioTest):

    @ResourceGroupPreparer(parameter_name='group_name', parameter_name_for_location='group_location')
    def test_dps_device_enrollment_lifecycle(self, group_name, group_location):
        # Set up a provisioning service
        dps_name = self._create_test_dps(group_name, group_location)

        # Set up cert file for test
        cert_file = "testcert.cer"
        key_file = "testkey.pvk"
        max_int = 9223372036854775807
        _create_test_cert(cert_file, key_file, self.create_random_name(prefix='TESTCERT', length=24), 3, random.randint(0, max_int))

        self.cmd('iot dps device-enrollment create --enrollment-id {} --attestation-type {} -g {} --dps-name {}  -p {} --provisioning-status {}'
            .format(),
            checks=[
        ])


        # Tear down the provisioning service
        self._delete_test_dps(dps_name, group_name)
        _delete_test_cert(cert_file)

    def _create_test_dps(self, group_name, group_location):
        dps_name = dps_name = self.create_random_name('iot-dps-for-dps-test', length=48)
        self.cmd('az iot dps create -g {} -n {}'.format(group_name, dps_name), checks=[
            self.check('name', dps_name),
            self.check('location', group_location)
        ])
        return dps_name

    def _delete_test_dps(self, dps_name, group_name):
        self.cmd('az iot dps delete -g {} -n {}'.format(group_name, dps_name))

