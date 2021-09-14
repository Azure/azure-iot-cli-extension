# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Dev note - think of this as a controller

from knack.util import CLIError
from typing import Union, List, Any
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.models.enum import ApiVersion
from azext_iot.central.providers.job_provider import CentralJobProvider
from azext_iot.central.models.preview import JobPreview
from azext_iot.central.models.v1_1_preview import JobV1_1_preview
from azext_iot.common import utility

JobType = Union[JobPreview, JobV1_1_preview]


def get_job(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> JobType:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_job(job_id=job_id, central_dns_suffix=central_dns_suffix)


def stop_job(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> JobType:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.stop_job(job_id=job_id, central_dns_suffix=central_dns_suffix)


def resume_job(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> JobType:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.resume_job(job_id=job_id, central_dns_suffix=central_dns_suffix)


def rerun_job(
    cmd,
    app_id: str,
    job_id: str,
    rerun_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> JobType:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.rerun_job(
        job_id=job_id, rerun_id=rerun_id, central_dns_suffix=central_dns_suffix
    )


def get_job_devices(
    cmd,
    app_id: str,
    job_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[Any]:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.get_job_devices(
        job_id=job_id, central_dns_suffix=central_dns_suffix
    )


def list_jobs(
    cmd,
    app_id: str,
    token=None,
    central_dns_suffix=CENTRAL_ENDPOINT,
    api_version=ApiVersion.v1_1_preview.value,
) -> List[JobType]:
    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.list_jobs(central_dns_suffix=central_dns_suffix)


def create_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
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
    api_version=ApiVersion.v1_1_preview.value,
) -> JobType:

    if not isinstance(content, str):
        raise CLIError("content must be a string: {}".format(content))

    payload = utility.process_json_arg(content, argument_name="content")

    provider = CentralJobProvider(
        cmd=cmd, app_id=app_id, api_version=api_version, token=token
    )

    return provider.create_job(
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
        central_dns_suffix=central_dns_suffix,
    )
