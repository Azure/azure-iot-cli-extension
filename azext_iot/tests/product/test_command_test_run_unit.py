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
from datetime import datetime
from knack.util import CLIError
from azext_iot.product.test.command_test_runs import show, submit
from azext_iot.sdk.product.models import TestRun
from azext_iot.product.shared import BASE_URL

mock_target = {}
mock_target["entity"] = BASE_URL
device_test_id = "12345"
device_test_run_id = "67890"

api_string = "?api-version=2020-05-01-preview"

patch_get_latest_test_run = "azext_iot.sdk.product.aicsapi.AICSAPI.get_latest_test_run"
patch_get_test_run = "azext_iot.sdk.product.aicsapi.AICSAPI.get_test_run"
patch_submit_test_run = "azext_iot.sdk.product.aicsapi.AICSAPI.submit_test_run"

queued_task = TestRun(
    id=device_test_run_id,
    start_time=datetime.now(),
    end_time=datetime.now(),
    status="Queued",
)
started_task = TestRun(
    id=device_test_run_id,
    start_time=datetime.now(),
    end_time=datetime.now(),
    status="Started",
)
running_task = TestRun(
    id=device_test_run_id,
    start_time=datetime.now(),
    end_time=datetime.now(),
    status="Running",
)
completed_task = TestRun(
    id=device_test_run_id,
    start_time=datetime.now(),
    end_time=datetime.now(),
    status="Completed",
)

queued_task_obj = {
    "id": queued_task.id,
    "start_time": "start_time",
    "end_time": "end_time",
    "status": "Queued",
}

run_result_body = json.dumps(queued_task_obj)
finished_run_result_body = run_result_body.replace("Queued", "Completed")


class TestRunShow(unittest.TestCase):
    @mock.patch(patch_get_latest_test_run)
    @mock.patch(patch_get_test_run)
    def test_run_show_latest(self, mock_get, mock_get_latest):
        show(self, test_id=device_test_id)

        # no run_id, so should call get_latest
        mock_get_latest.assert_called_with(device_test_id=device_test_id)
        mock_get.assert_not_called()

    @mock.patch(patch_get_latest_test_run)
    @mock.patch(patch_get_test_run)
    def test_run_show(self, mock_get, mock_get_latest):
        show(self, test_id=device_test_id, run_id=device_test_run_id)

        # one call to get
        mock_get.assert_called_with(
            device_test_id=device_test_id, test_run_id=device_test_run_id
        )

        # does not call get_latest
        mock_get_latest.assert_not_called()

    @mock.patch(patch_get_latest_test_run, return_value=queued_task)
    @mock.patch(
        patch_get_test_run,
        side_effect=iter([started_task, running_task, completed_task]),
    )
    def test_run_show_latest_wait(self, mock_get, mock_get_latest):
        result = show(self, test_id=device_test_id, wait=True, poll_interval=1)
        assert mock_get_latest.call_count == 1

        # three calls to 'get' until status is 'Completed', using run-id from get_latest call
        mock_get.assert_called_with(
            test_run_id=mock_get_latest.return_value.id, device_test_id=device_test_id
        )
        assert mock_get.call_count == 3

        # make sure we get the last result back
        assert result.status == "Completed"

    @mock.patch(patch_get_test_run, return_value=None)
    def test_sdk_run_show_error(self, fixture_cmd):
        with self.assertRaises(CLIError) as context:
            show(fixture_cmd, test_id=device_test_id, run_id=device_test_run_id)

        self.assertEqual(
            "No test run found for test ID '{}' with run ID '{}'".format(
                device_test_id, device_test_run_id
            ),
            str(context.exception),
        )


class TestRunSubmit(unittest.TestCase):
    @mock.patch(patch_submit_test_run)
    def test_run_submit(self, mock_submit):
        submit(self, test_id=device_test_id, run_id=device_test_run_id)
        mock_submit.assert_called_with(
            device_test_id=device_test_id, test_run_id=device_test_run_id
        )


class TestRunSDK(object):

    # Gets
    @pytest.fixture(params=[200])
    def service_client_get(self, mocked_response, fixture_mock_aics_token, request):
        # get latest
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/testRuns/latest{}".format(
                mock_target["entity"], device_test_id, api_string
            ),
            body=run_result_body,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        # get specific (completed)
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/testRuns/{}{}".format(
                mock_target["entity"], device_test_id, device_test_run_id, api_string
            ),
            body=finished_run_result_body,
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    # submit
    @pytest.fixture(params=[204])
    def service_client_submit(self, mocked_response, fixture_mock_aics_token, request):
        mocked_response.add(
            method=responses.POST,
            url="{}/deviceTests/{}/testRuns/{}/submit{}".format(
                mock_target["entity"], device_test_id, device_test_run_id, api_string
            ),
            body="{}",
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    # get error (invalid test task or run id)
    @pytest.fixture(params=[404])
    def service_client_error(self, mocked_response, fixture_mock_aics_token, request):
        mocked_response.add(
            method=responses.GET,
            url="{}/deviceTests/{}/testRuns/{}{}".format(
                mock_target["entity"], device_test_id, device_test_run_id, api_string
            ),
            body="",
            headers={"x-ms-command-statuscode": str(request.param)},
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

    def test_sdk_run_show(self, fixture_cmd, service_client_get):
        # get latest run
        result = show(fixture_cmd, test_id=device_test_id)
        req = service_client_get.calls[0].request

        assert "deviceTests/{}/testRuns/latest".format(device_test_id) in req.url
        assert req.method == "GET"
        assert result.id == device_test_run_id

        # specific run
        result = show(fixture_cmd, test_id=device_test_id, run_id=device_test_run_id)
        req = service_client_get.calls[1].request

        assert (
            "deviceTests/{}/testRuns/{}".format(device_test_id, device_test_run_id)
            in req.url
        )
        assert req.method == "GET"
        assert result.id == device_test_run_id

    # get latest, with wait
    def test_sdk_run_show_wait(self, fixture_cmd, service_client_get):
        result = show(fixture_cmd, test_id=device_test_id, wait=True, poll_interval=1)
        reqs = list(map(lambda call: call.request, service_client_get.calls))
        assert reqs[0].method == "GET"
        url = reqs[0].url
        assert "deviceTests/{}/testRuns/latest".format(device_test_id) in url

        assert reqs[1].method == "GET"
        url = reqs[1].url
        assert (
            "deviceTests/{}/testRuns/{}".format(device_test_id, device_test_run_id)
            in url
        )

        assert result.id == device_test_run_id
        assert result.status == "Completed"

    def test_sdk_task_submit(self, fixture_cmd, service_client_submit):
        result = submit(fixture_cmd, test_id=device_test_id, run_id=device_test_run_id)
        assert not result

        req = service_client_submit.calls[0].request
        url = req.url
        assert req.method == "POST"
        assert (
            "deviceTests/{}/testRuns/{}/submit".format(
                device_test_id, device_test_run_id
            )
            in url
        )
