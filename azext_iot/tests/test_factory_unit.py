# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

CANARY_ARM = "https://centraluseuap.management.azure.com"

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


@pytest.fixture
def cli_profile(mocker):
    profile = mocker.patch("azext_iot.common.auth.Profile")
    profile.return_value.get_login_credentials.return_value = (
        mocker.sentinel.credential, "test-sub", "test-tenant"
    )
    return profile


MANAGEMENT_FACTORIES = [
    ("iot_hub_service_factory", "azext_iot.sdk.iothub.mgmt.IotHubClient", "base_url"),
    ("iot_service_provisioning_factory", "azext_iot.sdk.dps.mgmt.IotDpsClient", "base_url"),
    ("adr_service_factory", "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient", "base_url"),
    ("adr_iot_hub_service_factory", "azext_iot.sdk.iothub.mgmt.IotHubClient", "base_url"),
    ("adr_iot_service_provisioning_factory", "azext_iot.sdk.dps.mgmt.IotDpsClient", "base_url"),
    ("adr_update_instance_service_factory", "azext_iot.sdk.deviceupdate.duregistry.DeviceUpdateClient", "base_url"),
]


@pytest.mark.parametrize("cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS])
class TestFactoryCredentialScopes:
    """Preserve scopes/endpoints while authenticating in the hosting CLI."""

    @pytest.mark.parametrize("factory_name,client_path,endpoint_key", MANAGEMENT_FACTORIES)
    def test_management_factory(
        self, mocker, cloud_config, cli_profile, factory_name, client_path, endpoint_key
    ):
        from azext_iot import _factory

        client_type = mocker.patch(client_path)
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub"
        )

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        assert getattr(_factory, factory_name)(cli_ctx) is client_type.return_value

        get_subscription.assert_called_once_with(cli_ctx)
        cli_profile.assert_called_once_with(cli_ctx=cli_ctx)
        cli_profile.return_value.get_login_credentials.assert_called_once_with(subscription_id="test-sub")
        client_type.assert_called_once()
        call_kwargs = client_type.call_args.kwargs
        assert call_kwargs["credential"] is mocker.sentinel.credential
        assert call_kwargs["subscription_id"] == "test-sub"
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs[endpoint_key] == CANARY_ARM
        assert "user_agent_policy" in call_kwargs
        assert "http_logging_policy" in call_kwargs

    @pytest.mark.parametrize(
        "factory_name,client_path,endpoint_key",
        MANAGEMENT_FACTORIES,
    )
    def test_management_factory_honors_subscription_override(
        self, mocker, cloud_config, cli_profile, factory_name, client_path, endpoint_key
    ):
        from azext_iot import _factory

        client_type = mocker.patch(client_path)
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id"
        )

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        getattr(_factory, factory_name)(cli_ctx, subscription_id="linked-sub")

        get_subscription.assert_not_called()
        cli_profile.assert_called_once_with(cli_ctx=cli_ctx)
        cli_profile.return_value.get_login_credentials.assert_called_once_with(subscription_id="linked-sub")
        kwargs = client_type.call_args.kwargs
        assert kwargs["subscription_id"] == "linked-sub"
        assert kwargs["credential"] is mocker.sentinel.credential
        assert kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert kwargs[endpoint_key] == CANARY_ARM


def test_credential_is_selected_per_context_without_global_cache(mocker, cli_profile):
    from azext_iot.common.auth import get_cli_credential

    first_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[0])
    second_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[1])
    second_ctx.data["subscription_id"] = "second-sub"
    cli_profile.return_value.get_login_credentials.side_effect = [
        (mocker.sentinel.first, "test-sub-id", "first-tenant"),
        (mocker.sentinel.second, "second-sub", "second-tenant"),
    ]

    assert get_cli_credential(first_ctx) is mocker.sentinel.first
    assert get_cli_credential(second_ctx) is mocker.sentinel.second

    assert cli_profile.call_args_list == [
        mocker.call(cli_ctx=first_ctx), mocker.call(cli_ctx=second_ctx)
    ]
    assert cli_profile.return_value.get_login_credentials.call_args_list == [
        mocker.call(subscription_id="test-sub-id"), mocker.call(subscription_id="second-sub")
    ]


def test_factory_propagates_login_failure(mocker, cli_profile):
    from knack.util import CLIError
    from azext_iot._factory import adr_service_factory

    error = CLIError("Please run 'az login' to setup account.")
    cli_profile.return_value.get_login_credentials.side_effect = error
    client_type = mocker.patch("azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient")

    with pytest.raises(CLIError) as raised:
        adr_service_factory(_build_cli_ctx(mocker, CLOUD_CONFIGS[0]))

    assert raised.value is error
    client_type.assert_not_called()


@pytest.mark.parametrize("operation", ["get", "create"])
@pytest.mark.parametrize("cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS])
def test_adr_requests_use_in_process_auth_without_spawning_cli(
    mocker, cli_profile, mocked_response, operation, cloud_config
):
    from urllib.parse import parse_qs, urlsplit
    from azure.cli.core.auth.credential_adaptor import CredentialAdaptor
    from azext_iot._factory import adr_service_factory
    from azext_iot.common.arm import adapt_modeless_lro_poller

    import platform
    platform.processor()
    cli_ctx = _build_cli_ctx(mocker, cloud_config)
    msal_credential = mocker.Mock()
    msal_credential.acquire_token.return_value = {
        "access_token": "test-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    cli_profile.return_value.get_login_credentials.return_value = (
        CredentialAdaptor(msal_credential), "test-sub-id", "test-tenant"
    )
    spawn = mocker.patch(
        "subprocess.Popen", side_effect=AssertionError("Authentication must not spawn a CLI")
    )
    namespace = {
        "name": "namespace",
        "location": "centraluseuap",
        "properties": {"provisioningState": "Succeeded"},
    }
    mocked_response.add(
        method="GET" if operation == "get" else "PUT",
        url=(
            f"{CANARY_ARM}/subscriptions/test-sub-id"
            "/resourceGroups/rg/providers/Microsoft.DeviceRegistry/namespaces/namespace"
        ),
        json=namespace,
        status=200,
    )

    for _ in range(2):
        with adr_service_factory(cli_ctx) as client:
            if operation == "get":
                result = client.namespaces.get(resource_group_name="rg", namespace_name="namespace")
            else:
                poller = client.namespaces.begin_create_or_replace(
                    resource_group_name="rg",
                    namespace_name="namespace",
                    resource={"location": "centraluseuap"},
                    polling=False,
                )
                # This tests authentication/transport, not the current ADR
                # generator's final-response callback defect.
                result = adapt_modeless_lro_poller(poller).result()
        assert result["name"] == "namespace"

    spawn.assert_not_called()
    assert len(mocked_response.calls) == 2
    assert all(
        call.request.headers["Authorization"] == "Bearer test-token"
        for call in mocked_response.calls
    )
    assert msal_credential.acquire_token.call_args_list == [
        mocker.call(cloud_config["expected_scopes"]),
        mocker.call(cloud_config["expected_scopes"]),
    ]
    assert cli_profile.return_value.get_login_credentials.call_args_list == [
        mocker.call(subscription_id="test-sub-id"),
        mocker.call(subscription_id="test-sub-id"),
    ]
    assert all(
        parse_qs(urlsplit(call.request.url).query)["api-version"] == ["2026-11-02-preview"]
        for call in mocked_response.calls
    )


@pytest.mark.parametrize("cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS])
def test_dps_request_uses_canary_endpoint_and_preserves_api_version(mocker, cli_profile, mocked_response, cloud_config):
    from urllib.parse import parse_qs, urlsplit
    from azure.core.credentials import AccessToken
    from azext_iot._factory import iot_service_provisioning_factory

    credential = mocker.Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken("test-token", 4102444800)
    cli_profile.return_value.get_login_credentials.return_value = (credential, "test-sub-id", "tenant")
    mocked_response.add(
        method="GET",
        url=(
            f"{CANARY_ARM}/subscriptions/test-sub-id/resourceGroups/rg"
            "/providers/Microsoft.Devices/provisioningServices/test-dps"
        ),
        json={"name": "test-dps"},
        status=200,
    )

    with iot_service_provisioning_factory(_build_cli_ctx(mocker, cloud_config)) as client:
        result = client.iot_dps_resource.get(provisioning_service_name="test-dps", resource_group_name="rg")

    assert result == {"name": "test-dps"}
    assert parse_qs(urlsplit(mocked_response.calls[0].request.url).query)["api-version"] == ["2026-06-01-preview"]
    assert credential.get_token.call_args.args == tuple(cloud_config["expected_scopes"])


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
