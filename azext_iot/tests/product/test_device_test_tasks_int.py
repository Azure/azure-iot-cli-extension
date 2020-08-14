# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from time import sleep
from . import AICSLiveScenarioTest
from azext_iot.product.shared import TaskType, DeviceTestTaskStatus


class TestProductDeviceTestTasks(AICSLiveScenarioTest):
    def __init__(self, _):
        super(TestProductDeviceTestTasks, self).__init__(_)
        self.kwargs.update(
            {
                "device_test_id": "524ac74f-752b-4748-9667-45cd09e8a098",
                "generate_task": TaskType.GenerateTestCases.value,
                "queue_task": TaskType.QueueTestRun.value,
            }
        )

    def setup(self):
        return True

    def teardown(self):
        return True

    def test_product_device_test_tasks(self):

        # create task for GenerateTestCases
        created = self.cmd(
            "iot product test task create -t {device_test_id} --type {generate_task} --wait --base-url {BASE_URL}"
        ).get_output_in_json()
        assert created["deviceTestId"] == self.kwargs["device_test_id"]
        assert json.dumps(created)

        test_task_id = created["id"]
        self.kwargs.update({"device_test_task_id": test_task_id})

        # show task
        show = self.cmd(
            "iot product test task show -t {device_test_id} --task-id {device_test_task_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        assert json.dumps(show)
        assert show["deviceTestId"] == self.kwargs["device_test_id"]
        assert show["id"] == self.kwargs["device_test_task_id"]

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
        assert queue_task["status"] != DeviceTestTaskStatus.queued.value

        if queue_task["status"] == DeviceTestTaskStatus.running:
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
