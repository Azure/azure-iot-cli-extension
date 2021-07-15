# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import unittest
import pytest
import json
import responses

from unittest import mock
from knack.util import CLIError
from azext_iot.sdk.product.models import DeviceTestTask, TestRun
from azext_iot.product.test.command_test_tasks import create, delete, show
from azext_iot.product.shared import TaskType
from azext_iot.product.shared import BASE_URL

mock_target = {}
mock_target["entity"] = BASE_URL
device_test_id = "12345"
device_test_task_id = "54321"
device_test_run_id = "67890"
task_result = {
    "id": device_test_task_id,
    "status": "Queued",
    "type": "QueueTestRun",
    "deviceTestId": device_test_id,
    "resultLink": "{}/testRuns/{}".format(device_test_id, device_test_run_id),
}

run_result = {
    "id": device_test_run_id,
    "start_time": "start_time",
    "end_time": "end_time",
    "status": "Completed",
    "certificationBadgeResults": [],
}

queued_task = DeviceTestTask(
    id=device_test_task_id, device_test_id=device_test_id, status="Queued"
)
started_task = DeviceTestTask(
    id=device_test_task_id, device_test_id=device_test_id, status="Started"
)
running_task = DeviceTestTask(
    id=device_test_task_id, device_test_id=device_test_id, status="Running"
)
completed_task = DeviceTestTask(
    id=device_test_task_id, device_test_id=device_test_id, status="Completed",
)

task_result_body = json.dumps(task_result)
finished_task_result_body = task_result_body.replace("Queued", "Completed")
api_string = "?api-version=2020-05-01-preview"


class TestTaskCreate(unittest.TestCase):
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test_task")
    def test_task_create(self, mock_create):
        create(self, test_id=device_test_id)
        mock_create.assert_called_with(
            device_test_id=device_test_id, task_type=TaskType.QueueTestRun.value
        )

    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test_task",
        return_value=queued_task,
    )
    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test_task",
        side_effect=iter([started_task, running_task, completed_task]),
    )
    @mock.patch("time.sleep")
    def test_task_create_wait(self, mock_sleep, mock_get, mock_create):
        result = create(self, test_id=device_test_id, wait=True, poll_interval=1)

        # one call to create
        mock_create.assert_called_with(
            device_test_id=device_test_id, task_type=TaskType.QueueTestRun.value
        )
        assert mock_create.call_count == 1

        # three calls to 'get' until status is 'Completed'
        mock_get.assert_called_with(
            task_id=device_test_task_id, device_test_id=device_test_id
        )
        assert mock_get.call_count == 3

        # make sure we get the last result back
        assert result.status == "Completed"

    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test_task",
        return_value=queued_task,
    )
    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test_task",
        side_effect=iter([started_task, running_task, completed_task]),
    )
    def test_task_create_no_wait(self, mock_get, mock_create):
        result = create(self, test_id=device_test_id, wait=False, poll_interval=1)

        # one call to create
        mock_create.assert_called_with(
            device_test_id=device_test_id, task_type=TaskType.QueueTestRun.value
        )
        assert mock_create.call_count == 1

        # no calls to 'get' since wait==Falce
        mock_get.assert_not_called()

        # initial create response returned
        assert result == queued_task

    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test_task",
        return_value={"error": "task currently running"},
    )
    def test_task_create_failure(self, mock_create):
        with self.assertRaises(CLIError) as context:
            create(self, test_id=device_test_id, wait=False)
            self.assertTrue({"error": "task currently running"}, context)

    @mock.patch(
        "azext_iot.sdk.product.aicsapi.AICSAPI.create_device_test_task",
        return_value=None,
    )
    def test_task_create_empty_response(self, mock_create):
        with self.assertRaises(CLIError) as context:
            create(self, test_id=device_test_id, wait=False)
            self.assertTrue(
                "Failed to create device test task - please ensure a device test exists with Id {}".format(
                    device_test_id
                ),
                context.exception,
            )


class TestTaskShow(unittest.TestCase):
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test_task")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_running_device_test_tasks")
    def test_task_show_task(self, mock_get_running, mock_get_task):
        show(self, test_id=device_test_id, task_id="456")
        mock_get_task.assert_called_with(task_id="456", device_test_id=device_test_id)
        self.assertEqual(mock_get_task.call_count, 1)
        self.assertEqual(mock_get_running.call_count, 0)

    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_device_test_task")
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.get_running_device_test_tasks")
    def test_task_show_running(self, mock_get_running, mock_get_task):
        show(self, test_id=device_test_id, running=True)
        mock_get_running.assert_called_with(device_test_id=device_test_id)
        self.assertEqual(mock_get_running.call_count, 1)
        self.assertEqual(mock_get_task.call_count, 0)

    def test_task_show_incorrect_params(self):
        with self.assertRaises(CLIError) as context:
            show(self, test_id=device_test_id)
            self.assertTrue(
                "Please provide a task-id for individual task details, or use the --running argument to list all running tasks",
                context.exception,
            )


class TestTaskDelete(unittest.TestCase):
    @mock.patch("azext_iot.sdk.product.aicsapi.AICSAPI.cancel_device_test_task")
    def test_task_delete(self, mock_delete):
        delete(self, test_id=device_test_id, task_id="234")
        assert mock_delete.call_count == 1
        mock_delete.assert_called_with(task_id="234", device_test_id=device_test_id)


class TestTasksSDK(object):

    # create call
    @pytest.fixture(params=[202])
    def service_client_create(self, mocked_response, fixture_mock_aics_token, request):

        # create test task
        mocked_response.add(
            method=responses.POST,
            url="{}/deviceTests/{}/tasks{}".format(
                mock_target["entity"], device_test_id, api_string
            ),
            body=task_result_body,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    # create task, get task, get run (for --wait)
    @pytest.fixture(params=[200])
    def service_client_create_wait(
        self, service_client_create, mocked_response, fixture_mock_aics_token, request
    ):
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/tasks/{}{}".format(
                mock_target["entity"], device_test_id, device_test_task_id, api_string
            ),
            body=finished_task_result_body,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        # get completed queued test run
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/testRuns/{}{}".format(
                mock_target["entity"], device_test_id, device_test_run_id, api_string
            ),
            body=json.dumps(run_result),
            headers={"x-ms-command-statuscode": str(200)},
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    # delete task
    @pytest.fixture(params=[202])
    def service_client_delete(self, mocked_response, fixture_mock_aics_token, request):
        mocked_response.add(
            method=responses.DELETE,
            url="{}/deviceTests/{}/tasks/{}{}".format(
                mock_target["entity"], device_test_id, device_test_task_id, api_string
            ),
            body="{}",
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    # get single task
    @pytest.fixture(params=[200])
    def service_client_get(self, mocked_response, fixture_mock_aics_token, request):

        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/tasks/{}{}".format(
                mock_target["entity"], device_test_id, device_test_task_id, api_string
            ),
            body=task_result_body,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    # get running tasks
    @pytest.fixture(params=[200])
    def service_client_get_running(
        self, mocked_response, fixture_mock_aics_token, request
    ):
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/tasks/running{}".format(
                mock_target["entity"], device_test_id, api_string
            ),
            body="[{}]".format(task_result_body),
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    def test_sdk_task_create(self, fixture_cmd, service_client_create):
        result = create(fixture_cmd, test_id=device_test_id)
        req = service_client_create.calls[0].request

        assert req.method == "POST"
        assert json.loads(req.body)["taskType"] == "QueueTestRun"
        assert result.id == device_test_task_id
        assert result.device_test_id == device_test_id

    def test_sdk_task_create_wait(self, fixture_cmd, service_client_create_wait):
        result = create(fixture_cmd, test_id=device_test_id, wait=True, poll_interval=1)
        reqs = list(map(lambda call: call.request, service_client_create_wait.calls))

        # Call 0 - create test task
        assert reqs[0].method == "POST"
        assert json.loads(reqs[0].body)["taskType"] == "QueueTestRun"
        url = reqs[0].url
        assert "deviceTests/{}/tasks".format(device_test_id) in url

        # Call 1 - get task status
        assert reqs[1].method == "GET"
        url = reqs[1].url
        assert (
            "deviceTests/{}/tasks/{}".format(device_test_id, device_test_task_id) in url
        )

        # Call 2 - get run results
        assert reqs[2].method == "GET"
        url = reqs[2].url
        assert (
            "deviceTests/{}/testRuns/{}".format(device_test_id, device_test_run_id)
            in url
        )

        # awaiting a queued test run should yield a test run object
        assert isinstance(result, TestRun)
        assert result.id == device_test_run_id
        assert result.status == "Completed"

    def test_sdk_task_delete(self, fixture_cmd, service_client_delete):
        result = delete(
            fixture_cmd, test_id=device_test_id, task_id=device_test_task_id
        )
        assert not result

        req = service_client_delete.calls[0].request
        url = req.url
        assert req.method == "DELETE"
        assert (
            "deviceTests/{}/tasks/{}".format(device_test_id, device_test_task_id) in url
        )

    def test_sdk_task_show_task(self, fixture_cmd, service_client_get):
        result = show(fixture_cmd, test_id=device_test_id, task_id=device_test_task_id)
        req = service_client_get.calls[0].request
        url = req.url
        assert (
            "deviceTests/{}/tasks/{}".format(device_test_id, device_test_task_id) in url
        )
        assert req.method == "GET"
        assert result.id == device_test_task_id
        assert result.device_test_id == device_test_id

    def test_sdk_task_show_running(self, fixture_cmd, service_client_get_running):
        result = show(fixture_cmd, test_id=device_test_id, running=True)
        req = service_client_get_running.calls[0].request
        url = req.url
        assert "deviceTests/{}/tasks/running".format(device_test_id) in url
        assert req.method == "GET"
        assert result[0].id == device_test_task_id
        assert result[0].device_test_id == device_test_id
