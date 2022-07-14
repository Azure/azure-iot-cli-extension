# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import List, Union

from azure.cli.core.azclierror import AzureResponseError, ClientRequestError, ResourceNotFoundError
from azext_iot.central.providers.base import IoTCentralProvider
from azext_iot._factory import CloudError
from azext_iot.common.utility import handle_service_exception
from azext_iot.sdk.central.preview_2022_06_30.models import Job, JobDeviceStatus, JobCancellationThreshold, JobBatch


class CentralJobProvider(IoTCentralProvider):
    def __init__(self, cmd, app_id: str):
        super().__init__(cmd=cmd, app_id=app_id)
        self.sdk_preview = self.get_sdk_preview().jobs
        self._jobs = {}

    def list(self) -> List[Job]:
        try:
            jobs = self.sdk_preview.list()
        except CloudError as e:
            handle_service_exception(e)

        # Update cache
        self._jobs.update({job.id: job for job in jobs})
        return jobs

    def get(
        self,
        job_id: str,
    ) -> Job:
        # Try cache
        job = self._jobs.get(job_id)

        if not job:
            try:
                job = self.sdk_preview.get(job_id=job_id)
            except CloudError as e:
                handle_service_exception(e)

        if not job:
            raise ResourceNotFoundError("No job found with id: '{}'.".format(job_id))

        # Update cache
        self._jobs[job_id] = job
        return job

    def stop(
        self,
        job_id: str,
    ) -> Job:
        try:
            job = self.sdk_preview.stop(job_id=job_id)
        except CloudError as e:
            handle_service_exception(e)

        if not job:
            raise AzureResponseError("Failed to stop job with id: '{}'.".format(job_id))

        return job

    def resume(
        self,
        job_id: str
    ) -> Job:
        try:
            job = self.sdk_preview.resume(job_id=job_id)
        except CloudError as e:
            handle_service_exception(e)

        if not job:
            raise AzureResponseError("Failed to resume job with id: '{}'.".format(job_id))

        return job

    def rerun(
        self,
        job_id: str,
        rerun_id: str,
    ) -> Job:
        try:
            job = self.sdk_preview.rerun(job_id=job_id, rerun_id=rerun_id)
        except CloudError as e:
            handle_service_exception(e)

        if not job:
            raise AzureResponseError("Failed to re-run job with id: '{}'.".format(job_id))

        return job

    def get_job_devices(
        self,
        job_id: str
    ) -> List[JobDeviceStatus]:
        try:
            devices = self.sdk_preview.get_devices(job_id=job_id)
        except CloudError as e:
            handle_service_exception(e)

        return {device["id"]: device for device in devices}

    def create(
        self,
        job_id: str,
        job_name: str,
        group_id: str,
        content: List,
        batch_percentage: bool,
        threshold_percentage: bool,
        threshold_batch: JobCancellationThreshold,
        batch: JobBatch,
        threshold: str,
        description: str,
    ):
        if job_id in self._jobs:
            raise ClientRequestError("Job already exists")

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

        try:
            job = self.sdk_preview.create(job_id=job_id, body=payload)
        except CloudError as e:
            handle_service_exception(e)

        if not job:
            raise AzureResponseError("Failed to create job with id: '{}'.".format(job_id))

        # Update cache
        self._jobs[job.id] = job

        return job
