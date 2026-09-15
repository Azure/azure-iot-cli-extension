# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import ArgumentUsageError
from azure.core.exceptions import HttpResponseError


@pytest.mark.parametrize(
    "report_type,group_name,selector",
    [
        (
            "NamespaceUpdateComplianceReport",
            None,
            {"reportType": "NamespaceUpdateComplianceReport"},
        ),
        (
            "GroupBestUpdatesComplianceReport",
            "  group  ",
            {
                "reportType": "GroupBestUpdatesComplianceReport",
                "reportTarget": "group",
            },
        ),
        (
            "GroupInstallableUpdatesReport",
            "group",
            {
                "reportType": "GroupInstallableUpdatesReport",
                "reportTarget": "group",
            },
        ),
    ],
)
def test_report_generate_all_types(
    fixture_report_provider,
    mock_poller,
    report_type,
    group_name,
    selector,
):
    poller = mock_poller()
    poller.result.return_value = None
    operations = fixture_report_provider.client.namespaces
    operations.begin_generate_report.return_value = poller

    def latest_report(**kwargs):
        poller.result.assert_called_once_with()
        return {"reportType": report_type}

    operations.get_latest_report.side_effect = latest_report

    result = fixture_report_provider.generate(
        namespace_name="namespace",
        resource_group_name="rg",
        report_type=report_type,
        group_name=group_name,
    )

    assert result == {"reportType": report_type}
    fixture_report_provider.client.namespaces.begin_generate_report.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        body=selector,
    )
    operations.get_latest_report.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        body=selector,
    )


@pytest.mark.parametrize(
    "report_type,group_name,selector",
    [
        (
            "NamespaceUpdateComplianceReport",
            None,
            {"reportType": "NamespaceUpdateComplianceReport"},
        ),
        (
            "GroupBestUpdatesComplianceReport",
            "group",
            {
                "reportType": "GroupBestUpdatesComplianceReport",
                "reportTarget": "group",
            },
        ),
        (
            "GroupInstallableUpdatesReport",
            "group",
            {
                "reportType": "GroupInstallableUpdatesReport",
                "reportTarget": "group",
            },
        ),
    ],
)
def test_report_latest_all_types(
    fixture_report_provider, report_type, group_name, selector
):
    fixture_report_provider.client.namespaces.get_latest_report.return_value = {
        "reportType": report_type
    }

    result = fixture_report_provider.latest(
        namespace_name="namespace",
        resource_group_name="rg",
        report_type=report_type,
        group_name=group_name,
    )

    assert result == {"reportType": report_type}
    fixture_report_provider.client.namespaces.get_latest_report.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        body=selector,
    )


@pytest.mark.parametrize(
    "report_type",
    [
        "GroupBestUpdatesComplianceReport",
        "GroupInstallableUpdatesReport",
    ],
)
def test_group_report_requires_group(fixture_report_provider, report_type):
    with pytest.raises(ArgumentUsageError, match="--group-name is required"):
        fixture_report_provider.generate(
            "namespace", "rg", report_type=report_type
        )
    fixture_report_provider.client.namespaces.begin_generate_report.assert_not_called()


def test_namespace_report_rejects_group(fixture_report_provider):
    with pytest.raises(
        ArgumentUsageError, match="only valid for group update reports"
    ):
        fixture_report_provider.latest(
            "namespace",
            "rg",
            report_type="NamespaceUpdateComplianceReport",
            group_name="group",
        )
    fixture_report_provider.client.namespaces.get_latest_report.assert_not_called()


def test_report_rejects_unknown_type(fixture_report_provider):
    with pytest.raises(ArgumentUsageError, match="Unsupported report type"):
        fixture_report_provider.generate(
            "namespace", "rg", report_type="UnknownReport"
        )


@pytest.mark.parametrize(
    "report_type,group_name",
    [
        ("NamespaceUpdateComplianceReport", None),
        ("GroupBestUpdatesComplianceReport", "group"),
        ("GroupInstallableUpdatesReport", "group"),
    ],
)
def test_report_generate_no_wait(
    fixture_report_provider, mock_poller, mocker, report_type, group_name
):
    poller = mock_poller(None)
    fixture_report_provider.client.namespaces.begin_generate_report.return_value = (
        poller
    )
    wait = mocker.spy(fixture_report_provider, "_wait")

    result = fixture_report_provider.generate(
        "namespace",
        "rg",
        report_type=report_type,
        group_name=group_name,
        no_wait=True,
    )

    assert result is poller
    poller.result.assert_not_called()
    wait.assert_not_called()
    fixture_report_provider.client.namespaces.get_latest_report.assert_not_called()


def test_report_generate_propagates_wait_failure(fixture_report_provider, mock_poller):
    poller = mock_poller()
    error = HttpResponseError(message="Report generation failed")
    poller.result.side_effect = error
    fixture_report_provider.client.namespaces.begin_generate_report.return_value = poller

    with pytest.raises(HttpResponseError) as raised:
        fixture_report_provider.generate("namespace", "rg", "NamespaceUpdateComplianceReport")

    assert raised.value is error
    fixture_report_provider.client.namespaces.get_latest_report.assert_not_called()


def test_report_generate_propagates_latest_failure(fixture_report_provider, mock_poller):
    poller = mock_poller()
    poller.result.return_value = None
    error = HttpResponseError(message="Report retrieval failed")
    operations = fixture_report_provider.client.namespaces
    operations.begin_generate_report.return_value = poller
    operations.get_latest_report.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        fixture_report_provider.generate("namespace", "rg", "NamespaceUpdateComplianceReport")

    assert raised.value is error
    poller.result.assert_called_once_with()
