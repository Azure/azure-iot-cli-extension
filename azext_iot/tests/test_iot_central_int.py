# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azure.cli.testsdk import LiveScenarioTest

APP_ID = os.environ.get("azext_iot_central_app_id")
DEVICE_ID = os.environ.get("azext_iot_central_device_id")
DEVICE_TEMPLATE_ID = os.environ.get("azext_iot_central_device_template_id")

if not all([APP_ID, DEVICE_ID, DEVICE_TEMPLATE_ID]):
    raise ValueError(
        "Set azext_iot_central_app_id, azext_iot_central_device_id "
        "and azext_iot_central_device_template_id to run central integration tests. "
    )


class TestIotCentral(LiveScenarioTest):
    def __init__(self, test_case):
        super(TestIotCentral, self).__init__(test_case)

    def test_central_device_show(self):
        # Verify incorrect app-id throws error
        self.cmd(
            'iotcentral device-twin show --app-id incorrect-app --device-id "{}"'.format(
                DEVICE_ID
            ),
            expect_failure=True,
        )
        # Verify incorrect device-id throws error
        self.cmd(
            'iotcentral device-twin show --app-id "{}" --device-id incorrect-device'.format(
                APP_ID
            ),
            expect_failure=True,
        )
        # Verify that no errors are thrown when device shown
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd(
            'iotcentral device-twin show --app-id "{}" --device-id "{}"'.format(
                APP_ID, DEVICE_ID
            )
        )

    def test_central_monitor_events(self):
        # Test with invalid app-id
        self.cmd(
            "iotcentral app monitor-events --app-id {}".format(APP_ID + "zzz"),
            expect_failure=True,
        )
        # Ensure no failure
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd("iotcentral app monitor-events --app-id {} --to 1".format(APP_ID))

    def test_central_validate_messages(self):
        # Test with invalid app-id
        self.cmd(
            "iot central app validate-messages --app-id {}".format(APP_ID + "zzz"),
            expect_failure=True,
        )
        # Ensure no failure
        # We cannot verify that the result is correct, as the Azure CLI for IoT Central does not support adding devices
        self.cmd("iot central app validate-messages --app-id {} --to 1".format(APP_ID))

    def test_central_device_methods_CRLD(self):
        # currently: create, show, list, delete
        self.cmd(
            "iot central app device create --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[
                self.check("approved", True),
                self.check("displayName", DEVICE_ID),
                self.check("id", DEVICE_ID),
                self.check("simulated", False),
            ],
        )

        self.cmd(
            "iot central app device show --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[
                self.check("approved", True),
                self.check("displayName", DEVICE_ID),
                self.check("id", DEVICE_ID),
                self.check("simulated", False),
            ],
        )

        list_output = self.cmd("iot central app device list --app-id {}".format(APP_ID))

        self.cmd(
            "iot central app device delete --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[self.check("result", "success")],
        )

        assert DEVICE_ID in list_output.get_output_in_json()

    def test_central_device_template_methods_CRLD(self):
        # currently: create, show, list, delete
        self.cmd(
            "iot central app device create --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[
                self.check("approved", True),
                self.check("displayName", DEVICE_ID),
                self.check("id", DEVICE_ID),
                self.check("simulated", False),
            ],
        )

        self.cmd(
            "iot central app device show --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[
                self.check("approved", True),
                self.check("displayName", DEVICE_ID),
                self.check("id", DEVICE_ID),
                self.check("simulated", False),
            ],
        )

        list_output = self.cmd("iot central app device list --app-id {}".format(APP_ID))

        self.cmd(
            "iot central app device delete --app-id {} -d {}".format(APP_ID, DEVICE_ID),
            checks=[self.check("result", "success")],
        )

        assert DEVICE_ID in list_output.get_output_in_json()
