# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azure.cli.testsdk import LiveScenarioTest

# az account get-access-token --resource "https://apps.azureiotcentral.com"
AAD_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6ImllX3FXQ1hoWHh0MXpJRXN1NGM3YWNRVkduNCIsImtpZCI6ImllX3FXQ1hoWHh0MXpJRXN1NGM3YWNRVkduNCJ9.eyJhdWQiOiJodHRwczovL2FwcHMuYXp1cmVpb3RjZW50cmFsLmNvbSIsImlzcyI6Imh0dHBzOi8vc3RzLndpbmRvd3MubmV0LzcyZjk4OGJmLTg2ZjEtNDFhZi05MWFiLTJkN2NkMDExZGI0Ny8iLCJpYXQiOjE1Njc1NzYxMDgsIm5iZiI6MTU2NzU3NjEwOCwiZXhwIjoxNTY3NTgwMDA4LCJhY3IiOiIxIiwiYWlvIjoiQVZRQXEvOE1BQUFBeldLSkRNWG5qM1lTZWhiY0t5M2JaQzJnOXc1Z2JUY0ViNzB3QWFlV3dSQ2tXaU1qZGVMcjlWZ1dzUDE4RUNkblJZeUJockpPYkVkQ2JqdDg1clVNKzJxVnp6UDVsSC9NNW14aG8wQ1d4TUE9IiwiYW1yIjpbIndpYSIsIm1mYSJdLCJhcHBpZCI6IjA0YjA3Nzk1LThkZGItNDYxYS1iYmVlLTAyZjllMWJmN2I0NiIsImFwcGlkYWNyIjoiMCIsImZhbWlseV9uYW1lIjoiQmFya2VyIiwiZ2l2ZW5fbmFtZSI6IkphY2siLCJpcGFkZHIiOiIxNjcuMjIwLjI2LjIxNiIsIm5hbWUiOiJKYWNrIEJhcmtlciIsIm9pZCI6IjUyMzNjNzNlLTJmNzktNGNhYy1iOTU1LTY2ZDE2OTQ4MDk5NCIsIm9ucHJlbV9zaWQiOiJTLTEtNS0yMS0xMjQ1MjUwOTUtNzA4MjU5NjM3LTE1NDMxMTkwMjEtMTg3ODkxOSIsInB1aWQiOiIxMDAzMjAwMDM0MTJCQTAwIiwic2NwIjoidXNlcl9pbXBlcnNvbmF0aW9uIiwic3ViIjoiYXd1TFhray03ZGw0RU1fcGtFc21sZUc4RnR2Y3dtRGN1WUVpbTRMQ21kYyIsInRpZCI6IjcyZjk4OGJmLTg2ZjEtNDFhZi05MWFiLTJkN2NkMDExZGI0NyIsInVuaXF1ZV9uYW1lIjoiamFiYXJrQG1pY3Jvc29mdC5jb20iLCJ1cG4iOiJqYWJhcmtAbWljcm9zb2Z0LmNvbSIsInV0aSI6InNadUN4S0UtQlV5QXJJRmhQQzRBQUEiLCJ2ZXIiOiIxLjAifQ.J_y0g5Pgrs-Do43CmOfEAkEBHINvlsw2SZbkTjV7J9Q0-ox_kDygfSawKkXSu10fnQLNMFZuEuOUwLRMKuKo877BpypGq-G48QVxeoUueNtBPo_Dm8vyThneJYaPV1Nv2Q_h-DMRPYfvcJdBlpjMfzwYDArtoAjVkUdLWaddOp2JHURlci0Qm0eCwrYF3K1lI3Qh6_bLHNOlQzRNYeEcHohYu0d46b-yy1Xs8kpgV4yBp1seGghxAG4gn4IIXf68jnkAJSFbK9plD6bAe62TOmL3jbw4siYlVOjgCCHk5x6Q8Pg75kMcD7lxjeaBmZnw58zxLQdvtPl_faLJ3IYs3g"
APP_ID = "dcd2ad87-87f5-44b4-aa0e-05529a50a3ca"
DEVICE_ID = "82c12e9c-e9f3-4207-b56a-d79e4eb7e557"

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
        self.cmd('az iotcentral device-twin show --app-id "{}"  --device-id "{}"  --aad-token incorrect-token'.
                 format(APP_ID, DEVICE_ID), expect_failure=True)
        self.cmd('az iot central device-twin show --app-id "{}"  --device-id "{}"  --aad-token incorrect-token'.
                 format(APP_ID, DEVICE_ID), expect_failure=True)
        # Verify incorrect app-id throws error
        self.cmd('az iotcentral device-twin show --app-id incorrect-app  --device-id "{}"  --aad-token {}'.
                 format(DEVICE_ID, AAD_TOKEN), expect_failure=True)
        self.cmd('az iot central device-twin show --app-id incorrect-app  --device-id "{}"  --aad-token {}'.
                 format(DEVICE_ID, AAD_TOKEN), expect_failure=True)
        # Verify incorrect device-id throws error
        self.cmd('az iotcentral device-twin show --app-id "{}"  --device-id incorrect-device  --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=True)
        self.cmd('az iot central device-twin show --app-id "{}"  --device-id incorrect-device  --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=True)
        # Verify that no errors are thrown when device shown
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd('az iotcentral device-twin show --app-id "{}"  --device-id "{}"  --aad-token "{}"'.
                 format(APP_ID, DEVICE_ID, AAD_TOKEN), expect_failure=False)
        # self.cmd('az iot central device-twin show --app-id "{}"  --device-id "{}"  --aad-token "{}"'.
        #          format(APP_ID, DEVICE_ID, AAD_TOKEN), expect_failure=False)

    def test_central_monitor_events(self):
        # Test with invalid aad token
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN + "zzz"), expect_failure=True)
        self.cmd('iot central app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN + "zzz"), expect_failure=True)
        # Test with invalid app-id
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID + "zzz", AAD_TOKEN), expect_failure=True)
        self.cmd('iot central app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID + "zzz", AAD_TOKEN), expect_failure=True)
        # Ensure no failure
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd('iotcentral app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=False)
        self.cmd('iot central app monitor-events --app-id {} --aad-token {}'.
                 format(APP_ID, AAD_TOKEN), expect_failure=False)
