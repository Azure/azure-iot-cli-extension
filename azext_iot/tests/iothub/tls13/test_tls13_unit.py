# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.common.shared import HostnameType


class TestResolveHostnameByType:
    """Tests for _resolve_hostname_by_type in hub.py"""

    def _make_target(self, device_hostname=None, service_hostname=None):
        return {
            "entity": "testhub.service.azure-devices.net",
            "name": "testhub",
            "deviceHostName": device_hostname,
            "serviceHostName": service_hostname,
        }

    def test_classic_returns_classic_hostname(self):
        from azext_iot.operations.hub import _resolve_hostname_by_type
        target = self._make_target()
        assert _resolve_hostname_by_type(target, HostnameType.CLASSIC.value) == "testhub.azure-devices.net"

    def test_device_returns_device_hostname(self):
        from azext_iot.operations.hub import _resolve_hostname_by_type
        target = self._make_target(device_hostname="testhub.device.azure-devices.net")
        assert _resolve_hostname_by_type(target, HostnameType.DEVICE.value) == "testhub.device.azure-devices.net"

    def test_service_returns_service_hostname(self):
        from azext_iot.operations.hub import _resolve_hostname_by_type
        target = self._make_target(service_hostname="testhub.service.azure-devices.net")
        result = _resolve_hostname_by_type(target, HostnameType.SERVICE.value)
        assert result == "testhub.service.azure-devices.net"

    def test_missing_device_hostname_raises_error(self):
        from azext_iot.operations.hub import _resolve_hostname_by_type
        target = self._make_target()
        with pytest.raises(InvalidArgumentValueError):
            _resolve_hostname_by_type(target, HostnameType.DEVICE.value)

    def test_missing_service_hostname_raises_error(self):
        from azext_iot.operations.hub import _resolve_hostname_by_type
        target = self._make_target()
        with pytest.raises(InvalidArgumentValueError):
            _resolve_hostname_by_type(target, HostnameType.SERVICE.value)


class TestTransformHostname:
    """Tests for _transform_hostname — string-based hostname transformation."""

    def test_classic_to_classic(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.azure-devices.net", HostnameType.CLASSIC.value) == "hub.azure-devices.net"

    def test_classic_to_device(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.azure-devices.net", HostnameType.DEVICE.value) == "hub.device.azure-devices.net"

    def test_classic_to_service(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.azure-devices.net", HostnameType.SERVICE.value) == "hub.service.azure-devices.net"

    def test_service_to_device(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.service.azure-devices.net", HostnameType.DEVICE.value) == "hub.device.azure-devices.net"

    def test_device_to_service(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.device.azure-devices.net", HostnameType.SERVICE.value) == "hub.service.azure-devices.net"

    def test_device_to_classic(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.device.azure-devices.net", HostnameType.CLASSIC.value) == "hub.azure-devices.net"

    def test_service_to_classic(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.service.azure-devices.net", HostnameType.CLASSIC.value) == "hub.azure-devices.net"

    def test_gov_cloud_classic_to_device(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.azure-devices.us", HostnameType.DEVICE.value) == "hub.device.azure-devices.us"

    def test_gov_cloud_service_to_classic(self):
        from azext_iot.operations.hub import _transform_hostname
        assert _transform_hostname("hub.service.azure-devices.us", HostnameType.CLASSIC.value) == "hub.azure-devices.us"
