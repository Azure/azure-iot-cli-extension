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
from azext_iot.iothub import job as subject
from azext_iot.common.shared import JobStatusType, JobType
from ..conftest import build_mock_response, path_service_client, mock_target


def generate_job_id():
    return "myjob-{}".format(str(uuid4()).replace("-", ""))


@pytest.fixture
def sample_job_show():
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


@pytest.fixture
def sample_job_status():
    return {"jobId": "test-job-wqcqw46tj6siwobiovgr4tv", "status": "cancelled"}


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
        fixture_cmd2,
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
            cmd=fixture_cmd2,
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
        body = args[0][2]

        assert "{}/jobs/v2/{}?".format(hub_name, job_id) in url
        assert method == "PUT"
        assert body["jobId"] == job_id
        assert body["startTime"] == start_time
        assert body["maxExecutionTimeInSeconds"] == ttl
        assert body["queryCondition"] == query_condition

        payload = json.loads(payload)

        if job_type == JobType.scheduleUpdateTwin.value:
            assert body["type"] == JobType.scheduleUpdateTwin.value
            payload["etag"] = "*"
            assert body["updateTwin"] == payload
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
        fixture_cmd2,
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
            cmd=fixture_cmd2,
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
        ],
    )
    def test_job_create_malformed(
        self,
        fixture_cmd2,
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
                cmd=fixture_cmd2,
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
        fixture_cmd2,
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
                cmd=fixture_cmd2,
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
    @pytest.fixture(params=[200])
    def serviceclient(
        self, mocker, fixture_ghcs, fixture_sas, request, sample_job_show
    ):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, sample_job_show
        )
        return service_client

    def test_job_show(self, fixture_cmd2, serviceclient, sample_job_show):
        target_job_id = generate_job_id()
        result = subject.job_show(
            cmd=fixture_cmd2, job_id=target_job_id, hub_name=mock_target["entity"]
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "{}/jobs/v2/{}?".format(mock_target["entity"], target_job_id) in url
        assert method == "GET"
        assert result == sample_job_show

    def test_job_show_error(self, fixture_cmd2, serviceclient_generic_error):
        target_job_id = generate_job_id()

        with pytest.raises(CLIError):
            subject.job_show(
                cmd=fixture_cmd2, job_id=target_job_id, hub_name=mock_target["entity"]
            )


class TestJobCancel:
    @pytest.fixture(params=[200])
    def serviceclient(
        self, mocker, fixture_ghcs, fixture_sas, request, sample_job_status
    ):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, sample_job_status
        )
        return service_client

    def test_job_cancel(self, fixture_cmd2, serviceclient, sample_job_status):
        target_job_id = generate_job_id()
        result = subject.job_cancel(
            cmd=fixture_cmd2, job_id=target_job_id, hub_name=mock_target["entity"]
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert (
            "{}/jobs/v2/{}/cancel?".format(mock_target["entity"], target_job_id) in url
        )
        assert method == "POST"
        assert result == sample_job_status

    def test_job_cancel_error(self, fixture_cmd2, serviceclient_generic_error):
        target_job_id = generate_job_id()

        with pytest.raises(CLIError):
            subject.job_cancel(
                cmd=fixture_cmd2, job_id=target_job_id, hub_name=mock_target["entity"]
            )


class TestJobList:
    @pytest.fixture(params=[200])
    def serviceclient(
        self, mocker, fixture_ghcs, fixture_sas, request, sample_job_list
    ):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param, sample_job_list[0], {"x-ms-continuation": None}
        )
        # Hack - for ease of access to expected count
        setattr(service_client, "expected_count", sample_job_list[1])

        return service_client

    @pytest.mark.parametrize(
        "job_type, job_status, top",
        [
            (JobType.scheduleUpdateTwin.value, JobStatusType.completed.value, 3),
            (JobType.scheduleDeviceMethod.value, JobStatusType.queued.value, 6),
            (None, None, None),
        ],
    )
    def test_job_list(self, fixture_cmd2, serviceclient, job_type, job_status, top):
        result = subject.job_list(
            cmd=fixture_cmd2,
            job_type=job_type,
            job_status=job_status,
            top=top,
            hub_name=mock_target["entity"],
        )

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert "{}/jobs/v2/query?".format(mock_target["entity"]) in url

        if job_type:
            assert "jobType={}".format(job_type)

        if job_status:
            assert "jobStatus={}".format(job_status)

        assert method == "GET"

        if serviceclient.expected_count:
            if top and top <= serviceclient.expected_count:
                assert len(result) == top
            else:
                assert len(result) == serviceclient.expected_count
        else:
            assert not len(result)
