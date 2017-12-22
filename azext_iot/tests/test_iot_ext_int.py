# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

import os
import random
import pytest
from azure.cli.testsdk import ResourceGroupPreparer, ScenarioTest, LiveScenarioTest
from azure.cli.core.util import read_file_content


device_id_1 = 'test-device-1'
device_id_2 = 'test-device-2'
device_id_3 = 'test-device-3'
module_id_1 = 'test-module-1'
module_id_2 = 'test-module-2'
config_id_1 = 'test-config-1'
config_id_2 = 'test-config-2'
hub = 'TestHub'
rg = 'IoT'
device_id_pattern = r'^test\-device\-\d$'
module_id_pattern = r'^test\-module\-\d$'
config_id_pattern = r'^test\-config\-\d$'
primary_thumbprint = 'A361EA6A7119A8B0B7BBFFA2EAFDAD1F9D5BED8C'
secondary_thumbprint = '14963E8F3BA5B3984110B3C1CA8E8B8988599087'
cwd = os.path.dirname(os.path.abspath(__file__))


class TestHub(LiveScenarioTest):
    def test_hub_cs(self):
        sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;SharedAccessKeyName={};SharedAccessKey='.format(
            hub, 'iothubowner')
        self.cmd('iot hub show-connection-string -n {} -g {}'.format(hub, rg), checks=[
            self.check_pattern('cs', sym_conn_str_pattern)
        ])
        self.cmd('iot hub show-connection-string -n {} -kt {}'.format(hub, 'secondary'), checks=[
            self.check_pattern('cs', sym_conn_str_pattern)
        ])
        self.cmd('iot hub show-connection-string -n {} -kt {} -po doesnotexist'.format(hub, 'secondary'), expect_failure=True)

    def test_hub_query(self):
        self.cmd('iot hub query --hub-name {} -q "{}"'.format(hub, "select * from devices"),
                 checks=[self.check('length([*])', 3),
                         self.check_pattern('[0].deviceId', device_id_pattern),
                         self.check_pattern('[1].deviceId', device_id_pattern),
                         self.check_pattern('[2].deviceId', device_id_pattern)])

    # Combined with unit test in Base CLI
    def test_sas_token(self):
        self.cmd('az iot hub generate-sas-token -n {}'.format(hub), checks=[
            self.exists('sas')
        ])
        self.cmd('az iot hub generate-sas-token -n {} -d {}'.format(hub, device_id_1), checks=[
            self.exists('sas')
        ])
        self.cmd('az iot hub generate-sas-token -n {} -d {} -kt "secondary"'.format(hub, device_id_2), checks=[
            self.exists('sas')
        ])


class TestDevice(LiveScenarioTest):
    @pytest.mark.first
    def test_device_create(self):
        self.cmd('iot hub device-identity create -d {} -n {} -g {} -ee'.format(device_id_1, hub, rg),
                 checks=[self.check('deviceId', device_id_1),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('connectionState', 'Disconnected'),
                         self.check('capabilities.iotEdge', True),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('''iot hub device-identity create --device-id {} --hub-name {} --edge-enabled
                    --auth-method x509_thumbprint --primary-thumbprint {} --secondary-thumbprint {}'''
                 .format(device_id_2, hub, primary_thumbprint, secondary_thumbprint),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('capabilities.iotEdge', True),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.check(
                             'authentication.x509Thumbprint.primaryThumbprint', primary_thumbprint),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', secondary_thumbprint)])

        statusReason = "Test Status Reason"
        self.cmd('''iot hub device-identity create --device-id {} --hub-name {}
                    --auth-method x509_ca --status disabled --status-reason "{}"'''
                 .format(device_id_3, hub, statusReason),
                 checks=[self.check('deviceId', device_id_3),
                         self.check('status', 'disabled'),
                         self.check('statusReason', statusReason),
                         self.check('capabilities.iotEdge', False),
                         self.check('connectionState', 'Disconnected'),
                         self.check(
                             'authentication.symmetricKey.primaryKey', None),
                         self.check(
                             'authentication.symmetricKey.secondaryKey', None),
                         self.check(
                             'authentication.x509Thumbprint.primaryThumbprint', None),
                         self.check('authentication.x509Thumbprint.secondaryThumbprint', None)])

    def test_device_show(self):
        self.cmd('iot hub device-identity show -d {} -n {} -g {}'.format(device_id_1, hub, rg),
                 checks=[self.check('deviceId', device_id_1),
                         self.check('status', 'enabled'),
                         self.check('statusReason', None),
                         self.check('connectionState', 'Disconnected'),
                         self.check('capabilities.iotEdge', True),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

    def test_device_list(self):
        self.cmd('iot hub device-identity list --hub-name {}'.format(hub),
                 checks=[self.check('length([*])', 3),
                         self.check_pattern('[0].deviceId', device_id_pattern),
                         self.check_pattern('[1].deviceId', device_id_pattern),
                         self.check_pattern('[2].deviceId', device_id_pattern)])

        # Until API is fixed
        # self.cmd('iot hub device-identity list --hub-name {} -ee'.format(hub),
        #          checks=[self.check('length([*])', 2)])

    def test_device_update(self):
        self.cmd('iot hub device-identity update -d {} -n {} --set capabilities.iotEdge={}'.format(device_id_2, hub, True),
                 checks=[
                     self.check('deviceId', device_id_2),
                     self.check('status', 'enabled'),
                     self.check('authentication.symmetricKey.primaryKey', None),
                     self.check('authentication.symmetricKey.secondaryKey', None),
                     self.check('authentication.x509Thumbprint.primaryThumbprint', primary_thumbprint),
                     self.check('authentication.x509Thumbprint.secondaryThumbprint', secondary_thumbprint)])

        self.cmd('''iot hub device-identity update -d {} -n {} --set authentication.symmetricKey.primaryKey=""
                    authentication.symmetricKey.secondaryKey=""'''.format(device_id_1, hub),
                 checks=[
                     self.check('deviceId', device_id_1),
                     self.check('status', 'enabled'),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

    def test_device_cs(self):
        sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};SharedAccessKey='.format(
            hub, device_id_1)
        cer_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};x509=true'.format(
            hub, device_id_2)
        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'.format(device_id_1, hub, rg), checks=[
            self.check_pattern('cs', sym_conn_str_pattern)
        ])
        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {} -kt {}'
                 .format(device_id_1, hub, rg, 'secondary'), checks=[self.check_pattern('cs', sym_conn_str_pattern)])
        self.cmd('iot hub device-identity show-connection-string -d {} -n {} -g {}'
                 .format(device_id_2, hub, rg), checks=[self.check_pattern('cs', cer_conn_str_pattern)])

    def test_device_twin_show(self):
        self.cmd('iot hub device-twin show -d {} -n {} -g {}'.format(device_id_2, hub, rg),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('status', 'enabled'),
                         self.exists('properties.desired'),
                         self.exists('properties.reported'),
                         self.check('x509Thumbprint.primaryThumbprint', primary_thumbprint),
                         self.check('x509Thumbprint.secondaryThumbprint', secondary_thumbprint)])

    def test_device_twin_update(self):
        self.cmd('iot hub device-twin update -d {} -n {} --set properties.desired.special={}'
                 .format(device_id_2, hub, '\'{"key":"value"}\''),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('status', 'enabled'),
                         self.check('properties.desired.special', {'key': 'value'})])

    def test_device_twin_replace(self):
        content_path = os.path.join(cwd, 'test_generic_replace.json')
        self.cmd("iot hub device-twin replace -d {} -n {} -j '{}'"
                 .format(device_id_2, hub, content_path),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        self.cmd("iot hub device-twin replace -d {} -n {} -j '{}'"
                 .format(device_id_2, hub, read_file_content(content_path)),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

    def test_device_apply_configuration(self):
        content_path = os.path.join(cwd, 'test_config_content.json')
        self.cmd("iot hub apply-configuration -d {} -n {} -k '{}'".format(device_id_1, hub, content_path),
                 checks=self.is_empty())
        self.cmd("iot hub apply-configuration -d {} -n {} --content '{}'"
                 .format(device_id_1, hub, read_file_content(content_path)),
                 checks=self.is_empty())


class TestModules(LiveScenarioTest):
    def test_module_create(self):
        self.cmd('iot hub module-identity create -d {} -n {} -g {} -m {}'.format(device_id_2, hub, rg, module_id_1),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_1),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub module-identity create --device-id {} --hub-name {} --module-id {}'
                 .format(device_id_2, hub, module_id_2),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_2),
                         self.check('managedBy', 'iotEdge'),
                         self.exists('authentication.symmetricKey.primaryKey'),
                         self.exists('authentication.symmetricKey.secondaryKey')])

        self.cmd('iot hub query --hub-name {} -q "{}"'
                 .format(hub, "select * from devices.modules where devices.deviceId='{}'".format(device_id_2)),
                 checks=[self.check('length([*])', 4)])

    def test_module_update(self):
        self.cmd('''iot hub module-identity update -d {} -n {} -m {}
                    --set authentication.symmetricKey.primaryKey=""
                    authentication.symmetricKey.secondaryKey=""'''.format(device_id_2, hub, module_id_1),
                 checks=[
                     self.check('deviceId', device_id_2),
                     self.check('moduleId', module_id_1),
                     self.check('managedBy', 'iotEdge'),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

    def test_module_list(self):
        self.cmd('iot hub module-identity list -d {} -n {}'.format(device_id_2, hub),
                 checks=[
                    self.check('length([*])', 4),
                    self.exists("[?moduleId=='$edgeAgent']"),
                    self.exists("[?moduleId=='$edgeHub']")])

    def test_module_show(self):
        self.cmd('iot hub module-identity show -d {} -n {} -m {}'.format(device_id_2, hub, module_id_1),
                 checks=[
                     self.check('deviceId', device_id_2),
                     self.check('moduleId', module_id_1),
                     self.check('managedBy', 'iotEdge'),
                     self.exists('authentication.symmetricKey.primaryKey'),
                     self.exists('authentication.symmetricKey.secondaryKey')])

    def test_module_cs(self):
        sym_conn_str_pattern = r'^HostName={}\.azure-devices\.net;DeviceId={};ModuleId={};SharedAccessKey='.format(
            hub, device_id_2, module_id_1)
        self.cmd('iot hub module-identity show-connection-string -d {} -n {} -m {} -g {}'
                 .format(device_id_2, hub, module_id_1, rg), checks=[self.check_pattern('cs', sym_conn_str_pattern)])
        self.cmd('iot hub module-identity show-connection-string -d {} -n {} -m {} -kt {}'
                 .format(device_id_2, hub, module_id_1, 'secondary'), checks=[self.check_pattern('cs', sym_conn_str_pattern)])

    def test_module_twin_show(self):
        self.cmd('iot hub module-twin show -d {} -n {} -m {} -g {}'.format(device_id_2, hub, module_id_1, rg),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_1),
                         self.exists('properties.desired'),
                         self.exists('properties.reported')])

    def test_module_twin_update(self):
        self.cmd('iot hub module-twin update -d {} -n {} -m {} --set properties.desired.special={}'
                 .format(device_id_2, hub, module_id_1, '\'{"key":"value"}\''),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_1),
                         self.check('properties.desired.special', {'key': 'value'})])

    def test_module_twin_replace(self):
        content_path = os.path.join(cwd, 'test_generic_replace.json')
        self.cmd("iot hub module-twin replace -d {} -n {} -m {} -j '{}'"
                 .format(device_id_2, hub, module_id_1, content_path),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_1),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])

        self.cmd("iot hub module-twin replace -d {} -n {} -m {} -j '{}'"
                 .format(device_id_2, hub, module_id_1, read_file_content(content_path)),
                 checks=[self.check('deviceId', device_id_2),
                         self.check('moduleId', module_id_1),
                         self.check('properties.desired.awesome', 9001),
                         self.check('properties.desired.temperature.min', 10),
                         self.check('properties.desired.temperature.max', 100),
                         self.check('tags.location.region', 'US')])


class TestEdgeDeployment(LiveScenarioTest):
    def test_edge_deployment_create_and_show(self):
        priority = random.randint(1, 10)
        condition = 'tags.building=9 and tags.environment=\'test\''
        content_path = os.path.join(cwd, 'test_config_content.json')
        labels = '{"key0":"value0", "key1":"value1"}'
        self.cmd("iot edge deployment create -c {} -n {} -pri {} -tc \"{}\" -lab '{}' -k '{}'"
                 .format(config_id_1, hub, priority, condition, labels, content_path),
                 checks=[
                     self.check('id', config_id_1),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', {"key0": "value0", "key1": "value1"})])

        self.cmd("iot edge deployment create -c {} -n {} --priority {} --target-condition \"{}\" --labels '{}' --content '{}'"
                 .format(config_id_2, hub, priority, condition, labels, read_file_content(content_path)),
                 checks=[
                     self.check('id', config_id_2),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', {"key0": "value0", "key1": "value1"})])

        self.cmd('iot edge deployment show -c {} -n {}'.format(config_id_1, hub),
                 checks=[
                     self.check('id', config_id_1),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('contentType', 'assignments'),
                     self.check('labels', {"key0": "value0", "key1": "value1"})])

    def test_edge_deployment_update(self):
        priority = random.randint(1, 10)
        condition = "tags.building=43 and tags.environment='dev'"
        labels = '{"key":"super_value"}'
        self.cmd('iot edge deployment update -c {} -n {} --set priority={} targetCondition="{}" labels=\'{}\''
                 .format(config_id_1, hub, priority, condition, labels),
                 checks=[
                     self.check('id', config_id_1),
                     self.check('priority', priority),
                     self.check('targetCondition', condition),
                     self.check('labels', {"key": "super_value"})])

    def test_edge_deployment_list(self):
        self.cmd("iot edge deployment list -n {}".format(hub),
                 checks=[self.check('length([*])', 2),
                         self.check_pattern('[0].id', config_id_pattern),
                         self.check_pattern('[1].id', config_id_pattern)])


class TestMessaging(LiveScenarioTest):
    def test_d2c(self):
        self.cmd('iot device send-d2c-message -d {} -n {}'.format(device_id_1, hub), checks=self.is_empty())
        self.cmd('iot device send-d2c-message -d {} -n {} -props "MessageId=12345;CorrelationId=54321"'.format(
            device_id_1, hub), checks=self.is_empty())

    def test_c2d(self):
        self.cmd('iot device c2d-message receive -d {} --hub-name {}'.format(device_id_1, hub), checks=self.is_empty())

        etag = '00000000-0000-0000-0000-000000000000'
        self.cmd('iot device c2d-message complete -d {} --hub-name {} -e {}'.format(device_id_1, hub, etag),
                 expect_failure=True)

        self.cmd('iot device c2d-message reject -d {} --hub-name {} -e {} -g {}'.format(device_id_1, hub, etag, rg),
                 expect_failure=True)

        self.cmd('iot device c2d-message abandon -d {} --hub-name {} --etag {}'.format(device_id_1, hub, etag),
                 expect_failure=True)

    def test_device_simulate(self):
        self.cmd("iot device simulate -d {} -n {} --data '{}' -rs 'complete'".format(device_id_1, hub, 'IoT Ext Test'),
                 checks=self.is_empty())


@pytest.mark.second_to_last
class TestCleanUp(LiveScenarioTest):
    def test_edge_deployment_delete(self):
        self.cmd('iot edge deployment delete -c {} -n {}'.format(config_id_1, hub), checks=self.is_empty())
        self.cmd('iot edge deployment delete -c {} -n {}'.format(config_id_2, hub), checks=self.is_empty())

    def test_module_delete(self):
        self.cmd('iot hub module-identity delete --device-id {} -n {} --module-id {}'.format(
            device_id_2, hub, module_id_1), checks=self.is_empty())
        self.cmd('iot hub module-identity delete -d {} -n {} -m {}'.format(device_id_2, hub, module_id_2), checks=self.is_empty())

    @pytest.mark.last
    def test_device_delete(self):
        self.cmd('iot hub device-identity delete -d {} -n {}'.format(device_id_1, hub), checks=self.is_empty())
        self.cmd('iot hub device-identity delete --device-id {} --hub-name {}'.format(device_id_2, hub), checks=self.is_empty())
        self.cmd('iot hub device-identity delete -d {} -n {}'.format(device_id_3, hub), checks=self.is_empty())
