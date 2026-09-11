# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import inspect
import json
import logging
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core.credentials import AccessToken
from azure.core.exceptions import HttpResponseError
from azure.core.polling import LROPoller

from azext_iot.adr.providers.group import GroupProvider
from azext_iot.adr.providers.registry_device import RegistryDeviceProvider
from azext_iot.adr.providers.report import ReportProvider
from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient, operations


SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
API_VERSION = "2026-11-02-preview"
NAMESPACE_URL = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
    "/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/namespace"
)
GENERATE_URL = f"{NAMESPACE_URL}/generateReport"
LATEST_URL = f"{NAMESPACE_URL}/getLatestReport"
STATUS_URL = f"{NAMESPACE_URL}/operationStatuses/report"
RESULT_URL = f"{NAMESPACE_URL}/operationResults/report"
REPORT_SELECTORS = [
    {"reportType": "NamespaceUpdateComplianceReport"},
    {"reportType": "GroupBestUpdatesComplianceReport", "reportTarget": "group"},
    {"reportType": "GroupInstallableUpdatesReport", "reportTarget": "group"},
]


@pytest.fixture
def wire_client():
    credential = Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("unit-test-token", 4102444800)
    with DeviceRegistryMgmtClient(
        credential,
        SUBSCRIPTION,
        polling_interval=0,
        retry_total=0,
        logging_enable=True,
    ) as client:
        yield client


def _assert_api_version(request):
    assert parse_qs(urlsplit(request.url).query) == {"api-version": [API_VERSION]}


def _mock_report_generation(mocked_response, status_code):
    headers = {}
    if status_code == 202:
        headers = {
            "Azure-AsyncOperation": STATUS_URL,
            "Location": RESULT_URL,
            "Retry-After": "0",
        }
        mocked_response.add("GET", STATUS_URL, json={"status": "InProgress"})
        mocked_response.add("GET", STATUS_URL, json={"status": "Succeeded"})
        mocked_response.add("GET", RESULT_URL, status=204)
    mocked_response.add("POST", GENERATE_URL, status=status_code, headers=headers)


@pytest.mark.parametrize(
    "operation_group",
    [
        operations.NamespaceAssetsOperations,
        operations.NamespaceDevicesOperations,
        operations.NamespaceDiscoveredAssetsOperations,
        operations.NamespaceDiscoveredDevicesOperations,
    ],
)
def test_namespace_child_lists_use_namespace_operation_name(operation_group):
    assert hasattr(operation_group, "list_by_namespace")
    assert not hasattr(operation_group, "list_by_resource_group")


def test_adr_sdk_is_modeless_and_synchronous():
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.aio") is None
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.models") is None
    assert importlib.util.find_spec("azext_iot.sdk.deviceregistry.types") is None
    operation_groups = [
        group for name, group in inspect.getmembers(operations, inspect.isclass)
        if name.endswith("Operations")
    ]
    assert len(operation_groups) == 24
    methods = [
        method for group in operation_groups
        for name, method in inspect.getmembers(group, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert len(methods) == 109
    assert all(not inspect.iscoroutinefunction(method) for method in methods)


def test_adr_client_and_api_version_match_preview_contract():
    client = DeviceRegistryMgmtClient(
        credential=object(),
        subscription_id="00000000-0000-0000-0000-000000000000",
        base_url="https://centraluseuap.management.azure.com",
    )

    assert client._config.api_version == "2026-11-02-preview"
    assert hasattr(client, "namespaces")
    assert hasattr(client, "certificate_authorities")
    assert hasattr(client, "certificate_policies")


@pytest.mark.parametrize("status_code", [200, 204])
@pytest.mark.parametrize("no_wait", [False, True])
def test_group_delete_wire_is_synchronous(
    fixture_cmd, wire_client, mocked_response, mocker, status_code, no_wait
):
    mocked_response.add("DELETE", f"{NAMESPACE_URL}/groups/group", status=status_code)
    provider = GroupProvider(fixture_cmd, client=wire_client)
    wait = mocker.spy(provider, "_wait")

    assert provider.delete("group", "namespace", "rg", no_wait=no_wait) is None

    assert not hasattr(wire_client.groups, "begin_delete")
    wait.assert_not_called()
    assert len(mocked_response.calls) == 1
    request = mocked_response.calls[0].request
    assert request.method == "DELETE"
    assert urlsplit(request.url).path.endswith("/namespaces/namespace/groups/group")
    _assert_api_version(request)


def test_group_delete_wire_rejects_async_response(fixture_cmd, wire_client, mocked_response):
    mocked_response.add("DELETE", f"{NAMESPACE_URL}/groups/group", status=202)
    provider = GroupProvider(fixture_cmd, client=wire_client)

    with pytest.raises(HttpResponseError) as raised:
        provider.delete("group", "namespace", "rg", no_wait=True)

    assert raised.value.status_code == 202
    assert len(mocked_response.calls) == 1


def test_show_keys_wire_uses_list_keys_without_secret_logging(
    fixture_cmd, wire_client, mocked_response, mocker, caplog
):
    profile_url = f"{NAMESPACE_URL}/registryDevices/device/authenticationProfiles/default"
    keys = {"symmetricKey": {"primaryKey": "test-primary-secret", "secondaryKey": "test-secondary-secret"}}
    mocked_response.add(
        "GET", profile_url, json={"properties": {"authenticationType": "SymmetricKey"}}
    )
    mocked_response.add("POST", f"{profile_url}/listKeys", json=keys)
    list_keys = mocker.spy(wire_client.registry_device_authentication_profiles, "list_keys")
    mocker.patch("azext_iot.adr.providers.base.adr_service_factory", return_value=wire_client)
    provider = RegistryDeviceProvider(fixture_cmd)

    with caplog.at_level(logging.DEBUG):
        assert provider.auth_show_keys("default", "device", "namespace", "rg") == keys

    list_keys.assert_called_once_with(
        resource_group_name="rg",
        namespace_name="namespace",
        registry_device_name="device",
        authentication_profile_name="default",
        logging_enable=False,
    )
    assert not hasattr(wire_client.registry_device_authentication_profiles, "get_keys")
    assert [call.request.method for call in mocked_response.calls] == ["GET", "POST"]
    for call in mocked_response.calls:
        _assert_api_version(call.request)
    assert urlsplit(mocked_response.calls[1].request.url).path.endswith("/default/listKeys")
    assert "The returned symmetric keys are secrets" in caplog.text
    assert "test-primary-secret" not in caplog.text
    assert "test-secondary-secret" not in caplog.text
    assert any(record.name.startswith("azure.") for record in caplog.records)


@pytest.mark.parametrize("status_code", [202, 204])
def test_generate_report_wire_returns_none_after_arm_polling(wire_client, mocked_response, status_code):
    _mock_report_generation(mocked_response, status_code)

    poller = wire_client.namespaces.begin_generate_report("rg", "namespace", REPORT_SELECTORS[0])

    assert isinstance(poller, LROPoller)
    assert poller.result() is None
    calls = mocked_response.calls
    assert [call.request.method for call in calls] == (
        ["POST", "GET", "GET", "GET"] if status_code == 202 else ["POST"]
    )
    _assert_api_version(calls[0].request)
    assert json.loads(calls[0].request.body) == REPORT_SELECTORS[0]
    if status_code == 202:
        assert [call.request.url for call in calls[1:]] == [STATUS_URL, STATUS_URL, RESULT_URL]


def test_generate_report_wire_rejects_old_200_response(wire_client, mocked_response):
    mocked_response.add("POST", GENERATE_URL, status=200)

    with pytest.raises(HttpResponseError) as raised:
        wire_client.namespaces.begin_generate_report("rg", "namespace", REPORT_SELECTORS[0])

    assert raised.value.status_code == 200
    assert len(mocked_response.calls) == 1


@pytest.mark.parametrize("selector", REPORT_SELECTORS)
@pytest.mark.parametrize("status_code", [202, 204])
@pytest.mark.parametrize("no_wait", [False, True])
@pytest.mark.parametrize("use_workaround", [False, True])
def test_generate_report_wire_output_and_no_wait(
    fixture_cmd, wire_client, mocked_response, mocker,
    selector, status_code, no_wait, use_workaround,
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", use_workaround)
    _mock_report_generation(mocked_response, status_code)
    report = {**selector, "generatedAt": "2026-09-10T04:00:00Z", "reportData": {"deviceCount": 3}}
    if not no_wait:
        mocked_response.add("POST", LATEST_URL, json=report)
    provider = ReportProvider(fixture_cmd, client=wire_client)
    begin = mocker.spy(wire_client.namespaces, "begin_generate_report")
    wait = mocker.spy(provider, "_wait")

    result = provider.generate(
        "namespace", "rg", selector["reportType"],
        group_name=selector.get("reportTarget"), no_wait=no_wait, wait_sec=0,
    )

    if no_wait:
        assert result is begin.spy_return
        assert isinstance(result, LROPoller)
        wait.assert_not_called()
    else:
        assert result == report
        wait.assert_called_once()
    # Join the real SDK poller before the mocked transport is torn down.
    assert begin.spy_return.result() is None
    action_calls = [call for call in mocked_response.calls if call.request.method == "POST"]
    assert [urlsplit(call.request.url).path for call in action_calls] == [
        urlsplit(url).path for url in ([GENERATE_URL] if no_wait else [GENERATE_URL, LATEST_URL])
    ]
    for call in action_calls:
        assert json.loads(call.request.body) == selector
        assert call.request.headers["Content-Type"] == "application/json"
        _assert_api_version(call.request)
    if status_code == 202 and not no_wait:
        latest_index = list(mocked_response.calls).index(action_calls[1])
        assert any(
            call.request.url == RESULT_URL for call in list(mocked_response.calls)[:latest_index]
        )


def test_generate_report_wire_failure_does_not_retrieve_latest(
    fixture_cmd, wire_client, mocked_response, mocker
):
    mocker.patch("azext_iot.adr.providers.base.POLL_PROVISIONING_STATE_WORKAROUND", False)
    mocked_response.add(
        "POST", GENERATE_URL, status=202, headers={"Azure-AsyncOperation": STATUS_URL}
    )
    mocked_response.add(
        "GET", STATUS_URL,
        json={"status": "Failed", "error": {"code": "ReportFailed", "message": "Report generation failed"}},
    )
    provider = ReportProvider(fixture_cmd, client=wire_client)

    with pytest.raises(HttpResponseError, match="Report generation failed"):
        provider.generate("namespace", "rg", REPORT_SELECTORS[0]["reportType"])

    assert [call.request.method for call in mocked_response.calls] == ["POST", "GET"]
