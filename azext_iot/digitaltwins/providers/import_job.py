# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.utility import handle_service_exception
from azext_iot.digitaltwins.providers.base import DigitalTwinsProvider
from azext_iot.digitaltwins.providers import ErrorResponseException
from azext_iot.common.embedded_cli import EmbeddedCLI
from azure.cli.core.azclierror import CLIInternalError
from knack.log import get_logger

logger = get_logger(__name__)


class ImportJobProvider(DigitalTwinsProvider):
    def __init__(self, cmd, name, rg=None):
        super(ImportJobProvider, self).__init__(cmd=cmd, name=name, rg=rg)
        self.sdk = self.get_sdk().import_jobs
        self.cli = EmbeddedCLI()

    def _get_blob_url(self, blob_name, blob_container, storage_account):
        storage_account_cstring_op = self.cli.invoke(
            "storage account show-connection-string -n '{}'".format(storage_account)
        )
        if not storage_account_cstring_op.success():
            raise CLIInternalError(
                "Unable to retrieve connection string for input storage account: {}".format(storage_account)
            )
        storage_account_cstring = storage_account_cstring_op.as_json()
        blob_url_op = self.cli.invoke(
            "storage blob url --connection-string '{}' --container-name '{}' --name '{}'".format(
                storage_account_cstring, blob_container, blob_name
            )
        )
        if not blob_url_op.success():
            raise CLIInternalError(
                "Unable to retrieve blob url for import data file: {} in {} container under {} account".format(
                    blob_name, blob_container, storage_account
                )
            )
        blob_url = blob_url_op.as_json()
        return blob_url

    def get(self, job_id):
        try:
            return self.sdk.get_by_id(job_id)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def list(self, top=None):  # top is guarded for int() in arg def
        from azext_iot.sdk.digitaltwins.dataplane.models import ImportJobsListOptions

        list_options = ImportJobsListOptions(max_item_count=top)

        try:
            return self.sdk.list(import_jobs_list_options=list_options,)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def create(
        self, job_id, input_blob_name, input_blob_container, input_storage_account,
        output_blob_name, output_blob_container=None, output_storage_account=None
    ):
        from azext_iot.sdk.digitaltwins.dataplane.models import BulkImportJob

        if output_storage_account is None:
            output_storage_account = input_storage_account

        if output_blob_container is None:
            output_blob_container = input_blob_container

        input_blob_url = self._get_blob_url(input_blob_name, input_blob_container, input_storage_account)
        output_blob_url = self._get_blob_url(output_blob_name, output_blob_container, output_storage_account)

        try:
            import_job = BulkImportJob(input_blob_uri=input_blob_url, output_blob_uri=output_blob_url)
            return self.sdk.put(id=job_id, import_job=import_job)
        except ErrorResponseException as e:
            handle_service_exception(e)

    def delete(self, job_id):
        try:
            return self.sdk.delete(id=job_id)
        except ErrorResponseException as e:
            handle_service_exception(e)
