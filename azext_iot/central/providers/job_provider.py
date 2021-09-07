# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Union
from knack.util import CLIError
from knack.log import get_logger
from azext_iot.constants import CENTRAL_ENDPOINT
from azext_iot.central import services as central_services
from azext_iot.central.models.preview import JobPreview
from azext_iot.central.models.v2 import JobV2

logger = get_logger(__name__)


class CentralJobProvider:
    def __init__(self, cmd, app_id: str, api_version: str, token=None):
        """
        Provider for jobs APIs

        Args:
            cmd: command passed into az
            app_id: name of app (used for forming request URL)
            token: (OPTIONAL) authorization token to fetch device details from IoTC.
                MUST INCLUDE type (e.g. 'SharedAccessToken ...', 'Bearer ...')
                Useful in scenarios where user doesn't own the app
                therefore AAD token won't work, but a SAS token generated by owner will
        """
        self._cmd = cmd
        self._app_id = app_id
        self._api_version = api_version
        self._token = token
        self._jobs = {}

    def list_jobs(
        self, central_dns_suffix=CENTRAL_ENDPOINT
    ) -> List[Union[JobPreview, JobV2]]:
        jobs = central_services.job.list_jobs(
            cmd=self._cmd,
            app_id=self._app_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        self._jobs.update({job.id: job for job in jobs})

        return jobs

    def get_job(
        self,
        job_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> Union[JobPreview, JobV2]:
        # get or add to cache
        job = self._jobs.get(job_id)
        if not job:
            job = central_services.job.get_job(
                cmd=self._cmd,
                app_id=self._app_id,
                job_id=job_id,
                token=self._token,
                central_dns_suffix=central_dns_suffix,
                api_version=self._api_version,
            )
            self._jobs[job_id] = job

        if not job:
            raise CLIError("No job found with id: '{}'.".format(job_id))

        return job

    def stop_job(
        self,
        job_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> Union[JobPreview, JobV2]:
        # get or add to cache
        job = central_services.job.stop_job(
            cmd=self._cmd,
            app_id=self._app_id,
            job_id=job_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )
        if not job:
            raise CLIError("No job found with id: '{}'.".format(job_id))

        return job

    def resume_job(
        self,
        job_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> Union[JobPreview, JobV2]:
        # get or add to cache
        job = central_services.job.resume_job(
            cmd=self._cmd,
            app_id=self._app_id,
            job_id=job_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        if not job:
            raise CLIError("No job found with id: '{}'.".format(job_id))

        return job

    def rerun_job(
        self,
        job_id,
        rerun_id,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ) -> Union[JobPreview, JobV2]:
        # get or add to cache
        job = central_services.job.rerun_job(
            cmd=self._cmd,
            app_id=self._app_id,
            job_id=job_id,
            rerun_id=rerun_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        if not job:
            raise CLIError("No job found with id: '{}'.".format(job_id))

        return job

    def get_job_devices(self, job_id, central_dns_suffix=CENTRAL_ENDPOINT) -> List:
        devices = central_services.job.get_job_devices(
            cmd=self._cmd,
            app_id=self._app_id,
            job_id=job_id,
            token=self._token,
            central_dns_suffix=central_dns_suffix,
            api_version=self._api_version,
        )

        # add to cache
        return {device["id"]: device for device in devices}

    def create_job(
        self,
        job_id,
        job_name,
        group_id,
        content,
        batch_percentage,
        threshold_percentage,
        threshold_batch,
        batch,
        threshold,
        description,
        central_dns_suffix=CENTRAL_ENDPOINT,
    ):
        if job_id in self._jobs:
            raise CLIError("Job already exists")
        job = central_services.job.create_job(
            self._cmd,
            self._app_id,
            job_id=job_id,
            job_name=job_name,
            group_id=group_id,
            content=content,
            description=description,
            batch_percentage=batch_percentage,
            threshold_percentage=threshold_percentage,
            threshold_batch=threshold_batch,
            batch=batch,
            threshold=threshold,
            token=self._token,
            api_version=self._api_version,
            central_dns_suffix=central_dns_suffix,
        )

        if not job:
            raise CLIError("No job found with id: '{}'.".format(job_id))

        # add to cache
        self._jobs[job.id] = job

        return job
