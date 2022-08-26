# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List

from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralScheduledJobProvider
from azext_iot.common import utility
from azext_iot.central.common import API_VERSION
from azext_iot.central.models.ga_2022_07_31 import ScheduledJobGa


def get_scheduled_job(
    cmd,
    app_id: str,
    schedule_job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_schedule_job(
        schedule_job_id=schedule_job_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_scheduled_jobs(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> List[ScheduledJobGa]:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_schedule_jobs(central_dns_suffix=central_dns_suffix)


def create_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    schedule: str,
    content: str,
    job_name=None,
    description=None,
    batch_type=None,
    threshold_type=None,
    threshold_batch=None,
    batch=None,
    threshold=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
    if not isinstance(content, str):
        raise InvalidArgumentValueError("content must be a string: {}".format(content))

    if not isinstance(schedule, str):
        raise InvalidArgumentValueError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    schedule = utility.process_json_arg(schedule, argument_name="schedule")

    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.create_scheduled_job(
        job_id=job_id,
        job_name=job_name,
        group_id=group_id,
        content=payload,
        schedule=schedule,
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
        central_dns_suffix=central_dns_suffix,
    )


def update_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str = None,
    schedule: str = None,
    content: str = None,
    job_name=None,
    description=None,
    batch_type=None,
    threshold_type=None,
    threshold_batch=None,
    batch=None,
    threshold=None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
    if content is not None:
        payload = utility.process_json_arg(content, argument_name="content")

    if schedule is not None:
        schedule = utility.process_json_arg(schedule, argument_name="schedule")

    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.update_scheduled_job(
        job_id=job_id,
        job_name=job_name,
        group_id=group_id,
        content=payload,
        schedule=schedule,
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
        central_dns_suffix=central_dns_suffix,
    )


def delete_scheduled_job(
    cmd,
    app_id: str,
    schedule_job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_scheduled_job(
        schedule_job_id=schedule_job_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_jobs_status(
    cmd,
    app_id: str,
    schedule_job_id: str,
    entry: str,
    certificate: str,
    verified: bool,
    etag: str = None,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_jobs_status(
        schedule_job_id=schedule_job_id,
        entry=entry,
        certificate=certificate,
        verified=verified,
        etag=etag,
        central_dns_suffix=central_dns_suffix,
    )
