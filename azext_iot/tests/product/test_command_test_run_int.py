# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from . import AICSLiveScenarioTest
from azext_iot.product.shared import TaskType


class TestProductDeviceTestRuns(AICSLiveScenarioTest):
    def __init__(self, _):
        super(TestProductDeviceTestRuns, self).__init__(_)
        self.kwargs.update(
            {
                "device_test_id": "524ac74f-752b-4748-9667-45cd09e8a098",
                "generate_task": TaskType.GenerateTestCases.value,
                "run_task": TaskType.QueueTestRun.value,
            }
        )

    def setup(self):
        # setup test runs
        gen_task_id = self.cmd(
            "iot product test task create -t {device_test_id} --type {generate_task} --wait --base-url {BASE_URL}"
        ).get_output_in_json()["id"]
        queue_task_id = self.cmd(
            "iot product test task create -t {device_test_id} --type {run_task} --wait --base-url {BASE_URL}"
        ).get_output_in_json()["id"]
        self.kwargs.update(
            {"generate_task_id": gen_task_id, "queue_task_id": queue_task_id}
        )

    def teardown(self):
        self.cmd(
            "iot product test task delete -t {device_test_id} --task-id {generate_task_id} --base-url {BASE_URL}"
        )
        self.cmd(
            "iot product test task delete -t {device_test_id} --task-id {queue_task_id} --base-url {BASE_URL}"
        )

    def test_product_device_test_run(self):
        # get latest test run
        latest = self.cmd(
            "iot product test run show -t {device_test_id} --base-url {BASE_URL}"
        ).get_output_in_json()
        run_id = latest["id"]
        self.kwargs.update({"test_run_id": run_id})
        specific = self.cmd(
            "iot product test run show -t {device_test_id} -r {test_run_id} --base-url {BASE_URL}"
        ).get_output_in_json()

        assert latest == specific

        # bad test/run id
        self.cmd(
            "iot product test run show -t bad_test_id -r bad_run_id --base-url {BASE_URL}",
            expect_failure=True,
        )

        # submit (currently cannot submit failed test)
        self.cmd(
            "iot product test run submit -t {device_test_id} -r {test_run_id} --base-url {BASE_URL}",
            expect_failure=True,
        )
