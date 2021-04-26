# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from time import sleep
from . import AICSLiveScenarioTest
from azext_iot.product.shared import (
    TaskType,
    BadgeType,
    DeviceTestTaskStatus,
    AttestationType,
)


class TestProductDeviceTestTasks(AICSLiveScenarioTest):
    def __init__(self, test_case):
        super(TestProductDeviceTestTasks, self).__init__(test_case)
        self.kwargs.update(
            {
                "generate_task": TaskType.GenerateTestCases.value,
                "queue_task": TaskType.QueueTestRun.value,
            }
        )

    def test_e2e(self):

        # Test requirement list
        self.cmd("iot product requirement list  --base-url {BASE_URL}")

        self.kwargs.update({"badge_type": BadgeType.IotDevice.value})
        requirements_output = self.cmd(
            "iot product requirement list --bt {badge_type}  --base-url {BASE_URL}"
        ).get_output_in_json()
        expected = [
            {
                "badgeType": "IotDevice",
                "provisioningRequirement": {
                    "provisioningTypes": ["SymmetricKey", "TPM", "X509"]
                },
            }
        ]

        assert requirements_output == expected
        # Device test operations
        test = self.cmd(
            "iot product test create --at SymmetricKey --dt DevKit --base-url {BASE_URL}"
        ).get_output_in_json()
        assert test["deviceType"].lower() == "devkit"
        assert test["provisioningConfiguration"]["type"].lower() == "symmetrickey"
        assert test["provisioningConfiguration"]["symmetricKeyEnrollmentInformation"][
            "primaryKey"
        ]

        self.kwargs.update({"device_test_id": test["id"]})

        test = self.cmd(
            "iot product test show -t {device_test_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert test["id"] == self.kwargs["device_test_id"]

        updated = self.cmd(
            "iot product test update -t {device_test_id} --at symmetricKey --base-url {BASE_URL}"
        ).get_output_in_json()
        assert updated["id"] == self.kwargs["device_test_id"]
        assert (
            updated["provisioningConfiguration"]["type"]
            == AttestationType.symmetricKey.value
        )
        assert updated["provisioningConfiguration"]["symmetricKeyEnrollmentInformation"]

        # Generate test cases
        generate_task = self.cmd(
            "iot product test task create -t {device_test_id} --type {generate_task} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert generate_task["status"] == DeviceTestTaskStatus.queued.value

        test_task = self.cmd(
            "iot product test task show --running -t {device_test_id} --base-url {BASE_URL}"
        ).get_output_in_json()[0]

        assert json.dumps(test_task)
        assert test_task.get("status") == DeviceTestTaskStatus.queued.value
        assert test_task.get("error") is None
        assert test_task.get("type") == TaskType.GenerateTestCases.value

        # wait for generate task to complete
        sleep(5)

        self.kwargs.update({"generate_task_id": test_task["id"]})
        test_task = self.cmd(
            "iot product test task show -t {device_test_id} --task-id {generate_task_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert test_task.get("error") is None
        assert test_task.get("type") == TaskType.GenerateTestCases.value

        # Test case operations
        case_list = self.cmd(
            "iot product test case list -t {device_test_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert json.dumps(case_list)
        assert json.dumps(case_list["certificationBadgeTestCases"])

        # TODO: Test case update

        # Queue a test run, await the run results
        run = self.cmd(
            "iot product test task create -t {device_test_id} --type {queue_task} --wait --base-url {BASE_URL}"
        ).get_output_in_json()
        # test run currently fails without simulator
        assert run["status"] == DeviceTestTaskStatus.failed.value
        assert json.dumps(run["certificationBadgeResults"])

        self.kwargs.update({"run_id": run["id"]})
        # show run
        run_get = self.cmd(
            "iot product test run show -t {device_test_id} -r {run_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        # show latest run
        run_latest = self.cmd(
            "iot product test run show -t {device_test_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert run_get == run_latest
        assert run_get["id"] == run_latest["id"] == self.kwargs["run_id"]
        assert (
            run_get["status"]
            == run_latest["status"]
            == DeviceTestTaskStatus.failed.value
        )

        # Queue a test run without wait, get run_id
        queue_task = self.cmd(
            "iot product test task create -t {device_test_id} --type {queue_task} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert queue_task["type"] == TaskType.QueueTestRun.value
        assert queue_task["status"] == DeviceTestTaskStatus.queued.value

        self.kwargs.update({"queue_task_id": queue_task["id"]})

        # allow test to start running
        sleep(5)

        queue_task = self.cmd(
            "iot product test task show -t {device_test_id} --task-id {queue_task_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert queue_task["type"] == TaskType.QueueTestRun.value
        assert queue_task["status"] == DeviceTestTaskStatus.running.value

        # Cancel running test task
        self.cmd(
            "iot product test task delete -t {device_test_id} --task-id {queue_task_id} --base-url {BASE_URL}"
        )

        # allow test to be cancelled
        sleep(5)

        # get cancelled test task
        show = self.cmd(
            "iot product test task show -t {device_test_id} --task-id {queue_task_id} --base-url {BASE_URL}"
        ).get_output_in_json()

        assert show["status"] == DeviceTestTaskStatus.cancelled.value

        # # Submit run
        # self.cmd(
        #     "iot product test run submit -t {device_test_id} -r {run_id} --base-url {BASE_URL}",
        #     expect_failure=True,
        # )
