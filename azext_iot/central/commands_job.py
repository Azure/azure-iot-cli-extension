# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from azure.cli.core.azclierror import InvalidArgumentValueError
from typing import List, Optional

from azext_iot.central.providers.job_provider import CentralJobProvider
from azext_iot.common import utility
from azext_iot.sdk.central.preview_2022_06_30.models import Job, JobDeviceStatus, JobCancellationThreshold, JobBatch


def get_job(
    cmd,
    app_id: str,
    job_id: str,
) -> Job:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.get(job_id=job_id)


def stop_job(
    cmd,
    app_id: str,
    job_id: str,
) -> Job:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.stop(job_id=job_id)


def resume_job(
    cmd,
    app_id: str,
    job_id: str,
) -> Job:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.resume(job_id=job_id)


def rerun_job(
    cmd,
    app_id: str,
    job_id: str,
    rerun_id: str,
) -> Job:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.rerun(job_id=job_id, rerun_id=rerun_id)


def get_job_devices(
    cmd,
    app_id: str,
    job_id: str,
) -> List[JobDeviceStatus]:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.get_job_devices(job_id=job_id)


def list_jobs(
    cmd,
    app_id: str,
) -> List[Job]:
    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.list()


def create_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    content: str,
    job_name: Optional[str] = None,
    description: Optional[str] = None,
    batch_type: Optional[str] = None,
    threshold_type: Optional[str] = None,
    threshold_batch: Optional[JobCancellationThreshold] = None,
    batch: Optional[JobBatch] = None,
    threshold: Optional[str] = None,
) -> Job:
    if not isinstance(content, str):
        raise InvalidArgumentValueError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralJobProvider(cmd=cmd, app_id=app_id)
    return provider.create(
        job_id=job_id,
        job_name=job_name,
        group_id=group_id,
        content=payload,
        description=description,
        batch_percentage=True
        if batch_type is not None and batch_type.lower() == "percentage"
        else False,
        threshold_percentage=True
        if threshold_type is not None and threshold_type.lower() == "percentage"
        else False,
        threshold_batch=threshold_batch,
        batch=batch,
        threshold=threshold,
    )
