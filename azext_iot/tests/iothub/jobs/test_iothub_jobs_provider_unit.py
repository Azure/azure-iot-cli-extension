# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Provider-direct unit tests for JobProvider error-handling and conversion paths."""

import logging

import pytest
from azure.cli.core.azclierror import CLIInternalError, AzureResponseError

from azext_iot.common.shared import JobType, JobVersionType
from azext_iot.iothub.providers.job import JobProvider
from azext_iot.iothub.providers.base import CloudError, SerializationError

logging.disable(logging.CRITICAL)

jp_path = "azext_iot.iothub.providers.job"


def _cloud_error():
    return CloudError.__new__(CloudError)


def _provider(mocker, service_sdk=None):
    p = JobProvider.__new__(JobProvider)
    p.cmd = mocker.MagicMock()
    p.hub_name = "hub"
    p.target = {"entity": "hub.azure-devices.net"}
    sdk = service_sdk or mocker.MagicMock()
    mocker.patch.object(JobProvider, "get_sdk", return_value=sdk)
    return p, sdk


class TestCancelV1Error:
    def test_cancel_import_export_job_cloud_error(self, mocker):
        p, sdk = _provider(mocker)
        sdk.jobs.cancel_import_export_job.side_effect = _cloud_error()
        handle = mocker.patch(
            f"{jp_path}.handle_service_exception",
            side_effect=AzureResponseError("boom"),
        )
        with pytest.raises(AzureResponseError):
            p._cancel("job1", JobVersionType.v1)
        assert handle.called


class TestCreateErrors:
    def _request_models(self, mocker):
        # create() imports JobRequest / CloudToDeviceMethod locally; nothing to patch.
        pass

    def test_create_cloud_error(self, mocker):
        p, sdk = _provider(mocker)
        sdk.jobs.create_scheduled_job.side_effect = _cloud_error()
        handle = mocker.patch(
            f"{jp_path}.handle_service_exception",
            side_effect=AzureResponseError("boom"),
        )
        with pytest.raises(AzureResponseError):
            p.create(
                job_id="job1",
                job_type=JobType.scheduleUpdateTwin.value,
                query_condition="*",
                twin_patch='{"properties": {}}',
            )
        assert handle.called

    def test_create_serialization_error(self, mocker):
        p, sdk = _provider(mocker)
        sdk.jobs.create_scheduled_job.side_effect = SerializationError("bad iso8601")
        with pytest.raises(CLIInternalError):
            p.create(
                job_id="job1",
                job_type=JobType.scheduleUpdateTwin.value,
                query_condition="*",
                twin_patch='{"properties": {}}',
            )

    def test_create_wait_polls_until_complete(self, mocker):
        p, sdk = _provider(mocker)
        sdk.jobs.create_scheduled_job.return_value.response.json.return_value = {
            "status": "running"
        }
        # First poll -> running (triggers sleep), second poll -> completed (breaks).
        mocker.patch.object(
            JobProvider,
            "_get",
            side_effect=[{"status": "running"}, {"status": "completed"}],
        )
        sleep_mock = mocker.patch(f"{jp_path}.sleep")
        result = p.create(
            job_id="job1",
            job_type=JobType.scheduleUpdateTwin.value,
            query_condition="*",
            twin_patch='{"properties": {}}',
            wait=True,
            poll_interval=1,
            poll_duration=600,
        )
        assert result == {"status": "completed"}
        assert sleep_mock.called

    def test_create_wait_times_out(self, mocker):
        from datetime import datetime, timedelta

        p, sdk = _provider(mocker)
        sdk.jobs.create_scheduled_job.return_value.response.json.return_value = {
            "status": "running"
        }
        # Job never reaches a terminal state; the poll-duration window elapses.
        mocker.patch.object(
            JobProvider, "_get", return_value={"status": "running"}
        )
        t0 = datetime(2020, 1, 1, 0, 0, 0)
        fake_dt = mocker.patch(f"{jp_path}.datetime")
        fake_dt.now.side_effect = [t0, t0 + timedelta(seconds=999)]
        result = p.create(
            job_id="job1",
            job_type=JobType.scheduleUpdateTwin.value,
            query_condition="*",
            twin_patch='{"properties": {}}',
            wait=True,
            poll_interval=1,
            poll_duration=1,
        )
        assert result == {"status": "running"}


class TestConvertV1ToV2:
    def test_convert_includes_failure_reason(self, mocker):
        p, _ = _provider(mocker)
        job_v1 = mocker.MagicMock()
        job_v1.failure_reason = "something failed"
        job_v1.additional_properties = {}
        result = p._convert_v1_to_v2(job_v1)
        assert result["failureReason"] == "something failed"

    def test_convert_without_failure_reason(self, mocker):
        p, _ = _provider(mocker)
        job_v1 = mocker.MagicMock()
        job_v1.failure_reason = None
        job_v1.additional_properties = {}
        result = p._convert_v1_to_v2(job_v1)
        assert "failureReason" not in result
