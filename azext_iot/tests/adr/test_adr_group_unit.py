# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    RequiredArgumentMissingError,
)
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.wait import group_membership_ready


def _refresh_error(status_code, code):
    error = HttpResponseError(message=code)
    error.status_code = status_code
    error.error = Mock(code=code)
    return error


def test_group_create_all_fields(fixture_group_provider):
    fixture_group_provider.client.groups.create_or_replace.return_value = {
        "name": "group"
    }

    result = fixture_group_provider.create(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        query_string="properties.manufacturer = 'Contoso'",
        group_type="RegistryDevice",
        location="eastus",
        display_name="Production",
        description="Production devices",
        tags={"env": "prod"},
    )

    assert result == {"name": "group"}
    fixture_group_provider.client.groups.create_or_replace.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
        resource={
            "location": "eastus",
            "properties": {
                "groupType": "RegistryDevice",
                "queryFilter": "properties.manufacturer = 'Contoso'",
                "displayName": "Production",
                "description": "Production devices",
            },
            "tags": {"env": "prod"},
        },
    )


def test_group_create_defaults_to_registry_device_type(fixture_group_provider):
    """The 2026-11-02-preview GroupType enum only defines RegistryDevice."""
    fixture_group_provider.client.groups.create_or_replace.return_value = {}

    fixture_group_provider.create(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        query_string="*",
        location="eastus",
    )

    body = fixture_group_provider.client.groups.create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["properties"]["groupType"] == "RegistryDevice"


def test_group_create_omits_identity(fixture_group_provider):
    """Group is a plain TrackedResource in 2026-11-02-preview: no identity block."""
    fixture_group_provider.client.groups.create_or_replace.return_value = {}

    fixture_group_provider.create(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        query_string="*",
        location="eastus",
    )

    body = fixture_group_provider.client.groups.create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert "identity" not in body


def test_group_create_inherits_parent_location(fixture_group_provider):
    fixture_group_provider.client.namespaces.get.return_value = {"location": "westus2"}
    fixture_group_provider.client.groups.create_or_replace.return_value = {}

    fixture_group_provider.create(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        query_string="*",
    )

    fixture_group_provider.client.namespaces.get.assert_called_once_with(
        resource_group_name="rg", namespace_name="namespace"
    )
    body = fixture_group_provider.client.groups.create_or_replace.call_args.kwargs[
        "resource"
    ]
    assert body["location"] == "westus2"


def test_group_update_all_mutable_fields(fixture_group_provider):
    fixture_group_provider.client.groups.update.return_value = {"name": "group"}

    fixture_group_provider.update(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        display_name="New name",
        description="New description",
        tags={"env": "staging"},
    )

    fixture_group_provider.client.groups.update.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
        properties={
            "properties": {
                "displayName": "New name",
                "description": "New description",
            },
            "tags": {"env": "staging"},
        },
    )


def test_group_update_tags_only_allows_clear(fixture_group_provider):
    fixture_group_provider.client.groups.update.return_value = {}

    fixture_group_provider.update(
        group_name="group",
        namespace_name="namespace",
        resource_group_name="rg",
        tags={},
    )

    assert (
        fixture_group_provider.client.groups.update.call_args.kwargs["properties"]
        == {"tags": {}}
    )


def test_group_update_rejects_empty_patch(fixture_group_provider):
    with pytest.raises(RequiredArgumentMissingError, match="Nothing to update"):
        fixture_group_provider.update(
            group_name="group",
            namespace_name="namespace",
            resource_group_name="rg",
        )
    fixture_group_provider.client.groups.update.assert_not_called()


def test_group_show_and_list(fixture_group_provider):
    fixture_group_provider.client.groups.get.return_value = {"name": "group"}
    fixture_group_provider.client.groups.list_by_namespace.return_value = iter(
        [{"name": "one"}, {"name": "two"}]
    )

    assert fixture_group_provider.show("group", "namespace", "rg") == {
        "name": "group"
    }
    assert fixture_group_provider.list("namespace", "rg") == [
        {"name": "one"},
        {"name": "two"},
    ]
    fixture_group_provider.client.groups.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )
    fixture_group_provider.client.groups.list_by_namespace.assert_called_once_with(
        resource_group_name="rg", namespace_name="namespace"
    )


def test_group_delete_calls_groups_delete_directly(
    fixture_group_provider, mocker
):
    fixture_group_provider.client.groups.delete.return_value = None
    wait = mocker.patch.object(fixture_group_provider, "_wait")

    assert fixture_group_provider.delete("group", "namespace", "rg") is None

    fixture_group_provider.client.groups.delete.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )
    fixture_group_provider.client.jobs.list_by_namespace.assert_not_called()
    fixture_group_provider.client.jobs.begin_delete.assert_not_called()
    fixture_group_provider.client.job_runs.list_by_job.assert_not_called()
    wait.assert_not_called()


def test_group_delete_no_wait(fixture_group_provider, mocker):
    fixture_group_provider.client.groups.delete.return_value = None
    wait = mocker.patch.object(fixture_group_provider, "_wait")

    result = fixture_group_provider.delete(
        "group", "namespace", "rg", no_wait=True
    )

    assert result is None
    fixture_group_provider.client.groups.delete.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )
    fixture_group_provider.client.jobs.list_by_namespace.assert_not_called()
    fixture_group_provider.client.jobs.begin_delete.assert_not_called()
    fixture_group_provider.client.job_runs.list_by_job.assert_not_called()
    wait.assert_not_called()


def test_group_refresh(fixture_group_provider, mock_poller):
    poller = mock_poller({"status": "Ready"})
    fixture_group_provider.client.groups.begin_refresh_members.return_value = poller

    result = fixture_group_provider.refresh(
        "group", "namespace", "rg", no_wait=True
    )

    assert result is poller
    fixture_group_provider.client.groups.begin_refresh_members.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )


def test_group_refresh_in_progress_no_wait_returns_current_group(
    fixture_group_provider,
):
    fixture_group_provider.client.groups.begin_refresh_members.side_effect = (
        _refresh_error(409, "GroupRefreshAlreadyInProgress")
    )
    fixture_group_provider.client.groups.get.return_value = {
        "properties": {"membershipState": "Resolving"}
    }

    result = fixture_group_provider.refresh(
        "group", "namespace", "rg", no_wait=True
    )

    assert result == {"properties": {"membershipState": "Resolving"}}
    fixture_group_provider.client.groups.get.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )


def test_group_refresh_in_progress_waits_for_current_group(
    fixture_group_provider, mocker
):
    fixture_group_provider.client.groups.begin_refresh_members.side_effect = (
        _refresh_error(409, "GroupRefreshAlreadyInProgress")
    )
    ready_group = {"properties": {"membershipState": "Ready"}}
    fixture_group_provider.client.groups.get.return_value = ready_group
    wait = mocker.patch(
        "azext_iot.adr.providers.group.wait_for_resource",
    )

    result = fixture_group_provider.refresh("group", "namespace", "rg")

    assert result == ready_group
    cli_ctx, getter, condition = wait.call_args.args
    assert cli_ctx is fixture_group_provider.cmd.cli_ctx
    assert condition is group_membership_ready
    assert getter() == ready_group
    assert (
        fixture_group_provider.client.groups.get.call_count == 2
    )


def test_group_refresh_rate_limit_is_not_treated_as_idempotent(
    fixture_group_provider,
):
    error = _refresh_error(409, "GroupRefreshRateLimited")
    fixture_group_provider.client.groups.begin_refresh_members.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        fixture_group_provider.refresh("group", "namespace", "rg")

    assert raised.value is error
    assert raised.value.error.code == "GroupRefreshRateLimited"
    fixture_group_provider.client.groups.get.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        _refresh_error(409, "SomeOtherConflict"),
        _refresh_error(400, "GroupRefreshAlreadyInProgress"),
    ],
)
def test_group_refresh_propagates_unrelated_error(
    fixture_group_provider, error
):
    fixture_group_provider.client.groups.begin_refresh_members.side_effect = error

    with pytest.raises(HttpResponseError) as raised:
        fixture_group_provider.refresh("group", "namespace", "rg")

    assert raised.value is error
    fixture_group_provider.client.groups.get.assert_not_called()


def test_group_list_members_single_page_uses_body(fixture_group_provider):
    fixture_group_provider.client.groups.list_members.return_value = {
        "members": [{"resourceId": "/devices/one"}]
    }

    result = fixture_group_provider.list_members(
        "group",
        "namespace",
        "rg",
        page_size=100,
        skip_token="initial",
    )

    assert result == [{"resourceId": "/devices/one"}]
    fixture_group_provider.client.groups.list_members.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
        body={"pageSize": 100, "skipToken": "initial"},
    )


def test_group_list_members_custom_skip_token_pagination(fixture_group_provider):
    responses = iter([
        {
            "members": [{"resourceId": "/devices/one"}],
            "skipToken": "next-one",
        },
        {
            "members": [{"resourceId": "/devices/two"}],
            "skipToken": "next-two",
        },
        {"members": [{"resourceId": "/devices/three"}], "skipToken": None},
    ])
    bodies = []

    def list_members(**kwargs):
        bodies.append(kwargs["body"].copy())
        return next(responses)

    fixture_group_provider.client.groups.list_members.side_effect = list_members

    result = fixture_group_provider.list_members(
        "group", "namespace", "rg", page_size=2
    )

    assert [item["resourceId"] for item in result] == [
        "/devices/one",
        "/devices/two",
        "/devices/three",
    ]
    assert bodies == [
        {"pageSize": 2},
        {"pageSize": 2, "skipToken": "next-one"},
        {"pageSize": 2, "skipToken": "next-two"},
    ]


def test_group_list_members_handles_empty_response(fixture_group_provider):
    fixture_group_provider.client.groups.list_members.return_value = None

    assert fixture_group_provider.list_members("group", "namespace", "rg") == []
    assert (
        fixture_group_provider.client.groups.list_members.call_args.kwargs["body"]
        == {}
    )


@pytest.mark.parametrize("page_size", [0, -1, 1001])
def test_group_list_members_rejects_invalid_page_size(
    fixture_group_provider, page_size
):
    with pytest.raises(InvalidArgumentValueError, match="between 1 and 1000"):
        fixture_group_provider.list_members(
            "group", "namespace", "rg", page_size=page_size
        )
    fixture_group_provider.client.groups.list_members.assert_not_called()


def test_group_list_members_rejects_repeated_skip_token(fixture_group_provider):
    fixture_group_provider.client.groups.list_members.side_effect = [
        {"members": [], "skipToken": "same"},
        {"members": [], "skipToken": "same"},
    ]

    with pytest.raises(AzureResponseError, match="repeated skip token"):
        fixture_group_provider.list_members("group", "namespace", "rg")


@pytest.mark.parametrize(
    "response,expected", [({"count": 42}, 42), ({"count": 0}, 0), ({}, 0), (None, 0)]
)
def test_group_count_members(fixture_group_provider, response, expected):
    fixture_group_provider.client.groups.count_members.return_value = response

    assert fixture_group_provider.count("group", "namespace", "rg") == expected
    fixture_group_provider.client.groups.count_members.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        group_name="group",
    )
