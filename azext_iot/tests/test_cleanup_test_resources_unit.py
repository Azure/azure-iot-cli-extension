# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


@pytest.fixture
def cleanup(mocker):
    path = Path(__file__).resolve().parents[2] / "scripts/cleanup_test_resources.py"
    spec = importlib.util.spec_from_file_location("test_resource_cleanup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mocker.patch.object(module, "inventory_url", return_value="https://management.azure.com/scope/resources")
    return module


@pytest.mark.parametrize("tags,excluded,expected", [
    ({}, False, False),
    ({"intTest": "true", "runUid": "owned", "createdEpoch": "999999"}, False, False),
    ({"intTest": "true", "runUid": "owned", "createdEpoch": "1"}, True, False),
    ({"intTest": "true", "createdEpoch": "1"}, False, False),
    ({"intTest": "true", "runUid": "owned", "createdEpoch": "invalid"}, False, False),
    ({"intTest": "true", "runUid": "owned", "createdEpoch": "1"}, False, True),
])
def test_cleanup_preserves_active_unowned_and_excluded_resources(cleanup, tags, excluded, expected):
    assert cleanup.expired({"name": "resource", "tags": tags}, {"resource"} if excluded else set(), 1000000) is expected


def test_cleanup_rechecks_ownership_before_deleting(cleanup, mocker):
    resource = {"name": "resource", "id": "/owned/id", "tags": {
        "intTest": "true", "runUid": "first-run", "createdEpoch": "1",
    }}
    changed = {**resource, "tags": {**resource["tags"], "runUid": "another-run"}}
    mocker.patch.object(cleanup, "inventory", return_value=[resource])
    mocker.patch.object(cleanup.subprocess, "check_output", return_value=json.dumps(changed))
    delete = mocker.patch.object(cleanup.subprocess, "run")
    with pytest.raises(RuntimeError, match="cleanup failures"):
        cleanup.cleanup("test-group", set(), now=1000000)
    delete.assert_not_called()


@pytest.mark.parametrize("error,failed", [
    (subprocess.CalledProcessError(3, "az", stderr="ERROR: (ResourceNotFound) absent"), False),
    (subprocess.CalledProcessError(1, "az", stderr="ERROR: (AuthorizationFailed) denied"), True),
])
def test_cleanup_continues_after_missing_or_failed_resource(cleanup, mocker, error, failed):
    resources = [
        {"name": name, "id": f"/owned/{name}",
         "tags": {"intTest": "true", "runUid": "owned", "createdEpoch": "1"}}
        for name in ("first", "second")
    ]
    mocker.patch.object(cleanup, "inventory", return_value=resources)
    mocker.patch.object(cleanup.subprocess, "check_output", side_effect=[error, json.dumps(resources[1])])
    delete = mocker.patch.object(cleanup.subprocess, "run")
    if failed:
        with pytest.raises(RuntimeError, match="1 resource cleanup failures"):
            cleanup.cleanup("test-group", set(), now=1000000)
    else:
        cleanup.cleanup("test-group", set(), now=1000000)
    assert delete.call_args.args[0][-1] == "/owned/second"


def test_cleanup_continues_after_delete_failure(cleanup, mocker):
    resources = [
        {"name": name, "id": f"/owned/{name}",
         "tags": {"intTest": "true", "runUid": "owned", "createdEpoch": "1"}}
        for name in ("first", "second")
    ]
    mocker.patch.object(cleanup, "inventory", return_value=resources)
    mocker.patch.object(cleanup.subprocess, "check_output", side_effect=list(map(json.dumps, resources)))
    delete = mocker.patch.object(cleanup.subprocess, "run", side_effect=[
        subprocess.CalledProcessError(1, "az", stderr="ERROR: (ScopeLocked) locked"), None,
    ])
    with pytest.raises(RuntimeError, match="1 resource cleanup failures"):
        cleanup.cleanup("test-group", set(), now=1000000)
    assert delete.call_count == 2


@pytest.mark.parametrize("name,owner,created,expected", [
    ("test-hub-" + "a" * 32, "b" * 32, "1970-01-02T00:00:00Z", True),
    ("test-hub-" + "a" * 32, "b" * 32, "1970-01-12T00:00:00Z", False),
    ("long-lived-hub", "b" * 32, "1970-01-02T00:00:00Z", False),
    ("test-hub-" + "a" * 32, "invalid", "1970-01-02T00:00:00Z", False),
    ("test-hub-" + "a" * 32, "b" * 32, "", False),
])
def test_cleanup_existing_hub_ownership_requires_age_and_naming(cleanup, name, owner, created, expected):
    resource = {
        "id": f"/subscriptions/sub/resourceGroups/group/providers/Microsoft.Devices/IotHubs/{name}",
        "name": name, "tags": {"azextHubRunId": owner}, "createdTime": created,
    }
    assert cleanup.expired(resource, set(), 1000000) is expected


@pytest.mark.parametrize("change", ["createdTime", "owner"])
def test_cleanup_rejects_replaced_hub_without_changing_test_tags(cleanup, mocker, change):
    name = "test-hub-" + "a" * 32
    resource = {
        "id": f"/subscriptions/sub/resourceGroups/group/providers/Microsoft.Devices/IotHubs/{name}",
        "name": name, "tags": {"azextHubRunId": "b" * 32}, "createdTime": "1970-01-02T00:00:00Z",
    }
    changed = {**resource}
    if change == "createdTime":
        changed["createdTime"] = "1970-01-03T00:00:00Z"
    else:
        changed["tags"] = {"azextHubRunId": "c" * 32}
    mocker.patch.object(cleanup, "inventory", side_effect=[[resource], [changed]])
    mocker.patch.object(cleanup.subprocess, "check_output", return_value=json.dumps(changed))
    delete = mocker.patch.object(cleanup.subprocess, "run")
    with pytest.raises(RuntimeError, match="cleanup failures"):
        cleanup.cleanup("test-group", set(), now=1000000)
    delete.assert_not_called()


@pytest.mark.parametrize("tags", [
    {"azextHubRunId": "b" * 32}, {"runUid": "b" * 32, "authPhase": "local-auth"},
])
def test_cleanup_reaps_only_verified_old_native_hub_roots(cleanup, mocker, tags):
    name = "test-hub-" + "a" * 32
    resource = {
        "id": f"/subscriptions/sub/resourceGroups/group/providers/Microsoft.Devices/IotHubs/{name}",
        "name": name, "tags": tags, "createdTime": "1970-01-02T00:00:00Z",
    }
    mocker.patch.object(cleanup, "inventory", return_value=[resource])
    mocker.patch.object(cleanup.subprocess, "check_output",
                        return_value=json.dumps({key: value for key, value in resource.items() if key != "createdTime"}))
    delete = mocker.patch.object(cleanup.subprocess, "run")
    cleanup.cleanup("test-group", set(), now=1000000)
    assert delete.call_args.args[0][-1] == resource["id"]


def test_cleanup_inventory_preserves_creation_metadata_across_pages(cleanup, mocker):
    url = "https://management.azure.com/scope/resources?api-version=2021-04-01&$expand=createdTime"
    mocker.patch.object(cleanup.subprocess, "check_output", side_effect=[
        json.dumps({"value": [{"createdTime": "first"}], "nextLink": url + "&$skiptoken=next"}),
        json.dumps({"value": [{"createdTime": "second"}]}),
    ])
    assert cleanup.inventory(url) == [{"createdTime": "first"}, {"createdTime": "second"}]
