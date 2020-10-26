# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
import json
from random import randint
from functools import partial
from uuid import uuid4
from knack.cli import CLIError
from azext_iot.iothub import commands_job as subject
from azext_iot.common.shared import JobStatusType, JobType
from ...conftest import build_mock_response, path_service_client, mock_target


def generate_job_id():
    return "myjob-{}".format(str(uuid4()).replace("-", ""))


def generate_job_status(job_status):
    return {"jobId": "test-job-wqcqw46tj6siwobiovgr4tv", "status": job_status}


def generate_job_show(
    job_status="completed", job_type=JobType.scheduleUpdateTwin.value, job_version="v2"
):
    if job_version == "v2":
        return {
            "createdTime": "2020-01-06T21:44:00.8884134Z",
            "deviceJobStatistics": {
                "deviceCount": 2,
                "failedCount": 0,
                "pendingCount": 0,
                "runningCount": 0,
                "succeededCount": 2,
            },
            "endTime": "2020-01-06T21:44:06.2536519Z",
            "jobId": "test-job-wqcqw46tj6siwobiovgr4tv",
            "maxExecutionTimeInSeconds": 300,
            "queryCondition": "deviceId in ['test-device-h6fdugt36sp73msf3b5f','test-device-e226yjpant3k2g4fqqfx']",
            "startTime": "2020-01-06T21:44:00.8884134Z",
            "status": job_status,
            "type": job_type,
            "updateTwin": {
                "deviceId": None,
                "etag": "*",
                "tags": {"deviceClass": "Class1, Class2, Class3"},
            },
        }

    return {
        "endTimeUtc": "2020-01-08T22:51:23+00:00",
        "excludeKeysInExport": True,
        "failureReason": None,
        "jobId": "8f560573-97d5-48d3-a524-6a2d536356e9",
        "outputBlobContainerUri": "",
        "parentJobId": None,
        "progress": 100,
        "startTimeUtc": "2020-01-08T22:51:16+00:00",
        "status": job_status,
        "statusMessage": None,
        "type": job_type,
        "useSecondaryStorageAsSource": False,
    }


@pytest.fixture(params=["v2", "v1"])
def sample_job_show(request):
    if request.param == "v2":
        return {
            "createdTime": "2020-01-06T21:44:00.8884134Z",
            "deviceJobStatistics": {
                "deviceCount": 2,
                "failedCount": 0,
                "pendingCount": 0,
                "runningCount": 0,
                "succeededCount": 2,
            },
            "endTime": "2020-01-06T21:44:06.2536519Z",
            "jobId": "test-job-wqcqw46tj6siwobiovgr4tv",
            "maxExecutionTimeInSeconds": 300,
            "queryCondition": "deviceId in ['test-device-h6fdugt36sp73msf3b5f','test-device-e226yjpant3k2g4fqqfx']",
            "startTime": "2020-01-06T21:44:00.8884134Z",
            "status": "completed",
            "type": "scheduleUpdateTwin",
            "updateTwin": {
                "deviceId": None,
                "etag": "*",
                "tags": {"deviceClass": "Class1, Class2, Class3"},
            },
        }
    if request.param == "v1":
        return {
            "endTimeUtc": "2020-01-08T22:51:23+00:00",
            "excludeKeysInExport": True,
            "failureReason": None,
            "jobId": "8f560573-97d5-48d3-a524-6a2d536356e9",
            "outputBlobContainerUri": "",
            "parentJobId": None,
            "progress": 100,
            "startTimeUtc": "2020-01-08T22:51:16+00:00",
            "status": "completed",
            "statusMessage": None,
            "type": "export",
            "useSecondaryStorageAsSource": False,
        }


@pytest.fixture(params=[5, 0])
def sample_job_list(sample_job_show, request):
    result = []
    for _ in range(request.param):
        result.append(sample_job_show)
    return (result, request.param)


class TestJobCreate:
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    # Simulate scenario where --wait is specified
    @pytest.fixture(
        params=[
            (200, JobStatusType.completed.value),
            (200, JobStatusType.failed.value),
            (200, JobStatusType.cancelled.value),
        ]
    )
    def serviceclient_test_wait(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            # Job Queued
            build_mock_response(
                mocker,
                request.param[0],
                {
                    "jobId": "myjob",
                    "status": JobStatusType.queued.value,
                    "type": JobType.scheduleUpdateTwin.value,
                },
            ),
            build_mock_response(
                mocker,
                request.param[0],
                {
                    "jobId": "myjob",
                    "status": JobStatusType.running.value,
                    "type": JobType.scheduleUpdateTwin.value,
                },
            ),
            build_mock_response(
                mocker,
                request.param[0],
                {
                    "createdTime": "2020-01-01T01:06:38.2649798Z",
                    "deviceJobStatistics": {
                        "deviceCount": 6,
                        "failedCount": 0,
                        "pendingCount": 0,
                        "runningCount": 0,
                        "succeededCount": 6,
                    },
                    "endTime": "2020-01-01T01:06:42.4993645Z",
                    "jobId": "myjob",
                    "maxExecutionTimeInSeconds": 900,
                    "queryCondition": "*",
                    "startTime": "2020-01-01T01:06:38.2649798Z",
                    "status": request.param[1],
                    "type": "scheduleUpdateTwin",
                    "updateTwin": {
                        "deviceId": None,
                        "etag": "*",
                        "tags": {"deviceClass": "Class1, Class2"},
                    },
                },
            ),
        ]
        service_client.side_effect = test_side_effect

    @pytest.mark.parametrize(
        "job_id, job_type, hub_name, start_time, query_condition, payload, ttl, method_name, mct, mrt",
        [
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                None,
                None,
                None,
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                "mymethod",
                randint(30, 90),
                randint(30, 90),
            ),
        ],
    )
    def test_job_create(
        self,
        fixture_cmd,
        serviceclient,
        job_id,
        job_type,
        hub_name,
        start_time,
        query_condition,
        payload,
        ttl,
        method_name,
        mct,
        mrt,
    ):
        job_create = partial(
            subject.job_create,
            cmd=fixture_cmd,
            job_id=job_id,
            job_type=job_type,
            hub_name=hub_name,
            start_time=start_time,
            query_condition=query_condition,
            ttl=ttl,
        )

        if job_type == JobType.scheduleUpdateTwin.value:
            job_create(twin_patch=payload)
        elif job_type == JobType.scheduleDeviceMethod.value:
            job_create(
                method_name=method_name,
                method_payload=payload,
                method_connect_timeout=mct,
                method_response_timeout=mrt,
            )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = json.loads(args[0][0].body)

        assert "{}/jobs/v2/{}?".format(hub_name, job_id) in url
        assert method == "PUT"
        assert body["jobId"] == job_id
        assert body["startTime"] == start_time
        assert body["maxExecutionTimeInSeconds"] == ttl
        assert body["queryCondition"] == query_condition

        payload = json.loads(payload)

        if job_type == JobType.scheduleUpdateTwin.value:
            assert body["type"] == JobType.scheduleUpdateTwin.value
            assert body["updateTwin"] == {'etag': '*'}
        elif job_type == JobType.scheduleDeviceMethod.value:
            assert body["type"] == JobType.scheduleDeviceMethod.value
            assert body["cloudToDeviceMethod"]["methodName"] == method_name
            assert body["cloudToDeviceMethod"]["payload"] == payload
            assert body["cloudToDeviceMethod"]["responseTimeoutInSeconds"] == mrt
            assert body["cloudToDeviceMethod"]["connectTimeoutInSeconds"] == mct

    @pytest.mark.parametrize(
        "job_id, job_type, hub_name, start_time, query_condition, payload, ttl, wait, poll_interval, poll_duration",
        [
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                True,
                1,
                5,
            ),
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                None,
                10,
                5,
            ),
        ],
    )
    def test_job_create_wait(
        self,
        fixture_cmd,
        serviceclient_test_wait,
        job_id,
        job_type,
        hub_name,
        start_time,
        query_condition,
        payload,
        ttl,
        wait,
        poll_interval,
        poll_duration,
    ):
        job_create = partial(
            subject.job_create,
            cmd=fixture_cmd,
            job_id=job_id,
            job_type=job_type,
            hub_name=hub_name,
            start_time=start_time,
            query_condition=query_condition,
            ttl=ttl,
            wait=wait,
            poll_interval=poll_interval,
            poll_duration=poll_duration,
        )

        result = None
        if job_type == JobType.scheduleUpdateTwin.value:
            result = job_create(twin_patch=payload)

        assert isinstance(result, dict)

        if not wait:
            assert result["status"] == JobStatusType.queued.value

    @pytest.mark.parametrize(
        "job_id, job_type, hub_name, start_time, query_condition, payload, ttl,"
        "method_name, mct, mrt, poll_interval, poll_duration, expected_error",
        [
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                None,
                '{"key1":"value1"}',
                randint(300, 900),
                None,
                None,
                None,
                5,
                10,
                "The query condition is required",
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                None,
                '{"key1":"value1"}',
                randint(300, 900),
                "mymethod",
                randint(30, 90),
                randint(30, 90),
                5,
                10,
                "The query condition is required",
            ),
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                None,
                randint(300, 900),
                None,
                None,
                None,
                5,
                10,
                "job type requires --twin-patch",
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                None,
                randint(30, 90),
                randint(30, 90),
                5,
                10,
                "job type requires --method-name",
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                "mymethod",
                randint(30, 90),
                randint(30, 90),
                0,
                1,
                "--poll-interval must be greater than 0!",
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                "mymethod",
                randint(30, 90),
                randint(30, 90),
                1,
                0,
                "--poll-duration must be greater than 0!",
            ),
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                "100",
                randint(300, 900),
                None,
                randint(30, 90),
                randint(30, 90),
                1,
                5,
                "Twin patches must be objects. Received type:",
            ),
        ],
    )
    def test_job_create_malformed(
        self,
        fixture_cmd,
        serviceclient,
        job_id,
        job_type,
        hub_name,
        start_time,
        query_condition,
        payload,
        ttl,
        method_name,
        mct,
        mrt,
        poll_interval,
        poll_duration,
        expected_error,
    ):
        with pytest.raises(CLIError) as exc:
            job_create = partial(
                subject.job_create,
                cmd=fixture_cmd,
                job_id=job_id,
                job_type=job_type,
                hub_name=hub_name,
                start_time=start_time,
                query_condition=query_condition,
                ttl=ttl,
                poll_interval=poll_interval,
                poll_duration=poll_duration,
            )

            if job_type == JobType.scheduleUpdateTwin.value:
                job_create(twin_patch=payload)
            elif job_type == JobType.scheduleDeviceMethod.value:
                job_create(
                    method_name=method_name,
                    method_payload=payload,
                    method_connect_timeout=mct,
                    method_response_timeout=mrt,
                )

        exception_obj = str(exc.value)

        assert expected_error in exception_obj

    @pytest.mark.parametrize(
        "job_id, job_type, hub_name, start_time, query_condition, payload, ttl, method_name, mct, mrt",
        [
            (
                generate_job_id(),
                JobType.scheduleUpdateTwin.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                None,
                None,
                None,
            ),
            (
                generate_job_id(),
                JobType.scheduleDeviceMethod.value,
                mock_target["entity"],
                "2020-01-06T23:55:11.538201Z",
                "*",
                '{"key1":"value1"}',
                randint(300, 900),
                "mymethod",
                randint(30, 90),
                randint(30, 90),
            ),
        ],
    )
    def test_job_create_error(
        self,
        fixture_cmd,
        serviceclient_generic_error,
        job_id,
        job_type,
        hub_name,
        start_time,
        query_condition,
        payload,
        ttl,
        method_name,
        mct,
        mrt,
    ):
        with pytest.raises(CLIError):
            job_create = partial(
                subject.job_create,
                cmd=fixture_cmd,
                job_id=job_id,
                job_type=job_type,
                hub_name=hub_name,
                start_time=start_time,
                query_condition=query_condition,
                ttl=ttl,
            )

            if job_type == JobType.scheduleUpdateTwin.value:
                job_create(twin_patch=payload)
            elif job_type == JobType.scheduleDeviceMethod.value:
                job_create(
                    method_name=method_name,
                    method_payload=payload,
                    method_connect_timeout=mct,
                    method_response_timeout=mrt,
                )


class TestJobShow:
    @pytest.fixture(params=["v2", "v1"])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.scenario = request.param

        if request.param == "v2":
            service_client.side_effect = [
                build_mock_response(
                    mocker,
                    200,
                    generate_job_show(
                        job_status=JobStatusType.running.value,
                        job_version=request.param,
                    ),
                )
            ]
        elif request.param == "v1":
            service_client.side_effect = [
                build_mock_response(
                    mocker,
                    200,
                    generate_job_status(job_status=JobStatusType.unknown.value),
                ),
                build_mock_response(
                    mocker,
                    200,
                    generate_job_show(
                        job_status=JobStatusType.running.value,
                        job_type=JobType.exportDevices.value,
                        job_version=request.param,
                    ),
                ),
            ]

        return service_client

    def test_job_show(self, fixture_cmd, serviceclient):
        target_job_id = generate_job_id()
        result = subject.job_show(
            cmd=fixture_cmd, job_id=target_job_id, hub_name=mock_target["entity"]
        )

        args_list = serviceclient.call_args_list

        # Always start with get from v2 endpoint
        get_v2_url = args_list[0][0][0].url
        assert (
            "{}/jobs/v2/{}?".format(mock_target["entity"], target_job_id) in get_v2_url
        )
        assert args_list[0][0][0].method == "GET"

        if serviceclient.scenario == "v1":
            # Get from v2 endpoint, then Get from v1
            len(args_list) == 2
            get_v1_url = args_list[1][0][0].url
            assert (
                "{}/jobs/{}?".format(mock_target["entity"], target_job_id) in get_v1_url
            )
            assert args_list[1][0][0].method == "GET"
            assert result["type"] == "export" or result["type"] == "import"

            # ensure conversion from v1 to v2
            assert result["startTime"]
            assert result["endTime"]

    def test_job_show_error(self, fixture_cmd, serviceclient_generic_error):
        target_job_id = generate_job_id()

        with pytest.raises(CLIError):
            subject.job_show(
                cmd=fixture_cmd, job_id=target_job_id, hub_name=mock_target["entity"]
            )


class TestJobCancel:
    @pytest.fixture(params=["v2", "v1"])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.scenario = request.param

        if request.param == "v2":
            service_client.side_effect = [
                build_mock_response(
                    mocker,
                    200,
                    generate_job_show(
                        job_status=JobStatusType.running.value,
                        job_version=request.param,
                    ),
                ),
                build_mock_response(
                    mocker,
                    200,
                    generate_job_status(job_status=JobStatusType.cancelled.value),
                ),
            ]
        elif request.param == "v1":
            service_client.side_effect = [
                build_mock_response(
                    mocker,
                    200,
                    generate_job_status(job_status=JobStatusType.unknown.value),
                ),
                build_mock_response(
                    mocker,
                    200,
                    generate_job_show(
                        job_status=JobStatusType.running.value,
                        job_type=JobType.exportDevices.value,
                        job_version=request.param,
                    ),
                ),
                build_mock_response(
                    mocker,
                    200,
                    generate_job_status(job_status=JobStatusType.cancelled.value),
                ),
            ]

        return service_client

    def test_job_cancel(self, fixture_cmd, serviceclient):
        target_job_id = generate_job_id()
        result = subject.job_cancel(
            cmd=fixture_cmd, job_id=target_job_id, hub_name=mock_target["entity"]
        )

        args_list = serviceclient.call_args_list

        # Always start with get from v2 endpoint
        get_v2_url = args_list[0][0][0].url
        assert (
            "{}/jobs/v2/{}?".format(mock_target["entity"], target_job_id) in get_v2_url
        )
        assert args_list[0][0][0].method == "GET"
        assert result["status"] == JobStatusType.cancelled.value

        if serviceclient.scenario == "v2":
            # Get from v2 endpoint then cancel with v2
            len(args_list) == 2
            cancel_v2_url = args_list[1][0][0].url
            assert (
                "{}/jobs/v2/{}/cancel?".format(mock_target["entity"], target_job_id)
                in cancel_v2_url
            )
            assert args_list[1][0][0].method == "POST"
        elif serviceclient.scenario == "v1":
            # Get from v2 endpoint, Get from v1 endpoint, then cancel with v1
            len(args_list) == 3
            get_v1_url = args_list[1][0][0].url
            assert (
                "{}/jobs/{}?".format(mock_target["entity"], target_job_id) in get_v1_url
            )
            assert args_list[1][0][0].method == "GET"

            cancel_v1_url = args_list[2][0][0].url
            assert (
                "{}/jobs/{}?".format(mock_target["entity"], target_job_id)
                in cancel_v1_url
            )
            assert args_list[2][0][0].method == "DELETE"

    def test_job_cancel_error(self, fixture_cmd, serviceclient_generic_error):
        target_job_id = generate_job_id()

        with pytest.raises(CLIError):
            subject.job_cancel(
                cmd=fixture_cmd, job_id=target_job_id, hub_name=mock_target["entity"]
            )


class TestJobList:
    @pytest.fixture(
        params=[
            {
                "v2": [
                    {
                        "status": JobStatusType.completed.value,
                        "type": JobType.scheduleUpdateTwin.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.scheduleDeviceMethod.value,
                    },
                ],
                "v1": [
                    {
                        "status": JobStatusType.completed.value,
                        "type": JobType.exportDevices.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.exportDevices.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.importDevices.value,
                    },
                ],
            },
            {
                "v2": [
                    {
                        "status": JobStatusType.completed.value,
                        "type": JobType.scheduleUpdateTwin.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.scheduleDeviceMethod.value,
                    },
                ],
                "v1": [],
            },
            {
                "v2": [],
                "v1": [
                    {
                        "status": JobStatusType.completed.value,
                        "type": JobType.exportDevices.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.exportDevices.value,
                    },
                    {
                        "status": JobStatusType.failed.value,
                        "type": JobType.importDevices.value,
                    },
                ],
            },
            {"v2": [], "v1": []},
        ]
    )
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        try:
            from urllib.parse import urlparse, parse_qs
        except ImportError:
            from urlparse import urlparse, parse_qs

        service_client = mocker.patch(path_service_client)

        def handle_calls(*args, **kwargs):
            parsed_url = urlparse(args[0].url)
            parsed_qs = parse_qs(parsed_url.query)
            result_set = []

            if "/jobs?" in args[0].url:
                payload = request.param["v1"]

                for job in payload:
                    result_set.append(
                        generate_job_show(
                            job_status=job["status"],
                            job_type=job["type"],
                            job_version="v1",
                        )
                    )

                return build_mock_response(mocker, 200, result_set)

            if "/jobs/v2/query?" in args[0].url:
                payload = request.param["v2"]
                status_request = None
                type_request = None

                if "jobType" in parsed_qs:
                    type_request = parsed_qs["jobType"][0]

                if "jobStatus" in parsed_qs:
                    status_request = parsed_qs["jobStatus"][0]

                for job in payload:
                    if type_request:
                        if job["type"] != type_request:
                            continue
                    if status_request:
                        if job["status"] != status_request:
                            continue

                    result_set.append(
                        generate_job_show(
                            job_status=job["status"], job_type=job["type"]
                        )
                    )

                return build_mock_response(
                    mocker, 200, result_set, {"x-ms-continuation": None}
                )

        service_client.side_effect = handle_calls
        service_client.scenario = request.param

        return service_client

    @pytest.mark.parametrize(
        "job_type, job_status, top",
        [
            (JobType.scheduleUpdateTwin.value, None, None),
            (JobType.scheduleDeviceMethod.value, JobStatusType.completed.value, None),
            (JobType.exportDevices.value, JobStatusType.failed.value, 1),
            (None, None, None),
            (None, None, 2),
            (None, None, 5),
        ],
    )
    def test_job_list(self, fixture_cmd, serviceclient, job_type, job_status, top):
        result = subject.job_list(
            cmd=fixture_cmd,
            job_type=job_type,
            job_status=job_status,
            top=top,
            hub_name=mock_target["entity"],
        )

        scenario = serviceclient.scenario
        args_list = serviceclient.call_args_list
        kpis = self.parse_scenario_kpi(
            scenario=scenario, job_status=job_status, job_type=job_type
        )

        if (
            job_type
            in [JobType.scheduleUpdateTwin.value, JobType.scheduleDeviceMethod.value]
            or job_type is None
        ):
            query_v2_url = args_list[0][0][0].url
            assert "{}/jobs/v2/query?".format(mock_target["entity"]) in query_v2_url
            assert args_list[0][0][0].method == "GET"

            if job_type:
                assert "jobType={}".format(job_type) in query_v2_url

            if job_status:
                assert "jobStatus={}".format(job_status) in query_v2_url

        if (
            job_type in [JobType.exportDevices.value, JobType.importDevices.value]
            or job_type is None
        ):

            v1_call_args = None
            if job_type:
                # If v1 JobType is specified then only the v1 API is called
                v1_call_args = args_list[0][0][0]
            elif (top and len(kpis["v2_in_criteria"]) < top) or not top:
                v1_call_args = args_list[1][0][0]

            if v1_call_args:
                assert "{}/jobs?".format(mock_target["entity"]) in v1_call_args.url
                assert v1_call_args.method == "GET"

        if job_type:
            for job in result:
                assert job["type"] == job_type

        if job_status:
            for job in result:
                assert job["status"] == job_status

        if top and top <= len(kpis["total_in_criteria"]):
            assert len(result) == top
        else:
            assert len(result) == len(kpis["total_in_criteria"])

    def parse_scenario_kpi(self, scenario, job_status=None, job_type=None):
        def _in_criteria(job_collection, job_status, job_type):
            filtered = []

            for job in job_collection:
                if job_status and job["status"] != job_status:
                    continue
                if job_type and job["type"] != job_type:
                    continue
                filtered.append(job)
            return filtered

        v1_jobs = scenario["v1"]
        v2_jobs = scenario["v2"]

        result = {
            "v1_in_criteria": _in_criteria(v1_jobs, job_status, job_type),
            "v2_in_criteria": _in_criteria(v2_jobs, job_status, job_type),
        }
        result["total_in_criteria"] = (
            result["v2_in_criteria"] + result["v1_in_criteria"]
        )
        result["total_count"] = len(v1_jobs) + len(v2_jobs)

        return result

    def test_job_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.job_list(cmd=fixture_cmd, hub_name=mock_target["entity"])
