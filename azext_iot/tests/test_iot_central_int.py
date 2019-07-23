# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azure.cli.testsdk import LiveScenarioTest

# az account get-access-token --resource "https://apps.azureiotcentral.com"
AAD_TOKEN = os.environ.get('azext_iot_central_aad_token')
APP_ID = os.environ.get('azext_iot_central_app_id')
DEVICE_ID = os.environ.get('azext_iot_central_device_id')

if not all([AAD_TOKEN, APP_ID, DEVICE_ID]):
    raise ValueError('Set azext_iot_central_aad_token, azext_iot_central_app_id '
                     'and azext_iot_central_device_id to run integration tests. '
                     'An aad-token can be retrieved through the command `az account '
                     'get-access-token --resource "https://apps.azureiotcentral.com"`.')


class TestIotCentral(LiveScenarioTest):
    def __init__(self, test_method):  # pylint: disable=W0613
        super(TestIotCentral, self).__init__('test_central_device_show')


    def test_central_device_show(self):
        # Verify incorrect token throws error
        self.cmd('az iotcentral device show --app-id "{}"  --device-id "{}"  --aad-token incorrect-token'.
                 format(APP_ID, DEVICE_ID), expect_failure=True)
        # Verify incorrect app-id throws error
        self.cmd('az iotcentral device show --app-id incorrect-app  --device-id "{}"  --aad-token {}'.
                 format(DEVICE_ID, AAD_TOKEN), expect_failure=True)
        # Verify incorrect device-id throws error
        self.cmd('az iotcentral device show --app-id "{}"  --device-id incorrect-device  --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=True)
        # Verify that no errors are thrown when device shown
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd('az iotcentral device show --app-id "{}"  --device-id "{}"  --aad-token "{}"'.
                 format(APP_ID, DEVICE_ID, AAD_TOKEN), expect_failure=False)


    def test_central_monitor_events(self):
        # Test with invalid aad token
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN + "zzz"), expect_failure=True)
        # Test with invalid app-id
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID + "zzz", AAD_TOKEN), expect_failure=True)
        # Ensure no failure
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=False)
