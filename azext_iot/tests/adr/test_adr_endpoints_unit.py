# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from knack.util import CLIError

from azext_iot import _factory
from azext_iot.adr.endpoints import CANARY_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT, get_adr_arm_endpoint
from azext_iot.tests.adr import conftest as integration


FACTORIES = [
    ("adr_service_factory", "namespaces", "Microsoft.DeviceRegistry/namespaces",
     {"namespace_name": "target"}, "2026-11-02-preview"),
    ("adr_update_instance_service_factory", "update_instances", "Microsoft.DeviceUpdate/updateInstances",
     {"update_instance_name": "target"}, "2026-11-02-preview"),
    ("adr_iot_hub_service_factory", "iot_hub_resource", "Microsoft.Devices/IotHubs",
     {"resource_name": "target"}, "2026-10-01-preview"),
    ("adr_iot_service_provisioning_factory", "iot_dps_resource", "Microsoft.Devices/provisioningServices",
     {"provisioning_service_name": "target"}, "2026-06-01-preview"),
]


@pytest.fixture
def cli_ctx(mocker):
    context = mocker.Mock()
    context.cloud.endpoints.active_directory = "https://login.microsoftonline.com"
    context.cloud.endpoints.active_directory_resource_id = "https://management.azure.com"
    credential = mocker.Mock()
    credential.get_token.return_value = AccessToken("test-token", 4102444800)
    mocker.patch.object(_factory, "get_cli_credential", return_value=credential)
    return context


@pytest.mark.parametrize("value,expected", [
    (None, CANARY_ARM_ENDPOINT),
    (CANARY_ARM_ENDPOINT, CANARY_ARM_ENDPOINT),
    (PUBLIC_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT),
    ("HTTPS://MANAGEMENT.AZURE.COM/", PUBLIC_ARM_ENDPOINT),
])
def test_endpoint_selection_is_explicit_and_independent_of_location(monkeypatch, value, expected):
    monkeypatch.delenv("AZURE_IOT_ADR_ARM_ENDPOINT", raising=False)
    monkeypatch.setenv("azext_iot_adr_location", "australiaeast")
    if value is not None:
        monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", value)
    assert get_adr_arm_endpoint() == expected
    assert _factory._ADR_CANARY_ARM_ENDPOINT == CANARY_ARM_ENDPOINT


@pytest.mark.parametrize("value", [
    "", "http://management.azure.com", "https://australiaeast.management.azure.com",
    "https://management.usgovcloudapi.net", "https://management.azure.com.invalid",
    "https://user@management.azure.com", "https://management.azure.com/path",
    "https://management.azure.com?query=1", "https://management.azure.com#fragment",
])
@pytest.mark.parametrize("factory_name", [row[0] for row in FACTORIES])
def test_invalid_endpoint_fails_before_credentials(monkeypatch, mocker, cli_ctx, value, factory_name):
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", value)
    credential = mocker.spy(_factory, "get_cli_credential")
    with pytest.raises(InvalidArgumentValueError, match="AZURE_IOT_ADR_ARM_ENDPOINT must be"):
        getattr(_factory, factory_name)(cli_ctx, subscription_id="sub")
    credential.assert_not_called()


@pytest.mark.parametrize("factory_name", [row[0] for row in FACTORIES])
def test_public_endpoint_preserves_cloud_authority_guard(monkeypatch, mocker, cli_ctx, factory_name):
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", PUBLIC_ARM_ENDPOINT)
    cli_ctx.cloud.endpoints.active_directory = "https://login.microsoftonline.us"
    credential = mocker.spy(_factory, "get_cli_credential")
    with pytest.raises(CLIError, match="Azure public cloud only"):
        getattr(_factory, factory_name)(cli_ctx, subscription_id="sub")
    credential.assert_not_called()


@pytest.mark.parametrize("factory_name,operations,resource_type,names,api", FACTORIES)
@pytest.mark.parametrize("endpoint", [CANARY_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT])
@pytest.mark.parametrize("status", [200, 400, 404])
def test_management_requests_keep_endpoint_and_api_without_fallback(
    monkeypatch, mocked_response, cli_ctx, factory_name, operations, resource_type, names, api, endpoint, status,
):
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", endpoint)
    url = f"{endpoint}/subscriptions/sub/resourceGroups/rg/providers/{resource_type}/target"
    body = {"name": "target", "location": "australiaeast"}
    mocked_response.add(
        method="GET", url=url, status=status,
        json=body if status == 200 else {"error": {"code": "InvalidApiVersionParameter", "message": "Unsupported API"}},
    )
    with getattr(_factory, factory_name)(cli_ctx, subscription_id="sub") as client:
        if status == 200:
            assert getattr(client, operations).get(resource_group_name="rg", **names) == body
        else:
            with pytest.raises(HttpResponseError):
                getattr(client, operations).get(resource_group_name="rg", **names)
    assert len(mocked_response.calls) == 1
    request = mocked_response.calls[0].request
    assert request.url.split("?")[0] == url
    assert parse_qs(urlsplit(request.url).query)["api-version"] == [api]


def test_public_namespace_write_keeps_australiaeast_in_body(monkeypatch, mocked_response, cli_ctx):
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", PUBLIC_ARM_ENDPOINT)
    url = f"{PUBLIC_ARM_ENDPOINT}/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/target"
    mocked_response.add(method="PUT", url=url, status=200, json={"location": "australiaeast"})
    with _factory.adr_service_factory(cli_ctx, subscription_id="sub") as client:
        client.namespaces.begin_create_or_replace(
            resource_group_name="rg", namespace_name="target", resource={"location": "australiaeast"}, polling=False,
        )
    assert len(mocked_response.calls) == 1
    assert json.loads(mocked_response.calls[0].request.body)["location"] == "australiaeast"


@pytest.mark.parametrize("test_endpoint,client_endpoint", [
    (PUBLIC_ARM_ENDPOINT, CANARY_ARM_ENDPOINT),
    (CANARY_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT),
    ("https://australiaeast.management.azure.com", PUBLIC_ARM_ENDPOINT),
])
def test_preflight_rejects_split_routing_before_azure_calls(monkeypatch, mocker, test_endpoint, client_endpoint):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", client_endpoint)
    monkeypatch.setattr(integration, "TEST_ARM_ENDPOINT", test_endpoint)
    run = mocker.patch.object(integration, "_run_preflight_command")
    with pytest.raises(pytest.UsageError, match="must match AZURE_IOT_ADR_ARM_ENDPOINT"):
        integration.run_adr_integration_preflight(mocker.Mock())
    run.assert_not_called()


def test_public_preflight_surfaces_unsupported_api_without_canary_retry(monkeypatch, mocker):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    monkeypatch.setenv("AZURE_IOT_ADR_ARM_ENDPOINT", PUBLIC_ARM_ENDPOINT)
    monkeypatch.setattr(integration, "TEST_ARM_ENDPOINT", PUBLIC_ARM_ENDPOINT)
    monkeypatch.setattr(integration, "TEST_LOCATION", "australiaeast")
    run = mocker.patch.object(integration.subprocess, "run", side_effect=[
        mocker.Mock(returncode=0, stdout=value)
        for value in ("", integration.TEST_SUBSCRIPTION, "", "", "Registered", "Registered")
    ] + [mocker.Mock(returncode=1, stderr="InvalidApiVersionParameter", stdout="")])
    with pytest.raises(pytest.UsageError, match="InvalidApiVersionParameter"):
        integration.run_adr_integration_preflight(mocker.Mock())
    assert run.call_count == 7
    command = run.call_args.args[0]
    assert command[command.index("--url") + 1] == (
        f"{PUBLIC_ARM_ENDPOINT}/subscriptions/{integration.TEST_SUBSCRIPTION}"
        f"/resourceGroups/{integration.TEST_RG}/providers/Microsoft.DeviceRegistry/namespaces"
        "?api-version=2026-11-02-preview"
    )
    assert command[command.index("--resource") + 1] == "https://management.azure.com"
