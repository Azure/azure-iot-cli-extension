# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import time
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.polling import LROPoller
from responses import matchers

from azext_iot.adr.providers.namespace import NamespaceProvider
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient

ARM = "https://management.example"
SUB = "00000000-0000-0000-0000-000000000001"
RG = "test-rg"
NS = "test-ns"
URL = f"{ARM}/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.DeviceRegistry/namespaces/{NS}"
ASSET = f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.DeviceRegistry/assets/asset"
NAMESPACE = {
    "id": URL[len(ARM):], "name": NS, "location": "centraluseuap",
    "identity": {"type": "SystemAssigned", "principalId": "principal", "tenantId": "tenant"},
    "properties": {"provisioningState": "Succeeded"},
}


@pytest.fixture
def sdk_provider(fixture_cmd, mocker):
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("offline-token", int(time.time()) + 3600)
    with DeviceRegistryMgmtClient(
        credential, SUB, base_url=ARM, credential_scopes=[ARM + "/.default"], polling_interval=0,
    ) as client:
        mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=client)
        yield NamespaceProvider(fixture_cmd)


@pytest.mark.parametrize(
    "operation,method,body,status",
    [
        ("create", "PUT", {
            "location": "centraluseuap", "identity": {"type": "SystemAssigned"},
            "tags": {"env": "test"}, "properties": {"messaging": {"endpoints": {"events": {"address": "host"}}}},
        }, 200),
        ("update", "PATCH", {
            "tags": {}, "identity": {"type": "None"}, "properties": {"messaging": {"endpoints": {}}},
        }, 200),
        ("delete", "DELETE", None, 204),
        ("migrate", "POST", {"scope": "Resources", "resourceIds": [ASSET]}, 200),
        ("identity_assign", "PATCH", {"identity": {"type": "SystemAssigned"}}, 200),
        ("identity_remove", "PATCH", {"identity": {"type": "None"}}, 200),
    ],
)
@pytest.mark.parametrize("no_wait", [False, True])
def test_provider_mutations_use_stable_wire_contract(sdk_provider, mocked_response, operation, method, body, status, no_wait):
    url = URL + ("/migrate" if operation == "migrate" else "")
    response_body = None if operation in {"migrate", "delete"} else NAMESPACE
    mocked_response.add(
        method=method, url=url, json=response_body, status=status,
        match=[matchers.json_params_matcher(body)] if body is not None else [],
    )
    kwargs = {"no_wait": no_wait, "wait_sec": 0}
    if operation == "create":
        kwargs.update(location="centraluseuap", tags={"env": "test"}, messaging_endpoints='{"events":{"address":"host"}}')
    elif operation == "update":
        kwargs.update(tags={}, system_assigned=False, messaging_endpoints="{}")
    elif operation == "migrate":
        kwargs["resource_ids"] = [ASSET]
    result = getattr(sdk_provider, operation)(NS, RG, **kwargs)
    if no_wait:
        assert isinstance(result, LROPoller)
        result = result.result()
        assert result == response_body
    elif operation.startswith("identity_"):
        assert result == NAMESPACE["identity"]
    elif operation == "create":
        assert result == {**NAMESPACE, "resourceGroup": RG}
    else:
        assert result == response_body
    request = mocked_response.calls[0].request
    assert parse_qs(urlsplit(request.url).query) == {"api-version": ["2026-04-01"]}
    assert request.headers["Authorization"] == "Bearer offline-token"
    if body is not None:
        assert json.loads(request.body) == body
    assert len(mocked_response.calls) == 1


@pytest.mark.parametrize("identity_only", [False, True])
def test_namespace_sdk_returns_modeless_json(sdk_provider, mocked_response, identity_only):
    mocked_response.add(method="GET", url=URL, json=NAMESPACE, status=200)
    result = sdk_provider.identity_show(NS, RG) if identity_only else sdk_provider.show(NS, RG)
    assert isinstance(result, dict)
    assert result == (NAMESPACE["identity"] if identity_only else NAMESPACE)


@pytest.mark.parametrize("resource_group", [None, RG])
def test_namespace_sdk_paginates(sdk_provider, mocked_response, resource_group):
    scope = f"/resourceGroups/{RG}" if resource_group else ""
    url = f"{ARM}/subscriptions/{SUB}{scope}/providers/Microsoft.DeviceRegistry/namespaces"
    next_link = url + "?api-version=2026-04-01&skipToken=next"
    mocked_response.add(
        method="GET", url=url, json={"value": [NAMESPACE], "nextLink": next_link}, status=200,
        match=[matchers.query_param_matcher({"api-version": "2026-04-01"})],
    )
    second = {**NAMESPACE, "name": "second"}
    mocked_response.add(
        method="GET", url=next_link, json={"value": [second]}, status=200,
        match=[matchers.query_param_matcher({"api-version": "2026-04-01", "skipToken": "next"})],
    )
    assert sdk_provider.list(resource_group) == [NAMESPACE, second]
    assert len(mocked_response.calls) == 2


@pytest.mark.parametrize("succeeds", [False, True])
def test_namespace_sdk_polls_standard_arm_operation(sdk_provider, mocked_response, succeeds):
    status_url = f"{ARM}/subscriptions/{SUB}/providers/Microsoft.DeviceRegistry/operationStatuses/test"
    mocked_response.add(
        method="PATCH", url=URL, json={**NAMESPACE, "properties": {"provisioningState": "Updating"}}, status=202,
        headers={"Azure-AsyncOperation": status_url},
    )
    status = {"status": "Succeeded"} if succeeds else {
        "status": "Failed", "error": {"code": "Denied", "message": "operation denied"},
    }
    mocked_response.add(method="GET", url=status_url, json=status, status=200)
    if succeeds:
        mocked_response.add(method="GET", url=URL, json=NAMESPACE, status=200)
        assert sdk_provider.update(NS, RG, tags={"env": "test"}, wait_sec=0) == NAMESPACE
    else:
        with pytest.raises(HttpResponseError, match="operation denied"):
            sdk_provider.update(NS, RG, tags={"env": "test"}, wait_sec=0)
    assert [call.request.method for call in mocked_response.calls] == (["PATCH", "GET", "GET"] if succeeds else ["PATCH", "GET"])


def test_namespace_sdk_404_is_not_swallowed(sdk_provider, mocked_response):
    mocked_response.add(
        method="GET", url=URL, json={"error": {"code": "ResourceNotFound", "message": "Namespace missing"}}, status=404,
    )
    with pytest.raises(HttpResponseError, match="Namespace missing"):
        sdk_provider.show(NS, RG)
