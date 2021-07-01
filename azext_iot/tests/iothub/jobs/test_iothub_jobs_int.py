# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json

from datetime import datetime, timedelta
from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES
from uuid import uuid4

settings = DynamoSettings(ENV_SET_TEST_IOTHUB_BASIC)
LIVE_HUB = settings.env.azext_iot_testhub if settings.env.azext_iot_testhub else "test-hub-" + str(uuid4())
LIVE_RG = settings.env.azext_iot_testrg


class TestIoTHubJobs(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubJobs, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    def test_jobs(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            device_count = 2
            device_ids_twin_tags = self.generate_device_names(device_count)
            device_ids_twin_props = self.generate_device_names(device_count)

            job_count = 3
            self.job_ids = self.generate_job_names(job_count)

            for device_id in device_ids_twin_tags + device_ids_twin_props:
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create -d {device_id} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase
                    )
                )

            # Focus is on scheduleUpdateTwin jobs until we improve JIT device simulation

            # Update twin tags scenario
            self.kwargs[
                "twin_patch_tags"
            ] = '{"tags": {"deviceClass": "Class1, Class2, Class3"}}'
            query_condition = "deviceId in ['{}']".format("','".join(device_ids_twin_tags))

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub job create --job-id {self.job_ids[0]} --job-type scheduleUpdateTwin -q \"{query_condition}\" "
                    f"-n {LIVE_HUB} -g {LIVE_RG} "
                    "--twin-patch '{twin_patch_tags}' --ttl 300 --wait",
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("jobId", self.job_ids[0]),
                    self.check("queryCondition", query_condition),
                    self.check("status", "completed"),
                    self.check("updateTwin.etag", "*"),
                    self.check(
                        "updateTwin.tags",
                        json.loads(self.kwargs["twin_patch_tags"])["tags"],
                    ),
                    self.check("type", "scheduleUpdateTwin"),
                ],
            )

            for device_id in device_ids_twin_tags:
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-twin show -d {device_id} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase
                    ),
                    checks=[
                        self.check(
                            "tags", json.loads(self.kwargs["twin_patch_tags"])["tags"]
                        )
                    ],
                )

            # Update twin desired properties
            self.kwargs[
                "twin_patch_props"
            ] = '{"properties": {"desired": {"arbitrary": "value"}}}'
            query_condition = "deviceId in ['{}']".format("','".join(device_ids_twin_props))

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub job create --job-id {self.job_ids[1]} --job-type scheduleUpdateTwin -q \"{query_condition}\" "
                    f"-n {LIVE_HUB} -g {LIVE_RG} "
                    "--twin-patch '{twin_patch_props}' --ttl 300 --wait",
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("jobId", self.job_ids[1]),
                    self.check("queryCondition", query_condition),
                    self.check("status", "completed"),
                    self.check("updateTwin.etag", "*"),
                    self.check(
                        "updateTwin.properties",
                        json.loads(self.kwargs["twin_patch_props"])["properties"],
                    ),
                    self.check("type", "scheduleUpdateTwin"),
                ],
            )

            # Error - omit queryCondition when scheduleUpdateTwin or scheduleDeviceMethod
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job create --job-id {} --job-type {} --twin-patch '{}' -n {}".format(
                        self.job_ids[1], "scheduleUpdateTwin", "{twin_patch_props}", LIVE_HUB
                    ),
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job create --job-id {} --job-type {} --twin-patch '{}' -n {}".format(
                        self.job_ids[1], "scheduleDeviceMethod", "{twin_patch_props}", LIVE_HUB
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Error - omit twin patch when scheduleUpdateTwin
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job create --job-id {} --job-type {} -q '*' -n {}".format(
                        self.job_ids[1], "scheduleUpdateTwin", LIVE_HUB
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Error - omit method name when scheduleDeviceMethod
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job create --job-id {} --job-type {} -q '*' -n {}".format(
                        self.job_ids[1], "scheduleDeviceMethod", LIVE_HUB
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Show Job tests
            # Using --wait when creating effectively uses show
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job show --job-id {} -n {} -g {}".format(
                        self.job_ids[0], LIVE_HUB, LIVE_RG
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("jobId", self.job_ids[0]),
                    self.check("type", "scheduleUpdateTwin"),
                ],
            )

            # Error - Show non-existant job
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job show --job-id notarealjobid -n {} -g {}".format(
                        LIVE_HUB, LIVE_RG
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # Cancel Job test
            # Create job to be cancelled - scheduled +7 days from now.
            scheduled_time_iso = (datetime.utcnow() + timedelta(days=6)).isoformat()

            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job create --job-id {} --job-type {} -q \"{}\" --twin-patch '{}' --start '{}' -n {} -g {}".format(
                        self.job_ids[2],
                        "scheduleUpdateTwin",
                        query_condition,
                        "{twin_patch_tags}",
                        scheduled_time_iso,
                        LIVE_HUB,
                        LIVE_RG,
                    ),
                    auth_type=auth_phase
                ),
                checks=[self.check("jobId", self.job_ids[2])],
            )

            # Allow time for job to transfer to scheduled state (cannot cancel job in running state)
            from time import sleep
            sleep(5)

            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job show --job-id {} -n {} -g {}".format(
                        self.job_ids[2], LIVE_HUB, LIVE_RG
                    ),
                    auth_type=auth_phase
                ),
                checks=[
                    self.check("jobId", self.job_ids[2]),
                    self.check("status", "scheduled"),
                ],
            )

            # Cancel job
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job cancel --job-id {} -n {} -g {}".format(
                        self.job_ids[2], LIVE_HUB, LIVE_RG
                    ),
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("jobId", self.job_ids[2]),
                    self.check("status", "cancelled"),
                ],
            )

            # Error - Cancel non-existant job
            self.cmd(
                self.set_cmd_auth_type(
                    "iot hub job cancel --job-id notarealjobid -n {} -g {}".format(
                        LIVE_HUB, LIVE_RG
                    ),
                    auth_type=auth_phase
                ),
                expect_failure=True,
            )

            # List Job tests
            # You can't explictly delete a job/job history so check for existance
            job_result_set = self.cmd(
                "iot hub job list -n {} -g {}".format(LIVE_HUB, LIVE_RG)
            ).get_output_in_json()

            self.validate_job_list(jobs_set=job_result_set)

    def validate_job_list(self, jobs_set):
        filtered_job_ids_result = {}

        for job in jobs_set:
            filtered_job_ids_result[job["jobId"]] = True

        for job_id in self.job_ids:
            assert job_id in filtered_job_ids_result
