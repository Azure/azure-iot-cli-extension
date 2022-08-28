# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/deviceGroups

from typing import List
import requests

from knack.log import get_logger

from azure.cli.core.azclierror import AzureResponseError
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azext_iot.central.models.ga_2022_07_31 import ScheduledJobGa
from azext_iot.central.common import API_VERSION

logger = get_logger(__name__)

BASE_PATH = "api/scheduledJobs"
MODEL = "ScheduledJob"


def list_scheduled_jobs(
    cmd,
    app_id: str,
    token: str,
    api_version=API_VERSION,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[ScheduledJobGa]:
    """
    Get a list of all scheduled jobs.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of scheduled jobs
    """
    api_version = API_VERSION

    scheduled_jobs = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(url, headers=headers, params=query_parameters)
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise AzureResponseError("Value is not present in body: {}".format(result))

        for scheduled_job in result["value"]:
            scheduled_jobs.append(ScheduledJobGa(scheduled_job))

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return scheduled_jobs


def get_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> ScheduledJobGa:
    """
    Get a specific scheduled job.

    Args:
        cmd: command passed into az
        job_id: case sensitive scheduled job id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        scheduled_job: dict
    """
    api_version = API_VERSION

    result = _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
    return _utility.get_object(result, model=MODEL, api_version=api_version)


def create_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    content: list,
    schedule: str,
    job_name: str,
    description: str,
    batch_percentage: bool,
    threshold_percentage: bool,
    threshold_batch: bool,
    batch: int,
    threshold: int,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> ScheduledJobGa:
    """
    Creates a scheduled job.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        job_id: unique case-sensitive job id
        group_id: The ID of the device group on which to execute the job.
        content: Data related to the operation being performed by this job.
        schedule: The schedule at which to execute the job.
        job_name: (OPTIONAL)(non-unique) human readable name for the job
        description: (OPTIONAL) Detailed description of the job.
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        scheduled_job: dict
    """
    api_version = API_VERSION

    if not job_name:
        job_name = job_id

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    payload = {"displayName": job_name, "group": group_id, "data": content, "schedule": schedule}

    if description:
        payload["description"] = description

    if batch is not None:
        payload["batch"] = {
            "value": batch,
            "type": "percentage" if batch_percentage else "number",
        }

    if threshold is not None:
        payload["cancellationThreshold"] = {
            "value": threshold,
            "type": "percentage" if threshold_percentage else "number",
            "batch": threshold_batch,
        }

    response = requests.put(url, headers=headers, json=payload, params=query_parameters)
    result = _utility.try_extract_result(response)

    return _utility.get_object(result, model=MODEL, api_version=api_version)


def update_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    content: list,
    schedule: str,
    job_name: str,
    description: str,
    batch_percentage: bool,
    threshold_percentage: bool,
    threshold_batch: bool,
    batch: int,
    threshold: int,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> ScheduledJobGa:
    """
    Updates a scheduled job.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        job_id: unique case-sensitive job id
        group_id: The ID of the device group on which to execute the job.
        content: Data related to the operation being performed by this job.
        schedule: The schedule at which to execute the job.
        job_name: (OPTIONAL)(non-unique) human readable name for the job.
        description: (OPTIONAL) Detailed description of the job.
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        scheduled_job: dict
    """
    api_version = API_VERSION

    if not job_name:
        job_name = job_id

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    payload = {}

    if job_name:
        payload["displayName"] = job_name

    if group_id:
        payload["group"] = group_id

    if content:
        payload["data"] = content

    if schedule:
        payload["schedule"] = schedule

    if description:
        payload["description"] = description

    if batch is not None:
        payload["batch"] = {
            "value": batch,
            "type": "percentage" if batch_percentage else "number",
        }

    if threshold is not None:
        payload["cancellationThreshold"] = {
            "value": threshold,
            "type": "percentage" if threshold_percentage else "number",
            "batch": threshold_batch,
        }

    response = requests.patch(url, headers=headers, json=payload, params=query_parameters)
    result = _utility.try_extract_result(response)

    return _utility.get_object(result, model=MODEL, api_version=api_version)


def delete_scheduled_job(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Delete a scheduled job.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        job_id: case sensitive scheduled job id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        scheduled_job: dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="DELETE",
        url="https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )


def list_jobs(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version=API_VERSION,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> dict:
    """
    Get the list of jobs for a scheduled job definition.

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        job_id: case sensitive scheduled job id,
        token: (OPTIONAL) authorization token to fetch device details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        scheduled_job: dict
    """
    api_version = API_VERSION

    return _utility.make_api_call(
        cmd,
        app_id=app_id,
        method="GET",
        url="https://{}.{}/{}/{}/jobs".format(app_id, central_dns_suffix, BASE_PATH, job_id),
        payload=None,
        token=token,
        api_version=api_version,
        central_dnx_suffix=central_dns_suffix,
    )
