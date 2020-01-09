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
from azext_iot.common.shared import SdkType
from azext_iot.common._azure import get_iot_hub_connection_string
from azext_iot.common.utility import unpack_msrest_error, process_json_arg
from azext_iot.operations.generic import _execute_query, _process_top


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
    from azext_iot.common.shared import JobType, JobStatusType
    from azext_iot.sdk.service.models.cloud_to_device_method import CloudToDeviceMethod
    from azext_iot.sdk.service.models.job_request import JobRequest

    if (
        job_type in [JobType.scheduleUpdateTwin.value, JobType.scheduleDeviceMethod.value]
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
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    return _job_show(target, job_id)


def _job_show(target, job_id):
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        return service_sdk.get_job1(id=job_id)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def job_list(
    cmd,
    job_type=None,
    job_status=None,
    top=None,
    hub_name=None,
    resource_group_name=None,
    login=None,
):
    top = _process_top(top)

    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        query = [job_type, job_status]
        query_method = service_sdk.query_jobs

        return _execute_query(query, query_method, top)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))


def job_cancel(cmd, job_id, hub_name=None, resource_group_name=None, login=None):
    target = get_iot_hub_connection_string(
        cmd, hub_name, resource_group_name, login=login
    )
    service_sdk, errors = _bind_sdk(target, SdkType.service_sdk)

    try:
        return service_sdk.cancel_job1(id=job_id)
    except errors.CloudError as e:
        raise CLIError(unpack_msrest_error(e))
