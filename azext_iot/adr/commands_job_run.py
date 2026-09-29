# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from azext_iot.adr.providers.job_run import JobRunProvider


def adr_job_run_delete(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = JobRunProvider(cmd)
    return provider.delete(
        job_name=job_name,
        run_name=run_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )


def adr_job_run_summary(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = JobRunProvider(cmd)
    return provider.summary(
        job_name=job_name,
        run_name=run_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_job_run_show(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
):
    provider = JobRunProvider(cmd)
    return provider.show(
        job_name=job_name,
        run_name=run_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
    )


def adr_job_run_list(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    job_name: Optional[str] = None,
    status_filter: Optional[str] = None,
    order_by: Optional[str] = None,
):
    provider = JobRunProvider(cmd)
    return provider.list(
        job_name=job_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        status_filter=status_filter,
        order_by=order_by,
    )


def adr_job_run_results(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
    status_filter: Optional[str] = None,
    order_by: Optional[str] = None,
):
    provider = JobRunProvider(cmd)
    return list(
        provider.results(
            job_name=job_name,
            run_name=run_name,
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            status_filter=status_filter,
            order_by=order_by,
        )
    )


def adr_job_run_cancel(
    cmd,
    job_name: str,
    run_name: str,
    namespace_name: str,
    resource_group_name: str,
    no_wait: bool = False,
):
    provider = JobRunProvider(cmd)
    return provider.cancel(
        job_name=job_name,
        run_name=run_name,
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        no_wait=no_wait,
    )
