# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import AzureResponseError, InvalidArgumentValueError, RequiredArgumentMissingError
from azure.core.exceptions import HttpResponseError

from azext_iot.adr.providers.base import parse_json_object
from azext_iot.adr.providers.namespace import _clean_migrate_resource_ids, _messaging_properties

NS = "test-ns"
RG = "test-rg"
ASSET_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/assets/asset1"
ENDPOINTS = {"events": {"address": "https://events.example", "endpointType": "EventGrid", "resourceId": "/event-grid"}}


@pytest.fixture
def provider(fixture_namespace_provider, mocker):
    mocker.patch("azext_iot.adr.providers.base.wait_for_terminal_state", side_effect=lambda poller, **_: poller.result())
    return fixture_namespace_provider


@pytest.mark.parametrize("value", [{"a": 1}, '{"a":1}'])
def test_json_objects(value):
    assert parse_json_object(value, "--arg") == {"a": 1}


def test_json_file():
    path = Path(__file__).parent / "fixtures" / "messaging.json"
    assert parse_json_object(str(path), "--messaging-endpoints") == ENDPOINTS


@pytest.mark.parametrize("value", ["bad json", "missing-file.json", "[]", "null", "1", [], 1, None])
def test_invalid_json(value):
    with pytest.raises(InvalidArgumentValueError, match="JSON object"):
        parse_json_object(value, "--arg")


@pytest.mark.parametrize("value,expected", [(None, {}), ({}, {"messaging": {"endpoints": {}}})])
def test_empty_messaging(value, expected):
    assert _messaging_properties(value) == expected


def test_messaging_does_not_mutate_input():
    value = deepcopy(ENDPOINTS)
    assert _messaging_properties(value) == {"messaging": {"endpoints": ENDPOINTS}}
    assert value == ENDPOINTS


@pytest.mark.parametrize(
    "value,error",
    [
        ({"": {"address": "value"}}, "nonempty endpoint names"),
        ({"  ": {"address": "value"}}, "nonempty endpoint names"),
        ({1: {"address": "value"}}, "nonempty endpoint names"),
        ({"one": []}, "JSON objects"),
        ({"one": {"address": "value", "authentication": {}}}, "unsupported properties: authentication"),
        ({"one": {}}, "requires a nonempty address"),
        ({"one": {"address": None}}, "requires a nonempty address"),
        ({"one": {"address": "  "}}, "requires a nonempty address"),
        ({"one": {"address": 1}}, "requires a nonempty address"),
        ({"one": {"address": "value", "endpointType": None}}, "endpointType.*must be a string"),
        ({"one": {"address": "value", "resourceId": {}}}, "resourceId.*must be a string"),
    ],
)
def test_invalid_messaging(provider, value, error):
    with pytest.raises(InvalidArgumentValueError, match=error):
        provider.create(NS, RG, messaging_endpoints=value)
    provider.client.namespaces.begin_create_or_replace.assert_not_called()


@pytest.mark.parametrize("system_assigned", [True, False])
@pytest.mark.parametrize("tags", [None, {}, {"env": "test"}])
@pytest.mark.parametrize("endpoints", [None, {}, ENDPOINTS])
def test_namespace_create(provider, tags, endpoints, system_assigned):
    result = {"name": NS}
    provider.client.namespaces.begin_create_or_replace.return_value.result.return_value = result
    assert provider.create(
        NS, RG, location="centraluseuap", tags=tags,
        system_assigned=system_assigned, messaging_endpoints=endpoints,
    ) == {"name": NS, "resourceGroup": RG}
    body = {
        "location": "centraluseuap",
        "identity": {"type": "SystemAssigned" if system_assigned else "None"},
    }
    if tags is not None:
        body["tags"] = tags
    if endpoints is not None:
        body["properties"] = {"messaging": {"endpoints": endpoints}}
    provider.client.namespaces.begin_create_or_replace.assert_called_once_with(
        resource_group_name=RG, namespace_name=NS, resource=body,
    )
    provider.client.namespaces.get.assert_not_called()


@pytest.mark.parametrize("result", [None, {"resourceGroup": "existing"}, {}])
def test_namespace_create_result_shapes(provider, mocker, result):
    fallback = mocker.patch.object(provider, "_ensure_location", return_value="group-location")
    provider.client.namespaces.begin_create_or_replace.return_value.result.return_value = result
    assert provider.create(NS, RG) is result
    fallback.assert_called_once_with(provider.cmd.cli_ctx, RG, None)
    assert provider.client.namespaces.begin_create_or_replace.call_args.kwargs["resource"]["identity"] == {
        "type": "SystemAssigned"
    }


@pytest.mark.parametrize("operation", ["create", "update", "delete", "migrate", "identity_assign", "identity_remove"])
def test_mutations_no_wait(provider, operation, mocker):
    wait = mocker.patch("azext_iot.adr.providers.base.wait_for_terminal_state")
    arguments = {"location": "centraluseuap"} if operation == "create" else {}
    if operation == "migrate":
        arguments["resource_ids"] = [ASSET_ID]
    sdk_operation = {
        "create": "begin_create_or_replace", "delete": "begin_delete", "migrate": "begin_migrate",
    }.get(operation, "begin_update")
    poller = getattr(provider.client.namespaces, sdk_operation).return_value
    assert getattr(provider, operation)(NS, RG, no_wait=True, **arguments) is poller
    wait.assert_not_called()
    poller.result.assert_not_called()


@pytest.mark.parametrize("system_assigned", [None, True, False])
@pytest.mark.parametrize("tags", [None, {}, {"env": "test"}])
@pytest.mark.parametrize("endpoints", [None, {}, ENDPOINTS])
def test_namespace_update(provider, tags, endpoints, system_assigned):
    expected = {}
    if tags is not None:
        expected["tags"] = tags
    if system_assigned is not None:
        expected["identity"] = {"type": "SystemAssigned" if system_assigned else "None"}
    if endpoints is not None:
        expected["properties"] = {"messaging": {"endpoints": endpoints}}
    poller = provider.client.namespaces.begin_update.return_value
    assert provider.update(NS, RG, tags, system_assigned, endpoints) is poller.result.return_value
    provider.client.namespaces.begin_update.assert_called_once_with(
        resource_group_name=RG, namespace_name=NS, properties=expected,
    )
    provider.client.namespaces.get.assert_not_called()


def test_namespace_show(provider):
    assert provider.show(NS, RG) is provider.client.namespaces.get.return_value
    provider.client.namespaces.get.assert_called_once_with(resource_group_name=RG, namespace_name=NS)


@pytest.mark.parametrize("resource_group", [RG, None])
def test_namespace_list(provider, resource_group):
    operation = (
        provider.client.namespaces.list_by_resource_group if resource_group
        else provider.client.namespaces.list_by_subscription
    )
    operation.return_value = iter([{"name": "one"}, {"name": "two"}])
    assert provider.list(resource_group) == [{"name": "one"}, {"name": "two"}]
    operation.assert_called_once_with(**({"resource_group_name": RG} if resource_group else {}))


def test_namespace_delete(provider):
    provider.client.namespaces.begin_delete.return_value.result.return_value = None
    assert provider.delete(NS, RG) is None
    provider.client.namespaces.begin_delete.assert_called_once_with(resource_group_name=RG, namespace_name=NS)


@pytest.mark.parametrize("during_poll", [True, False])
@pytest.mark.parametrize("not_empty", [True, False])
def test_delete_errors(provider, during_poll, not_empty):
    error = HttpResponseError("NamespaceNotEmpty" if not_empty else "Forbidden")
    operation = provider.client.namespaces.begin_delete
    if during_poll:
        operation.return_value.result.side_effect = error
    else:
        operation.side_effect = error
    with pytest.raises(AzureResponseError if not_empty else HttpResponseError) as raised:
        provider.delete(NS, RG)
    if not_empty:
        assert raised.value.__cause__ is error
        assert "does not cascade" in str(raised.value)
        assert "az iot adr ns" not in str(raised.value)
    else:
        assert raised.value is error


@pytest.mark.parametrize("operation", ["create", "update", "show", "list", "migrate"])
def test_service_errors_propagate(provider, operation):
    error = HttpResponseError("Forbidden")
    sdk_operation = {
        "create": "begin_create_or_replace", "update": "begin_update", "show": "get",
        "list": "list_by_resource_group", "migrate": "begin_migrate",
    }[operation]
    getattr(provider.client.namespaces, sdk_operation).side_effect = error
    arguments = {"location": "centraluseuap"} if operation == "create" else {}
    if operation == "migrate":
        arguments["resource_ids"] = [ASSET_ID]
    with pytest.raises(HttpResponseError) as raised:
        if operation == "list":
            provider.list(RG)
        else:
            getattr(provider, operation)(NS, RG, **arguments)
    assert raised.value is error


def test_migrate(provider):
    poller = provider.client.namespaces.begin_migrate.return_value
    assert provider.migrate(NS, RG, [ASSET_ID, " " + ASSET_ID.upper() + "/ "]) is poller.result.return_value
    provider.client.namespaces.begin_migrate.assert_called_once_with(
        namespace_name=NS, resource_group_name=RG, body={"scope": "Resources", "resourceIds": [ASSET_ID]},
    )


@pytest.mark.parametrize("value", [None, []])
def test_missing_migration_ids(value):
    with pytest.raises(RequiredArgumentMissingError, match="--resource-ids"):
        _clean_migrate_resource_ids(value)


@pytest.mark.parametrize(
    "value",
    [None, 1, "", " ", "bad", ASSET_ID.replace("DeviceRegistry", "Other"),
     ASSET_ID.replace("/assets/", "/namespaces/"), ASSET_ID + "/child/name"],
)
def test_invalid_migration_ids(provider, value):
    with pytest.raises(InvalidArgumentValueError, match="resource ID"):
        provider.migrate(NS, RG, [value])
    provider.client.namespaces.begin_migrate.assert_not_called()


@pytest.mark.parametrize("identity", [None, {}, {"type": "SystemAssigned", "principalId": "principal"}])
def test_identity_show(provider, identity):
    provider.client.namespaces.get.return_value = {"identity": identity}
    assert provider.identity_show(NS, RG) == (identity or {})


@pytest.mark.parametrize("operation,identity_type", [("identity_assign", "SystemAssigned"), ("identity_remove", "None")])
@pytest.mark.parametrize("result", [None, {}, {"identity": None}, {"identity": {"type": "SystemAssigned"}}])
def test_identity_mutations(provider, operation, identity_type, result):
    provider.client.namespaces.begin_update.return_value.result.return_value = result
    expected = None if result is None else result.get("identity") or {}
    assert getattr(provider, operation)(NS, RG) == expected
    provider.client.namespaces.begin_update.assert_called_once_with(
        namespace_name=NS, resource_group_name=RG, properties={"identity": {"type": identity_type}},
    )


def test_wait_forwards_poll_options(fixture_adr_provider, mocker):
    wait = mocker.patch("azext_iot.adr.providers.base.wait_for_terminal_state")
    poller = Mock()
    assert fixture_adr_provider._wait(poller, "waiting", wait_sec=0, no_wait=False) is wait.return_value
    wait.assert_called_once_with(poller, wait_sec=0)
