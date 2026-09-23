# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Partial state export through the real EmbeddedCLI error-preservation path."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import ResourceNotFoundError
from knack.util import CLIError

from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.iothub.providers import state
from azext_iot.tests._hub_ownership import OwnershipError


ENDPOINT_TYPES = {
    "eventHubs": "Event Hub",
    "serviceBusQueues": "Service Bus Queue",
    "serviceBusTopics": "Service Bus Topic",
    "cosmosDBSqlContainers": "Cosmos DB Sql Collection",
    "storageContainers": "Storage Container",
}
KEY_FIELDS = {
    "eventHubs": {
        "connectionString": (
            "Endpoint=sb://endpoint.servicebus.windows.net/;EntityPath=events;"
            "SharedAccessKeyName=policy;SharedAccessKey=offline-secret"
        ),
    },
    "serviceBusQueues": {
        "connectionString": (
            "Endpoint=sb://endpoint.servicebus.windows.net/;EntityPath=queue;"
            "SharedAccessKeyName=policy;SharedAccessKey=offline-secret"
        ),
    },
    "serviceBusTopics": {
        "connectionString": (
            "Endpoint=sb://endpoint.servicebus.windows.net/;EntityPath=topic;"
            "SharedAccessKeyName=policy;SharedAccessKey=offline-secret"
        ),
    },
    "cosmosDBSqlContainers": {"primaryKey": "offline-secret", "secondaryKey": "offline-secondary"},
    "storageContainers": {
        "connectionString": (
            "DefaultEndpointsProtocol=https;AccountName=endpoint;AccountKey=offline-secret;"
            "EndpointSuffix=core.windows.net"
        ),
    },
}
KEY_RESULTS = {
    "primaryConnectionString": "refreshed-connection",
    "connectionString": "refreshed-storage-connection",
    "connectionStrings": [
        {"description": "Primary SQL Connection String",
         "connectionString": "AccountEndpoint=https://endpoint.documents.azure.com/;AccountKey=refreshed-primary;"},
        {"description": "Secondary SQL Connection String",
         "connectionString": "AccountEndpoint=https://endpoint.documents.azure.com/;AccountKey=refreshed-secondary;"},
    ],
}


def _endpoint(kind, key_auth):
    endpoint = {
        "name": "endpoint",
        "subscriptionId": "endpoint-subscription",
        "resourceGroup": "endpoint-rg",
        "endpointUri": "https://endpoint.example.invalid/",
        "entityPath": "events",
        "databaseName": "database",
        "collectionName": "container",
        "authenticationType": "keyBased" if key_auth else "identityBased",
    }
    if key_auth:
        endpoint.update(KEY_FIELDS[kind])
    return endpoint


def _hub(kind, endpoint):
    endpoints = {name: [] for name in ENDPOINT_TYPES}
    endpoints[kind] = [endpoint]
    return {
        "identity": {},
        "properties": {
            "routing": {
                "endpoints": endpoints,
                "routes": [
                    {"name": "endpoint-route", "endpointNames": ["endpoint"]},
                    {"name": "builtin-route", "endpointNames": ["events"]},
                ],
            },
            "storageEndpoints": {},
        },
    }


@pytest.fixture
def embedded(mocker):
    client = Mock(result=None)
    mocker.patch("azext_iot.common.embedded_cli.get_default_cli", return_value=client)
    wrapper = EmbeddedCLI()
    mocker.patch.object(state, "cli", wrapper)
    mocker.patch("socket.socket.connect", side_effect=AssertionError("No live socket allowed"))
    outcome = SimpleNamespace(error=None, output=KEY_RESULTS, exit_code=0)

    def invoke(_args, out_file):
        client.result = SimpleNamespace(error=outcome.error)
        out_file.write(json.dumps(outcome.output))
        return outcome.exit_code

    client.invoke.side_effect = invoke
    return client, wrapper, outcome


@pytest.mark.parametrize("kind", ENDPOINT_TYPES)
@pytest.mark.parametrize("key_auth", [False, True])
@pytest.mark.parametrize("missing", ["subscriptionId", "resourceGroup", "both"])
@pytest.mark.parametrize("value", ["absent", None, ""])
def test_missing_endpoint_scope_skips_lookup_and_route(embedded, caplog, kind, key_auth, missing, value):
    client, _, outcome = embedded
    outcome.error = OwnershipError("Foreign subscription override")
    outcome.exit_code = 1
    endpoint = _endpoint(kind, key_auth)
    for field in ("subscriptionId", "resourceGroup") if missing == "both" else (missing,):
        endpoint.pop(field)
        if value != "absent":
            endpoint[field] = value
    hub = _hub(kind, endpoint)

    # Identity-based Storage show uses its globally unique account name within the explicit subscription.
    if kind == "storageContainers" and not key_auth and missing == "resourceGroup":
        outcome.error = None
        outcome.exit_code = 0
        state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
        client.invoke.assert_called_once_with(
            ["storage", "account", "show", "--name", "endpoint", "--subscription", "endpoint-subscription", "-o", "json"],
            out_file=client.invoke.call_args.kwargs["out_file"],
        )
        assert hub["properties"]["routing"]["endpoints"][kind] == [endpoint]
        assert len(hub["properties"]["routing"]["routes"]) == 2
        assert not caplog.records
    else:
        state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
        client.invoke.assert_not_called()
        assert hub["properties"]["routing"]["endpoints"][kind] == []
        assert hub["properties"]["routing"]["routes"] == [{"name": "builtin-route", "endpointNames": ["events"]}]
        message = (
            state.usr_msgs.SAVE_ENDPOINT_RETRIEVE_FAIL_MSG if key_auth else state.usr_msgs.SAVE_ENDPOINT_INFO_RETRIEVE_FAIL_MSG
        )
        assert message.format(ENDPOINT_TYPES[kind], "endpoint") in caplog.messages
        assert state.usr_msgs.SAVE_ROUTE_FAIL_MSG.format("endpoint-route", "endpoint") in caplog.messages
    assert "offline-secret" not in caplog.text
    assert "offline-secondary" not in caplog.text
    assert "endpoint.example.invalid" not in caplog.text


@pytest.mark.parametrize("kind", ENDPOINT_TYPES)
@pytest.mark.parametrize("key_auth", [False, True])
def test_valid_scope_retains_endpoint_and_existing_lookup(embedded, caplog, kind, key_auth):
    client, _, _ = embedded
    endpoint = _endpoint(kind, key_auth)
    hub = _hub(kind, endpoint)
    state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    client.invoke.assert_called_once()
    args = client.invoke.call_args.args[0]
    assert args[args.index("--subscription") + 1] == "endpoint-subscription"
    if kind != "storageContainers" or key_auth:
        flag = "-g" if kind == "storageContainers" else "--resource-group"
        assert args[args.index(flag) + 1] == "endpoint-rg"
    if key_auth:
        expected = {
            "cosmosDBSqlContainers": {"primaryKey": "refreshed-primary", "secondaryKey": "refreshed-secondary"},
            "storageContainers": {"connectionString": "refreshed-storage-connection"},
        }.get(kind, {"connectionString": "refreshed-connection"})
        assert all(endpoint[key] == value for key, value in expected.items())
    assert hub["properties"]["routing"]["endpoints"][kind] == [endpoint]
    assert len(hub["properties"]["routing"]["routes"]) == 2
    assert not caplog.records


@pytest.mark.parametrize("kind", ENDPOINT_TYPES)
@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("error_type", [OwnershipError, CLIError, RuntimeError])
def test_valid_key_scope_preserves_original_non_azcli_failure(embedded, kind, capture, error_type):
    client, wrapper, outcome = embedded
    wrapper.capture_stderr = capture
    error = error_type("original lookup failure")
    outcome.error, outcome.exit_code = error, 1
    hub = _hub(kind, _endpoint(kind, True))
    original = deepcopy(hub)
    with pytest.raises(error_type) as raised:
        state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    assert raised.value is error
    assert hub == original
    client.invoke.assert_called_once()


@pytest.mark.parametrize("kind", ENDPOINT_TYPES)
@pytest.mark.parametrize("capture", [False, True])
def test_valid_key_scope_retains_azcli_partial_export_contract(embedded, caplog, kind, capture):
    client, wrapper, outcome = embedded
    wrapper.capture_stderr = capture
    outcome.error, outcome.exit_code = ResourceNotFoundError("missing resource"), 3
    hub = _hub(kind, _endpoint(kind, True))
    state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    client.invoke.assert_called_once()
    assert hub["properties"]["routing"]["endpoints"][kind] == []
    assert len(hub["properties"]["routing"]["routes"]) == 1
    assert state.usr_msgs.SAVE_ENDPOINT_RETRIEVE_FAIL_MSG.format(ENDPOINT_TYPES[kind], "endpoint") in caplog.messages


def test_secondary_only_cosmos_key_is_not_treated_as_identity(embedded, caplog):
    client, _, _ = embedded
    endpoint = _endpoint("cosmosDBSqlContainers", True)
    endpoint.pop("primaryKey")
    endpoint.pop("subscriptionId")
    hub = _hub("cosmosDBSqlContainers", endpoint)
    state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    client.invoke.assert_not_called()
    assert not hub["properties"]["routing"]["endpoints"]["cosmosDBSqlContainers"]
    assert state.usr_msgs.SAVE_ENDPOINT_RETRIEVE_FAIL_MSG.format("Cosmos DB Sql Collection", "endpoint") in caplog.messages


def test_partial_export_retains_valid_siblings_and_file_upload(embedded):
    client, _, _ = embedded
    invalid = {"name": "endpoint", **KEY_FIELDS["eventHubs"]}
    hub = _hub("eventHubs", invalid)
    valid = _endpoint("eventHubs", True)
    valid["name"] = "valid-endpoint"
    endpoints = hub["properties"]["routing"]["endpoints"]
    endpoints["eventHubs"].append(valid)
    endpoints["fabricEventStreams"] = [{"name": "fabric", "connectionString": "opaque-credentials"}]
    hub["properties"]["storageEndpoints"]["$default"] = dict(KEY_FIELDS["storageContainers"])
    state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    assert endpoints["eventHubs"] == [valid]
    assert valid["connectionString"] == "refreshed-connection"
    assert endpoints["fabricEventStreams"] == [{"name": "fabric", "connectionString": "opaque-credentials"}]
    assert hub["properties"]["storageEndpoints"]["$default"]["connectionString"] == "refreshed-storage-connection"
    assert client.invoke.call_count == 2
    assert client.invoke.call_args_list[-1].args[0] == [
        "storage", "account", "show-connection-string", "-n", "endpoint", "-o", "json",
    ]


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("error_type", [OwnershipError, CLIError, RuntimeError])
def test_file_upload_preserves_original_non_azcli_failure(embedded, capture, error_type):
    client, wrapper, outcome = embedded
    wrapper.capture_stderr = capture
    error = error_type("original file upload lookup failure")
    outcome.error, outcome.exit_code = error, 1
    hub = _hub("eventHubs", {"name": "endpoint", **KEY_FIELDS["eventHubs"]})
    hub["properties"]["storageEndpoints"]["$default"] = dict(KEY_FIELDS["storageContainers"])
    with pytest.raises(error_type) as raised:
        state.StateProvider.__new__(state.StateProvider).check_controlplane(hub)
    assert raised.value is error
    assert hub["properties"]["storageEndpoints"]["$default"] == KEY_FIELDS["storageContainers"]
    client.invoke.assert_called_once()
