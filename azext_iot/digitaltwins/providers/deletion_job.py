# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azext_iot.common.utility import handle_service_exception
from azext_iot.digitaltwins.providers.base import DigitalTwinsProvider
from azext_iot.digitaltwins.providers import ErrorResponseException
from azext_iot.common.embedded_cli import EmbeddedCLI
from knack.log import get_logger
from uuid import uuid4

DEFAULT_DELETE_JOB_ID_PREFIX = "delete-job-"
logger = get_logger(__name__)


class DeletionJobProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name: str, rg: str = None):
        super(DeletionJobProvider, self).__init__(cmd=cmd, name=name, rg=rg)
        self.sdk = self.get_sdk().delete_jobs
        self.cli = EmbeddedCLI(cli_ctx=cmd.cli_ctx)

    def get(self, job_id: str):
        try:
            return self.sdk.get_by_id(job_id)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def list(self, top: int = None):  # top is guarded for int() in arg def
        from azext_iot.sdk.digitaltwins.dataplane.models import DeleteJobsListOptions

        list_options = DeleteJobsListOptions(max_items_per_page=top)

        try:
            return self.sdk.list(import_jobs_list_options=list_options,)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def create(self, job_id: Optional[str] = None, timeout_in_min: Optional[int] = None):
        # Check if error msg is good enough first.
        # if timeout_in_min < 1:
        #     raise Exception("Timeout needs to be a postiive integer.")
        job_id = job_id if job_id else DEFAULT_DELETE_JOB_ID_PREFIX + str(uuid4()).replace("-", "")
        self.sdk.config.operation_id = job_id
        self.sdk.config.timeout_in_minutes = timeout_in_min
        try:
            return self.sdk.add(polling=False)
        except ErrorResponseException as e:
            handle_service_exception(e)
