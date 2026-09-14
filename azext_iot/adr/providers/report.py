# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional

from azure.cli.core.azclierror import ArgumentUsageError

from azext_iot.adr.common import ReportType
from azext_iot.adr.providers.base import ADRProvider


_GROUP_REPORT_TYPES = {
    ReportType.group_best_updates_compliance.value,
    ReportType.group_installable_updates.value,
}
_REPORT_TYPES = {item.value for item in ReportType}


class ReportProvider(ADRProvider):
    @staticmethod
    def _build_selector(report_type: str, group_name: Optional[str]) -> dict:
        if report_type not in _REPORT_TYPES:
            raise ArgumentUsageError(f"Unsupported report type: {report_type}.")
        if group_name is not None:
            group_name = group_name.strip() or None
        if report_type in _GROUP_REPORT_TYPES:
            if not group_name:
                raise ArgumentUsageError(
                    "--group-name is required for group update reports."
                )
        elif group_name:
            raise ArgumentUsageError(
                "--group-name is only valid for group update reports."
            )

        selector = {"reportType": report_type}
        if group_name:
            selector["reportTarget"] = group_name
        return selector

    def generate(
        self,
        namespace_name: str,
        resource_group_name: str,
        report_type: str,
        group_name: Optional[str] = None,
        **kwargs,
    ):
        poller = self.client.namespaces.begin_generate_report(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            body=self._build_selector(report_type, group_name),
        )
        if kwargs.pop("no_wait", False):
            return poller
        self._wait(
            poller,
            f"Generating {report_type} for namespace {namespace_name}...",
            **kwargs,
        )
        return self.latest(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            report_type=report_type,
            group_name=group_name,
        )

    def latest(
        self,
        namespace_name: str,
        resource_group_name: str,
        report_type: str,
        group_name: Optional[str] = None,
    ):
        return self.client.namespaces.get_latest_report(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            body=self._build_selector(report_type, group_name),
        )
