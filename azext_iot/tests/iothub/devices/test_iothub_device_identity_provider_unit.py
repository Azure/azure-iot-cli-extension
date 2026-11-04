# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Provider-direct unit tests for DeviceIdentityProvider helper methods."""

import logging

import pytest
from azure.cli.core.azclierror import AzureResponseError

from azext_iot.iothub.providers.device_identity import DeviceIdentityProvider

logging.disable(logging.CRITICAL)


def _provider(mocker):
    p = DeviceIdentityProvider.__new__(DeviceIdentityProvider)
    p.cmd = mocker.MagicMock()
    p.hub_name = "hub"
    p.service_sdk = mocker.MagicMock()
    return p


class TestDeleteDeviceIdentities:
    def test_delete_success(self, mocker):
        p = _provider(mocker)
        p.delete_device_identities(["dev1", "dev2"])
        assert p.service_sdk.devices.delete_identity.call_count == 2

    def test_delete_wraps_error(self, mocker):
        p = _provider(mocker)
        p.service_sdk.devices.delete_identity.side_effect = Exception("boom")
        with pytest.raises(AzureResponseError):
            p.delete_device_identities(["dev1"])
