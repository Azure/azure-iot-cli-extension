# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from copy import deepcopy

import pytest
from azure.cli.core.azclierror import ArgumentUsageError
from knack.util import CLIError

from azext_iot.core import custom


ENDPOINTS = [
    ("eventhub", "eventHubs"), ("servicebusqueue", "serviceBusQueues"),
    ("servicebustopic", "serviceBusTopics"), ("azurestoragecontainer", "storageContainers"),
]


def assert_hub_write(client, hub, result):
    assert result is client.iot_hub_resource.begin_create_or_update.return_value
    client.iot_hub_resource.begin_create_or_update.assert_called_once_with(
        resource_group_name="rg", resource_name="hub", iot_hub_description=hub, etag="hub-etag"
    )


@pytest.mark.parametrize("endpoint_type,key", ENDPOINTS)
@pytest.mark.parametrize("identity", [None, "[system]", "/identities/user"])
def test_endpoint_create_preview_fields(preview_mgmt, endpoint_type, key, identity):
    cmd, client, hub, _, _ = preview_mgmt
    authentication_type = "identityBased" if identity else None
    result = custom.iot_hub_routing_endpoint_create(
        cmd, client, "hub", "endpoint", endpoint_type, "endpoint-rg", "endpoint-sub",
        connection_string="cs", container_name="uploads", authentication_type=authentication_type,
        endpoint_uri="https://endpoint.test", entity_path="entity", identity=identity,
    )
    expected = {
        "connectionString": "cs", "name": "endpoint", "subscriptionId": "endpoint-sub",
        "resourceGroup": "endpoint-rg", "authenticationType": authentication_type,
        "endpointUri": "https://endpoint.test",
        "identity": {"userAssignedIdentity": identity} if identity == "/identities/user" else None,
    }
    if key == "storageContainers":
        expected.update({
            "containerName": "uploads", "encoding": "avro", "fileNameFormat": "{iothub}/{partition}/{YYYY}/{MM}/{DD}/{HH}/{mm}",
            "batchFrequencyInSeconds": 300, "maxChunkSizeInBytes": 300 * 1048576,
        })
    else:
        expected["entityPath"] = "entity"
    assert hub["properties"]["routing"]["endpoints"][key] == [expected]
    assert all(not entries for name, entries in hub["properties"]["routing"]["endpoints"].items() if name != key)
    assert_hub_write(client, hub, result)


@pytest.mark.parametrize("arguments,error,message", [
    ({"identity": "/identities/user"}, ArgumentUsageError, "identityBased"),
    ({}, CLIError, "Container name is required"),
])
def test_endpoint_create_invalid_arguments_do_not_write(preview_mgmt, arguments, error, message):
    cmd, client, _, _, _ = preview_mgmt
    with pytest.raises(error, match=message):
        custom.iot_hub_routing_endpoint_create(
            cmd, client, "hub", "endpoint", "azurestoragecontainer", "endpoint-rg", "sub", **arguments
        )
    client.iot_hub_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("endpoint_type,arguments,message", [
    ("eventhub", {}, "connection string"),
    ("azurestoragecontainer", {"connection_string": "cs"}, "endpoint uri"),
    ("eventhub", {"authentication_type": "identityBased", "endpoint_uri": "https://endpoint.test"}, "entity path"),
])
def test_endpoint_auth_validation(endpoint_type, arguments, message):
    with pytest.raises(CLIError, match=message):
        custom.validate_authentication_type_input(endpoint_type, **arguments)


@pytest.mark.parametrize("endpoint_type,_", ENDPOINTS)
def test_endpoint_auth_accepts_complete_parameters(endpoint_type, _):
    assert custom.validate_authentication_type_input(
        endpoint_type, authentication_type="identityBased", endpoint_uri="https://endpoint.test", entity_path="entity"
    ) is None


@pytest.fixture
def populated_endpoints(preview_mgmt):
    _, _, hub, _, _ = preview_mgmt
    endpoints = hub["properties"]["routing"]["endpoints"]
    for _, key in ENDPOINTS:
        endpoints[key] = [{"name": key, "connectionString": key}, {"name": f"{key}-keep"}]
    return endpoints


@pytest.mark.parametrize("endpoint_type,key", ENDPOINTS)
def test_endpoint_list_and_case_insensitive_show(preview_mgmt, populated_endpoints, endpoint_type, key):
    cmd, client, _, _, _ = preview_mgmt
    assert custom.iot_hub_routing_endpoint_list(cmd, client, "hub") == populated_endpoints
    assert custom.iot_hub_routing_endpoint_list(cmd, client, "hub", endpoint_type.upper()) == populated_endpoints[key]
    assert custom.iot_hub_routing_endpoint_show(cmd, client, "hub", key.upper()) == populated_endpoints[key][0]


def test_endpoint_show_missing(preview_mgmt, populated_endpoints):
    cmd, client, _, _, _ = preview_mgmt
    with pytest.raises(CLIError, match="No endpoint found"):
        custom.iot_hub_routing_endpoint_show(cmd, client, "hub", "missing")


@pytest.mark.parametrize("endpoint_type,key", ENDPOINTS)
@pytest.mark.parametrize("selector", ["name", "type"])
def test_endpoint_delete_preserves_other_endpoints(preview_mgmt, populated_endpoints, endpoint_type, key, selector):
    cmd, client, hub, _, _ = preview_mgmt
    expected = deepcopy(populated_endpoints)
    arguments = {"endpoint_name": key.upper()} if selector == "name" else {"endpoint_type": endpoint_type.upper()}
    expected[key] = expected[key][1:] if selector == "name" else []
    result = custom.iot_hub_routing_endpoint_delete(cmd, client, "hub", **arguments)
    assert hub["properties"]["routing"]["endpoints"] == expected
    assert_hub_write(client, hub, result)


def test_endpoint_delete_all(preview_mgmt, populated_endpoints):
    cmd, client, hub, _, _ = preview_mgmt
    result = custom.iot_hub_routing_endpoint_delete(cmd, client, "hub")
    assert hub["properties"]["routing"]["endpoints"] == {key: [] for _, key in ENDPOINTS}
    assert_hub_write(client, hub, result)


@pytest.mark.parametrize("enabled,condition", [(None, None), (False, "temperature > 20")])
def test_route_create_defaults_and_explicit_values(preview_mgmt, enabled, condition):
    cmd, client, hub, _, _ = preview_mgmt
    result = custom.iot_hub_route_create(
        cmd, client, "hub", "route", "DeviceMessages", "first second", enabled=enabled, condition=condition
    )
    assert hub["properties"]["routing"]["routes"] == [{
        "name": "route", "source": "DeviceMessages", "endpointNames": ["first", "second"],
        "condition": "true" if condition is None else condition, "isEnabled": True if enabled is None else enabled,
    }]
    assert_hub_write(client, hub, result)


@pytest.fixture
def routes(preview_mgmt):
    _, _, hub, _, _ = preview_mgmt
    routes = [
        {"name": "messages", "source": "DeviceMessages", "endpointNames": ["events"], "condition": "true", "isEnabled": True},
        {"name": "twins", "source": "TwinChangeEvents", "endpointNames": ["events"], "condition": "true", "isEnabled": True},
    ]
    hub["properties"]["routing"]["routes"] = routes
    return routes


def test_route_list_filter_and_show(preview_mgmt, routes):
    cmd, client, _, _, _ = preview_mgmt
    assert custom.iot_hub_route_list(cmd, client, "hub") == routes
    assert custom.iot_hub_route_list(cmd, client, "hub", "devicemessages") == [routes[0]]
    assert custom.iot_hub_route_show(cmd, client, "hub", "TWINS") == routes[1]


@pytest.mark.parametrize("action", ["show", "update"])
def test_route_missing_fails_before_write(preview_mgmt, routes, action):
    cmd, client, _, _, _ = preview_mgmt
    with pytest.raises(CLIError, match="No route found"):
        getattr(custom, f"iot_hub_route_{action}")(cmd, client, "hub", "missing")
    client.iot_hub_resource.begin_create_or_update.assert_not_called()


@pytest.mark.parametrize("arguments", [{}, {"route_name": "MESSAGES"}, {"source_type": "devicemessages"}])
def test_route_delete_selectors(preview_mgmt, routes, arguments):
    cmd, client, hub, _, _ = preview_mgmt
    expected = [deepcopy(routes[1])] if arguments else []
    result = custom.iot_hub_route_delete(cmd, client, "hub", **arguments)
    assert hub["properties"]["routing"]["routes"] == expected
    assert_hub_write(client, hub, result)


@pytest.mark.parametrize("change", [False, True])
def test_route_update_preserves_unspecified_fields(preview_mgmt, routes, change):
    cmd, client, hub, _, _ = preview_mgmt
    expected = deepcopy(routes)
    arguments = {}
    if change:
        arguments = {"source_type": "TwinChangeEvents", "endpoint_name": "a b", "enabled": False, "condition": "false"}
        expected[0].update({
            "source": "TwinChangeEvents", "endpointNames": ["a", "b"], "isEnabled": False, "condition": "false"
        })
    result = custom.iot_hub_route_update(cmd, client, "hub", "MESSAGES", **arguments)
    assert hub["properties"]["routing"]["routes"] == expected
    assert_hub_write(client, hub, result)


@pytest.mark.parametrize("route_name", [None, "messages"])
def test_route_test_deserializes_properties(preview_mgmt, routes, route_name):
    cmd, client, _, _, _ = preview_mgmt
    result = custom.iot_hub_route_test(
        cmd, client, "hub", route_name=route_name, source_type="DeviceMessages", body="message",
        app_properties='{"app":"value"}', system_properties='{"contentType":"text/plain"}',
    )
    message = {"body": "message", "appProperties": {"app": "value"}, "systemProperties": {"contentType": "text/plain"}}
    operation = client.iot_hub_resource.test_route if route_name else client.iot_hub_resource.test_all_routes
    body = {"message": message, "twin": None}
    body.update({"route": routes[0]} if route_name else {"routingSource": "DeviceMessages"})
    assert result is operation.return_value
    operation.assert_called_once_with(iot_hub_name="hub", resource_group_name="rg", input=body)


@pytest.mark.parametrize("action", ["create", "update", "delete", "list"])
def test_message_enrichment_crud(preview_mgmt, action):
    cmd, client, hub, _, _ = preview_mgmt
    routing = hub["properties"]["routing"]
    keep = {"key": "keep", "value": "original", "endpointNames": ["other"]}
    if action != "create":
        routing["enrichments"] = [keep, {"key": "site", "value": "old", "endpointNames": ["old"]}]
    if action in ("create", "update"):
        result = getattr(custom, f"iot_message_enrichment_{action}")(
            cmd, client, "hub", "site", "new", ["events"]
        )
        expected = [{"key": "site", "value": "new", "endpointNames": ["events"]}]
        if action == "update":
            expected.insert(0, keep)
    elif action == "delete":
        result = custom.iot_message_enrichment_delete(cmd, client, "hub", "site")
        expected = [keep]
    else:
        assert custom.iot_message_enrichment_list(cmd, client, "hub") == routing["enrichments"]
        client.iot_hub_resource.begin_create_or_update.assert_not_called()
        return
    assert routing["enrichments"] == expected
    assert_hub_write(client, hub, result)


@pytest.mark.parametrize("action", ["update", "delete"])
def test_message_enrichment_missing_fails_before_write(preview_mgmt, action):
    cmd, client, hub, _, _ = preview_mgmt
    hub["properties"]["routing"]["enrichments"] = []
    arguments = ("value", ["events"]) if action == "update" else ()
    with pytest.raises(CLIError, match="No message enrichment"):
        getattr(custom, f"iot_message_enrichment_{action}")(cmd, client, "hub", "missing", *arguments)
    client.iot_hub_resource.begin_create_or_update.assert_not_called()
