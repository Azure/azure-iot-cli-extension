# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=W0703

# This style of testing is deprecated and will be replaced in a future release

try:
    from unittest.mock import MagicMock
    from unittest.mock import patch
    from unittest.mock import mock_open
except ImportError:
    from mock import MagicMock
    from mock import patch
    from mock import mock_open

import unittest
import uuid
import os
import contextlib
from azext_iot import custom as subject
from azext_iot.iot_sdk.utility import Default_Msg_Callbacks
from azext_iot.iot_sdk.device_manager import (DeviceManager, IoTHubMessage, IoTHubMessageDispositionResult,
                                              IoTHubClientConfirmationResult)
from azure.cli.core.util import CLIError
from iothub_client import IoTHubClientError


json = '{\"properties\":{\"desired\":{\"Awesome\":1}}}'
device_name = 'device'
hub_name = 'hub'
connstring = 'HostName=abcd;SharedAccessKeyName=name;SharedAccessKey=value'


mock_target = {}
mock_target['cs'] = connstring
mock_target['hub'] = 'hub'
mock_target['primarykey'] = 'abcde'
mock_target['policy'] = 'iothubowner'


class HubMessageTests(unittest.TestCase):
    @patch('azext_iot.custom.get_iot_hub_connection_string')
    def test_hub_send(self, mock_hub):
        mock_hub.return_value = mock_target
        client = MagicMock()
        with patch.dict("sys.modules", iothub_service_client=client):
            subject.iot_hub_message_send(MagicMock(), device_name, hub_name,
                                         str(uuid.uuid4()), str(uuid.uuid4()))
            self.assertIs(client.IoTHubMessaging.return_value.open.call_count, 1)
            self.assertIs(client.IoTHubMessaging.return_value.send_async.call_count, 1)
            self.assertIs(client.IoTHubMessaging.return_value.close.call_count, 1)

    @patch('azext_iot.custom.get_iot_hub_connection_string')
    def test_hub_send_error(self, mock_hub):
        e = ValueError('errors')
        mock_hub.return_value = mock_target
        client = MagicMock(name='iothub_service_client')
        client.IoTHubMessaging.return_value.open.side_effect = e
        client.IoTHubError = ValueError
        with patch.dict("sys.modules", **{
                'iothub_service_client': client
                }):
            with self.assertRaises(CLIError):
                subject.iot_hub_message_send(MagicMock(), device_name, hub_name,
                                             str(uuid.uuid4()), str(uuid.uuid4()))


class DeviceMessageTests(unittest.TestCase):
    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.keep_alive')
    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_msg(self, mock_hub, mock_deviceclient, keepalive):
        txt_protocol = 'http'
        mock_hub.return_value = connstring
        keepalive.side_effect = [True, True, False]
        subject.iot_device_send_message_ext(MagicMock(), device_name, hub_name, txt_protocol,
                                            'data', None, str(uuid.uuid4()), str(uuid.uuid4()), 'user')
        protocol = subject._iot_sdk_device_process_protocol(txt_protocol)
        mock_deviceclient.assert_called_with(connstring, protocol)

    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.keep_alive')
    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.get_errors')
    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_msg_runtime_error(self, mock_hub, mock_deviceclient, gerrors, keepalive):
        txt_protocol = 'amqp'
        mock_hub.return_value = connstring
        keepalive.side_effect = [True, True, False]
        gerrors.receive_value = 'errors'
        with self.assertRaises(CLIError):
            subject.iot_device_send_message_ext(MagicMock(), device_name, hub_name, txt_protocol)
            protocol = subject._iot_sdk_device_process_protocol(txt_protocol)
            mock_deviceclient.assert_called_with(connstring, protocol)

    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.send_event')
    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_msg_sdk_error(self, mock_hub, mock_deviceclient, mock_send):
        txt_protocol = 'mqtt'
        mock_hub.return_value = connstring
        e = IoTHubClientError('errors')
        mock_send.side_effect = e
        with self.assertRaises(CLIError):
            subject.iot_device_send_message_ext(MagicMock(), device_name, hub_name, txt_protocol)
            protocol = subject._iot_sdk_device_process_protocol(txt_protocol)
            mock_deviceclient.assert_called_with(connstring, protocol)

    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_msg_invalid_protocol_error(self, mock_hub, mock_deviceclient):
        txt_protocol = 'protocol'
        mock_hub.return_value = connstring
        with self.assertRaises(ValueError):
            subject.iot_device_send_message_ext(MagicMock(), device_name, hub_name, txt_protocol)
            protocol = subject._iot_sdk_device_process_protocol(txt_protocol)
            mock_deviceclient.assert_called_with(connstring, protocol)


class SimulationTests(unittest.TestCase):
    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.received')
    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.keep_alive')
    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_sim(self, mock_hub, mock_deviceclient, keepalive, received):
        txt_protocol = 'amqp'
        txt_settle = 'complete'
        expected_msgs = 3
        receive_count = 2
        mock_hub.return_value = connstring
        keepalive.return_value = False
        mock_deviceclient.return_value.send_event_async.return_value = True
        received.side_effect = [0, 1, 2]
        mo = mock_open()
        with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
            with patch('azext_iot.iot_sdk.device_manager.open', mo, create=True):
                subject.iot_simulate_device(MagicMock(), device_name, hub_name, txt_settle, txt_protocol,
                                            'data', expected_msgs, 1, receive_count, 'path')
                protocol = subject._iot_sdk_device_process_protocol(txt_protocol)
                mock_deviceclient.assert_called_with(connstring, protocol)
                self.assertIs(mock_deviceclient.return_value.send_event_async.call_count, expected_msgs)
                self.assertIs(received.call_count, receive_count + 1)

    @patch('azext_iot.iot_sdk.device_manager.DeviceManager.send_event')
    @patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
    @patch('azext_iot.custom._build_device_connection_string')
    def test_device_sim_error(self, mock_hub, mock_deviceclient, mock_send):
        txt_protocol = 'amqp'
        txt_settle = 'reject'
        expected_msgs = 3
        receive_count = 2
        mock_hub.return_value = connstring
        mock_deviceclient.return_value.send_event_async.return_value = True
        e = RuntimeError('errors')
        mock_send.side_effect = e
        with self.assertRaises(CLIError):
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                subject.iot_simulate_device(MagicMock(), device_name, hub_name, txt_settle, txt_protocol,
                                            'data', expected_msgs, 1, receive_count)


@patch('azext_iot.custom.get_iot_hub_connection_string')
@patch('azext_iot.custom.SasTokenAuthentication.generate_sas_token')
class SasTokenTests(unittest.TestCase):
    def test_generate_token(self, mock_sas_provider, mock_ihpg):
        # Format from the actual SasTokenAuthentication.generate_sas_token
        mock_sas = (
            'SharedAccessSignature sr={0}.azure-devices.net%252fdevices%252f{1}&'
            'sig=52u8jNpJyHr8USSNSTiA1MWlUFVu0xdWA76XGyzMjVi'
            '%3D&se={2}&skn={3}'
            )
        mock_sas = mock_sas.format(hub_name, device_name, '3600', 'policy')
        mock_sas_provider.return_value = mock_sas
        result = subject.iot_get_sas_token(MagicMock(), device_name, hub_name, 'policy', 3600, None)
        self.assertIsNotNone(result)
        self.assertEqual(result, mock_sas)


@patch('azext_iot.iot_sdk.device_manager.IoTHubClient')
class DeviceManagerCallbackTests(unittest.TestCase):
    def test_upload_file_to_blob_result_callback(self, mock_deviceclient):
        device = DeviceManager('cs')
        try:
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                device.upload_file_to_blob_result_callback('success', 'context')
        except Exception as e:
            self.fail('test_upload_file_to_blob_result_callback exception: {}'.format(e))

    def test_receive_message_callback(self, mock_deviceclient):
        device = DeviceManager('cs')
        try:
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                msg = IoTHubMessage(bytearray('data', 'utf8'))
                device.configure_receive_settle('abandon')
                result = device.receive_message_callback(msg, 'context')
                device.receive_message_callback(msg, 'context')
                self.assertIs(result, IoTHubMessageDispositionResult.ABANDONED)
                self.assertIs(device.received(), 2)
        except Exception as e:
            self.fail('test_receive_message_callback exception: {}'.format(e))

    def test_send_event_result_callback(self, mock_deviceclient):
        device = DeviceManager('cs')
        try:
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                msg = IoTHubMessage(bytearray('data', 'utf8'))
                device.send_event_result_callback(msg, IoTHubClientConfirmationResult.OK, 0)
                self.assertFalse(device.keep_alive('msg'))
        except Exception as e:
            self.fail('test_send_event_result_callback exception: {}'.format(e))

    def test_error_send_event_result_callback(self, mock_deviceclient):
        device = DeviceManager('cs')
        with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
            msg = IoTHubMessage(bytearray('data', 'utf8'))
            device.send_event_result_callback(msg, IoTHubClientConfirmationResult.ERROR, 0)
            self.assertFalse(device.keep_alive('msg'))
            self.assertIsNotNone(device.get_errors('msg'))


class UtilityCallbackTests(unittest.TestCase):
    def test_hub_default_callback(self):
        try:
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                fake_records = [{'key0': 'value0'}, {'key1': 'value1'}]
                dmc = Default_Msg_Callbacks()
                dmc.feedback_received_callback(0, 1234, 4321, fake_records)
        except Exception as e:
            self.fail('test_hub_default_callback exception: {}'.format(e))


if __name__ == '__main__':
    unittest.main()
