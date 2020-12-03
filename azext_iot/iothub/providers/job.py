# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from datetime import datetime, timedelta
from knack.log import get_logger
from knack.util import CLIError
from azext_iot.common.shared import SdkType, JobStatusType, JobType, JobVersionType
from azext_iot.common.utility import unpack_msrest_error, process_json_arg
from azext_iot.operations.generic import _execute_query, _process_top
from azext_iot.iothub.providers.base import IoTHubProvider, CloudError, SerializationError


logger = get_logger(__name__)


class JobProvider(IoTHubProvider):
    def get(self, job_id):
        job_result = self._get(job_id)
        if "status" in job_result and job_result["status"] == JobStatusType.unknown.value:
            # Replace 'unknown' v2 result with v1 result
            job_result = self._get(job_id, JobVersionType.v1)

        return job_result

    def _get(self, job_id, job_version=JobVersionType.v2):
        service_sdk = self.get_sdk(SdkType.service_sdk)

        try:
            if job_version == JobVersionType.v2:
                return service_sdk.jobs.get_scheduled_job(id=job_id, raw=True).response.json()
            return self._convert_v1_to_v2(service_sdk.jobs.get_import_export_job(id=job_id))
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def cancel(self, job_id):
        job_result = self.get(job_id)
        if "type" in job_result and job_result["type"] in [JobType.exportDevices.value, JobType.importDevices.value]:
            # v1 Job
            return self._cancel(job_id, JobVersionType.v1)

        # v2 Job
        return self._cancel(job_id)

    def _cancel(self, job_id, job_version=JobVersionType.v2):
        service_sdk = self.get_sdk(SdkType.service_sdk)

        try:
            if job_version == JobVersionType.v2:
                return service_sdk.jobs.cancel_scheduled_job(id=job_id, raw=True).response.json()
            return service_sdk.jobs.cancel_import_export_job(id=job_id)
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def list(self, job_type=None, job_status=None, top=None):
        top = _process_top(top)
        jobs_collection = []

        if (
            job_type not in [JobType.exportDevices.value, JobType.importDevices.value]
            or not job_type
        ):
            jobs_collection.extend(
                self._list(job_type=job_type, job_status=job_status, top=top)
            )

        if (
            job_type in [JobType.exportDevices.value, JobType.importDevices.value]
            or not job_type
        ):
            if (top and len(jobs_collection) < top) or not top:
                jobs_collection.extend(self._list(job_version=JobVersionType.v1))

                # v1 API has no means of filtering service side :(
                jobs_collection = self._filter_jobs(
                    jobs=jobs_collection, job_type=job_type, job_status=job_status
                )

                # Trim based on top, since there is no way to pass a 'top' into the v1 API :(
                if top:
                    jobs_collection = jobs_collection[:top]

        return jobs_collection

    def _list(self, job_type=None, job_status=None, top=None, job_version=JobVersionType.v2):
        service_sdk = self.get_sdk(SdkType.service_sdk)
        jobs_collection = []

        try:
            if job_version == JobVersionType.v2:
                query = [job_type, job_status]
                query_method = service_sdk.jobs.query_scheduled_jobs
                jobs_collection.extend(_execute_query(query, query_method, top))
            elif job_version == JobVersionType.v1:
                jobs_collection.extend(service_sdk.jobs.get_import_export_jobs())
                jobs_collection = [self._convert_v1_to_v2(job) for job in jobs_collection]

            return jobs_collection
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def create(
        self,
        job_id,
        job_type,
        start_time=None,
        query_condition=None,
        twin_patch=None,
        method_name=None,
        method_payload=None,
        method_connect_timeout=30,
        method_response_timeout=30,
        ttl=3600,
        wait=False,
        poll_interval=10,
        poll_duration=600,
    ):
        from azext_iot.sdk.iothub.service.models import (
            CloudToDeviceMethod,
            JobRequest
        )

        if (
            job_type
            in [JobType.scheduleUpdateTwin.value, JobType.scheduleDeviceMethod.value]
            and not query_condition
        ):
            raise CLIError(
                "The query condition is required when job type is {} or {}. "
                "Use query condition '*' if you need to run job on all devices.".format(
                    JobType.scheduleUpdateTwin.value, JobType.scheduleDeviceMethod.value
                )
            )

        if poll_duration < 1:
            raise CLIError("--poll-duration must be greater than 0!")

        if poll_interval < 1:
            raise CLIError("--poll-interval must be greater than 0!")

        if job_type == JobType.scheduleUpdateTwin.value:
            if not twin_patch:
                raise CLIError(
                    "The {} job type requires --twin-patch.".format(
                        JobType.scheduleUpdateTwin.value
                    )
                )

            twin_patch = process_json_arg(twin_patch, argument_name="twin-patch")
            if not isinstance(twin_patch, dict):
                raise CLIError(
                    "Twin patches must be objects. Received type: {}".format(
                        type(twin_patch)
                    )
                )
        elif job_type == JobType.scheduleDeviceMethod.value:
            if not method_name:
                raise CLIError(
                    "The {} job type requires --method-name.".format(
                        JobType.scheduleDeviceMethod.value
                    )
                )

            method_payload = process_json_arg(
                method_payload, argument_name="method-payload"
            )

        job_request = JobRequest(
            job_id=job_id,
            type=job_type,
            start_time=start_time,
            max_execution_time_in_seconds=ttl,
            query_condition=query_condition,
        )

        if job_type == JobType.scheduleUpdateTwin.value:
            # scheduleUpdateTwin job type is a force update, which only accepts '*' as the Etag.
            twin_patch["etag"] = "*"
            job_request.update_twin = twin_patch
        elif job_type == JobType.scheduleDeviceMethod.value:
            job_request.cloud_to_device_method = CloudToDeviceMethod(
                method_name=method_name,
                connect_timeout_in_seconds=method_connect_timeout,
                response_timeout_in_seconds=method_response_timeout,
                payload=method_payload,
            )

        service_sdk = self.get_sdk(SdkType.service_sdk)

        try:
            job_result = service_sdk.jobs.create_scheduled_job(id=job_id, job_request=job_request, raw=True).response.json()
            if wait:
                logger.info("Waiting for job finished state...")
                current_datetime = datetime.now()
                end_datetime = current_datetime + timedelta(seconds=poll_duration)

                while True:
                    job_result = self._get(job_id)
                    if "status" in job_result:
                        refreshed_job_status = job_result["status"]
                        logger.info("Refreshed job status: '%s'", refreshed_job_status)

                        if refreshed_job_status in [
                            JobStatusType.completed.value,
                            JobStatusType.failed.value,
                            JobStatusType.cancelled.value,
                        ]:
                            break

                    if datetime.now() > end_datetime:
                        logger.info("Job not completed within poll duration....")
                        break

                    logger.info("Waiting %d seconds for next refresh...", poll_interval)
                    sleep(poll_interval)

            return job_result
        except CloudError as e:
            raise CLIError(unpack_msrest_error(e))
        except SerializationError as se:
            # ISO8601 parsing is handled by msrest
            raise CLIError(se)

    def _convert_v1_to_v2(self, job_v1):
        v2_result = {}

        # For v1 jobs, startTime is the same as createdTime
        v2_result["createdTime"] = job_v1.start_time_utc
        v2_result["startTime"] = job_v1.start_time_utc
        v2_result["endTime"] = job_v1.end_time_utc
        v2_result["jobId"] = job_v1.job_id
        v2_result["status"] = job_v1.status
        v2_result["type"] = job_v1.type
        v2_result["progress"] = job_v1.progress
        v2_result["excludeKeysInExport"] = job_v1.exclude_keys_in_export

        if job_v1.failure_reason:
            v2_result["failureReason"] = job_v1.failure_reason

        v2_result.update(job_v1.additional_properties)
        return v2_result

    def _filter_jobs(self, jobs, job_type=None, job_status=None):
        if job_type:
            jobs = [job for job in jobs if job["type"] == job_type]

        if job_status:
            jobs = [job for job in jobs if job["status"] == job_status]

        return jobs
