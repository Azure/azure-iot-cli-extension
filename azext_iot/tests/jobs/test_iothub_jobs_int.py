# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json

from .. import IoTLiveScenarioTest
from ..settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC


settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg
LIVE_HUB_CS = settings.env.azext_iot_testhub_cs


class TestIoTHubJobs(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubJobs, self).__init__(test_case, LIVE_HUB, LIVE_RG, LIVE_HUB_CS)

    def test_job_create(self):
        device_count = 3
        device_ids = self.generate_device_names(device_count)

        job_count = 3
        job_ids = self.generate_job_names(job_count)

        for device_id in device_ids:
            self.cmd(
                "iot hub device-identity create -d {} -n {} -g {}".format(
                    device_id, LIVE_HUB, LIVE_RG
                )
            )

        # Focus is on scheduleUpdateTwin jobs until we improve JIT device simulation

        # Update twin tags scenario
        self.kwargs["twin_patch_tags"] = '{"tags": {"deviceClass": "Class1, Class2, Class3"}}'
        query_condition = "deviceId in ['{}']".format("','".join(device_ids))

        self.cmd(
            "iot hub job create --job-id {} --job-type {} -q \"{}\" --twin-patch '{}' -n {} -g {} --ttl 300 --wait".format(
                job_ids[0],
                "scheduleUpdateTwin",
                query_condition,
                "{twin_patch_tags}",
                LIVE_HUB,
                LIVE_RG,
            ),
            checks=[
                self.check("jobId", job_ids[0]),
                self.check("queryCondition", query_condition),
                self.check("status", "completed"),
                self.check("updateTwin.etag", "*"),
                self.check("updateTwin.tags", json.loads(self.kwargs["twin_patch_tags"])["tags"]),
                self.check("type", "scheduleUpdateTwin"),
            ]
        )

        for device_id in device_ids:
            self.cmd(
                "iot hub device-twin show -d {} -n {} -g {}".format(
                    device_id, LIVE_HUB, LIVE_RG
                ),
                checks=[
                    self.check("tags", json.loads(self.kwargs["twin_patch_tags"])["tags"])
                ],
            )

        # Update twin desired properties
