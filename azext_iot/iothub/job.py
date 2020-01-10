# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from time import sleep
from datetime import datetime, timedelta
from knack.log import get_logger
from knack.util import CLIError
from azext_iot._factory import _bind_sdk
from azext_iot.common.shared import SdkType, JobStatusType, JobType
from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot.common.utility import unpack_msrest_error, process_json_arg
from azext_iot.operations.generic import _execute_query, _process_top
from azext_iot.iothub.mgmt_helpers import ErrorDetailsException, get_mgmt_iothub_client
from azext_iot.iothub import IoTHubProvider


logger = get_logger(__name__)


def job_create(
    cmd,
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
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    from msrest.exceptions import SerializationError
    from azext_iot.sdk.service.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot.sdk.service.models.job_request import JobRequest

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

    job_request = JobRequest(
        job_id=job_id,
        type=job_type,
        start_time=start_time,
        max_execution_time_in_seconds=ttl,
        query_condition=query_condition,
    )

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

        # scheduleUpdateTwin job type is a force update, which only accepts '*' as the Etag.
        twin_patch["etag"] = "*"
        job_request.update_twin = twin_patch
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
        job_request.cloud_to_device_method = CloudToDeviceMethod(
            method_name=method_name,
            connect_timeout_in_seconds=method_connect_timeout,
            response_timeout_in_seconds=method_response_timeout,
            payload=method_payload,
        )

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        job_result = service_sdk.create_job1(id=job_id, job_request=job_request)
        if wait:
            logger.info("Waiting for job finished state...")
            current_datetime = datetime.now()
            end_datetime = current_datetime + timedelta(seconds=poll_duration)

            while True:
                job_result = _job_show(target, job_id)
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
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
    except SerializationError as se:
        # ISO8601 parsing is handled by msrest
        raise CLIError(se)


def job_show(cmd, job_id, hub_name=None, resource_group_name=None, login=None):
    jobs = JobProvider(cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login)
    return jobs.get(job_id)


def job_list(
    cmd,
    job_type=None,
    job_status=None,
    top=None,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    jobs = JobProvider(cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login)
    return jobs.list(job_type=job_type, job_status=job_status, top=top)


def job_cancel(cmd, job_id, hub_name=None, resource_group_name=None, login=None):
    jobs = JobProvider(cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login)
    return jobs.cancel(job_id)


class JobProvider(IoTHubProvider):
    def get(self, job_id):
        job_result = self._get(job_id)
        if (
            "status" in job_result
            and job_result["status"] == JobStatusType.unknown.value
        ):
            # Replace 'unknown' job_result with object from control plane if it exists
            cp_job_result = self._get_from_cp(job_id)
            if cp_job_result:
                job_result = cp_job_result

        return job_result

    def _get(self, job_id):
        service_sdk, errors = self.get_sdk(SdkType.service_sdk)

        try:
            return service_sdk.get_job1(id=job_id)
        except errors.CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def _get_from_cp(self, job_id):
        client = get_mgmt_iothub_client(self.cmd)
        if not client:
            return

        try:
            return client.get_job(
                resource_group_name=self.target["resourcegroup"],
                resource_name=self.target["entity"].split(".")[
                    0
                ],  # entity is iothub fqdn
                job_id=job_id,
            )
        except ErrorDetailsException as e:
            # ErrorDetailsException can be treated like CloudError
            raise CLIError(unpack_msrest_error(e))

    def cancel(self, job_id):
        job_result = self.get(job_id)
        if not isinstance(job_result, dict):
            job_result = job_result.as_dict()
        job_type = job_result["type"]
        if job_type in [JobType.exportDevices.value, JobType.importDevices.value]:
            # v1 Job
            raise CLIError("You are unable to cancel device import/export jobs!")

        # v2 Job
        return self._cancel(job_id)

    def _cancel(self, job_id):
        service_sdk, errors = self.get_sdk(SdkType.service_sdk)

        try:
            return service_sdk.cancel_job1(id=job_id)
        except errors.CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def list(self, job_type=None, job_status=None, top=None):
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
                jobs_collection.extend(self._list_from_cp(top))

                # Trim based on top, since there is no way to pass a 'top' into the cp API :(
                jobs_collection = jobs_collection[:top]

        return jobs_collection

    def _list(self, job_type=None, job_status=None, top=None):
        top = _process_top(top)
        service_sdk, errors = self.get_sdk(SdkType.service_sdk)
        jobs_collection = []

        try:
            query = [job_type, job_status]
            query_method = service_sdk.query_jobs
            jobs_collection.extend(_execute_query(query, query_method, top))
            return jobs_collection
        except errors.CloudError as e:
            raise CLIError(unpack_msrest_error(e))

    def _list_from_cp(self, top=None):
        client = get_mgmt_iothub_client(self.cmd)
        if not client:
            return []

        try:
            return client.list_jobs(
                resource_group_name=self.target["resourcegroup"],
                resource_name=self.target["entity"].split(".")[
                    0
                ],  # entity is iothub fqdn
            )
        except ErrorDetailsException as e:
            # ErrorDetailsException can be treated like CloudError
            raise CLIError(unpack_msrest_error(e))


    def create(self):
        pass