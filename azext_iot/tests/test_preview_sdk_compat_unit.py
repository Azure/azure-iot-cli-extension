# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import importlib.util
import inspect

import pytest
from azure.core.credentials import AzureKeyCredential

from azext_iot.sdk.deviceregistry import DeviceRegistryMgmtClient
from azext_iot.sdk.dps.mgmt import IotDpsClient
from azext_iot.sdk.dps.device import ProvisioningDeviceClient
from azext_iot.sdk.dps.service import ProvisioningServiceClient
from azext_iot.sdk.iothub.mgmt import IotHubClient


@pytest.mark.parametrize(
    "package",
    [
        "azext_iot.sdk.deviceregistry",
        "azext_iot.sdk.dps.service",
        "azext_iot.sdk.dps.device",
    ],
)
def test_preview_sdks_are_synchronous_and_modeless(package):
    assert importlib.util.find_spec(f"{package}.aio") is None
    assert importlib.util.find_spec(f"{package}.models") is None


def test_preview_control_client_names_versions_and_operation_groups():
    credential = object()
    subscription = "00000000-0000-0000-0000-000000000000"
    endpoint = "https://centraluseuap.management.azure.com"
    clients = [
        (
            DeviceRegistryMgmtClient(credential, subscription, endpoint),
            "2026-11-01",
            ("namespaces", "certificate_authorities", "certificate_policies"),
        ),
        (
            IotHubClient(credential, subscription, endpoint),
            "2026-11-01",
            ("iot_hub_resource", "iot_hub", "certificates"),
        ),
        (
            IotDpsClient(credential, subscription, endpoint),
            "2026-11-01",
            ("iot_dps_resource", "dps_certificate"),
        ),
    ]

    for client, api_version, groups in clients:
        assert client._config.base_url == endpoint
        assert client._config.api_version == api_version
        assert all(hasattr(client, group) for group in groups)


def test_preview_dps_service_client_constructor_and_operations():
    service_signature = inspect.signature(ProvisioningServiceClient)
    assert list(service_signature.parameters)[:2] == ["dps_name", "credential"]
    service = ProvisioningServiceClient("mydps", AzureKeyCredential("test-token"))
    assert service._config.api_version == "2026-11-01"
    assert hasattr(service, "individual_enrollment")
    assert hasattr(service, "enrollment_group")
    assert hasattr(service, "device_registration_state")
    device = ProvisioningDeviceClient(endpoint="https://global.azure-devices-provisioning.net")
    assert device._config.api_version == "2026-11-01"
    assert hasattr(device.runtime_registration, "register_device_and_issue_certificate")
    assert hasattr(device.runtime_registration, "operation_status_lookup_preview")
