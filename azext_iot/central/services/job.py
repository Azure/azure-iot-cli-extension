# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# This is largely derived from https://docs.microsoft.com/en-us/rest/api/iotcentral/jobs

from typing import List, Union
import requests

from knack.util import CLIError
from knack.log import get_logger

from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central.services import _utility
from azure.cli.core.util import should_disable_connection_verify
from azext_iot.central.models.v2 import JobV2
from azext_iot.central.models.preview import JobPreview


logger = get_logger(__name__)

BASE_PATH = "api/jobs"


def _call_job(
    cmd,
    method: str,
    path: str,
    app_id: str,
    job_id: str,
    body: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id)
    headers = _utility.get_headers(token, cmd)

    if path is not None:
        url = "{}/{}".format(url, path)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    if method is None:
        method = "get"

    response = requests.request(
        method=method.upper(),
        url=url,
        headers=headers,
        params=query_parameters,
        verify=not should_disable_connection_verify(),
        json=body,
    )
    result = _utility.try_extract_result(response)

    return result


def _list_job(
    cmd,
    app_id: str,
    path: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[JobPreview, JobV2]]:
    """
    Get a list of all jobs in IoTC app

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        list of jobs
    """

    values = []

    url = "https://{}.{}/{}".format(app_id, central_dns_suffix, BASE_PATH)
    headers = _utility.get_headers(token, cmd)

    if path is not None:
        url = "{}/{}".format(url, path)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    pages_processed = 0
    while (max_pages == 0 or pages_processed < max_pages) and url:
        response = requests.get(
            url,
            headers=headers,
            params=query_parameters,
            verify=not should_disable_connection_verify(),
        )
        result = _utility.try_extract_result(response)

        if "value" not in result:
            raise CLIError("Value is not present in body: {}".format(result))

        values.extend(result["value"])

        url = result.get("nextLink", None)
        pages_processed = pages_processed + 1

    return values


def get_job(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[JobPreview, JobV2]:
    """
    Get job info given a job id

    Args:
        cmd: command passed into az
        job_id: unique case-sensitive job id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    result = _call_job(
        cmd=cmd,
        method="get",
        path=None,
        app_id=app_id,
        job_id=job_id,
        body=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )
    return _utility.get_object(result, "Job", api_version)


def stop_job(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[JobPreview, JobV2]:
    """
    Stop a running job

    Args:
        cmd: command passed into az
        job_id: unique case-sensitive job id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    result = _call_job(
        cmd=cmd,
        method="post",
        path="stop",
        app_id=app_id,
        job_id=job_id,
        body=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )
    return _utility.get_object(result, "Job", api_version)


def resume_job(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[JobPreview, JobV2]:
    """
    Resume a stopped job

    Args:
        cmd: command passed into az
        job_id: unique case-sensitive job id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    result = _call_job(
        cmd=cmd,
        method="post",
        path="resume",
        app_id=app_id,
        job_id=job_id,
        body=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )
    return _utility.get_object(result, "Job", api_version)


def rerun_job(
    cmd,
    app_id: str,
    job_id: str,
    rerun_id: str,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[JobPreview, JobV2]:
    """
    Rerun a job on failed devices

    Args:
        cmd: command passed into az
        job_id: unique case-sensitive job id,
        rerun_id: unique case-sensitive rerun id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    result = _call_job(
        cmd=cmd,
        method="put",
        path="rerun/{}".format(rerun_id),
        app_id=app_id,
        job_id=job_id,
        body=None,
        token=token,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )
    return _utility.get_object(result, "Job", api_version)


def get_job_devices(
    cmd,
    app_id: str,
    job_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
):
    """
    Get device statuses

    Args:
        cmd: command passed into az
        job_id: unique case-sensitive job id,
        app_id: name of app (used for forming request URL)
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    return _list_job(
        cmd=cmd,
        app_id=app_id,
        path="{}/{}".format(job_id, "devices"),
        token=token,
        max_pages=max_pages,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )


def list_jobs(
    cmd,
    app_id: str,
    token: str,
    api_version: str,
    max_pages=0,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> List[Union[JobPreview, JobV2]]:

    values = _list_job(
        cmd=cmd,
        app_id=app_id,
        path=None,
        token=token,
        max_pages=max_pages,
        central_dns_suffix=central_dns_suffix,
        api_version=api_version,
    )

    return [_utility.get_object(job, "Job", api_version) for job in values]


def create_job(
    cmd,
    app_id: str,
    job_id: str,
    group_id: str,
    content: list,
    job_name: str,
    description: str,
    batch_percentage: bool,
    threshold_percentage: bool,
    threshold_batch: bool,
    batch: int,
    threshold: int,
    token: str,
    api_version: str,
    central_dns_suffix=CENTRAL_ENDPOINT,
) -> Union[JobPreview, JobV2]:
    """
    Create a job in IoTC

    Args:
        cmd: command passed into az
        app_id: name of app (used for forming request URL)
        job_id: unique case-sensitive job id
        group_id: The ID of the device group on which to execute the job.
        content: see example payload available in
            <repo-root>/azext_iot/tests/central/json/job_int_test.json
            or check here for more information
            https://docs.microsoft.com/en-us/rest/api/iotcentral/1.1-preview/jobs/create#cloudpropertyjobdata
        job_name: (OPTIONAL)(non-unique) human readable name for the job
        description: (OPTIONAL) Detailed description of the job.
        token: (OPTIONAL) authorization token to fetch job details from IoTC.
            MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
        central_dns_suffix: {centralDnsSuffixInPath} as found in docs

    Returns:
        job: dict
    """

    if not job_name:
        job_name = job_id

    url = "https://{}.{}/{}/{}".format(app_id, central_dns_suffix, BASE_PATH, job_id)
    headers = _utility.get_headers(token, cmd, has_json_payload=True)

    # Construct parameters
    query_parameters = {}
    query_parameters["api-version"] = api_version

    payload = {"displayName": job_name, "group": group_id, "data": content}

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

    return _utility.get_object(result, "Job", api_version)
