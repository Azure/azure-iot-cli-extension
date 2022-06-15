# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.digitaltwins.providers.import_job import ImportJobProvider


def create_import_job(
    cmd, name_or_hostname: str, data_file_name: str, input_blob_container_name: str,
    input_storage_account_name: str, output_file_name: str = None, output_blob_container_name: str = None,
    output_storage_account_name: str = None, job_id: str = None, resource_group_name: str = None
):
    import_job_provider = ImportJobProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return import_job_provider.create(
        job_id=job_id, input_blob_name=data_file_name, input_blob_container=input_blob_container_name,
        input_storage_account=input_storage_account_name, output_blob_name=output_file_name,
        output_blob_container=output_blob_container_name, output_storage_account=output_storage_account_name
    )


def show_import_job(cmd, name_or_hostname: str, job_id: str, resource_group_name: str = None):
    import_job_provider = ImportJobProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return import_job_provider.get(job_id=job_id)


def list_import_jobs(cmd, name_or_hostname: str, resource_group_name: str = None):
    import_job_provider = ImportJobProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return import_job_provider.list()


def delete_import_job(cmd, name_or_hostname: str, job_id: str, resource_group_name: str = None):
    import_job_provider = ImportJobProvider(cmd=cmd, name=name_or_hostname, rg=resource_group_name)
    return import_job_provider.delete(job_id=job_id)
