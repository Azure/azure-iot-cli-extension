# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.iothub.providers.job import JobProvider


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
    jobs = JobProvider(cmd=cmd, hub_name=hub_name, rg=resource_group_name, login=login)
    return jobs.create(
        job_id=job_id,
        job_type=job_type,
        start_time=start_time,
        query_condition=query_condition,
        twin_patch=twin_patch,
        method_name=method_name,
        method_payload=method_payload,
        method_connect_timeout=method_connect_timeout,
        method_response_timeout=method_response_timeout,
        ttl=ttl,
        wait=wait,
        poll_interval=poll_interval,
        poll_duration=poll_duration,
    )


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
