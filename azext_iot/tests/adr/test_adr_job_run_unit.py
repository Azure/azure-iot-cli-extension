# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import re
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError

from azext_iot.adr import commands_job_run


def test_job_run_show(fixture_job_run_provider):
    expected = {"name": "run", "properties": {"status": "Succeeded"}}
    fixture_job_run_provider.client.job_runs.get.return_value = expected

    assert (
        fixture_job_run_provider.show("job", "run", "namespace", "rg")
        is expected
    )
    fixture_job_run_provider.client.job_runs.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
    )


def test_job_run_list_by_job(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_by_job.return_value = iter(
        [{"name": "one"}, {"name": "two"}]
    )

    result = fixture_job_run_provider.list(
        "namespace", "rg", job_name="job"
    )

    assert result == [{"name": "one"}, {"name": "two"}]
    fixture_job_run_provider.client.job_runs.list_by_job.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
    )
    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.assert_not_called()


def test_job_run_list_by_job_with_filter(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_by_job.return_value = iter([])

    fixture_job_run_provider.list(
        "namespace",
        "rg",
        job_name="job",
        status_filter="status eq 'Active'",
    )

    fixture_job_run_provider.client.job_runs.list_by_job.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        filter="status eq 'Active'",
    )


def test_job_run_list_by_job_with_order_by(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_by_job.return_value = iter([])

    fixture_job_run_provider.list(
        "namespace",
        "rg",
        job_name="job",
        order_by="status desc",
    )

    fixture_job_run_provider.client.job_runs.list_by_job.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        order_by="status desc",
    )


def test_job_run_list_by_namespace_with_filter(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.return_value = iter(
        [{"name": "one"}]
    )

    result = fixture_job_run_provider.list(
        "namespace",
        "rg",
        status_filter="status eq 'Active'",
    )

    assert result == [{"name": "one"}]
    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        filter="status eq 'Active'",
    )
    fixture_job_run_provider.client.job_runs.list_by_job.assert_not_called()


def test_job_run_list_by_namespace_with_order_by(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.return_value = iter([])

    fixture_job_run_provider.list(
        "namespace",
        "rg",
        order_by="status asc",
    )

    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        order_by="status asc",
    )
    fixture_job_run_provider.client.job_runs.list_by_job.assert_not_called()


def test_job_run_list_wrapper_forwards_order_by(mocker):
    provider = mocker.patch.object(
        commands_job_run, "JobRunProvider"
    ).return_value

    commands_job_run.adr_job_run_list(
        Mock(),
        namespace_name="namespace",
        resource_group_name="rg",
        job_name="job",
        status_filter="status eq 'Active'",
        order_by="status desc",
    )

    provider.list.assert_called_once_with(
        job_name="job",
        namespace_name="namespace",
        resource_group_name="rg",
        status_filter="status eq 'Active'",
        order_by="status desc",
    )


def test_job_run_list_accepts_status_in(fixture_job_run_provider):
    status_filter = "status in ('Active', 'Scheduled')"
    fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.return_value = iter([])

    fixture_job_run_provider.list(
        "namespace", "rg", status_filter=status_filter
    )

    assert (
        fixture_job_run_provider.client.job_runs_by_namespace.list_by_namespace.call_args.kwargs[
            "filter"
        ]
        == status_filter
    )


@pytest.mark.parametrize(
    "status_filter",
    [
        "status ne 'Canceled'",
        "status eq 'Unknown'",
        "status eq 'Queued'",
        "status eq 'Active' or status eq 'Scheduled'",
        "status in ()",
        "status in ('Active', Scheduled)",
        "name eq 'Active'",
    ],
)
def test_job_run_list_rejects_unsupported_filters(
    fixture_job_run_provider, status_filter
):
    with pytest.raises(InvalidArgumentValueError):
        fixture_job_run_provider.list(
            "namespace", "rg", status_filter=status_filter
        )


def test_job_run_results_posts_empty_body(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.return_value = {
        "value": [{"deviceId": "one"}],
        "skipToken": None,
    }

    result = list(
        fixture_job_run_provider.results("job", "run", "namespace", "rg")
    )

    assert result == [{"deviceId": "one"}]
    fixture_job_run_provider.client.job_runs.list_results.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
        body={},
    )


def test_job_run_results_posts_filter_body(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.return_value = {
        "value": [],
        "skipToken": None,
    }

    list(
        fixture_job_run_provider.results(
            "job",
            "run",
            "namespace",
            "rg",
            status_filter="status eq 'Failed'",
        )
    )

    assert (
        fixture_job_run_provider.client.job_runs.list_results.call_args.kwargs["body"]
        == {"filter": "status eq 'Failed'"}
    )


def test_job_run_results_posts_order_by(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.return_value = {
        "value": [],
        "skipToken": None,
    }

    list(
        fixture_job_run_provider.results(
            "job",
            "run",
            "namespace",
            "rg",
            order_by="status desc",
        )
    )

    assert (
        fixture_job_run_provider.client.job_runs.list_results.call_args.kwargs["body"]
        == {"orderBy": "status desc"}
    )


def test_job_run_results_rejects_unsupported_order_by(fixture_job_run_provider):
    with pytest.raises(InvalidArgumentValueError):
        list(
            fixture_job_run_provider.results(
                "job",
                "run",
                "namespace",
                "rg",
                order_by="createdTime desc",
            )
        )
    fixture_job_run_provider.client.job_runs.list_results.assert_not_called()


@pytest.mark.parametrize(
    "status_filter",
    [
        "status ne 'Failed'",
        "status eq 'Unknown'",
        "status eq 'NotApplied'",
        "status in ('Failed', 'Canceled')",
        "status eq 'Failed' or status eq 'Canceled'",
    ],
)
def test_job_run_results_rejects_unsupported_filters(
    fixture_job_run_provider, status_filter
):
    with pytest.raises(InvalidArgumentValueError):
        list(
            fixture_job_run_provider.results(
                "job",
                "run",
                "namespace",
                "rg",
                status_filter=status_filter,
            )
        )


def test_job_run_results_posts_each_page_with_skip_token(
    fixture_job_run_provider,
):
    fixture_job_run_provider.client.job_runs.list_results.side_effect = [
        {
            "value": [{"deviceId": "one"}],
            "skipToken": "token-1",
        },
        {
            "value": [{"deviceId": "two"}],
            "skipToken": "token-2",
        },
        {
            "value": [{"deviceId": "three"}],
        },
    ]

    result = list(
        fixture_job_run_provider.results(
            "job",
            "run",
            "namespace",
            "rg",
            status_filter="status eq 'Failed'",
            order_by="status asc",
        )
    )

    assert [item["deviceId"] for item in result] == ["one", "two", "three"]
    assert [
        call.kwargs["body"]
        for call in fixture_job_run_provider.client.job_runs.list_results.call_args_list
    ] == [
        {
            "filter": "status eq 'Failed'",
            "orderBy": "status asc",
        },
        {
            "filter": "status eq 'Failed'",
            "orderBy": "status asc",
            "skipToken": "token-1",
        },
        {
            "filter": "status eq 'Failed'",
            "orderBy": "status asc",
            "skipToken": "token-2",
        },
    ]


def test_job_run_results_follows_skip_token_after_empty_page(
    fixture_job_run_provider,
):
    fixture_job_run_provider.client.job_runs.list_results.side_effect = [
        {"value": None, "skipToken": "token-1"},
        {"value": [{"deviceId": "one"}]},
    ]

    assert list(
        fixture_job_run_provider.results("job", "run", "namespace", "rg")
    ) == [{"deviceId": "one"}]
    assert (
        fixture_job_run_provider.client.job_runs.list_results.call_args_list[1].kwargs[
            "body"
        ]
        == {"skipToken": "token-1"}
    )


def test_job_run_results_handles_empty_response(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.return_value = None

    assert not list(
        fixture_job_run_provider.results("job", "run", "namespace", "rg")
    )


def test_job_run_results_is_lazy_across_pages(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.side_effect = [
        {
            "value": [{"deviceId": "one"}, {"deviceId": "two"}],
            "skipToken": "token-1",
        },
        {"value": [{"deviceId": "three"}]},
    ]

    results = fixture_job_run_provider.results(
        "job", "run", "namespace", "rg"
    )
    assert [next(results), next(results)] == [
        {"deviceId": "one"},
        {"deviceId": "two"},
    ]
    assert fixture_job_run_provider.client.job_runs.list_results.call_count == 1
    assert next(results) == {"deviceId": "three"}
    assert fixture_job_run_provider.client.job_runs.list_results.call_count == 2


def test_job_run_results_rejects_repeated_skip_token(fixture_job_run_provider):
    fixture_job_run_provider.client.job_runs.list_results.side_effect = [
        {"value": [], "skipToken": "token-1"},
        {"value": [], "skipToken": "token-1"},
    ]

    with pytest.raises(AzureResponseError, match="repeated skip token"):
        list(
            fixture_job_run_provider.results(
                "job", "run", "namespace", "rg"
            )
        )
    assert fixture_job_run_provider.client.job_runs.list_results.call_count == 2


def test_job_run_cancel_waits_for_lro(fixture_job_run_provider, mock_poller):
    fixture_job_run_provider.client.job_runs.begin_cancel.return_value = mock_poller(
        {"status": "Canceled"}
    )

    result = fixture_job_run_provider.cancel(
        "job", "run", "namespace", "rg"
    )

    assert result == {"status": "Canceled"}
    fixture_job_run_provider.client.job_runs.begin_cancel.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
    )


def test_job_run_cancel_no_wait(fixture_job_run_provider, mock_poller):
    poller = mock_poller(None)
    fixture_job_run_provider.client.job_runs.begin_cancel.return_value = poller

    result = fixture_job_run_provider.cancel(
        "job", "run", "namespace", "rg", no_wait=True
    )

    assert result is poller
    poller.result.assert_not_called()


# ==================== Create / Delete / Summary (2026-11-02-preview) ====================


def test_job_run_create_with_scheduled_time(fixture_job_run_provider, mock_poller):
    """scheduledTime is the only writable field on JobRunProperties."""
    fixture_job_run_provider.client.job_runs.begin_create_or_replace.return_value = (
        mock_poller({"name": "run"})
    )

    result = fixture_job_run_provider.create(
        job_name="job",
        namespace_name="namespace",
        resource_group_name="rg",
        run_name="run",
        scheduled_time="2026-11-02T08:00:00Z",
    )

    assert result == {"name": "run"}
    fixture_job_run_provider.client.job_runs.begin_create_or_replace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
        resource={"properties": {"scheduledTime": "2026-11-02T08:00:00Z"}},
    )


def test_job_run_create_generates_run_name(fixture_job_run_provider, mock_poller):
    """runName is a required path segment, so omitting it generates one."""
    fixture_job_run_provider.client.job_runs.begin_create_or_replace.return_value = (
        mock_poller({})
    )

    fixture_job_run_provider.create(
        job_name="job", namespace_name="namespace", resource_group_name="rg"
    )

    kwargs = fixture_job_run_provider.client.job_runs.begin_create_or_replace.call_args.kwargs
    assert re.fullmatch(r"run-\d{14}", kwargs["run_name"])
    assert kwargs["resource"] == {"properties": {}}


@pytest.mark.parametrize(
    "scheduled_time",
    ["2026-11-02T08:00:00", "not-a-time", "2026-11-02"],
)
def test_job_run_create_rejects_non_absolute_time(
    fixture_job_run_provider, scheduled_time
):
    with pytest.raises(InvalidArgumentValueError, match="ISO 8601 UTC datetime"):
        fixture_job_run_provider.create(
            job_name="job",
            namespace_name="namespace",
            resource_group_name="rg",
            scheduled_time=scheduled_time,
        )
    fixture_job_run_provider.client.job_runs.begin_create_or_replace.assert_not_called()


def test_job_run_create_no_wait(fixture_job_run_provider, mock_poller):
    poller = mock_poller({})
    fixture_job_run_provider.client.job_runs.begin_create_or_replace.return_value = poller

    result = fixture_job_run_provider.create(
        job_name="job",
        namespace_name="namespace",
        resource_group_name="rg",
        no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()


def test_job_run_delete(fixture_job_run_provider, mock_poller):
    fixture_job_run_provider.client.job_runs.begin_delete.return_value = mock_poller(None)

    fixture_job_run_provider.delete(
        job_name="job",
        run_name="run",
        namespace_name="namespace",
        resource_group_name="rg",
    )

    fixture_job_run_provider.client.job_runs.begin_delete.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
    )


def test_job_run_delete_no_wait(fixture_job_run_provider, mock_poller):
    poller = mock_poller(None)
    fixture_job_run_provider.client.job_runs.begin_delete.return_value = poller

    result = fixture_job_run_provider.delete(
        job_name="job",
        run_name="run",
        namespace_name="namespace",
        resource_group_name="rg",
        no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()


def test_job_run_summary(fixture_job_run_provider):
    expected = {
        "total": 10,
        "succeeded": 7,
        "failed": 1,
        "inProgress": 1,
        "pending": 1,
        "canceled": 0,
        "notApplied": 0,
    }
    fixture_job_run_provider.client.job_runs.get_summary.return_value = expected

    assert (
        fixture_job_run_provider.summary(
            job_name="job",
            run_name="run",
            namespace_name="namespace",
            resource_group_name="rg",
        )
        is expected
    )
    fixture_job_run_provider.client.job_runs.get_summary.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        job_name="job",
        run_name="run",
    )
