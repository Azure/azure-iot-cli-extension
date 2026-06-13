# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from unittest.mock import Mock

import pytest


def test_device_show(fixture_device_provider):
    mock_device = Mock()
    fixture_device_provider.client.namespace_devices.get.return_value = mock_device

    result = fixture_device_provider.show(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.get.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
    )


def test_device_list(fixture_device_provider):
    mock_devices = [Mock(), Mock()]
    fixture_device_provider.client.namespace_devices.list_by_resource_group.return_value = mock_devices

    result = fixture_device_provider.list(
        namespace_name="test-namespace",
        resource_group_name="test-rg",
    )

    assert len(result) == 2
    fixture_device_provider.client.namespace_devices.list_by_resource_group.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
    )


@pytest.mark.parametrize("enabled", [None, True, False])
def test_device_update_enabled(fixture_device_provider, mock_poller, enabled):
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        enabled=enabled,
    )

    assert result == mock_device
    if enabled is not None:
        expected_props = {"properties": {"enabled": enabled}}
    else:
        expected_props = {}
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties=expected_props,
    )


def test_device_update_all_fields(fixture_device_provider, mock_poller):
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        enabled=False,
        tags={"env": "test"},
        operating_system_version="2.0.1",
        attributes={"key": "value"},
        policy_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/"
            "namespaces/ns/credentials/default/policies/p1"
        ),
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={
            "properties": {
                "enabled": False,
                "operatingSystemVersion": "2.0.1",
                "attributes": {"key": "value"},
                "policy": {
                    "resourceId": (
                        "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.DeviceRegistry/"
                        "namespaces/ns/credentials/default/policies/p1"
                    )
                },
            },
            "tags": {"env": "test"},
        },
    )


@pytest.mark.parametrize(
    "disable, expected_body",
    [
        (False, {}),
        (True, {"disable": True}),
    ],
)
def test_device_revoke(fixture_device_provider, mock_poller, disable, expected_body):
    mock_revoke_result = Mock()
    mock_revoke_result.result = "Succeeded"
    poller = mock_poller(mock_revoke_result)
    fixture_device_provider.client.namespace_devices.begin_revoke.return_value = poller

    result = fixture_device_provider.revoke(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        disable=disable,
    )

    assert result == mock_revoke_result
    fixture_device_provider.client.namespace_devices.begin_revoke.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        body=expected_body,
    )


def test_device_revoke_response_with_error(fixture_device_provider, mock_poller):
    mock_revoke_result = Mock()
    mock_revoke_result.result = "Failed"
    mock_revoke_result.error = Mock()
    mock_revoke_result.error.message = "Device not found"
    poller = mock_poller(mock_revoke_result)
    fixture_device_provider.client.namespace_devices.begin_revoke.return_value = poller

    result = fixture_device_provider.revoke(
        device_name="nonexistent-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
    )

    assert result == mock_revoke_result
    assert result.result == "Failed"
    assert result.error.message == "Device not found"


# --- Update: clearing / emptying property tests ---


def test_device_update_clear_tags(fixture_device_provider, mock_poller):
    """--tags '' sends an empty dict to clear all tags."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        tags={},
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"tags": {}},
    )


def test_device_update_clear_attributes_empty_dict(fixture_device_provider, mock_poller):
    """--attributes '{}' sends an empty dict to clear all attributes."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        attributes={},
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"attributes": {}}},
    )


def test_device_update_attributes_json_string(fixture_device_provider, mock_poller):
    """attributes arriving as a JSON string are parsed into a dict."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        attributes='{"key": "value", "num": 42}',
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"attributes": {"key": "value", "num": 42}}},
    )


def test_device_update_clear_attributes_json_string(fixture_device_provider, mock_poller):
    """attributes arriving as '{}' JSON string are parsed into an empty dict."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        attributes="{}",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"attributes": {}}},
    )


def test_device_update_clear_attributes_empty_string(fixture_device_provider, mock_poller):
    """--attributes '' (empty string) clears attributes by sending None."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        attributes="",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"attributes": None}},
    )


def test_device_update_clear_os_version(fixture_device_provider, mock_poller):
    """--os-version '' sends an empty string to clear the OS version."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        operating_system_version="",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"operatingSystemVersion": ""}},
    )


def test_device_update_clear_policy(fixture_device_provider, mock_poller):
    """--policy-resource-id '' sends policy=None to dissociate the policy."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        policy_resource_id="",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={"properties": {"policy": None}},
    )


def test_device_update_noop(fixture_device_provider, mock_poller):
    """Calling update with all defaults sends an empty properties dict (no-op)."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={},
    )


def test_device_update_clear_all_clearable(fixture_device_provider, mock_poller):
    """Clear all clearable properties in a single update call."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        tags={},
        operating_system_version="",
        attributes={},
        policy_resource_id="",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={
            "properties": {
                "operatingSystemVersion": "",
                "attributes": {},
                "policy": None,
            },
            "tags": {},
        },
    )


def test_device_update_set_and_clear_mixed(fixture_device_provider, mock_poller):
    """Set some properties while clearing others in the same call."""
    mock_device = Mock()
    poller = mock_poller(mock_device)
    fixture_device_provider.client.namespace_devices.begin_update.return_value = poller

    result = fixture_device_provider.update(
        device_name="test-device",
        namespace_name="test-namespace",
        resource_group_name="test-rg",
        enabled=True,
        tags={"env": "prod"},
        operating_system_version="",
        attributes={},
        policy_resource_id="",
    )

    assert result == mock_device
    fixture_device_provider.client.namespace_devices.begin_update.assert_called_once_with(
        resource_group_name="test-rg",
        namespace_name="test-namespace",
        device_name="test-device",
        properties={
            "properties": {
                "enabled": True,
                "operatingSystemVersion": "",
                "attributes": {},
                "policy": None,
            },
            "tags": {"env": "prod"},
        },
    )
