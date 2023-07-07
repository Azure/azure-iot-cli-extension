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
from azure.cli.core.azclierror import ResourceNotFoundError
from knack.log import get_logger
from uuid import uuid4

DEFAULT_DELETE_JOB_ID_PREFIX = "delete-job-"
logger = get_logger(__name__)


class DeleteJobProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name: str, rg: str = None):
        super(DeleteJobProvider, self).__init__(cmd=cmd, name=name, rg=rg)
        self.sdk = self.get_sdk().delete_jobs
        self.cli = EmbeddedCLI(cli_ctx=cmd.cli_ctx)

    def _get_blob_url(self, blob_name: str, blob_container: str, storage_account: str):
        storage_account_cstring_op = self.cli.invoke(
            "storage account show-connection-string -n '{}'".format(storage_account)
        )
        if not storage_account_cstring_op.success():
            raise ResourceNotFoundError(
                "Unable to retrieve connection string for input storage account: {}".format(storage_account)
            )
        storage_account_cstring = storage_account_cstring_op.as_json()
        blob_url_op = self.cli.invoke(
            "storage blob url --connection-string '{}' --container-name '{}' --name '{}'".format(
                storage_account_cstring, blob_container, blob_name
            )
        )
        if not blob_url_op.success():
            raise ResourceNotFoundError(
                "Unable to retrieve blob url for import data file: {} in {} container under {} account".format(
                    blob_name, blob_container, storage_account
                )
            )
        blob_url = blob_url_op.as_json()
        return blob_url

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

    def create(self, job_id: Optional[str] = None):
        job_id = job_id if job_id else DEFAULT_DELETE_JOB_ID_PREFIX + str(uuid4()).replace("-", "")
        self.sdk.config.operation_id = job_id
        try:
            return self.sdk.add()
        except ErrorResponseException as e:
            handle_service_exception(e)
