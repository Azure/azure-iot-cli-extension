# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from typing import List, Optional

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.providers import CentralScheduledJobProvider
from azext_iot.common import utility
from azext_iot.central.common import API_VERSION
from azext_iot.central.models.ga_2022_07_31 import ScheduledJobGa


def get_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.get_scheduled_job(
        job_id=job_id,
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

    return provider.list_scheduled_jobs(central_dns_suffix=central_dns_suffix)


def create_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    schedule: str,
    content: str,
    job_name: Optional[str] = None,
    description: Optional[str] = None,
    batch_type: Optional[str] = None,
    threshold_type: Optional[str] = None,
    threshold_batch: Optional[bool] = None,
    batch: Optional[int] = None,
    threshold: Optional[int] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
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
        if batch_type.lower() == "percentage"
        else False,
        threshold_percentage=True
        if threshold_type.lower() == "percentage"
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
    group_id: Optional[str] = None,
    schedule: Optional[str] = None,
    content: Optional[str] = None,
    job_name: Optional[str] = None,
    description: Optional[str] = None,
    batch_type: Optional[str] = None,
    threshold_type: Optional[str] = None,
    threshold_batch: Optional[bool] = None,
    batch: Optional[int] = None,
    threshold: Optional[int] = None,
    token: Optional[str] = None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> ScheduledJobGa:
    payload = None
    if content:
        payload = utility.process_json_arg(content, argument_name="content")

    schedule_payload = None
    if schedule:
        schedule_payload = utility.process_json_arg(schedule, argument_name="schedule")

    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.update_scheduled_job(
        job_id=job_id,
        job_name=job_name,
        group_id=group_id,
        content=payload,
        schedule=schedule_payload,
        description=description,
        batch_percentage=True
        if batch_type.lower() == "percentage"
        else False,
        threshold_percentage=True
        if threshold_type.lower() == "percentage"
        else False,
        threshold_batch=threshold_batch,
        batch=batch,
        threshold=threshold,
        central_dns_suffix=central_dns_suffix,
    )


def delete_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.delete_scheduled_job(
        job_id=job_id,
        central_dns_suffix=central_dns_suffix,
    )


def list_runs(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=API_VERSION,
) -> dict:
    provider = CentralScheduledJobProvider(
        cmd=cmd, app_id=app_id, token=token, api_version=api_version
    )

    return provider.list_runs(
        job_id=job_id,
        central_dns_suffix=central_dns_suffix,
    )
