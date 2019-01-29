# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements,wrong-import-position,too-many-lines,import-error

import os
import random
import json
import pytest
import sys

from uuid import uuid4
from azure.cli.testsdk import LiveScenarioTest
from azure.cli.core.util import read_file_content
from azext_iot.common.utility import validate_min_python_version, execute_onthread, calculate_millisec_since_unix_epoch_utc

# Add test tools to path
sys.path.append(os.path.abspath(os.path.join('.', 'iotext_test_tools')))

# Set these to the proper IoT Hub, IoT Hub Cstring and Resource Group for Live Integration Tests.
LIVE_HUB = os.environ.get('azext_iot_testhub')
LIVE_RG = os.environ.get('azext_iot_testrg')
LIVE_HUB_CS = os.environ.get('azext_iot_testhub_cs')

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE = os.environ.get('azext_iot_teststorageuri')
LIVE_CONSUMER_GROUPS = ['test1', 'test2', 'test3']

if not all([LIVE_HUB, LIVE_HUB_CS, LIVE_RG]):
    raise ValueError('Set azext_iot_testhub, azext_iot_testhub_cs and azext_iot_testrg to run IoT Hub integration tests.')

CWD = os.path.dirname(os.path.abspath(__file__))

PRIMARY_THUMBPRINT = 'A361EA6A7119A8B0B7BBFFA2EAFDAD1F9D5BED8C'
SECONDARY_THUMBPRINT = '14963E8F3BA5B3984110B3C1CA8E8B8988599087'

DEVICE_PREFIX = 'test-device-'


class TestIoTHub(LiveScenarioTest):
    def __init__(self, _):
        from iotext_test_tools import DummyCliOutputProducer
        super(TestIoTHub, self).__init__(_)
        self.cli_ctx = DummyCliOutputProducer()

    def setUp(self):
        self._entity_names = None

    # TODO: @digimaun - Maybe put a helper like this in the shared lib, when you create it?
    def command_execute_assert(self, command, asserts):
        from iotext_test_tools import capture_output

        with capture_output() as buffer:
            self.cmd(command, checks=None)
            output = buffer.get_output()

        for a in asserts:
            assert a in output

    def _create_entity_names(self, devices=0, edge_devices=0, modules=0, configs=0):
        result = {}
        if devices:
            device_ids = []
            for _ in range(devices):
                device_ids.append(self.create_random_name(prefix=DEVICE_PREFIX, length=32))
            result['device_ids'] = device_ids

        if edge_devices:
            edge_device_ids = []
            for _ in range(edge_devices):
                edge_device_ids.append(self.create_random_name(prefix='test-edge-device-', length=32))
            result['edge_device_ids'] = edge_device_ids

        if modules:
            module_ids = []
            for _ in range(modules):
                module_ids.append(self.create_random_name(prefix='test-module-', length=32))
            result['module_ids'] = module_ids

        if configs:
            config_ids = []
            for _ in range(configs):
                config_ids.append(self.create_random_name(prefix='test-config-', length=32))
            result['config_ids'] = config_ids

        self._entity_names = result
        return result

    def _remove_entities(self, names=None):
        if not names:
            names = self._entity_names
            self._entity_names = None

        device_ids = names.get('device_ids')
        if not device_ids:
            device_ids = []
        edge_device_ids = names.get('edge_device_ids')
        if edge_device_ids:
            device_ids.extend(edge_device_ids)

        for i in device_ids:
            if device_ids.index(i) == (len(device_ids) - 1):
                # With connection string
                self.cmd('iot hub device-identity delete -d {} --login {}'
                         .format(i, LIVE_HUB_CS), checks=self.is_empty())
            else:
                self.cmd('iot hub device-identity delete -d {} -n {} -g {}'
                         .format(i, LIVE_HUB, LIVE_RG), checks=self.is_empty())

        config_ids = names.get('config_ids')
        if config_ids:
            for i in config_ids:
                if config_ids.index(i) == (len(config_ids) - 1):
                    # With connection string
                    self.cmd('iot hub configuration delete -c {} --login {}'
                             .format(i, LIVE_HUB_CS), checks=self.is_empty())
                else:
                    self.cmd('iot hub configuration delete -c {} -n {} -g {}'
                             .format(i, LIVE_HUB, LIVE_RG), checks=self.is_empty())

    def tearDown(self):
        if self._entity_names:
            self._remove_entities()

    def test_hub(self):
        hub_policy = "iothubowner"

        hub_conn_str_pattern = r'^HostName={}\.azure-devices\.net;SharedAccessKeyName={};SharedAccessKey='.format(
            LIVE_HUB, hub_policy)

        self.cmd('iot hub show-connection-string -n {} -g {}'.format(LIVE_HUB, LIVE_RG), checks=[
            self.check_pattern('cs', hub_conn_str_pattern)
        ])
        self.cmd('iot hub show-connection-string -n {} -g {} --kt {}'.format(LIVE_HUB, LIVE_RG, 'secondary'), checks=[
            self.check_pattern('cs', hub_conn_str_pattern)
        ])
        self.cmd('iot hub show-connection-string -n {} -g {} --kt {} --pn doesnotexist'.format(LIVE_HUB, LIVE_RG, 'secondary'),
                 expect_failure=True)

        self.cmd('az iot hub generate-sas-token -n {} -g {}'.format(LIVE_HUB, LIVE_RG), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token -n {}'.format(LIVE_HUB), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token -n {} --du {}'.format(LIVE_HUB, '1000'), checks=[
            self.exists('sas')
        ])

        # With connection string
        self.cmd('az iot hub generate-sas-token --login {}'.format(LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token --login {} --pn somepolicy'.format(LIVE_HUB_CS), expect_failure=True)

        # With connection string
        # Error can't change key for a sas token with conn string
        self.cmd('az iot hub generate-sas-token --login {} --kt secondary'.format(LIVE_HUB_CS), expect_failure=True)

        self.cmd('iot hub query --hub-name {} -q "{}"'.format(LIVE_HUB, "select * from devices"),
                 checks=[self.check('length([*])', 0)])

        # With connection string
        self.cmd('iot hub query --query-command "{}" --login {}'.format("select * from devices", LIVE_HUB_CS),
                 checks=[self.check('length([*])', 0)])

        # Test mode 2 handler
        self.cmd('iot hub query -q "{}"'.format("select * from devices"), expect_failure=True)

        self.cmd('iot hub query -q "{}" -l "{}"'.format("select * from devices", 'Hostname=badlogin;key=1235'),
                 expect_failure=True)

    def test_hub_devices(self):
        device_count = 3
        edge_device_count = 2

        names = self._create_entity_names(devices=device_count, edge_devices=edge_device_count)
        device_ids = names['device_ids']
        edge_device_ids = names['edge_device_ids']

        for i in range(edge_device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(edge_device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', edge_device_ids[i]),
                             self.check('status', 'enabled'),
                             self.check('statusReason', None),
                             self.check('connectionState', 'Disconnected'),
                             self.check('capabilities.iotEdge', True),
                             self.exists('authentication.symmetricKey.primaryKey'),
                             self.exists('authentication.symmetricKey.secondaryKey')])

        query_checks = [self.check('length([*])', edge_device_count)]
        for i in range(edge_device_count):
            query_checks.append(self.exists('[?deviceId==`{}`]'.format(edge_device_ids[i])))

        # Not currently supported
        self.cmd('iot hub device-identity create -d {} -n {} -g {} --auth-method x509_thumbprint --ee'.format(
            'willnotwork', LIVE_HUB, LIVE_RG), expect_failure=True)

        # Not currently supported
        self.cmd('iot hub device-identity create -d {} -n {} -g {} --auth-method x509_ca --ee'.format(
            'willnotwork', LIVE_HUB, LIVE_RG), expect_failure=True)

        self.cmd('iot hub query --hub-name {} -g {} -q "{}"'.format(LIVE_HUB, LIVE_RG, "select * from devices"),
                 checks=query_checks)

        # With connection string
        self.cmd('iot hub query -q "{}" --login {}'.format("select * from devices", LIVE_HUB_CS),
                 checks=query_checks)

        self.cmd('iot hub query -q "{}" --login {} --top -1'.format("select * from devices", LIVE_HUB_CS),
                 checks=query_checks)

        self.cmd('''iot hub device-identity create --device-id {} --hub-name {} --resource-group {}
                    --auth-method x509_thumbprint --primary-thumbprint {} --secondary-thumbprint {}'''
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, PRIMARY_THUMBPRINT, SECONDARY_THUMBPRINT),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('capabilities.iotEdge', False),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.check(
                             'authentication.x509Thumbprint.primaryThumbprint', PRIMARY_THUMBPRINT),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', SECONDARY_THUMBPRINT)])

        self.cmd('''iot hub device-identity create --device-id {} --hub-name {} --resource-group {}
                    --auth-method x509_thumbprint --valid-days {}'''
                 .format(device_ids[1], LIVE_HUB, LIVE_RG, 10),
                 checks=[self.check('deviceId', device_ids[1]),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('capabilities.iotEdge', False),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.exists('authentication.x509Thumbprint.primaryThumbprint'),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', None)])

        # With connection string
        status_reason = "Test Status Reason"
        self.cmd('''iot hub device-identity create --device-id {} --login {}
                    --auth-method x509_ca --status disabled --status-reason "{}"'''
                 .format(device_ids[2], LIVE_HUB_CS, status_reason),
                 checks=[self.check('deviceId', device_ids[2]),
                         self.check('status', 'disabled'),
                         self.check('statusReason', status_reason),
                         self.check('capabilities.iotEdge', False),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.check(
                             'authentication.x509Thumbprint.primaryThumbprint', None),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', None)])

        self.cmd('iot hub device-identity show -d {} -n {} -g {}'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('connectionState', 'Disconnected'),
                         self.check('capabilities.iotEdge', True),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('iot hub device-identity show -d {} --login {}'.format(edge_device_ids[0], LIVE_HUB_CS),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('connectionState', 'Disconnected'),
                         self.check('capabilities.iotEdge', True),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub device-identity list --hub-name {} --resource-group {}'.format(LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', device_count + edge_device_count)])

        self.cmd('iot hub device-identity list --hub-name {} --resource-group {} --top -1'.format(LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', device_count + edge_device_count)])

        self.cmd('iot hub device-identity list -n {} -g {} --ee'.format(LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', edge_device_count)])

        # With connection string
        self.cmd('iot hub device-identity list --ee --login {}'.format(LIVE_HUB_CS),
                 checks=[self.check('length([*])', edge_device_count)])

        self.cmd('iot hub device-identity update -d {} -n {} -g {} --set capabilities.iotEdge={}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, True),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('status', 'enabled'),
                         self.check('capabilities.iotEdge', True),
                         self.check('authentication.symmetricKey.primaryKey', None),
                         self.check('authentication.symmetricKey.secondaryKey', None),
                         self.check('authentication.x509Thumbprint.primaryThumbprint', PRIMARY_THUMBPRINT),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', SECONDARY_THUMBPRINT)])

        self.cmd('''iot hub device-identity update -d {} -n {} -g {} --set authentication.symmetricKey.primaryKey=""
                    authentication.symmetricKey.secondaryKey=""'''
                 .format(edge_device_ids[1], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', edge_device_ids[1]),
                         self.check('status', 'enabled'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('''iot hub device-identity update -d {} --login {} --set authentication.symmetricKey.primaryKey=""
                 authentication.symmetricKey.secondaryKey=""'''
                 .format(edge_device_ids[1], LIVE_HUB_CS),
                 checks=[self.check('deviceId', edge_device_ids[1]),
                         self.check('status', 'enabled'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};SharedAccessKey='.format(
            LIVE_HUB, edge_device_ids[0])
        cer_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};x509=true'.format(
            LIVE_HUB, device_ids[2])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check_pattern('cs', sym_conn_str_pattern)])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {} --kt {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, 'secondary'),
                 checks=[self.check_pattern('cs', sym_conn_str_pattern)])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'
                 .format(device_ids[2], LIVE_HUB, LIVE_RG),
                 checks=[self.check_pattern('cs', cer_conn_str_pattern)])

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {}'.format(LIVE_HUB, LIVE_RG, edge_device_ids[0]), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {} --du {}'.format(LIVE_HUB, LIVE_RG, edge_device_ids[0], '1000'),
                 checks=[self.exists('sas')])

        # None SAS device auth
        self.cmd('iot hub generate-sas-token -n {} -g {} -d {}'.format(LIVE_HUB, LIVE_RG, device_ids[1]), expect_failure=True)

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {} --kt "secondary"'.format(LIVE_HUB, LIVE_RG, edge_device_ids[1]),
                 checks=[self.exists('sas')])

        # With connection string
        self.cmd('iot hub generate-sas-token -d {} --login {}'.format(edge_device_ids[0], LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -d {} --login {} --kt "secondary"'.format(edge_device_ids[1], LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -d {} --login {} --pn "mypolicy"'.format(edge_device_ids[1], LIVE_HUB_CS),
                 expect_failure=True)

    def test_hub_apply_device_content(self):
        edge_device_count = 2
        names = self._create_entity_names(edge_devices=edge_device_count)
        edge_device_ids = names['edge_device_ids']

        for device_id in edge_device_ids:
            self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(device_id, LIVE_HUB, LIVE_RG))

        content_path = os.path.join(CWD, 'test_config_modules_content.json')
        content_path_v1 = os.path.join(CWD, 'test_config_modules_content_v1.json')

        self.kwargs['generic_content'] = read_file_content(content_path)

        self.cmd("iot hub apply-configuration -d {} -n {} -g {} -k '{}'"
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, content_path), checks=[self.check('length([*])', 3)])

        self.cmd("iot hub apply-configuration -d {} -n {} -g {} --content '{}'"
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, '{generic_content}'), self.check('length([*])', 3))

        # With connection string
        self.cmd("iot hub apply-configuration -d {} --login {} -k '{}'"
                 .format(edge_device_ids[0], LIVE_HUB_CS, content_path_v1), checks=[self.check('length([*])', 4)])

        # iot edge set-modules replaces apply-configuration
        self.cmd("iot edge set-modules -d {} -n {} -g {} -k '{}'"
                 .format(edge_device_ids[1], LIVE_HUB, LIVE_RG, content_path), checks=[self.check('length([*])', 3)])

        self.cmd("iot edge set-modules -d {} -n {} -g {} --content '{}'"
                 .format(edge_device_ids[1], LIVE_HUB, LIVE_RG, '{generic_content}'), self.check('length([*])', 3))

        # With connection string
        self.cmd("iot edge set-modules -d {} --login {} -k '{}'"
                 .format(edge_device_ids[1], LIVE_HUB_CS, content_path_v1), checks=[self.check('length([*])', 4)])

    def test_hub_device_twins(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
        self.kwargs['bad_format'] = "{'key: 'value'}"
        device_count = 2

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        for i in range(device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', device_ids[i])])

        self.cmd('iot hub device-twin show -d {} -n {} -g {}'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('status', 'enabled'),
                         self.exists('properties.desired'),
                         self.exists('properties.reported')])

        # With connection string
        self.cmd('iot hub device-twin show -d {} --login {}'.format(device_ids[0], LIVE_HUB_CS),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('status', 'enabled'),
                         self.exists('properties.desired'),
                         self.exists('properties.reported')])

        result = self.cmd('iot hub device-twin update -d {} -n {} -g {} --set properties.desired.special={}'
                          .format(device_ids[0], LIVE_HUB, LIVE_RG, '"{generic_dict}"')).get_output_in_json()
        assert result['deviceId'] == device_ids[0]
        assert result['properties']['desired']['special']['key'] == 'value'

        result = self.cmd('iot hub device-twin update -d {} -n {} -g {} --set properties.desired.special="null"'
                          .format(device_ids[0], LIVE_HUB, LIVE_RG)).get_output_in_json()
        assert result['deviceId'] == device_ids[0]
        assert result['properties']['desired'].get('special') is None

        # With connection string
        result = self.cmd('iot hub device-twin update -d {} --login {} --set properties.desired.special={}'
                          .format(device_ids[0], LIVE_HUB_CS, '"{generic_dict}"')).get_output_in_json()
        assert result['deviceId'] == device_ids[0]
        assert result['properties']['desired']['special']['key'] == 'value'

        # Error case, test type enforcer
        self.cmd('iot hub device-twin update -d {} -n {} -g {} --set tags={}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, '"{bad_format}"'),
                 expect_failure=True)

        content_path = os.path.join(CWD, 'test_generic_replace.json')
        self.cmd("iot hub device-twin replace -d {} -n {} -g {} -j '{}'"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, content_path),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        self.kwargs['twin_payload'] = read_file_content(content_path)
        self.cmd("iot hub device-twin replace -d {} -n {} -g {} -j '{}'"
                 .format(device_ids[1], LIVE_HUB, LIVE_RG, '{twin_payload}'),
                 checks=[self.check('deviceId', device_ids[1]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        # With connection string
        self.cmd("iot hub device-twin replace -d {} --login {} -j '{}'"
                 .format(device_ids[1], LIVE_HUB_CS, '{twin_payload}'),
                 checks=[self.check('deviceId', device_ids[1]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

    def test_hub_modules(self):
        edge_device_count = 2
        device_count = 1
        module_count = 2

        names = self._create_entity_names(edge_devices=edge_device_count, devices=device_count, modules=module_count)
        edge_device_ids = names['edge_device_ids']
        module_ids = names['module_ids']
        device_ids = names['device_ids']

        for edge_device in edge_device_ids:
            self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(edge_device, LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', edge_device)])

        self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        # Symmetric Key
        # With connection string
        self.cmd('iot hub module-identity create --device-id {} --hub-name {} --resource-group {} --module-id {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[1]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[1]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity create -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # Error can't get a sas token for module without device
        self.cmd('az iot hub generate-sas-token -n {} -g {} -m {}'
                 .format(LIVE_HUB, LIVE_RG, module_ids[1]), expect_failure=True)

        # sas token for module
        self.cmd('iot hub generate-sas-token -n {} -g {} -d {} -m {}'
                 .format(LIVE_HUB, LIVE_RG, edge_device_ids[0], module_ids[1]),
                 checks=[self.exists('sas')])

        # X509 Thumbprint
        # With connection string
        self.cmd('''iot hub module-identity create --module-id {} --device-id {} --login {}
                    --auth-method x509_thumbprint --primary-thumbprint {} --secondary-thumbprint {}'''
                 .format(module_ids[0], device_ids[0], LIVE_HUB_CS, PRIMARY_THUMBPRINT, SECONDARY_THUMBPRINT),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.check(
                             'authentication.x509Thumbprint.primaryThumbprint', PRIMARY_THUMBPRINT),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', SECONDARY_THUMBPRINT)])

        self.cmd('''iot hub module-identity create -m {} -d {} -n {} -g {} --am x509_thumbprint --vd {}'''
                 .format(module_ids[1], device_ids[0], LIVE_HUB, LIVE_RG, 10),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('moduleId', module_ids[1]),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.exists('authentication.x509Thumbprint.primaryThumbprint'),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', None)])

        # X509 CA
        # With connection string
        self.cmd('''iot hub module-identity create --module-id {} --device-id {} --login {} --auth-method x509_ca'''
                 .format(module_ids[0], edge_device_ids[1], LIVE_HUB_CS),
                 checks=[self.check('deviceId', edge_device_ids[1]),
                         self.check('moduleId', module_ids[0]),
                         self.check('connectionState', 'Disconnected'),
                         self.check('authentication.symmetricKey.primaryKey', None),
                         self.check('authentication.symmetricKey.secondaryKey', None),
                         self.check('authentication.x509Thumbprint.primaryThumbprint', None),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', None)])

        # Includes $edgeAgent && $edgeHub system modules
        result = self.cmd('iot hub query --hub-name {} -g {} -q "{}"'
                          .format(LIVE_HUB, LIVE_RG, "select * from devices.modules where devices.deviceId='{}'"
                                  .format(edge_device_ids[0]))).get_output_in_json()
        assert len(result) == 4

        self.cmd('''iot hub module-identity update -d {} -n {} -g {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('''iot hub module-identity update -d {} --login {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity list -d {} -n {} -g {}'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', 4),
                         self.exists("[?moduleId=='$edgeAgent']"),
                         self.exists("[?moduleId=='$edgeHub']")])

        self.cmd('iot hub module-identity list -d {} -n {} -g {} --top -1'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', 4),
                         self.exists("[?moduleId=='$edgeAgent']"),
                         self.exists("[?moduleId=='$edgeHub']")])

        # With connection string
        self.cmd('iot hub module-identity list -d {} --login {}'.format(edge_device_ids[0], LIVE_HUB_CS),
                 checks=[self.check('length([*])', 4),
                         self.exists("[?moduleId=='$edgeAgent']"),
                         self.exists("[?moduleId=='$edgeHub']")])

        self.cmd('iot hub module-identity show -d {} -n {} -g {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[
                     self.check('deviceId', edge_device_ids[0]),
                     self.check('moduleId', module_ids[0]),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('iot hub module-identity show -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[
                     self.check('deviceId', edge_device_ids[0]),
                     self.check('moduleId', module_ids[0]),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

        mod_sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};ModuleId={};SharedAccessKey='.format(
            LIVE_HUB, edge_device_ids[0], module_ids[0])
        self.cmd('iot hub module-identity show-connection-string -d {} -n {} -g {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check_pattern('cs', mod_sym_conn_str_pattern)])

        # With connection string
        self.cmd('iot hub module-identity show-connection-string -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check_pattern('cs', mod_sym_conn_str_pattern)])

        self.cmd('iot hub module-identity show-connection-string -d {} -n {} -g {} -m {} --kt {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], "secondary"),
                 checks=[self.check_pattern('cs', mod_sym_conn_str_pattern)])

        for i in module_ids:
            if module_ids.index(i) == (len(module_ids) - 1):
                # With connection string
                self.cmd('iot hub module-identity delete -d {} --login {} --module-id {}'
                         .format(edge_device_ids[0], LIVE_HUB_CS, i), checks=self.is_empty())
            else:
                self.cmd('iot hub module-identity delete -d {} -n {} -g {} --module-id {}'
                         .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, i), checks=self.is_empty())

    def test_hub_module_twins(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
        self.kwargs['bad_format'] = "{'key: 'value'}"
        edge_device_count = 1
        device_count = 1
        module_count = 1

        names = self._create_entity_names(edge_devices=edge_device_count, modules=module_count, devices=device_count)
        edge_device_ids = names['edge_device_ids']
        module_ids = names['module_ids']
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', edge_device_ids[0])])

        self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        self.cmd('iot hub module-identity create -d {} -n {} -g {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity create -d {} -n {} -g {} -m {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-twin show -d {} -n {} -g {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('properties.desired'),
                         self.exists('properties.reported')])

        # With connection string
        self.cmd('iot hub module-twin show -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.exists('properties.desired'),
                         self.exists('properties.reported')])

        self.cmd('iot hub module-twin update -d {} -n {} -g {} -m {} --set properties.desired.special={}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], '"{generic_dict}"'),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('properties.desired.special.key', 'value')])

        # With connection string
        self.cmd('iot hub module-twin update -d {} --login {} -m {} --set properties.desired.special={}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{generic_dict}"'),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('properties.desired.special.key', 'value')])

        # Error case test type enforcer
        self.cmd('iot hub module-twin update -d {} --login {} -m {} --set properties.desired={}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{bad_format}"'), expect_failure=True)

        self.cmd('iot hub module-twin update -d {} --login {} -m {} --set tags={}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0], '"{bad_format}"'), expect_failure=True)

        content_path = os.path.join(CWD, 'test_generic_replace.json')
        self.cmd("iot hub module-twin replace -d {} -n {} -g {} -m {} -j '{}'"
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], content_path),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        # With connection string
        self.cmd("iot hub module-twin replace -d {} --login {} -m {} -j '{}'"
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0], content_path),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        self.kwargs['twin_payload'] = read_file_content(content_path)
        self.cmd("iot hub module-twin replace -d {} -n {} -g {} -m {} -j '{}'"
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0], '{twin_payload}'),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        for i in module_ids:
            self.cmd('iot hub module-identity delete -d {} -n {} -g {} --module-id {}'
                     .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, i), checks=self.is_empty())

    def test_device_configurations(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
        self.kwargs['bad_format'] = "{'key: 'value'}"
        config_count = 5
        names = self._create_entity_names(configs=config_count)
        config_ids = names['config_ids']

        content_path = os.path.join(CWD, 'test_config_device_content.json')
        metrics_path = os.path.join(CWD, 'test_config_device_metrics.json')

        self.kwargs['configuration_payload'] = read_file_content(content_path)
        self.kwargs['metrics_payload'] = read_file_content(metrics_path)

        priority = random.randint(1, 10)
        condition = 'tags.building=9 and tags.environment=\'test\''
        empty_metrics = {'queries': {}, 'results': {}}

        # With connection string
        self.cmd("iot hub configuration create -c {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}'"
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict}"', content_path),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.deviceContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['deviceContent']),
                     self.check('metrics', empty_metrics)])

        self.cmd("""iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'"""
                 .format(config_ids[1], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict}"', '{configuration_payload}'),
                 checks=[
                     self.check('id', config_ids[1]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.deviceContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['deviceContent']),
                     self.check('metrics', empty_metrics)])

        # With connection string
        self.cmd("iot hub configuration create -c {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}' -m '{}'"
                 .format(config_ids[2], LIVE_HUB_CS, priority, condition, '"{generic_dict}"', content_path, metrics_path),
                 checks=[
                     self.check('id', config_ids[2]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.deviceContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['deviceContent']),
                     self.check('metrics.queries', json.loads(self.kwargs['metrics_payload'])['queries'])])

        self.cmd("""iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}' --metrics '{}'"""
                 .format(config_ids[3], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict}"',
                         '{configuration_payload}', '{metrics_payload}'),
                 checks=[
                     self.check('id', config_ids[3]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.deviceContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['deviceContent']),
                     self.check('metrics.queries', json.loads(self.kwargs['metrics_payload'])['queries'])])

        self.cmd("""iot hub configuration create --config-id {} --hub-name {} --resource-group {} --priority {}
                 --content '{}' """
                 .format(config_ids[4], LIVE_HUB, LIVE_RG, priority, '{configuration_payload}'),
                 checks=[
                     self.check('id', config_ids[4]),
                     self.check('priority', priority),
                     self.check('targetCondition', ''),
                     self.check('content.deviceContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['deviceContent'])])

        # With connection string
        self.cmd('iot hub configuration show -c {} --login {}'.format(config_ids[0], LIVE_HUB_CS),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('metrics', empty_metrics)])

        self.cmd('iot hub configuration show -c {} --login {}'.format(config_ids[3], LIVE_HUB_CS),
                 checks=[
                     self.check('id', config_ids[3]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('metrics.queries', json.loads(self.kwargs['metrics_payload'])['queries'])])

        self.cmd('iot hub configuration show --config-id {} --hub-name {} --resource-group {}'.format(config_ids[2],
                                                                                                      LIVE_HUB, LIVE_RG),
                 checks=[
                     self.check('id', config_ids[2]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('metrics.queries', json.loads(self.kwargs['metrics_payload'])['queries'])])

        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs['generic_dict_updated'] = {'key': 'super_value'}
        self.cmd('iot hub configuration update -c {} -n {} -g {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        # With connection string
        self.cmd('iot hub configuration update -c {} --login {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        # Error via type enforcer
        self.cmd('iot hub configuration update -c {} --login {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{bad_format}"'), expect_failure=True)

        self.cmd('iot hub configuration update -c {} --login {} --set content={}'
                 .format(config_ids[0], LIVE_HUB_CS, '"{bad_format}"'), expect_failure=True)

        # Metrics
        user_metric_name = 'mymetric'
        system_metric_name = 'appliedCount'
        config_output = self.cmd('iot hub configuration show --login {} --config-id {}'.format(
            LIVE_HUB_CS, config_ids[2])).get_output_in_json()

        self.cmd('iot hub configuration show-metric --metric-id {} --login {} --config-id {} --metric-type {}'
                 .format(user_metric_name, LIVE_HUB_CS, config_ids[2], 'user'),
                 checks=[
                     self.check('metric', user_metric_name),
                     self.check('query', config_output['metrics']['queries'][user_metric_name])
                 ])

        # With connection string
        self.cmd('iot hub configuration show-metric -m {} --login {} -c {} --metric-type {}'
                 .format('doesnotexist', LIVE_HUB_CS, config_ids[2], 'user'), expect_failure=True)

        self.cmd('iot hub configuration show-metric -m {} --login {} -c {} --metric-type {}'
                 .format(system_metric_name, LIVE_HUB_CS, config_ids[2], 'system'),
                 checks=[
                     self.check('metric', system_metric_name),
                     self.check('query', config_output['systemMetrics']['queries'][system_metric_name])
                 ])

        config_list_check = [
            self.check('length([*])', 5),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2])),
            self.exists("[?id=='{}']".format(config_ids[3])),
            self.exists("[?id=='{}']".format(config_ids[4]))
        ]

        self.cmd("iot hub configuration list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
                 checks=config_list_check)

        # With connection string
        self.cmd("iot hub configuration list --login {}".format(LIVE_HUB_CS),
                 checks=config_list_check)

        # Error top of -1 does not work with configurations
        self.cmd("iot hub configuration list -n {} -g {} --top -1".format(LIVE_HUB, LIVE_RG), expect_failure=True)

        # Error max top of 20 with configurations
        self.cmd("iot hub configuration list -n {} -g {} --top 100".format(LIVE_HUB, LIVE_RG), expect_failure=True)

    def test_edge_deployments(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
        config_count = 3
        names = self._create_entity_names(configs=config_count)
        config_ids = names['config_ids']

        content_path = os.path.join(CWD, 'test_config_modules_content.json')
        content_path_v1 = os.path.join(CWD, 'test_config_modules_content_v1.json')

        self.kwargs['configuration_payload'] = read_file_content(content_path)
        self.kwargs['configuration_payload_v1'] = read_file_content(content_path_v1)

        priority = random.randint(1, 10)
        condition = 'tags.building=9 and tags.environment=\'test\''

        # With connection string
        self.cmd("iot edge deployment create -d {} --login {} --pri {} --tc \"{}\" --lab {} -k '{}'"
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict}"', content_path),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.modulesContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['modulesContent'])])

        self.cmd("""iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'"""
                 .format(config_ids[1], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict}"', '{configuration_payload}'),
                 checks=[
                     self.check('id', config_ids[1]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.modulesContent', json.loads(
                         self.kwargs['configuration_payload'])['content']['modulesContent'])])

        self.cmd("""iot edge deployment create --deployment-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'"""
                 .format(config_ids[2], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict}"', content_path_v1),
                 checks=[
                     self.check('id', config_ids[2]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict']),
                     self.check('content.modulesContent', json.loads(
                         # moduleContent for v1
                         self.kwargs['configuration_payload_v1'])['content']['moduleContent'])])

        # With connection string
        self.cmd('iot edge deployment show -d {} --login {}'.format(config_ids[1], LIVE_HUB_CS),
                 checks=[
                     self.check('id', config_ids[1]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict'])])

        self.cmd('iot edge deployment show --deployment-id {} --hub-name {} --resource-group {}'.format(config_ids[0],
                                                                                                        LIVE_HUB, LIVE_RG),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict'])])

        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs['generic_dict_updated'] = {'key': 'super_value'}
        self.cmd('iot edge deployment update -d {} -n {} -g {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        # With connection string
        self.cmd('iot edge deployment update -d {} --login {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        # Metrics
        system_metric_name = 'appliedCount'
        config_output = self.cmd('iot edge deployment show --login {} --config-id {}'.format(
            LIVE_HUB_CS, config_ids[2])).get_output_in_json()

        self.cmd('iot edge deployment show-metric --metric-id {} --config-id {} --hub-name {}'
                 .format(system_metric_name, config_ids[2], LIVE_HUB),
                 checks=[
                     self.check('metric', system_metric_name),
                     self.check('query', config_output['systemMetrics']['queries'][system_metric_name])
                 ])

        # With connection string
        self.cmd('iot edge deployment show-metric -m {} --login {} -c {}'
                 .format('doesnotexist', LIVE_HUB_CS, config_ids[2]), expect_failure=True)

        self.cmd('iot edge deployment show-metric --metric-id {} --login {} --config-id {}'
                 .format(system_metric_name, LIVE_HUB_CS, config_ids[2]),
                 checks=[
                     self.check('metric', system_metric_name),
                     self.check('query', config_output['systemMetrics']['queries'][system_metric_name])
                 ])

        config_list_check = [
            self.check('length([*])', 3),
            self.exists("[?id=='{}']".format(config_ids[0])),
            self.exists("[?id=='{}']".format(config_ids[1])),
            self.exists("[?id=='{}']".format(config_ids[2]))
        ]

        self.cmd("iot edge deployment list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
                 checks=config_list_check)

        # With connection string
        self.cmd("iot edge deployment list --login {}".format(LIVE_HUB_CS),
                 checks=config_list_check)

        # Explicit delete for edge deployment
        self.cmd("iot edge deployment delete -d {} -n {} -g {}".format(
            config_ids[1], LIVE_HUB, LIVE_RG))
        del config_ids[1]
        self.cmd("iot edge deployment delete -d {} --login {}".format(
            config_ids[0], LIVE_HUB_CS))
        del config_ids[0]

        # Error top of -1 does not work with configurations
        self.cmd("iot edge deployment list -n {} -g {} --top -1".format(LIVE_HUB, LIVE_RG), expect_failure=True)

        # Error max top of 20 with configurations
        self.cmd("iot edge deployment list -n {} -g {} --top 100".format(LIVE_HUB, LIVE_RG), expect_failure=True)

    @pytest.mark.skipif(not validate_min_python_version(3, 4, exit_on_fail=False), reason="minimum python version not satisfied")
    def test_uamqp_device_messaging(self):
        device_count = 1

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        test_body = str(uuid4())
        test_props = 'key0=value0;key1=value1'
        test_cid = str(uuid4())

        self.cmd('iot device c2d-message send -d {} --hub-name {} -g {} --data {} --cid {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, test_body, test_cid), checks=self.is_empty())

        result = self.cmd('iot device c2d-message receive -d {} --hub-name {} -g {}'.format(
            device_ids[0], LIVE_HUB, LIVE_RG)).get_output_in_json()

        assert result['data'] == test_body
        assert result['correlationId'] == test_cid
        assert result['ack'] == 'none'
        etag = result['etag']

        self.cmd('iot device c2d-message complete -d {} --hub-name {} -g {} --etag {}'.format(
            device_ids[0], LIVE_HUB, LIVE_RG, etag), checks=self.is_empty())

        test_body = str(uuid4())
        test_cid = str(uuid4())

        # With connection string
        self.cmd('iot device c2d-message send -d {} --data {} --props {} --cid {} --ack {} --login {}'
                 .format(device_ids[0], test_body, test_props, test_cid, 'positive', LIVE_HUB_CS), checks=self.is_empty())

        result = self.cmd('iot device c2d-message receive -d {} --login {}'.format(
            device_ids[0], LIVE_HUB_CS)).get_output_in_json()

        assert result['data'] == test_body
        assert result['correlationId'] == test_cid
        assert result['ack'] == 'positive'
        etag = result['etag']

        self.cmd('iot device c2d-message reject -d {} --etag {} --login {}'.format(
            device_ids[0], etag, LIVE_HUB_CS), checks=self.is_empty())

        # Test waiting for ack from c2d send
        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)

        token, thread = execute_onthread(method=iot_simulate_device,
                                         args=[client, device_ids[0], LIVE_HUB, 'complete',
                                               'Ping from c2d ack wait test', 2, 5, 'http'],
                                         max_runs=5,
                                         return_handle=True)

        self.cmd('iot device c2d-message send -d {} --ack {} --login {} --wait -y'.format(device_ids[0], 'full', LIVE_HUB_CS))
        token.set()
        thread.join()

        # Error - invalid wait when no ack requested
        self.cmd('iot device c2d-message send -d {} --login {} --wait -y'.format(
            device_ids[0], LIVE_HUB_CS), expect_failure=True)

    def test_device_messaging(self):
        device_count = 1

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        self.cmd('iot device c2d-message receive -d {} --hub-name {} -g {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG), checks=self.is_empty())

        # With connection string
        self.cmd('iot device c2d-message receive -d {} --login {}'
                 .format(device_ids[0], LIVE_HUB_CS), checks=self.is_empty())

        etag = '00000000-0000-0000-0000-000000000000'
        self.cmd('iot device c2d-message complete -d {} --hub-name {} -g {} -e {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, etag), expect_failure=True)

        # With connection string
        self.cmd('iot device c2d-message complete -d {} --login {} -e {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag), expect_failure=True)

        self.cmd('iot device c2d-message reject -d {} --hub-name {} -g {} -e {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, etag), expect_failure=True)

        # With connection string
        self.cmd('iot device c2d-message reject -d {} --login {} -e {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag), expect_failure=True)

        self.cmd('iot device c2d-message abandon -d {} --hub-name {} -g {} --etag {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, etag), expect_failure=True)

        # With connection string
        self.cmd('iot device c2d-message abandon -d {} --login {} --etag {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag), expect_failure=True)

        self.cmd("iot device simulate -d {} -n {} -g {} --mc {} --mi {} --data '{}' --rs 'complete'"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        # With connection string
        self.cmd("iot device simulate -d {} --login {} --mc {} --mi {} --data '{}' --rs 'complete'"
                 .format(device_ids[0], LIVE_HUB_CS, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        self.cmd("iot device simulate -d {} -n {} -g {} --mc {} --mi {} --data '{}' --rs 'abandon' --protocol http"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        # With connection string
        self.cmd("iot device simulate -d {} --login {} --mc {} --mi {} --data '{}' --rs 'abandon' --protocol http"
                 .format(device_ids[0], LIVE_HUB_CS, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        self.cmd("iot device simulate -d {} -n {} -g {} --data '{}' --rs 'reject'"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 'IoT Ext Test'), checks=self.is_empty(), expect_failure=True)

        self.cmd('iot device send-d2c-message -d {} -n {} -g {}'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=self.is_empty())

        self.cmd('iot device send-d2c-message -d {} -n {} -g {} --props "MessageId=12345;CorrelationId=54321"'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG), checks=self.is_empty())

        # With connection string
        self.cmd('iot device send-d2c-message -d {} --login {} --props "MessageId=12345;CorrelationId=54321"'
                 .format(device_ids[0], LIVE_HUB_CS), checks=self.is_empty())

    @pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
    def test_hub_monitor_events(self):
        for cg in LIVE_CONSUMER_GROUPS:
            self.cmd('az iot hub consumer-group create --hub-name {} --resource-group {} --name {}'.format(LIVE_HUB, LIVE_RG, cg),
                     checks=[self.check('name', cg)])

        from azext_iot.operations.hub import iot_device_send_message
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.core.mock import DummyCli

        cli_ctx = DummyCli()
        client = iot_hub_service_factory(cli_ctx)
        device_count = 10

        # Test with invalid connection string
        self.cmd('iot hub monitor-events -t 1 -y --login {}'.format(LIVE_HUB_CS + 'zzz'), expect_failure=True)

        # Create and Simulate Devices
        device_ids = self._create_entity_names(devices=device_count)['device_ids']

        for i in range(device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', device_ids[i])])

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        for i in range(device_count):
            execute_onthread(method=iot_device_send_message,
                             args=[client, device_ids[i], LIVE_HUB, '{\r\n"payload_data1":"payload_value1"\r\n}',
                                   '$.mid=12345;key0=value0;key1=1', 1, LIVE_RG],
                             max_runs=1)
        # Monitor events for all devices and include sys, anno, app
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y -p sys anno app'
                                    .format(LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time),
                                    device_ids + ['system', 'annotations', 'application',
                                                  '"message_id": "12345"', '"key0": "value0"', '"key1": "1"'])

        # Monitor events for a single device
        self.command_execute_assert('iot hub monitor-events -n {} -g {} -d {} --cg {} --et {} -t 10 -y -p sys anno app'
                                    .format(LIVE_HUB, LIVE_RG, device_ids[0], LIVE_CONSUMER_GROUPS[1], enqueued_time),
                                    [device_ids[0], 'system', 'annotations', 'application', '"message_id": "12345"',
                                     '"key0": "value0"', '"key1": "1"'])

        # Monitor events with device-id wildcards
        self.command_execute_assert('iot hub monitor-events -n {} -g {} -d {} --et {} -t 10 -y -p sys anno app'
                                    .format(LIVE_HUB, LIVE_RG, DEVICE_PREFIX + '*', enqueued_time),
                                    device_ids)

        # Monitor events for specific devices using query language
        device_subset_include = device_ids[:device_count // 2]
        device_include_string = ', '.join(['\'' + deviceId + '\'' for deviceId in device_subset_include])
        query_string = 'select * from devices where deviceId in [{}]'.format(device_include_string)

        self.command_execute_assert('iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 10 -y -p sys anno app'
                                    .format(LIVE_HUB, LIVE_RG, query_string, enqueued_time),
                                    device_subset_include)

        # Expect failure for excluded devices
        device_subset_exclude = device_ids[device_count // 2:]
        with pytest.raises(Exception):
            self.command_execute_assert('iot hub monitor-events -n {} -g {} --device-query "{}" --et {} -t 10 -y -p sys anno app'
                                        .format(LIVE_HUB, LIVE_RG, query_string, enqueued_time),
                                        device_subset_exclude)

        # Monitor events with --login parameter
        self.command_execute_assert('iot hub monitor-events -t 10 -y -p all --cg {} --et {} --login {}'.format(
            LIVE_CONSUMER_GROUPS[2], enqueued_time, LIVE_HUB_CS), device_ids)

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload, but do not pass $.ct property
        execute_onthread(method=iot_device_send_message, args=[client, device_ids[i], LIVE_HUB,
                                                               '{\r\n"payload_data1":"payload_value1"\r\n}', '', 1,
                                                               LIVE_RG], max_runs=1)

        # Monitor messages for ugly JSON output
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y'.format(
            LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time), ['\\r\\n'])

        # Monitor messages and parse payload as JSON with the --ct parameter
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 --ct application/json -y'.format(
            LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time), ['"payload_data1": "payload_value1"'])

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have JSON payload and have $.ct property
        execute_onthread(method=iot_device_send_message,
                         args=[client, device_ids[i], LIVE_HUB, '{\r\n"payload_data1":"payload_value1"\r\n}',
                               '$.ct=application/json', 1, LIVE_RG],
                         max_runs=1)

        # Monitor messages for pretty JSON output
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y'.format(
            LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time), ['"payload_data1": "payload_value1"'])

        # Monitor messages with yaml output
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y -o yaml'.format(
            LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[1], enqueued_time), ['payload_data1: payload_value1'])

        enqueued_time = calculate_millisec_since_unix_epoch_utc()

        # Send messages that have improperly formatted JSON payload and a $.ct property
        execute_onthread(method=iot_device_send_message,
                         args=[client, device_ids[i], LIVE_HUB, '{\r\n"payload_data1""payload_value1"\r\n}',
                               '$.ct=application/json', 1, LIVE_RG], max_runs=1)

        # Monitor messages to ensure it returns improperly formatted JSON
        self.command_execute_assert('iot hub monitor-events -n {} -g {} --cg {} --et {} -t 10 -y'.format(
            LIVE_HUB, LIVE_RG, LIVE_CONSUMER_GROUPS[0], enqueued_time), ['{\\r\\n\\"payload_data1\\"\\"payload_value1\\"\\r\\n}'])

    @pytest.mark.skipif(not validate_min_python_version(3, 4, exit_on_fail=False), reason="minimum python version not satisfied")
    def test_hub_monitor_feedback(self):
        device_count = 1

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        for i in range(device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', device_ids[i])])

        ack = 'full'
        self.cmd('iot device c2d-message send -d {} --hub-name {} -g {} --ack {} -y'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, ack), checks=self.is_empty())

        result = self.cmd('iot device c2d-message receive -d {} --hub-name {} -g {}'
                          .format(device_ids[0], LIVE_HUB, LIVE_RG)).get_output_in_json()
        msg_id = result['messageId']
        etag = result['etag']
        assert result['ack'] == ack

        self.cmd('iot device c2d-message complete -d {} --hub-name {} -g {} -e {}'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, etag))

        self.command_execute_assert('iot hub monitor-feedback -n {} -g {} -w {} -y'.format(
            LIVE_HUB, LIVE_RG, msg_id), ['description: Success'])

        # With connection string - filter on device
        ack = 'positive'
        self.cmd('iot device c2d-message send -d {} --login {} --ack {} -y'
                 .format(device_ids[0], LIVE_HUB_CS, ack), checks=self.is_empty())

        result = self.cmd('iot device c2d-message receive -d {} --login {}'
                          .format(device_ids[0], LIVE_HUB_CS)).get_output_in_json()
        msg_id = result['messageId']
        etag = result['etag']
        assert result['ack'] == ack

        self.cmd('iot device c2d-message complete -d {} --login {} -e {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag))

        self.command_execute_assert('iot hub monitor-feedback --login {} -w {} -d {} -y'.format(
            LIVE_HUB_CS, msg_id, device_ids[0]), ['description: Success'])

        # With connection string - dead lettered case + unrelated ack
        ack = 'negative'

        # Create some noise
        self.cmd('iot device c2d-message send -d {} --login {} --ack {} -y'
                 .format(device_ids[0], LIVE_HUB_CS, ack), checks=self.is_empty())
        result = self.cmd('iot device c2d-message receive -d {} --login {}'
                          .format(device_ids[0], LIVE_HUB_CS)).get_output_in_json()
        etag = result['etag']
        self.cmd('iot device c2d-message reject -d {} --login {} -e {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag))

        # Target message
        self.cmd('iot device c2d-message send -d {} --login {} --ack {} -y'
                 .format(device_ids[0], LIVE_HUB_CS, ack), checks=self.is_empty())

        result = self.cmd('iot device c2d-message receive -d {} --login {}'
                          .format(device_ids[0], LIVE_HUB_CS)).get_output_in_json()
        msg_id = result['messageId']
        etag = result['etag']
        assert result['ack'] == ack

        self.cmd('iot device c2d-message reject -d {} --login {} -e {}'
                 .format(device_ids[0], LIVE_HUB_CS, etag))

        self.command_execute_assert('iot hub monitor-feedback --login {} -w {} -y'.format(
            LIVE_HUB_CS, msg_id), ['description: Message rejected'])

    @pytest.mark.skipif(not LIVE_STORAGE, reason="empty azext_iot_teststorageuri env var")
    def test_storage(self):
        device_count = 1

        content_path = os.path.join(CWD, 'test_config_modules_content_v1.json')
        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} --ee'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        self.cmd('iot device upload-file -d {} -n {} --fp "{}" --ct {}'
                 .format(device_ids[0], LIVE_HUB, content_path, 'application/json'),
                 checks=self.is_empty())

        # With connection string
        self.cmd('iot device upload-file -d {} --login {} --fp "{}" --ct {}'
                 .format(device_ids[0], LIVE_HUB_CS, content_path, 'application/json'),
                 checks=self.is_empty())

        self.cmd('iot hub device-identity export -n {} --bcu "{}"'.format(LIVE_HUB, LIVE_STORAGE),
                 checks=[
                     self.check('outputBlobContainerUri', LIVE_STORAGE),
                     self.check('failureReason', None),
                     self.check('type', 'export'),
                     self.exists('jobId')])
