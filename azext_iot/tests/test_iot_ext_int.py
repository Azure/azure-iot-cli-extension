# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

import os
import random
import pytest

from azure.cli.testsdk import LiveScenarioTest
from azure.cli.core.util import read_file_content
from azext_iot.common.utility import validate_min_python_version, execute_onthread


# Set these to the proper IoT Hub, IoT Hub Cstring and Resource Group for Live Integration Tests.
LIVE_HUB = os.environ.get('azext_iot_testhub')
LIVE_RG = os.environ.get('azext_iot_testrg')
LIVE_HUB_CS = os.environ.get('azext_iot_testhub_cs')

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE = os.environ.get('azext_iot_teststorageuri')

if not all([LIVE_HUB, LIVE_HUB_CS, LIVE_RG]):
    raise ValueError('Set azext_iot_testhub, azext_iot_testhub_cs and azext_iot_testrg to run IoT Hub integration tests.')


CWD = os.path.dirname(os.path.abspath(__file__))

PRIMARY_THUMBPRINT = 'A361EA6A7119A8B0B7BBFFA2EAFDAD1F9D5BED8C'
SECONDARY_THUMBPRINT = '14963E8F3BA5B3984110B3C1CA8E8B8988599087'


class TestIoTHub(LiveScenarioTest):
    def setUp(self):
        self._entity_names = None

    def _create_entity_names(self, devices=0, edge_devices=0, modules=0, configs=0):
        result = {}
        if devices:
            device_ids = []
            for _ in range(devices):
                device_ids.append(self.create_random_name(prefix='test-device-', length=32))
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
                    self.cmd('iot edge deployment delete -c {} --login {}'
                             .format(i, LIVE_HUB_CS), checks=self.is_empty())
                else:
                    self.cmd('iot edge deployment delete -c {} -n {} -g {}'
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
        self.cmd('iot hub show-connection-string -n {} -g {} -kt {}'.format(LIVE_HUB, LIVE_RG, 'secondary'), checks=[
            self.check_pattern('cs', hub_conn_str_pattern)
        ])
        self.cmd('iot hub show-connection-string -n {} -g {} -kt {} -pn doesnotexist'.format(LIVE_HUB, LIVE_RG, 'secondary'),
                 expect_failure=True)

        self.cmd('az iot hub generate-sas-token -n {} -g {}'.format(LIVE_HUB, LIVE_RG), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token -n {}'.format(LIVE_HUB), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token -n {} -du {}'.format(LIVE_HUB, '1000'), checks=[
            self.exists('sas')
        ])

        # With connection string
        self.cmd('az iot hub generate-sas-token --login {}'.format(LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('az iot hub generate-sas-token --login {} -pn somepolicy'.format(LIVE_HUB_CS), expect_failure=True)

        # With connection string
        # Error can't change key for a sas token with conn string
        self.cmd('az iot hub generate-sas-token --login {} -kt secondary'.format(LIVE_HUB_CS), expect_failure=True)

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
            self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(edge_device_ids[i], LIVE_HUB, LIVE_RG),
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

        self.cmd('iot hub query --hub-name {} -g {} -q "{}"'.format(LIVE_HUB, LIVE_RG, "select * from devices"),
                 checks=query_checks)

        # With connection string
        self.cmd('iot hub query -q "{}" --login {}'.format("select * from devices", LIVE_HUB_CS),
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

        self.cmd('iot hub device-identity list -n {} -g {} -ee'.format(LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', edge_device_count)])

        # With connection string
        self.cmd('iot hub device-identity list -ee --login {}'.format(LIVE_HUB_CS),
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

        content_path = os.path.join(CWD, 'test_config_content.json')
        self.cmd("iot hub apply-configuration -d {} -n {} -g {} -k '{}'"
                 .format(edge_device_ids[1], LIVE_HUB, LIVE_RG, content_path), checks=[self.check('length([*])', 3)])

        # With connection string
        content_path = os.path.join(CWD, 'test_config_content.json')
        self.cmd("iot hub apply-configuration -d {} --login {} -k '{}'"
                 .format(edge_device_ids[1], LIVE_HUB_CS, content_path), checks=[self.check('length([*])', 3)])

        self.kwargs['generic_content'] = read_file_content(content_path)
        self.cmd("iot hub apply-configuration -d {} -n {} -g {} --content '{}'"
                 .format(edge_device_ids[1], LIVE_HUB, LIVE_RG, '{generic_content}'), self.check('length([*])', 3))

        sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};SharedAccessKey='.format(
            LIVE_HUB, edge_device_ids[0])
        cer_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};x509=true'.format(
            LIVE_HUB, device_ids[2])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check_pattern('cs', sym_conn_str_pattern)])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {} -kt {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, 'secondary'),
                 checks=[self.check_pattern('cs', sym_conn_str_pattern)])

        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'
                 .format(device_ids[2], LIVE_HUB, LIVE_RG),
                 checks=[self.check_pattern('cs', cer_conn_str_pattern)])

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {}'.format(LIVE_HUB, LIVE_RG, edge_device_ids[0]), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {} -du {}'.format(LIVE_HUB,
                                                                              LIVE_RG, edge_device_ids[0], '1000'),
                 checks=[self.exists('sas')])

        # None SAS device auth
        self.cmd('iot hub generate-sas-token -n {} -g {} -d {}'.format(LIVE_HUB, LIVE_RG, device_ids[1]), expect_failure=True)

        self.cmd('iot hub generate-sas-token -n {} -g {} -d {} -kt "secondary"'.format(LIVE_HUB, LIVE_RG, edge_device_ids[1]),
                 checks=[self.exists('sas')])

        # With connection string
        self.cmd('iot hub generate-sas-token -d {} --login {}'.format(edge_device_ids[0], LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -d {} --login {} -kt "secondary"'.format(edge_device_ids[1], LIVE_HUB_CS), checks=[
            self.exists('sas')
        ])

        self.cmd('iot hub generate-sas-token -d {} --login {} -pn "mypolicy"'.format(edge_device_ids[1], LIVE_HUB_CS),
                 expect_failure=True)

    def test_hub_device_twins(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
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
        edge_device_count = 1
        module_count = 2

        names = self._create_entity_names(edge_devices=edge_device_count, modules=module_count)
        edge_device_ids = names['edge_device_ids']
        module_ids = names['module_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', edge_device_ids[0])])

        # With connection string
        self.cmd('iot hub module-identity create -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity create --device-id {} --hub-name {} --resource-group {} --module-id {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[1]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[1]),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # Uncomment after API change. Currently API let's you create modules on non-edge devices.
        # self.cmd('iot hub module-identity create --device-id {} --hub-name {} --resource-group {} --module-id {}'
        #          .format(self.device_ids[2], LIVE_HUB, LIVE_RG, module_ids[1]),
        #          expect_failure=True)

        # Includes $edgeAgent && $edgeHub system modules
        result = self.cmd('iot hub query --hub-name {} -g {} -q "{}"'
                          .format(LIVE_HUB, LIVE_RG, "select * from devices.modules where devices.deviceId='{}'"
                                  .format(edge_device_ids[0]))).get_output_in_json()
        assert len(result) == 4

        self.cmd('''iot hub module-identity update -d {} -n {} -g {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''.format(
                 edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('''iot hub module-identity update -d {} --login {} -m {}
                    --set authentication.symmetricKey.primaryKey="" authentication.symmetricKey.secondaryKey=""'''.format(
                 edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity list -d {} -n {} -g {}'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
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
                     self.check('managedBy', 'iotEdge'),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

        # With connection string
        self.cmd('iot hub module-identity show -d {} --login {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB_CS, module_ids[0]),
                 checks=[
                     self.check('deviceId', edge_device_ids[0]),
                     self.check('moduleId', module_ids[0]),
                     self.check('managedBy', 'iotEdge'),
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

        self.cmd('iot hub module-identity show-connection-string -d {} -n {} -g {} -m {} -kt {}'
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
        edge_device_count = 1
        module_count = 1

        names = self._create_entity_names(edge_devices=edge_device_count, modules=module_count)
        edge_device_ids = names['edge_device_ids']
        module_ids = names['module_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(edge_device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', edge_device_ids[0])])

        self.cmd('iot hub module-identity create -d {} -n {} -g {} -m {}'
                 .format(edge_device_ids[0], LIVE_HUB, LIVE_RG, module_ids[0]),
                 checks=[self.check('deviceId', edge_device_ids[0]),
                         self.check('moduleId', module_ids[0]),
                         self.check('managedBy', 'iotEdge'),
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

    def test_edge_deployments(self):
        self.kwargs['generic_dict'] = {'key': 'value'}
        config_count = 2
        names = self._create_entity_names(configs=config_count)
        config_ids = names['config_ids']

        content_path = os.path.join(CWD, 'test_config_content.json')
        priority = random.randint(1, 10)
        condition = 'tags.building=9 and tags.environment=\'test\''

        # With connection string
        self.cmd("iot edge deployment create -c {} --login {} -pri {} -tc \"{}\" -lab {} -k '{}'"
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict}"', content_path),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', self.kwargs['generic_dict'])])

        self.kwargs['deployment_payload'] = read_file_content(content_path)
        self.cmd("""iot edge deployment create --config-id {} --hub-name {} --resource-group {} --priority {}
                    --target-condition \"{}\" --labels {} --content '{}'"""
                 .format(config_ids[1], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict}"', '{deployment_payload}'),
                 checks=[
                     self.check('id', config_ids[1]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', self.kwargs['generic_dict'])])

        self.cmd('iot edge deployment show -c {} -n {} -g {}'.format(config_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', self.kwargs['generic_dict'])])

        # With connection string
        self.cmd('iot edge deployment show -c {} --login {}'.format(config_ids[1], LIVE_HUB_CS),
                 checks=[
                     self.check('id', config_ids[1]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', self.kwargs['generic_dict'])])

        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        self.kwargs['generic_dict_updated'] = {'key': 'super_value'}
        self.cmd('iot edge deployment update -c {} -n {} -g {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB, LIVE_RG, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        # With connection string
        self.cmd('iot edge deployment update -c {} --login {} --set priority={} targetCondition="{}" labels={}'
                 .format(config_ids[0], LIVE_HUB_CS, priority, condition, '"{generic_dict_updated}"'),
                 checks=[
                     self.check('id', config_ids[0]),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', self.kwargs['generic_dict_updated'])])

        self.cmd("iot edge deployment list -n {} -g {}".format(LIVE_HUB, LIVE_RG),
                 checks=[self.check('length([*])', 2),
                         self.exists("[?id=='{}']".format(config_ids[0])),
                         self.exists("[?id=='{}']".format(config_ids[1]))])

        # With connection string
        self.cmd("iot edge deployment list --login {}".format(LIVE_HUB_CS),
                 checks=[self.check('length([*])', 2),
                         self.exists("[?id=='{}']".format(config_ids[0])),
                         self.exists("[?id=='{}']".format(config_ids[1]))])

    def test_device_messaging(self):
        device_count = 1

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(device_ids[0], LIVE_HUB, LIVE_RG),
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

        self.cmd("iot device simulate -d {} -n {} -g {} -mc {} -mi {} --data '{}' -rs 'complete'"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        # With connection string
        self.cmd("iot device simulate -d {} --login {} -mc {} -mi {} --data '{}' -rs 'complete'"
                 .format(device_ids[0], LIVE_HUB_CS, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        self.cmd("iot device simulate -d {} -n {} -g {} -mc {} -mi {} --data '{}' -rs 'abandon' --protocol http"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        # With connection string
        self.cmd("iot device simulate -d {} --login {} -mc {} -mi {} --data '{}' -rs 'abandon' --protocol http"
                 .format(device_ids[0], LIVE_HUB_CS, 2, 1, 'IoT Ext Test'), checks=self.is_empty())

        self.cmd("iot device simulate -d {} -n {} -g {} --data '{}' -rs 'reject'"
                 .format(device_ids[0], LIVE_HUB, LIVE_RG, 'IoT Ext Test'), checks=self.is_empty(), expect_failure=True)

        self.cmd('iot device send-d2c-message -d {} -n {} -g {}'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=self.is_empty())

        self.cmd('iot device send-d2c-message -d {} -n {} -g {} -props "MessageId=12345;CorrelationId=54321"'
                 .format(device_ids[0], LIVE_HUB, LIVE_RG), checks=self.is_empty())

        # With connection string
        self.cmd('iot device send-d2c-message -d {} --login {} -props "MessageId=12345;CorrelationId=54321"'
                 .format(device_ids[0], LIVE_HUB_CS), checks=self.is_empty())

    @pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
    def test_hub_monitor_event_all(self):
        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.testsdk import TestCli

        cli_ctx = TestCli()
        client = iot_hub_service_factory(cli_ctx)

        device_count = 10

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        for i in range(device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', device_ids[i])])

        for i in range(device_count):
            execute_onthread(method=iot_simulate_device,
                             args=[client, device_ids[i], LIVE_HUB, 'complete', 'Ping from test', 5, 1],
                             max_runs=1)

        self.cmd('iot hub monitor-events -n {} -g {} -to 10 -y -props sys anno app --debug'.format(
            LIVE_HUB, LIVE_RG), checks=None)

    @pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
    def test_hub_monitor_event_device(self):
        from azext_iot.operations.hub import iot_simulate_device
        from azext_iot._factory import iot_hub_service_factory
        from azure.cli.testsdk import TestCli

        cli_ctx = TestCli()
        client = iot_hub_service_factory(cli_ctx)

        device_count = 2

        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        for i in range(device_count):
            self.cmd('iot hub device-identity create -d {} -n {} -g {}'.format(device_ids[i], LIVE_HUB, LIVE_RG),
                     checks=[self.check('deviceId', device_ids[i])])

        for i in range(device_count):
            execute_onthread(method=iot_simulate_device,
                             args=[client, device_ids[i], LIVE_HUB, 'complete', 'Ping from test', 5, 1, 'http'],
                             max_runs=1)

        self.cmd('iot hub monitor-events -n {} -to 10 -y -props all -d {} --debug'.format(
            LIVE_HUB, device_ids[0]), checks=None)

    @pytest.mark.skipif(not LIVE_STORAGE, reason="empty azext_iot_teststorageuri env var")
    def test_storage(self):
        device_count = 1

        content_path = os.path.join(CWD, 'test_config_content.json')
        names = self._create_entity_names(devices=device_count)
        device_ids = names['device_ids']

        self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(device_ids[0], LIVE_HUB, LIVE_RG),
                 checks=[self.check('deviceId', device_ids[0])])

        self.cmd('iot device upload-file -d {} -n {} -fp "{}" -ct {}'
                 .format(device_ids[0], LIVE_HUB, content_path, 'application/json'),
                 checks=self.is_empty())

        # With connection string
        self.cmd('iot device upload-file -d {} --login {} -fp "{}" -ct {}'
                 .format(device_ids[0], LIVE_HUB_CS, content_path, 'application/json'),
                 checks=self.is_empty())

        self.cmd('iot hub device-identity export -n {} -bcu "{}"'.format(LIVE_HUB, LIVE_STORAGE),
                 checks=[
                     self.check(
                         'additionalProperties.outputBlobContainerUri', LIVE_STORAGE),
                     self.check('failureReason', None),
                     self.check('type', 'export'),
                     self.exists('jobId')])
