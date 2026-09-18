# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from azext_iot.adr.common import ReportType
from azext_iot.adr.providers.report import ReportProvider


def adr_report_generate(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    report_type: str = ReportType.namespace_update_compliance.value,
    group_name: Optional[str] = None,
    no_wait: bool = False,
):
    provider = ReportProvider(cmd)
    return provider.generate(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        report_type=report_type,
        group_name=group_name,
        no_wait=no_wait,
    )


def adr_report_latest(
    cmd,
    namespace_name: str,
    resource_group_name: str,
    report_type: str = ReportType.namespace_update_compliance.value,
    group_name: Optional[str] = None,
):
    provider = ReportProvider(cmd)
    return provider.latest(
        namespace_name=namespace_name,
        resource_group_name=resource_group_name,
        report_type=report_type,
        group_name=group_name,
    )
