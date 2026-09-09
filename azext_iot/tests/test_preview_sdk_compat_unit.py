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
from azext_iot.sdk.deviceupdate.duregistry import DeviceUpdateClient
from azext_iot.sdk.deviceupdate.duregistrydata import (
    DeviceRegistrySoftwareUpdateClient,
)
from azext_iot.sdk.dps.device import ProvisioningDeviceClient
from azext_iot.sdk.dps.mgmt import IotDpsClient
from azext_iot.sdk.dps.service import ProvisioningServiceClient
from azext_iot.sdk.iothub.mgmt import IotHubClient


@pytest.mark.parametrize(
    "package",
    [
        "azext_iot.sdk.deviceregistry",
        "azext_iot.sdk.deviceupdate.duregistry",
        "azext_iot.sdk.deviceupdate.duregistrydata",
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
            "2026-11-02-preview",
            ("namespaces", "certificate_authorities", "certificate_policies"),
        ),
        (
            IotHubClient(credential, subscription, endpoint),
            "2026-10-01-preview",
            ("iot_hub_resource", "iot_hub", "certificates"),
        ),
        (
            IotDpsClient(credential, subscription, endpoint),
            "2026-06-01-preview",
            ("iot_dps_resource", "dps_certificate"),
        ),
        (
            DeviceUpdateClient(credential, subscription, endpoint),
            "2026-11-02-preview",
            ("update_instances",),
        ),
    ]

    for client, api_version, groups in clients:
        assert client._config.base_url == endpoint
        assert client._config.api_version == api_version
        assert all(hasattr(client, group) for group in groups)


def test_dps_data_client_constructors_and_operations():
    service_signature = inspect.signature(ProvisioningServiceClient)
    assert list(service_signature.parameters)[:2] == ["dps_name", "credential"]
    service = ProvisioningServiceClient(
        "mydps", AzureKeyCredential("SharedAccessSignature token")
    )
    assert service._config.api_version == "2026-11-02-preview"
    assert hasattr(service, "individual_enrollment")
    assert hasattr(service, "enrollment_group")
    assert hasattr(service, "device_registration_state")

    device = ProvisioningDeviceClient(
        endpoint="https://global.azure-devices-provisioning.net"
    )
    assert device._config.api_version == "2026-11-02-preview"
    assert hasattr(
        device.runtime_registration, "register_device_and_issue_certificate"
    )
    # These service-generated agent methods intentionally remain in the SDK,
    # but are not registered as public operator CLI commands.
    assert hasattr(device.device_update, "request_software_updates")
    assert hasattr(device.device_update, "request_onboarding_updates")
    assert hasattr(device.device_update, "report_update_status")


def test_software_update_data_constructor_and_operation_groups():
    signature = inspect.signature(DeviceRegistrySoftwareUpdateClient)
    assert list(signature.parameters)[:2] == ["endpoint", "credential"]
    client = DeviceRegistrySoftwareUpdateClient(
        "updates.example.test", object()
    )

    assert client._config.api_version == "2026-11-02-preview"
    assert hasattr(client, "software_update")
    assert hasattr(client, "device_classes")
    assert hasattr(client.software_update, "list_operation_statuses")
    assert hasattr(client.software_update, "list_providers")
    assert hasattr(client.software_update, "list_names")
    assert hasattr(client.software_update, "list_versions")
