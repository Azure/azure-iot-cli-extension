# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Dict, Optional

from azext_iot.adr.common import JobType
from azext_iot.adr.providers.job import JobProvider
from azext_iot.adr.providers.job_run import JobRunProvider


def adr_job_create(
    cmd,
    job_name: str,
    namespace_name: str,
    resource_group_name: str,
    update_provider: Optional[str] = None,
    update_name: Optional[str] = None,
    update_version: Optional[str] = None,
    target_group_name: Optional[str] = None,
    job_type: str = JobType.software_update.value,
    description: Optional[str] = None,
    display_name: Optional[str] = None,
    location: Optional[str] = None,
    tags: Optional[Dict[str, str]] = None,
    no_wait: bool = False,
):
    provider = JobProvider(cmd)
    return provider.create(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        update_provider=update_provider,
        update_name=update_name,
        update_version=update_version,
        target_group_name=target_group_name,
        job_type=job_type,
        description=description,
        display_name=display_name,
        location=location,
        tags=tags,
        no_wait=no_wait,
    )


def adr_job_update(
    cmd,
    job_name: str,
    namespace_name: str,
    resource_group_name: str,
    tags: Optional[Dict[str, str]] = None,
):
    provider = JobProvider(cmd)
    return provider.update(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        tags=tags,
    )


def adr_job_show(cmd, job_name: str, namespace_name: str, resource_group_name: str):
    provider = JobProvider(cmd)
    return provider.show(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_job_list(cmd, namespace_name: str, resource_group_name: str):
    provider = JobProvider(cmd)
    return provider.list(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_job_delete(
    cmd,
    job_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = JobProvider(cmd)
    return provider.delete(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_job_schedule(
    cmd,
    job_name: str,
    namespace_name: str,
    resource_group_name: str,
    run_name: Optional[str] = None,
    scheduled_time: Optional[str] = None,
    no_wait: bool = False,
):
    """Schedule an execution of a job.

    Backed by ``JobRuns_CreateOrReplace``: a job defines *what* to roll out and
    *to whom*, and each run carries *when* it executes. ``scheduledTime`` is the
    only writable field on a run, so scheduling is expressed by creating one.
    """
    provider = JobRunProvider(cmd)
    return provider.create(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        run_name=run_name,
        scheduled_time=scheduled_time,
        no_wait=no_wait,
    )
