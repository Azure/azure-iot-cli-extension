# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import RequiredArgumentMissingError

from azext_iot.iothub.providers.mqtt import MQTTProvider

logging.disable(logging.CRITICAL)

mqtt_path = "azext_iot.iothub.providers.mqtt"


@pytest.fixture()
def mock_device_client(mocker):
    mocker.patch(f"{mqtt_path}.ensure_azure_namespace_path")
    import azure.iot.device as iot_device

    client_cls = mocker.patch.object(iot_device, "IoTHubDeviceClient")
    mocker.patch.object(iot_device, "X509")
    yield client_cls


def _make_provider(mock_device_client, **kwargs):
    defaults = {
        "hub_hostname": "myhub.azure-devices.net",
        "device_id": "dev1",
        "device_conn_string": "HostName=h;DeviceId=dev1;SharedAccessKey=key",
    }
    defaults.update(kwargs)
    return MQTTProvider(**defaults)


class TestInit:
    def test_init_connection_string(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        assert provider.device_id == "dev1"
        mock_device_client.create_from_connection_string.assert_called_once()

    def test_init_x509(self, mock_device_client):
        _make_provider(
            mock_device_client,
            device_conn_string=None,
            x509_files={
                "certificateFile": "cert.pem",
                "keyFile": "key.pem",
                "passphrase": "pp",
            },
        )
        mock_device_client.create_from_x509_certificate.assert_called_once()

    def test_init_x509_missing_files(self, mock_device_client):
        with pytest.raises(RequiredArgumentMissingError):
            _make_provider(
                mock_device_client,
                device_conn_string="HostName=h;DeviceId=dev1;x509=true",
            )


class TestSendD2CMessage:
    def test_send_message_content(self, mock_device_client, mocker):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "Message", side_effect=lambda d: SimpleNamespace(data=d))
        provider = _make_provider(mock_device_client)
        provider.send_d2c_message(message_content="hello", properties={"a": "b"})
        provider.device_client.send_message.assert_called_once()

    def test_send_message_file_text(self, mock_device_client, mocker, tmp_path):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "Message", side_effect=lambda d: SimpleNamespace(data=d))
        f = tmp_path / "msg.txt"
        f.write_text("file-content")
        provider = _make_provider(mock_device_client)
        provider.send_d2c_message(message_content=None, message_file_path=str(f))
        provider.device_client.send_message.assert_called_once()

    def test_send_message_file_binary(self, mock_device_client, mocker, tmp_path):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "Message", side_effect=lambda d: SimpleNamespace(data=d))
        f = tmp_path / "msg.bin"
        f.write_bytes(b"\x00\x01")
        provider = _make_provider(mock_device_client)
        provider.send_d2c_message(
            message_content=None,
            message_file_path=str(f),
            properties={"$.ct": "application/octet-stream"},
        )
        provider.device_client.send_message.assert_called_once()

    def test_send_message_file_not_found(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        with pytest.raises(FileNotFoundError):
            provider.send_d2c_message(message_content=None, message_file_path="/no/such/file")


class TestHandlers:
    def test_message_handler_with_encoding(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        message = SimpleNamespace(
            message_id="id",
            content_encoding="utf-8",
            data=b"hello",
            custom_properties={"k": "v"},
        )
        provider.message_handler(message)

    def test_message_handler_default_encoding(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        message = SimpleNamespace(data=b"hello", custom_properties={})
        provider.message_handler(message)

    def test_message_handler_bad_encoding_raises(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        message = SimpleNamespace(
            content_encoding="not-a-real-encoding",
            data=b"hello",
            custom_properties={},
        )
        with pytest.raises(LookupError):
            provider.message_handler(message)

    def test_method_request_handler_defaults(self, mock_device_client, mocker):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "MethodResponse")
        provider = _make_provider(mock_device_client)
        method_request = SimpleNamespace(request_id="r1", name="reboot", payload={})
        provider.method_request_handler(method_request)
        provider.device_client.send_method_response.assert_called_once()

    def test_method_request_handler_custom(self, mock_device_client, mocker):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "MethodResponse")
        provider = _make_provider(
            mock_device_client,
            method_response_code=204,
            method_response_payload={"ok": True},
        )
        method_request = SimpleNamespace(request_id="r1", name="reboot", payload={})
        provider.method_request_handler(method_request)
        provider.device_client.send_method_response.assert_called_once()

    def test_twin_patch_handler(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        provider.twin_patch_handler({"prop1": "value", "$version": 2})
        provider.device_client.patch_twin_reported_properties.assert_called_once_with(
            {"prop1": "value"}
        )

    def test_twin_patch_handler_no_modified(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        provider.twin_patch_handler({"$version": 2})
        provider.device_client.patch_twin_reported_properties.assert_not_called()


class TestExecuteShutdown:
    def test_execute(self, mock_device_client, mocker):
        import azure.iot.device as iot_device

        mocker.patch.object(iot_device, "Message", side_effect=lambda d: SimpleNamespace(data=d))
        mocker.patch(f"{mqtt_path}.sleep")
        provider = _make_provider(mock_device_client, init_reported_properties={"x": 1})
        data = mocker.MagicMock()
        data.generate.return_value = "payload"
        provider.execute(data=data, msg_count=2, publish_delay=0)
        assert provider.device_client.send_message.call_count == 2
        provider.device_client.patch_twin_reported_properties.assert_called_once_with({"x": 1})

    def test_execute_raises(self, mock_device_client, mocker):
        mocker.patch(f"{mqtt_path}.sleep")
        provider = _make_provider(mock_device_client)
        data = mocker.MagicMock()
        data.generate.side_effect = ValueError("boom")
        with pytest.raises(ValueError):
            provider.execute(data=data, msg_count=1, publish_delay=0)

    def test_shutdown(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        provider.shutdown()
        provider.device_client.shutdown.assert_called_once()

    def test_shutdown_handles_error(self, mock_device_client):
        provider = _make_provider(mock_device_client)
        provider.device_client.shutdown.side_effect = Exception("boom")
        # Should not raise.
        provider.shutdown()
