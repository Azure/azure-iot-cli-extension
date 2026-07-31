# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest


CLOUD_CONFIGS = [
    {
        "id": "public",
        "resource_manager": "https://management.azure.com",
        "active_directory_resource_id": "https://management.core.windows.net/",
        "expected_scopes": ["https://management.core.windows.net//.default"],
    },
    {
        "id": "usgov",
        "resource_manager": "https://management.usgovcloudapi.net",
        "active_directory_resource_id": "https://management.core.usgovcloudapi.net/",
        "expected_scopes": ["https://management.core.usgovcloudapi.net//.default"],
    },
]


def _build_cli_ctx(mocker, cloud_config):
    cli_ctx = mocker.MagicMock()
    cli_ctx.cloud.endpoints.resource_manager = cloud_config["resource_manager"]
    cli_ctx.cloud.endpoints.active_directory_resource_id = cloud_config["active_directory_resource_id"]
    cli_ctx.data = {"subscription_id": "test-sub-id"}
    return cli_ctx


@pytest.mark.parametrize("cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS])
class TestFactoryCredentialScopes:
    """Ensure management client factories pass cloud-specific credential_scopes."""

    def test_iot_hub_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.AZURE_CLI_CREDENTIAL")
        mock_client_cls = mocker.patch("azext_iot.sdk.iothub.mgmt.IotHubClient")
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import iot_hub_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        iot_hub_service_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs["base_url"] == cloud_config["resource_manager"]

    def test_dps_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.AZURE_CLI_CREDENTIAL")
        mock_client_cls = mocker.patch("azext_iot.sdk.dps.mgmt.IotDpsClient")
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import iot_service_provisioning_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        iot_service_provisioning_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs["endpoint"] == cloud_config["resource_manager"]

    def test_adr_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.AZURE_CLI_CREDENTIAL")
        mock_client_cls = mocker.patch("azext_iot.sdk.deviceregistry.MicrosoftDeviceRegistryManagementService")
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import adr_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        adr_service_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]


class TestSdkResolverHostnames:
    def _target(self, **overrides):
        target = {
            "entity": "myhub.device.azure-devices.net",
            "serviceHostName": "myhub.service.azure-devices.net",
            "deviceHostName": "myhub.device.azure-devices.net",
            "policy": "policy",
            "primarykey": "key",
        }
        target.update(overrides)
        return target

    def test_device_sdk_uses_device_hostname(self, mocker):
        from azext_iot._factory import SdkResolver

        auth = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        client = mocker.patch("azext_iot.sdk.iothub.device.IotHubGatewayDeviceAPIs")

        SdkResolver(self._target(), device_id="device1")._get_iothub_device_sdk()

        assert auth.call_args.kwargs["uri"] == "myhub.device.azure-devices.net/devices/device1"
        assert client.call_args.kwargs["base_url"] == "https://myhub.device.azure-devices.net"

    def test_service_sdk_uses_service_hostname(self, mocker):
        from azext_iot._factory import SdkResolver

        auth = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        client = mocker.patch("azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs")

        SdkResolver(self._target())._get_iothub_service_sdk()

        assert auth.call_args.kwargs["uri"] == "myhub.service.azure-devices.net"
        assert client.call_args.kwargs["base_url"] == "https://myhub.service.azure-devices.net"

    def test_device_sdk_falls_back_to_classic_hostname(self, mocker):
        from azext_iot._factory import SdkResolver

        auth = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        client = mocker.patch("azext_iot.sdk.iothub.device.IotHubGatewayDeviceAPIs")

        target = {
            "entity": "myhub.azure-devices.net",
            "policy": "policy",
            "primarykey": "key",
        }
        SdkResolver(target, device_id="device1")._get_iothub_device_sdk()

        assert auth.call_args.kwargs["uri"] == "myhub.azure-devices.net/devices/device1"
        assert client.call_args.kwargs["base_url"] == "https://myhub.azure-devices.net"

    def test_service_sdk_falls_back_to_classic_hostname(self, mocker):
        from azext_iot._factory import SdkResolver

        auth = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        client = mocker.patch("azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs")

        target = {
            "entity": "myhub.azure-devices.net",
            "policy": "policy",
            "primarykey": "key",
        }
        SdkResolver(target)._get_iothub_service_sdk()

        assert auth.call_args.kwargs["uri"] == "myhub.azure-devices.net"
        assert client.call_args.kwargs["base_url"] == "https://myhub.azure-devices.net"
