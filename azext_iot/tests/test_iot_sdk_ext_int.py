# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

# This style of testing is deprecated and will be replaced

try:
    from unittest.mock import MagicMock
    from unittest.mock import patch
except ImportError:
    from mock import MagicMock
    from mock import patch

import unittest
import os
import contextlib
import json
import uuid
from azext_iot import custom as subject


hub_cs = os.environ.get('iot_ext_hub_connstring')
hub_name = os.environ.get('iot_ext_hub_name')
device_cs = os.environ.get('iot_ext_device_connstring')
device_name = os.environ.get('iot_ext_device_name')

if not hub_cs:
    raise KeyError('Test setup failure missing {iot_ext_hub} env var')
if not hub_name:
    raise KeyError('Test setup failure missing {iot_ext_hub_name} env var')
if not device_cs:
    raise KeyError('Test setup failure missing {iot_ext_device_connstring} env var')
if not device_name:
    raise KeyError('Test setup failure missing {iot_ext_device_name} env var')


class HubMessageTests(unittest.TestCase):
    @patch('azext_iot.custom.iot_hub_show_connection_string')
    def test_hub_send(self, hub):
        hub.return_value = {'connectionString': hub_cs}
        subject.iot_hub_message_send(MagicMock(), device_name, hub_name,
                                     str(uuid.uuid4()), str(uuid.uuid4()))


class DeviceMessageTests(unittest.TestCase):
    @patch('azext_iot.custom._get_single_device_connection_string')
    def test_device_msg(self, device):
        device.return_value = device_cs
        for protocol in ['http', 'mqtt', 'amqp']:
            subject.iot_device_send_message_ext(MagicMock(), device_name, hub_name,
                                                protocol, 'msg data test with {}'.format(protocol),
                                                None, str(uuid.uuid4()))


class SimulationTests(unittest.TestCase):
    @patch('azext_iot.custom._get_single_device_connection_string')
    def test_device_sim(self, device):
        device.return_value = device_cs
        for protocol in ['http', 'amqp']:
            with open(os.devnull, "w") as f, contextlib.redirect_stdout(f):
                subject.iot_simulate_device(MagicMock(), device_name, hub_name,
                                            'complete', protocol, 'sim data test with {}'.format(protocol), 2)


if __name__ == '__main__':
    unittest.main()
