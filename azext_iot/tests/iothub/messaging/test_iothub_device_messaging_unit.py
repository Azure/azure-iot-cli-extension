# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import (
    ArgumentUsageError,
    CLIInternalError,
    InvalidArgumentValueError,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
)

from azext_iot._factory import CloudError
from azext_iot.iothub.providers.device_messaging import (
    DeviceMessagingProvider,
    _simulate_get_default_properties,
)
from azext_iot.common.shared import DeviceAuthApiType, SettleType, ProtocolType

logging.disable(logging.CRITICAL)

dm_path = "azext_iot.iothub.providers.device_messaging"


def _provider(mocker):
    p = DeviceMessagingProvider.__new__(DeviceMessagingProvider)
    p.cmd = mocker.MagicMock()
    p.device_id = "dev1"
    p.target = {"entity": "myhub.azure-devices.net"}
    p.device_sdk = mocker.MagicMock()
    return p


def _cloud_error(mocker):
    return CloudError.__new__(CloudError)


class TestSimpleSdkCalls:
    def test_send_message_http(self, mocker):
        p = _provider(mocker)
        p.device_send_message_http(data="hi", headers={"h": "v"})
        p.device_sdk.device.send_device_event.assert_called_once()

    def test_send_message_http_error(self, mocker):
        p = _provider(mocker)
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.send_device_event.side_effect = _cloud_error(mocker)
        p.device_send_message_http(data="hi")
        handler.assert_called_once()

    def test_c2d_complete(self, mocker):
        p = _provider(mocker)
        p.c2d_message_complete(etag="e")
        p.device_sdk.device.complete_device_bound_notification.assert_called_once()

    def test_c2d_complete_error(self, mocker):
        p = _provider(mocker)
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.complete_device_bound_notification.side_effect = _cloud_error(mocker)
        p.c2d_message_complete(etag="e")
        handler.assert_called_once()

    def test_c2d_reject(self, mocker):
        p = _provider(mocker)
        p.c2d_message_reject(etag="e")
        p.device_sdk.device.complete_device_bound_notification.assert_called_once_with(
            id="dev1", etag="e", reject=""
        )

    def test_c2d_reject_error(self, mocker):
        p = _provider(mocker)
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.complete_device_bound_notification.side_effect = _cloud_error(mocker)
        p.c2d_message_reject(etag="e")
        handler.assert_called_once()

    def test_c2d_abandon(self, mocker):
        p = _provider(mocker)
        p.c2d_message_abandon(etag="e")
        p.device_sdk.device.abandon_device_bound_notification.assert_called_once()

    def test_c2d_abandon_error(self, mocker):
        p = _provider(mocker)
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.abandon_device_bound_notification.side_effect = _cloud_error(mocker)
        p.c2d_message_abandon(etag="e")
        handler.assert_called_once()

    def test_c2d_purge(self, mocker):
        p = _provider(mocker)
        service_sdk = mocker.MagicMock()
        mocker.patch.object(p, "get_sdk", return_value=service_sdk)
        p.c2d_message_purge()
        service_sdk.cloud_to_device_messages.purge_cloud_to_device_message_queue.assert_called_once_with("dev1")


class TestC2DMessageReceive:
    def test_receive_mutually_exclusive(self, mocker):
        p = _provider(mocker)
        with pytest.raises(MutuallyExclusiveArgumentError):
            p.c2d_message_receive(complete=True, abandon=True)

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            ({"abandon": True}, SettleType.abandon.value),
            ({"complete": True}, SettleType.complete.value),
            ({"reject": True}, SettleType.reject.value),
            ({}, None),
        ],
    )
    def test_receive_dispatch(self, mocker, kwargs, expected):
        p = _provider(mocker)
        inner = mocker.patch.object(p, "_c2d_message_receive", return_value={"ok": True})
        p.c2d_message_receive(**kwargs)
        inner.assert_called_once_with(60, expected)

    def _result(self, status_code=200, headers=None, content=b""):
        return SimpleNamespace(
            status_code=status_code,
            headers=headers if headers is not None else {},
            content=content,
        )

    def test_inner_receive_with_ack_complete(self, mocker):
        p = _provider(mocker)
        result = self._result(
            headers={"etag": '"my-etag"', "iothub-app-foo": "bar", "content-encoding": "utf-8"},
            content=b"hello",
        )
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        ack_resp = SimpleNamespace(response=SimpleNamespace(status_code=204))
        p.device_sdk.device.complete_device_bound_notification.return_value = ack_resp
        payload = p._c2d_message_receive(lock_timeout=30, ack=SettleType.complete.value)
        assert payload["etag"] == "my-etag"
        assert payload["ack"] == SettleType.complete.value
        assert payload["properties"]["app"]["foo"] == "bar"
        assert payload["data"] == "hello"

    def test_inner_receive_ack_abandon(self, mocker):
        p = _provider(mocker)
        result = self._result(headers={"etag": '"e"'})
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        p.device_sdk.device.abandon_device_bound_notification.return_value = SimpleNamespace(
            response=SimpleNamespace(status_code=204)
        )
        payload = p._c2d_message_receive(ack=SettleType.abandon.value)
        assert payload["ack"] == SettleType.abandon.value

    def test_inner_receive_ack_reject(self, mocker):
        p = _provider(mocker)
        result = self._result(headers={"etag": '"e"'})
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        p.device_sdk.device.complete_device_bound_notification.return_value = SimpleNamespace(
            response=SimpleNamespace(status_code=204)
        )
        payload = p._c2d_message_receive(ack=SettleType.reject.value)
        assert payload["ack"] == SettleType.reject.value

    def test_inner_receive_no_content(self, mocker):
        p = _provider(mocker)
        result = self._result(headers={"etag": '"e"'}, content=b"")
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        payload = p._c2d_message_receive()
        assert payload["etag"] == "e"
        assert "data" not in payload

    def test_inner_receive_non_200(self, mocker):
        p = _provider(mocker)
        result = self._result(status_code=204)
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        assert p._c2d_message_receive() is None

    def test_inner_receive_decode_failure(self, mocker):
        p = _provider(mocker)
        bad_content = mocker.MagicMock()
        bad_content.decode.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "boom")
        result = self._result(headers={"etag": '"e"', "content-encoding": "utf-8"}, content=bad_content)
        p.device_sdk.device.receive_device_bound_notification.return_value.response = result
        payload = p._c2d_message_receive()
        from azext_iot.iothub.providers.device_messaging import NON_DECODABLE_PAYLOAD

        assert payload["data"] == NON_DECODABLE_PAYLOAD

    def test_inner_receive_error(self, mocker):
        p = _provider(mocker)
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.receive_device_bound_notification.side_effect = _cloud_error(mocker)
        p._c2d_message_receive()
        handler.assert_called_once()


class TestC2DMessageSend:
    def test_send_wait_without_ack(self, mocker):
        p = _provider(mocker)
        with pytest.raises(RequiredArgumentMissingError):
            p.c2d_message_send(wait_on_feedback=True, ack=None)

    def test_send_expiry_in_past(self, mocker):
        p = _provider(mocker)
        with pytest.raises(InvalidArgumentValueError):
            p.c2d_message_send(expiry_time_utc="1")

    def test_send_success(self, mocker):
        p = _provider(mocker)
        send = mocker.patch("azext_iot.monitor.event.send_c2d_message", return_value=("msg-id", None))
        p.c2d_message_send(data="hi", properties="a=b")
        send.assert_called_once()

    def test_send_with_errors(self, mocker):
        p = _provider(mocker)
        mocker.patch("azext_iot.monitor.event.send_c2d_message", return_value=(None, "some-error"))
        with pytest.raises(CLIInternalError):
            p.c2d_message_send(data="hi")

    def test_send_wait_on_feedback(self, mocker):
        p = _provider(mocker)
        mocker.patch("azext_iot.monitor.event.send_c2d_message", return_value=("msg-id", None))
        feedback = mocker.patch(f"{dm_path}._iot_hub_monitor_feedback")
        p.c2d_message_send(data="hi", ack="full", wait_on_feedback=True)
        feedback.assert_called_once()


class TestDeviceSendMessage:
    def test_send_message_symmetric(self, mocker):
        p = _provider(mocker)
        mqtt_cls = mocker.patch("azext_iot.iothub.providers.mqtt.MQTTProvider")
        mocker.patch(f"{dm_path}._build_device_or_module_connection_string", return_value="cs")
        p.device_send_message(
            data="hi", device_symmetric_key="key", properties="a=b", msg_count=2
        )
        assert mqtt_cls.return_value.send_d2c_message.call_count == 2
        mqtt_cls.return_value.shutdown.assert_called_once()


class TestDeviceAuthProps:
    def test_symmetric(self, mocker):
        p = _provider(mocker)
        result = p._d2c_get_device_auth_props(symmetric_key="key")
        assert result["authentication"]["type"] == DeviceAuthApiType.sas.value

    def test_x509(self, mocker):
        p = _provider(mocker)
        result = p._d2c_get_device_auth_props(certificate_file="c.pem", key_file="k.pem", passphrase="pp")
        assert result["authentication"]["type"] == DeviceAuthApiType.selfSigned.value

    def test_x509_missing(self, mocker):
        p = _provider(mocker)
        with pytest.raises(RequiredArgumentMissingError):
            p._d2c_get_device_auth_props(certificate_file="c.pem")

    def test_service_lookup(self, mocker):
        p = _provider(mocker)
        show = mocker.patch(f"{dm_path}._iot_device_show", return_value={"deviceId": "dev1"})
        result = p._d2c_get_device_auth_props()
        show.assert_called_once()
        assert result["deviceId"] == "dev1"


class TestUploadFile:
    def test_upload_missing_file(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{dm_path}.exists", return_value=False)
        from azure.cli.core.azclierror import FileOperationError

        with pytest.raises(FileOperationError):
            p.device_upload_file(file_path="/no/file", content_type="text/plain")

    def test_upload_success(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{dm_path}.exists", return_value=True)
        mocker.patch(f"{dm_path}.read_file_content", return_value="content")
        mocker.patch(f"{dm_path}.basename", return_value="f.txt")
        p.device_sdk.device.create_file_upload_sas_uri.return_value.response.json.return_value = {
            "hostName": "host",
            "containerName": "cont",
            "blobName": "blob",
            "sasToken": "?sas",
            "correlationId": "corr",
        }
        p.device_sdk.device.upload_file_to_container.return_value = SimpleNamespace(
            status_code=201, reason="Created"
        )
        p.device_upload_file(file_path="f.txt", content_type="text/plain")
        p.device_sdk.device.update_file_upload_status.assert_called_once()

    def test_upload_error(self, mocker):
        p = _provider(mocker)
        mocker.patch(f"{dm_path}.exists", return_value=True)
        mocker.patch(f"{dm_path}.read_file_content", return_value="content")
        mocker.patch(f"{dm_path}.basename", return_value="f.txt")
        handler = mocker.patch(f"{dm_path}.handle_service_exception")
        p.device_sdk.device.create_file_upload_sas_uri.side_effect = _cloud_error(mocker)
        p.device_upload_file(file_path="f.txt", content_type="text/plain")
        handler.assert_called_once()


class TestHandleC2DMsg:
    def test_handle_complete(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "_c2d_message_receive", return_value={"etag": "e"})
        complete = mocker.patch.object(p, "c2d_message_complete")
        assert p._handle_c2d_msg("complete") is True
        complete.assert_called_once_with("e")

    def test_handle_reject(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "_c2d_message_receive", return_value={"etag": "e"})
        reject = mocker.patch.object(p, "c2d_message_reject")
        p._handle_c2d_msg("reject")
        reject.assert_called_once_with("e")

    def test_handle_abandon(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "_c2d_message_receive", return_value={"etag": "e"})
        abandon = mocker.patch.object(p, "c2d_message_abandon")
        p._handle_c2d_msg("abandon")
        abandon.assert_called_once_with("e")

    def test_handle_no_message(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "_c2d_message_receive", return_value=None)
        assert p._handle_c2d_msg("complete") is False


class TestSimulateDevice:
    def test_simulate_mqtt_invalid_settle(self, mocker):
        p = _provider(mocker)
        with pytest.raises(InvalidArgumentValueError):
            p.simulate_device(receive_settle="reject", protocol_type="mqtt")

    def test_simulate_bad_interval(self, mocker):
        p = _provider(mocker)
        with pytest.raises(InvalidArgumentValueError):
            p.simulate_device(protocol_type="mqtt", msg_interval=0)

    def test_simulate_bad_count(self, mocker):
        p = _provider(mocker)
        with pytest.raises(InvalidArgumentValueError):
            p.simulate_device(protocol_type="mqtt", msg_count=0)

    def test_simulate_http_method_response_code_error(self, mocker):
        p = _provider(mocker)
        with pytest.raises(ArgumentUsageError):
            p.simulate_device(protocol_type="http", method_response_code=200)

    def test_simulate_http_model_id_error(self, mocker):
        p = _provider(mocker)
        with pytest.raises(ArgumentUsageError):
            p.simulate_device(protocol_type="http", model_id="dtmi:com:ex;1")

    def test_simulate_http_method_response_payload_error(self, mocker):
        p = _provider(mocker)
        with pytest.raises(ArgumentUsageError):
            p.simulate_device(protocol_type="http", method_response_payload="{}")

    def test_simulate_http_init_reported_properties_error(self, mocker):
        p = _provider(mocker)
        with pytest.raises(ArgumentUsageError):
            p.simulate_device(protocol_type="http", init_reported_properties="{}")

    def test_simulate_http_x509_error(self, mocker):
        p = _provider(mocker)
        with pytest.raises(ArgumentUsageError):
            p.simulate_device(protocol_type="http", certificate_file="c.pem")

    def test_simulate_mqtt_success(self, mocker):
        p = _provider(mocker)
        mqtt_cls = mocker.patch("azext_iot.iothub.providers.mqtt.MQTTProvider")
        mocker.patch(f"{dm_path}._build_device_or_module_connection_string", return_value="cs")
        mocker.patch.object(p, "_d2c_get_device_auth_props", return_value={"authentication": {}})
        p.simulate_device(
            protocol_type="mqtt",
            msg_count=2,
            msg_interval=1,
            method_response_payload="{}",
            init_reported_properties="{}",
        )
        mqtt_cls.return_value.execute.assert_called_once()
        mqtt_cls.return_value.shutdown.assert_called_once()

    def test_simulate_http_success(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(p, "_d2c_get_device_auth_props", return_value={"authentication": {}})
        mocker.patch(f"{dm_path}.sleep")
        handle = mocker.patch.object(p, "_handle_c2d_msg")
        thread = mocker.patch("threading.Thread")
        thread.return_value.is_alive.side_effect = [True, False]
        p.simulate_device(protocol_type="http", msg_count=1, msg_interval=1, receive_settle="complete")
        thread.return_value.start.assert_called_once()
        handle.assert_called_once_with("complete")

    def test_simulate_internal_error(self, mocker):
        p = _provider(mocker)
        mocker.patch.object(
            p, "_d2c_get_device_auth_props", side_effect=ValueError("boom")
        )
        with pytest.raises(CLIInternalError):
            p.simulate_device(protocol_type="http", msg_count=1, msg_interval=1)


class TestSimulateDefaultProps:
    def test_mqtt(self):
        props = _simulate_get_default_properties(ProtocolType.mqtt.name)
        assert props["$.ct"] == "application/json"
        assert props["$.ce"] == "utf-8"

    def test_http(self):
        props = _simulate_get_default_properties("http")
        assert props["content-type"] == "application/json"
        assert props["content-encoding"] == "utf-8"


class TestCommandLayer:
    def test_iot_device_send_message(self, mocker):
        import azext_iot.iothub.commands_device_messaging as cmd_subject

        provider_cls = mocker.patch.object(cmd_subject, "DeviceMessagingProvider")
        instance = provider_cls.return_value
        result = cmd_subject.iot_device_send_message(cmd=mocker.MagicMock(), device_id="dev1")
        provider_cls.assert_called_once()
        instance.device_send_message.assert_called_once()
        assert result == instance.device_send_message.return_value

    def test_iot_c2d_message_send(self, mocker):
        import azext_iot.iothub.commands_device_messaging as cmd_subject

        provider_cls = mocker.patch.object(cmd_subject, "DeviceMessagingProvider")
        instance = provider_cls.return_value
        result = cmd_subject.iot_c2d_message_send(cmd=mocker.MagicMock(), device_id="dev1")
        provider_cls.assert_called_once()
        instance.c2d_message_send.assert_called_once()
        assert result == instance.c2d_message_send.return_value

    def test_iot_device_upload_file(self, mocker):
        import azext_iot.iothub.commands_device_messaging as cmd_subject

        provider_cls = mocker.patch.object(cmd_subject, "DeviceMessagingProvider")
        instance = provider_cls.return_value
        result = cmd_subject.iot_device_upload_file(
            cmd=mocker.MagicMock(),
            device_id="dev1",
            file_path="/tmp/f",
            content_type="text/plain",
        )
        provider_cls.assert_called_once()
        instance.device_upload_file.assert_called_once()
        assert result == instance.device_upload_file.return_value
