# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging

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
        mocker.sentinel.credential,
        "test-sub",
        "test-tenant",
    )
    return profile


def test_credential_is_selected_per_context_and_subscription(
    mocker, cli_profile
):
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
        mocker.call(cli_ctx=first_ctx),
        mocker.call(cli_ctx=second_ctx),
    ]
    assert (
        cli_profile.return_value.get_login_credentials.call_args_list
        == [
            mocker.call(subscription_id="test-sub-id"),
            mocker.call(subscription_id="second-sub"),
        ]
    )


def test_factory_propagates_login_failure(mocker, cli_profile):
    from knack.util import CLIError

    from azext_iot._factory import adr_service_factory

    error = CLIError("Please run 'az login' to setup account.")
    cli_profile.return_value.get_login_credentials.side_effect = error
    client_type = mocker.patch(
        "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient"
    )

    with pytest.raises(CLIError) as raised:
        adr_service_factory(_build_cli_ctx(mocker, CLOUD_CONFIGS[0]))

    assert raised.value is error
    client_type.assert_not_called()


@pytest.mark.parametrize(
    "cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS]
)
def test_adr_request_uses_in_process_auth_without_spawning_cli(
    mocker, cli_profile, mocked_response, cloud_config
):
    import platform
    from urllib.parse import parse_qs, urlsplit

    from azure.cli.core.auth.credential_adaptor import CredentialAdaptor

    from azext_iot._factory import adr_service_factory

    platform.processor()
    cli_ctx = _build_cli_ctx(mocker, cloud_config)
    msal_credential = mocker.Mock()
    msal_credential.acquire_token.return_value = {
        "access_token": "test-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    cli_profile.return_value.get_login_credentials.return_value = (
        CredentialAdaptor(msal_credential),
        "test-sub-id",
        "test-tenant",
    )
    spawn = mocker.patch(
        "subprocess.Popen",
        side_effect=AssertionError("Authentication must not spawn a CLI"),
    )
    mocked_response.add(
        method="GET",
        url=(
            f"{CANARY_ARM}/subscriptions/test-sub-id/resourceGroups/rg/"
            "providers/Microsoft.DeviceRegistry/namespaces/namespace"
        ),
        json={
            "name": "namespace",
            "location": "centraluseuap",
            "properties": {"provisioningState": "Succeeded"},
        },
        status=200,
    )

    with adr_service_factory(cli_ctx) as client:
        result = client.namespaces.get(
            resource_group_name="rg", namespace_name="namespace"
        )

    assert result["name"] == "namespace"
    spawn.assert_not_called()
    assert parse_qs(urlsplit(mocked_response.calls[0].request.url).query)[
        "api-version"
    ] == ["2026-11-02-preview"]
    assert msal_credential.acquire_token.call_args.args == (
        cloud_config["expected_scopes"],
    )


@pytest.mark.parametrize(
    "cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS]
)
def test_dps_factory_request_uses_retained_api(
    mocker, cli_profile, mocked_response, cloud_config
):
    from urllib.parse import parse_qs, urlsplit

    from azure.core.credentials import AccessToken

    from azext_iot._factory import iot_service_provisioning_factory

    credential = mocker.Mock(spec=["get_token"])
    credential.get_token.return_value = AccessToken(
        "test-token", 4102444800
    )
    cli_profile.return_value.get_login_credentials.return_value = (
        credential,
        "test-sub-id",
        "tenant",
    )
    mocked_response.add(
        method="GET",
        url=(
            f"{cloud_config['resource_manager']}/subscriptions/test-sub-id/"
            "resourceGroups/rg/providers/Microsoft.Devices/"
            "provisioningServices/test-dps"
        ),
        json={"name": "test-dps"},
        status=200,
    )

    with iot_service_provisioning_factory(
        _build_cli_ctx(mocker, cloud_config)
    ) as client:
        result = client.iot_dps_resource.get(
            provisioning_service_name="test-dps",
            resource_group_name="rg",
        )

    assert result == {"name": "test-dps"}
    assert parse_qs(urlsplit(mocked_response.calls[0].request.url).query)[
        "api-version"
    ] == ["2026-06-01-preview"]
    assert credential.get_token.call_args.args == tuple(
        cloud_config["expected_scopes"]
    )


@pytest.mark.parametrize("cloud_config", CLOUD_CONFIGS, ids=[c["id"] for c in CLOUD_CONFIGS])
class TestFactoryCredentialScopes:
    """Ensure management client factories pass cloud-specific credential_scopes."""

    def test_iot_hub_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch("azext_iot.sdk.iothub.mgmt.IotHubClient")
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import iot_hub_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        iot_hub_service_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["api_version"] == "2026-06-01-preview"
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs["base_url"] == cloud_config["resource_manager"]

    def test_iot_hub_factory_honors_subscription_override(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch(
            "azext_iot.sdk.iothub.mgmt.IotHubClient"
        )
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id"
        )

        from azext_iot._factory import iot_hub_service_factory

        iot_hub_service_factory(
            _build_cli_ctx(mocker, cloud_config),
            subscription_id="linked-sub",
        )

        assert mock_client_cls.call_args.kwargs["subscription_id"] == "linked-sub"
        get_subscription.assert_not_called()

    def test_dps_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch("azext_iot.sdk.dps.mgmt.IotDpsClient")
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import iot_service_provisioning_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        iot_service_provisioning_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs["base_url"] == cloud_config["resource_manager"]

    def test_dps_factory_honors_subscription_override(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch(
            "azext_iot.sdk.dps.mgmt.IotDpsClient"
        )
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id"
        )

        from azext_iot._factory import iot_service_provisioning_factory

        iot_service_provisioning_factory(
            _build_cli_ctx(mocker, cloud_config),
            subscription_id="linked-sub",
        )

        assert mock_client_cls.call_args.kwargs["subscription_id"] == "linked-sub"
        get_subscription.assert_not_called()

    def test_update_instance_factory_honors_subscription_override(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch(
            "azext_iot.sdk.deviceupdate.duregistry.DeviceUpdateClient"
        )
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id"
        )

        from azext_iot._factory import adr_update_instance_service_factory

        adr_update_instance_service_factory(
            _build_cli_ctx(mocker, cloud_config),
            subscription_id="linked-sub",
        )

        assert mock_client_cls.call_args.kwargs["subscription_id"] == "linked-sub"
        assert mock_client_cls.call_args.kwargs["base_url"] == CANARY_ARM
        get_subscription.assert_not_called()

    def test_adr_factory(self, mocker, cloud_config):
        mocker.patch("azext_iot._factory.get_cli_credential")
        mock_client_cls = mocker.patch(
            "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient"
        )
        mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="test-sub")

        from azext_iot._factory import adr_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        adr_service_factory(cli_ctx)

        mock_client_cls.assert_called_once()
        call_kwargs = mock_client_cls.call_args.kwargs
        assert call_kwargs["credential_scopes"] == cloud_config["expected_scopes"]
        assert call_kwargs["base_url"] == CANARY_ARM

    def test_adr_factory_honors_subscription_override(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        client = mocker.patch(
            "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient"
        )
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id"
        )

        from azext_iot._factory import adr_service_factory

        adr_service_factory(
            _build_cli_ctx(mocker, cloud_config),
            subscription_id="namespace-sub",
        )

        assert client.call_args.kwargs["subscription_id"] == "namespace-sub"
        get_subscription.assert_not_called()

    def test_adr_command_factory_uses_cli_selected_subscription(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        client = mocker.patch(
            "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient"
        )
        profile_fallback = mocker.patch(
            "azure.cli.core._profile.Profile.get_subscription_id"
        )
        from azext_iot._factory import adr_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        cli_ctx.data["subscription_id"] = "explicit-namespace-sub"

        # CommandOperation passes its argument dictionary as the second
        # positional value. The global --subscription action has already put
        # the selected namespace subscription on cli_ctx.
        adr_service_factory(cli_ctx, {"namespace_name": "namespace"})

        assert (
            client.call_args.kwargs["subscription_id"]
            == "explicit-namespace-sub"
        )
        profile_fallback.assert_not_called()

    def test_adr_command_factory_uses_current_subscription_by_default(
        self, mocker, cloud_config
    ):
        mocker.patch("azext_iot._factory.get_cli_credential")
        client = mocker.patch(
            "azext_iot.sdk.deviceregistry.DeviceRegistryMgmtClient"
        )
        get_subscription = mocker.patch(
            "azure.cli.core.commands.client_factory.get_subscription_id",
            return_value="current-sub",
        )
        from azext_iot._factory import adr_service_factory

        cli_ctx = _build_cli_ctx(mocker, cloud_config)
        cli_ctx.data.clear()

        adr_service_factory(cli_ctx, {"namespace_name": "namespace"})

        assert client.call_args.kwargs["subscription_id"] == "current-sub"
        get_subscription.assert_called_once_with(cli_ctx)

    @pytest.mark.parametrize(
        "factory_name,client_path",
        [
            (
                "adr_iot_hub_service_factory",
                "azext_iot.sdk.iothub.mgmt.IotHubClient",
            ),
            (
                "adr_iot_service_provisioning_factory",
                "azext_iot.sdk.dps.mgmt.IotDpsClient",
            ),
        ],
    )
    def test_adr_link_target_factories_keep_canary_arm(
        self, mocker, cloud_config, factory_name, client_path
    ):
        import azext_iot._factory as subject

        mocker.patch.object(subject, "get_cli_credential")
        client = mocker.patch(client_path)
        factory = getattr(subject, factory_name)

        factory(
            _build_cli_ctx(mocker, cloud_config),
            subscription_id="linked-sub",
        )

        assert client.call_args.kwargs["base_url"] == CANARY_ARM
        if factory_name == "adr_iot_hub_service_factory":
            assert (
                client.call_args.kwargs["api_version"]
                == "2026-06-01-preview"
            )
        assert (
            client.call_args.kwargs["credential_scopes"]
            == cloud_config["expected_scopes"]
        )


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

    def test_modeless_dps_sdk_uses_name_and_azure_key_credential(self, mocker):
        from azure.core.credentials import AzureKeyCredential
        from azext_iot._factory import SdkResolver

        sas = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        sas.return_value.generate_sas_token.return_value = "SharedAccessSignature token"
        client = mocker.patch(
            "azext_iot.sdk.dps.service.ProvisioningServiceClient"
        )
        target = {
            "entity": "mydps.azure-devices-provisioning.net",
            "policy": "owner",
            "primarykey": "key",
        }

        SdkResolver(target)._get_dps_service_sdk()

        kwargs = client.call_args.kwargs
        assert kwargs["dps_name"] == "mydps"
        assert isinstance(kwargs["credential"], AzureKeyCredential)
        assert kwargs["credential"].key == "SharedAccessSignature token"

    @pytest.mark.parametrize(
        "hostname,policy",
        [
            ("public.azure-devices-provisioning.net", "owner"),
            ("government.azure-devices-provisioning.us", "owner"),
            ("private.login.contoso.example", "login"),
        ],
        ids=["public", "usgov", "custom-login"],
    )
    def test_modeless_dps_sdk_builds_requests_for_discovered_hostname(
        self, mocker, hostname, policy
    ):
        from azext_iot._factory import SdkResolver

        sas = mocker.patch("azext_iot._factory.SasTokenAuthentication")
        sas.return_value.generate_sas_token.return_value = (
            "SharedAccessSignature service-token"
        )
        oauth = mocker.patch("azext_iot._factory.IoTOAuth")
        oauth.return_value.signed_session.return_value.headers = {
            "Authorization": "Bearer login-token"
        }
        target = {
            "entity": hostname,
            "policy": policy,
            "primarykey": "key",
            "cmd": mocker.MagicMock(),
        }

        client = SdkResolver(target)._get_dps_service_sdk()
        request = _capture_pipeline_request(
            mocker,
            client,
            lambda sdk: sdk.individual_enrollment.get("registration"),
        )

        assert request.url.startswith(
            f"https://{hostname}/enrollments/registration?"
        )
        if policy == "login":
            assert request.headers["Authorization"] == "Bearer login-token"
            sas.assert_not_called()
        else:
            assert (
                request.headers["Authorization"]
                == "SharedAccessSignature service-token"
            )
            assert sas.call_args.kwargs["uri"] == hostname


def test_software_update_data_factory_requires_service_endpoint(mocker):
    from azure.cli.core.azclierror import RequiredArgumentMissingError
    from azext_iot._factory import adr_software_update_data_service_factory

    cli_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[0])
    with pytest.raises(RequiredArgumentMissingError, match="service-derived"):
        adr_software_update_data_service_factory(cli_ctx)

    credential = mocker.patch(
        "azext_iot._factory.get_cli_credential",
        return_value=mocker.sentinel.credential,
    )
    client = mocker.patch(
        "azext_iot.sdk.deviceupdate.duregistrydata."
        "DeviceRegistrySoftwareUpdateClient"
    )
    adr_software_update_data_service_factory(
        cli_ctx, endpoint="updates.example.test"
    )
    assert client.call_args.kwargs["endpoint"] == "updates.example.test"
    assert (
        client.call_args.kwargs["credential"]
        is mocker.sentinel.credential
    )
    credential.assert_called_once_with(cli_ctx)


def test_dps_device_factory_uses_service_endpoint(mocker):
    from azext_iot._factory import dps_device_service_factory

    sas = mocker.patch(
        "azext_iot._factory.get_dps_sas_auth_header",
        return_value="SharedAccessSignature redacted",
    )
    client = mocker.patch(
        "azext_iot.sdk.dps.device.ProvisioningDeviceClient"
    )
    cli_ctx = _build_cli_ctx(mocker, CLOUD_CONFIGS[0])
    dps_device_service_factory(
        cli_ctx,
        endpoint="https://global.azure-devices-provisioning.net",
        registration_id="registration",
        id_scope="scope",
        device_symmetric_key="secret-key",
    )
    assert (
        client.call_args.kwargs["endpoint"]
        == "https://global.azure-devices-provisioning.net"
    )
    sas.assert_called_once_with("scope", "registration", "secret-key")
    assert (
        client.call_args.kwargs["authentication_policy"]._credential.key
        == "SharedAccessSignature redacted"
    )


def _capture_pipeline_request(mocker, client, operation):
    captured = []

    def capture(request, **_):
        captured.append(request)
        raise RuntimeError("request captured")

    transport = client._client._pipeline._transport
    mocker.patch.object(transport, "send", side_effect=capture)
    with pytest.raises(RuntimeError, match="request captured"):
        operation(client)
    return captured[0]


@pytest.mark.parametrize(
    "operation",
    [
        lambda client: client.runtime_registration.register_device_and_issue_certificate(
            registration_id="registration",
            id_scope="scope",
            device_registration={"registrationId": "registration"},
            logging_enable=True,
        ),
        lambda client: client.runtime_registration.operation_status_lookup_preview(
            registration_id="registration",
            operation_id="operation",
            id_scope="scope",
            logging_enable=True,
        ),
        lambda client: client.device_update.request_software_updates(
            registration_id="registration",
            id_scope="scope",
            body={},
            logging_enable=True,
        ),
        lambda client: client.device_update.request_onboarding_updates(
            registration_id="registration",
            id_scope="scope",
            body={},
            logging_enable=True,
        ),
        lambda client: client.device_update.report_update_status(
            registration_id="registration",
            id_scope="scope",
            body={},
            logging_enable=True,
        ),
    ],
    ids=[
        "register",
        "operation-status",
        "request-software-updates",
        "request-onboarding-updates",
        "report-update-status",
    ],
)
def test_dps_device_operations_send_sas_without_logging_it(
    mocker, caplog, operation
):
    # Includes generated device-agent methods that are deliberately not exposed
    # as public operator CLI commands.
    import azext_iot._factory as subject

    secret_key = "raw-device-secret"
    sas_token = "SharedAccessSignature sr=scope%2Fregistrations%2Fregistration&sig=secret"
    mocker.patch.object(
        subject, "get_dps_sas_auth_header", return_value=sas_token
    )
    caplog.set_level(logging.DEBUG)

    client = subject.dps_device_service_factory(
        mocker.MagicMock(),
        endpoint="device.provisioning.example",
        registration_id="registration",
        id_scope="scope",
        device_symmetric_key=secret_key,
    )
    request = _capture_pipeline_request(mocker, client, operation)

    assert request.headers["Authorization"] == sas_token
    assert request.url.startswith("https://device.provisioning.example/")
    assert secret_key not in caplog.text
    assert sas_token not in caplog.text


def test_dps_device_x509_transport_loads_passphrase_and_reaches_request(
    mocker
):
    import azext_iot._factory as subject

    ssl_context = mocker.MagicMock()
    mocker.patch.object(
        subject.ssl, "create_default_context", return_value=ssl_context
    )
    client = subject.dps_device_service_factory(
        mocker.MagicMock(),
        endpoint="device.provisioning.example",
        registration_id="registration",
        id_scope="scope",
        certificate_file="device-cert.pem",
        key_file="device-key.pem",
        passphrase="private-passphrase",
    )

    request = _capture_pipeline_request(
        mocker,
        client,
        lambda sdk: sdk.runtime_registration.operation_status_lookup_preview(
            registration_id="registration",
            operation_id="operation",
            id_scope="scope",
        ),
    )

    ssl_context.load_cert_chain.assert_called_once_with(
        certfile="device-cert.pem",
        keyfile="device-key.pem",
        password="private-passphrase",
    )
    transport = client._client._pipeline._transport
    adapter = transport.session.adapters["https://"]
    assert adapter._ssl_context is ssl_context
    assert request.url.startswith("https://device.provisioning.example/")


def test_mutual_tls_adapter_preserves_context_for_direct_and_proxy_pools(
    mocker
):
    import requests
    import azext_iot._factory as subject

    ssl_context = mocker.MagicMock()
    adapter = subject._MutualTlsAdapter(ssl_context)
    request = requests.Request(
        "GET", "https://device.provisioning.example"
    ).prepare()

    _, pool_kwargs = adapter.build_connection_pool_key_attributes(
        request, True, ("cert.pem", "key.pem")
    )
    assert pool_kwargs["ssl_context"] is ssl_context
    assert "cert_file" not in pool_kwargs
    assert "key_file" not in pool_kwargs

    proxy_manager = mocker.patch.object(
        subject.HTTPAdapter, "proxy_manager_for"
    )
    adapter.proxy_manager_for("https://proxy.example")
    assert (
        proxy_manager.call_args.kwargs["ssl_context"] is ssl_context
    )


def test_mutual_tls_adapter_supports_requests_without_pool_key_builder(
    mocker
):
    import azext_iot._factory as subject

    mocker.patch.object(
        subject.HTTPAdapter,
        "build_connection_pool_key_attributes",
        None,
    )
    ssl_context = mocker.MagicMock()
    adapter = subject._MutualTlsAdapter(ssl_context)

    host, pool_kwargs = adapter.build_connection_pool_key_attributes(
        mocker.MagicMock(), True
    )

    assert not host
    assert pool_kwargs == {"ssl_context": ssl_context}


def test_dps_device_x509_transport_sanitizes_certificate_error(mocker):
    from azure.cli.core.azclierror import InvalidArgumentValueError
    import azext_iot._factory as subject

    ssl_context = mocker.MagicMock()
    ssl_context.load_cert_chain.side_effect = OSError(
        "unable to load certificate"
    )
    mocker.patch.object(
        subject.ssl, "create_default_context", return_value=ssl_context
    )

    with pytest.raises(
        InvalidArgumentValueError, match="Could not open certificate files"
    ):
        subject.dps_device_service_factory(
            mocker.MagicMock(),
            registration_id="registration",
            id_scope="scope",
            certificate_file="device-cert.pem",
            key_file="device-key.pem",
            passphrase="private-passphrase",
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"device_symmetric_key": "key"},
        {"certificate_file": "cert.pem"},
        {"key_file": "key.pem"},
        {"passphrase": "secret"},
    ],
)
def test_dps_device_factory_rejects_incomplete_authentication(mocker, kwargs):
    from azure.cli.core.azclierror import RequiredArgumentMissingError
    from azext_iot._factory import dps_device_service_factory

    with pytest.raises(RequiredArgumentMissingError):
        dps_device_service_factory(
            mocker.MagicMock(),
            endpoint="device.provisioning.example",
            **kwargs,
        )


def test_resource_factory_delegates_to_cli_management_factory(mocker):
    from azure.cli.core.profiles import ResourceType
    from azext_iot._factory import resource_service_factory

    management_factory = mocker.patch(
        "azure.cli.core.commands.client_factory.get_mgmt_service_client"
    )
    cli_ctx = mocker.MagicMock()
    assert (
        resource_service_factory(cli_ctx)
        is management_factory.return_value
    )
    management_factory.assert_called_once_with(
        cli_ctx, ResourceType.MGMT_RESOURCE_RESOURCES
    )


def test_sdk_resolver_get_sdk_configures_legacy_but_not_modeless_client(mocker):
    from azext_iot._factory import SdkResolver
    from azext_iot.common.shared import SdkType

    resolver = SdkResolver(
        {"entity": "entity", "policy": "policy", "primarykey": "key"}
    )
    assert set(resolver._construct_sdk_map()) == {
        SdkType.service_sdk,
        SdkType.device_sdk,
        SdkType.dps_sdk,
    }
    legacy = mocker.MagicMock()
    modeless = object()
    resolver._construct_sdk_map = mocker.MagicMock(
        return_value={
            SdkType.service_sdk: lambda: legacy,
            SdkType.dps_sdk: lambda: modeless,
        }
    )

    assert resolver.get_sdk(SdkType.service_sdk) is legacy
    assert legacy.config.enable_http_logger is True
    legacy.config.add_user_agent.assert_called_once()
    assert resolver.get_sdk(SdkType.dps_sdk) is modeless


def test_iothub_service_sdk_supports_override_and_login(mocker):
    from azext_iot._factory import SdkResolver

    client = mocker.patch(
        "azext_iot.sdk.iothub.service.IotHubGatewayServiceAPIs"
    )
    override = object()
    target = {
        "entity": "hub.azure-devices.net",
        "policy": "policy",
        "primarykey": "key",
    }
    SdkResolver(target, auth_override=override)._get_iothub_service_sdk()
    assert client.call_args.kwargs["credentials"] is override

    oauth = mocker.patch("azext_iot._factory.IoTOAuth")
    target.update(policy="login", cmd=mocker.MagicMock())
    SdkResolver(target)._get_iothub_service_sdk()
    assert client.call_args.kwargs["credentials"] is oauth.return_value


def test_modeless_dps_sdk_supports_override_and_login(mocker):
    from azure.core.credentials import AzureKeyCredential
    from azext_iot._factory import SdkResolver

    client = mocker.patch(
        "azext_iot.sdk.dps.service.ProvisioningServiceClient"
    )
    target = {
        "entity": "dps.azure-devices-provisioning.net",
        "policy": "owner",
        "primarykey": "key",
    }
    key_credential = AzureKeyCredential("token")
    SdkResolver(target, auth_override=key_credential)._get_dps_service_sdk()
    assert client.call_args.kwargs["credential"] is key_credential

    custom_auth = mocker.MagicMock()
    custom_auth.signed_session.return_value.headers = {
        "Authorization": "SharedAccessSignature custom"
    }
    SdkResolver(target, auth_override=custom_auth)._get_dps_service_sdk()
    assert (
        client.call_args.kwargs["credential"].key
        == "SharedAccessSignature custom"
    )

    oauth = mocker.patch("azext_iot._factory.IoTOAuth")
    oauth.return_value.signed_session.return_value.headers = {
        "Authorization": "Bearer aad"
    }
    target.update(policy="login", cmd=mocker.MagicMock())
    SdkResolver(target)._get_dps_service_sdk()
    assert client.call_args.kwargs["credential"].key == "Bearer aad"
