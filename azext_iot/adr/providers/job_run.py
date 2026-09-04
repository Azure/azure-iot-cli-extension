# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
from datetime import datetime, timezone
from typing import Iterator, Optional

from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError

from azext_iot.adr.common import validate_iso8601_datetime
from azext_iot.adr.providers.base import ADRProvider

_JOB_RUN_STATUSES = {
    "Scheduled",
    "Active",
    "Succeeded",
    "Failed",
    "TimedOut",
    "Canceled",
}
_RESULT_STATUSES = {
    "Succeeded",
    "Failed",
    "InProgress",
    "Canceled",
}
_STATUS_FILTER = re.compile(
    r"status\s+(?:eq\s+'(?P<equality>[^']+)'|in\s+\((?P<values>.*)\))"
)
_STATUS_VALUE = re.compile(r"\s*'([^']+)'\s*")
_ORDER_BY_CLAUSE = re.compile(r"(?P<field>[A-Za-z][A-Za-z0-9_.]*)(?:\s+(?P<dir>asc|desc))?")
_ORDER_BY_FIELDS = {"status"}


def _generate_job_run_name() -> str:
    """Generate a default job run name.

    ``runName`` is a required path segment, but the common case is "run this job
    now" where the caller does not care about the name. A UTC timestamp keeps
    generated names sortable and collision-free at second resolution.
    """
    return f"run-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _validate_order_by(order_by: Optional[str]):
    """Validate an OData ``orderBy`` expression, e.g. ``status asc``."""
    if not order_by:
        return
    match = _ORDER_BY_CLAUSE.fullmatch(order_by.strip())
    if not match or match.group("field") not in _ORDER_BY_FIELDS:
        values = ", ".join(sorted(_ORDER_BY_FIELDS))
        raise InvalidArgumentValueError(
            "Use an order by expression such as \"status asc\" or \"status desc\". "
            f"Supported fields: {values}."
        )


def _validate_status_filter(
    status_filter: Optional[str],
    allowed_statuses: set,
    allow_in: bool,
):
    if not status_filter:
        return
    match = _STATUS_FILTER.fullmatch(status_filter.strip())
    selected_statuses = []
    if match:
        equality = match.group("equality")
        if equality:
            selected_statuses = [equality]
        elif allow_in:
            raw_values = match.group("values").split(",")
            parsed_values = [_STATUS_VALUE.fullmatch(value) for value in raw_values]
            if all(parsed_values):
                selected_statuses = [value.group(1) for value in parsed_values]

    if not selected_statuses or any(
        status not in allowed_statuses for status in selected_statuses
    ):
        values = ", ".join(sorted(allowed_statuses))
        example = (
            "\"status eq 'Active'\" or \"status in ('Active', 'Scheduled')\""
            if allow_in
            else "\"status eq 'Failed'\""
        )
        raise InvalidArgumentValueError(
            f"Use a supported status filter such as {example}. "
            f"Supported statuses: {values}."
        )


class JobRunProvider(ADRProvider):
    def create(
        self,
        job_name: str,
        namespace_name: str,
        resource_group_name: str,
        run_name: Optional[str] = None,
        scheduled_time: Optional[str] = None,
        **kwargs,
    ):
        """Create a run for an existing job.

        ``scheduledTime`` is the only writable field on ``JobRunProperties``; every
        other field is service-populated. ``run_name`` is a required path segment,
        so when the caller omits it a UTC-timestamped name is generated and echoed
        back in the response.
        """
        if scheduled_time is not None:
            validate_iso8601_datetime(scheduled_time)
        run_name = run_name or _generate_job_run_name()

        resource = {"properties": {}}
        if scheduled_time is not None:
            resource["properties"]["scheduledTime"] = scheduled_time

        poller = self.client.job_runs.begin_create_or_replace(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            job_name=job_name,
            run_name=run_name,
            resource=resource,
        )
        return self._wait(
            poller,
            f"Creating run '{run_name}' for job '{job_name}'...",
            **kwargs,
        )

    def delete(
        self,
        job_name: str,
        run_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        poller = self.client.job_runs.begin_delete(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            job_name=job_name,
            run_name=run_name,
        )
        return self._wait(
            poller,
            f"Deleting run '{run_name}' for job '{job_name}'...",
            **kwargs,
        )

    def summary(
        self,
        job_name: str,
        run_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return self.client.job_runs.get_summary(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            job_name=job_name,
            run_name=run_name,
        )

    def show(
        self,
        job_name: str,
        run_name: str,
        namespace_name: str,
        resource_group_name: str,
    ):
        return self.client.job_runs.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            job_name=job_name,
            run_name=run_name,
        )

    def list(
        self,
        namespace_name: str,
        resource_group_name: str,
        job_name: Optional[str] = None,
        status_filter: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> list:
        _validate_status_filter(status_filter, _JOB_RUN_STATUSES, allow_in=True)
        _validate_order_by(order_by)
        kwargs = {}
        if status_filter:
            kwargs["filter"] = status_filter
        if order_by:
            kwargs["order_by"] = order_by
        if job_name:
            result = self.client.job_runs.list_by_job(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                job_name=job_name,
                **kwargs,
            )
        else:
            result = self.client.job_runs_by_namespace.list_by_namespace(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                **kwargs,
            )
        return list(result)

    def cancel(
        self,
        job_name: str,
        run_name: str,
        namespace_name: str,
        resource_group_name: str,
        **kwargs,
    ):
        poller = self.client.job_runs.begin_cancel(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
            job_name=job_name,
            run_name=run_name,
        )
        return self._wait(
            poller,
            f"Canceling run '{run_name}' for job '{job_name}'...",
            **kwargs,
        )

    def results(
        self,
        job_name: str,
        run_name: str,
        namespace_name: str,
        resource_group_name: str,
        status_filter: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> Iterator[dict]:
        _validate_status_filter(status_filter, _RESULT_STATUSES, allow_in=False)
        _validate_order_by(order_by)
        body = {}
        if status_filter:
            body["filter"] = status_filter
        if order_by:
            body["orderBy"] = order_by

        skip_token = None
        seen_tokens = set()
        while True:
            request_body = dict(body)
            if skip_token:
                request_body["skipToken"] = skip_token
            response = self.client.job_runs.list_results(
                resource_group_name=resource_group_name,
                namespace_name=namespace_name,
                job_name=job_name,
                run_name=run_name,
                body=request_body,
            )
            yield from (response or {}).get("value") or []
            next_token = (response or {}).get("skipToken")
            if not next_token:
                return
            if next_token in seen_tokens:
                raise AzureResponseError(
                    "The job run results returned a repeated skip token."
                )
            seen_tokens.add(next_token)
            skip_token = next_token
