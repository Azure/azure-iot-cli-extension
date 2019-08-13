# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Unpublished works.
# --------------------------------------------------------------------------------------------
import pytest
import random
import json
import os
import sys

from io import open
from os.path import exists
from uuid import uuid4
from azure.cli.testsdk import LiveScenarioTest
from azure.cli.core.util import read_file_content


# Add test tools to path
sys.path.append(os.path.abspath(os.path.join('.', 'iotext_test_tools')))

# Set these to the proper PnP Endpoint, PnP Cstring and PnP Repository for Live Integration Tests.
_endpoint = os.environ.get('azext_pnp_endpoint')
_repo_id = os.environ.get('azext_pnp_repository')
_repo_cs = os.environ.get('azext_pnp_cs')

_interface_payload = 'test_pnp_create_payload_interface.json'
_capability_model_payload = 'test_pnp_create_payload_model.json'

if not all([_endpoint, _repo_id, _repo_cs]):
    raise ValueError('Set azext_pnp_endpoint, azext_pnp_repository and azext_pnp_cs to run PnP model integration tests.')


def change_dir():
    from inspect import getsourcefile
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


class TestPnPModel(LiveScenarioTest):

    rand_val = random.randint(1, 10001)

    def __init__(self, _):
        from iotext_test_tools import DummyCliOutputProducer
        super(TestPnPModel, self).__init__(_)
        self.cli_ctx = DummyCliOutputProducer()
        self.kwargs.update({
            'endpoint': _endpoint,
            'repo': _repo_id,
            'repo_cs': _repo_cs,
            'interface': 'test_interface_definition.json',
            'interface-updated': 'test_interface_updated_definition.json',
            'model': 'test_model_definition.json',
            'model-updated': 'test_model_updated_definition.json'
        })

    def setUp(self):
        change_dir()
        if(self._testMethodName == 'test_interface_life_cycle'):
            interface = str(read_file_content(_interface_payload))
            _interface_id = '{}{}'.format(json.loads(interface)['@id'], TestPnPModel.rand_val)
            self.kwargs.update({'interface_id': _interface_id})
            interface_newContent = interface.replace(json.loads(interface)['@id'], self.kwargs['interface_id'])
            interface_newContent = interface_newContent.replace('\n', '')

            fo = open(self.kwargs['interface'], "w+", encoding='utf-8')
            fo.write(interface_newContent)
            fo.close()

        if(self._testMethodName == 'test_model_life_cycle'):
            model = str(read_file_content(_capability_model_payload))
            _model_id = '{}{}'.format(json.loads(model)['@id'], TestPnPModel.rand_val)
            self.kwargs.update({'model_id': _model_id})
            model_newContent = model.replace(json.loads(model)['@id'], self.kwargs['model_id'])
            model_newContent = model_newContent.replace('\n', '')

            fo = open(self.kwargs['model'], "w+", encoding='utf-8')
            fo.write(model_newContent)
            fo.close()

    def tearDown(self):
        change_dir()
        if exists(self.kwargs['interface-updated']):
            os.remove(self.kwargs['interface-updated'])
        if exists(self.kwargs['model-updated']):
            os.remove(self.kwargs['model-updated'])
        if exists(self.kwargs['interface']):
            os.remove(self.kwargs['interface'])
        if exists(self.kwargs['model']):
            os.remove(self.kwargs['model'])

    def test_interface_life_cycle(self):

        # Error: missing repo-id or login
        self.cmd('iot pnp interface create -e {endpoint} --def {interface}', expect_failure=True)

        # Error: Invalid Interface definition file
        self.cmd('iot pnp interface create -e {endpoint} -r {repo} --def interface', expect_failure=True)

        # Error: wrong path of Interface definition
        self.cmd('iot pnp interface create -e {endpoint} -r {repo} --def interface.json', expect_failure=True)

        # Success: Create new Interface
        self.cmd('iot pnp interface create -e {endpoint} -r {repo} --def {interface}', checks=self.is_empty())

        # Checking the Interface list
        self.cmd('iot pnp interface list -e {endpoint} -r {repo}',
                 checks=[self.greater_than('length([*])', 0)])

        # Get Interface
        interface = self.cmd('iot pnp interface show -e {endpoint} -r {repo} -i {interface_id}').get_output_in_json()
        assert json.dumps(interface)
        assert interface['@id'] == self.kwargs['interface_id']
        assert interface['displayName'] == 'MXChip1'
        assert len(interface['contents']) > 0

        # Success: Update Interface
        interface = str(read_file_content(self.kwargs['interface']))
        display_name = json.loads(interface)['displayName']
        interface_newContent = interface.replace(display_name, '{}-Updated'.format(display_name))
        interface_newContent = interface_newContent.replace('\n', '')
        fo = open(self.kwargs['interface-updated'], "w+", encoding='utf-8')
        fo.write(interface_newContent)
        fo.close()
        self.cmd('iot pnp interface update -e {endpoint} -r {repo} --def {interface-updated}', checks=self.is_empty())

        # Todo: Publish Interface
        self.cmd('iot pnp interface publish -e {endpoint} -r {repo} -i {interface_id}', checks=self.is_empty())

        # Success: Delete Interface
        self.cmd('iot pnp interface delete -e {endpoint} -r {repo} -i {interface_id}', checks=self.is_empty())

    def test_model_life_cycle(self):

        # Checking the Capability-Model list
        self.cmd('iot pnp capability-model list -e {endpoint} -r {repo}',
                 checks=[self.check('length([*])', 0)])

        # Error: missing repo-id or login
        self.cmd('iot pnp capability-model create -e {endpoint} --def {model}', expect_failure=True)

        # Error: Invalid Capability-Model definition file
        self.cmd('iot pnp capability-model create -e {endpoint} -r {repo} --def model', expect_failure=True)

        # Error: wrong path of Capability-Model definition
        self.cmd('iot pnp capability-model create -e {endpoint} -r {repo} --def model.json', expect_failure=True)

        # Success: Create new Capability-Model
        self.cmd('iot pnp capability-model create -e {endpoint} -r {repo} --def {model}', checks=self.is_empty())

        # Checking the Capability-Model list
        self.cmd('iot pnp capability-model list -e {endpoint} -r {repo}',
                 checks=[self.check('length([*])', 1)])

        # Get Capability-Model
        model = self.cmd('iot pnp capability-model show -e {endpoint} -r {repo} -m {model_id}').get_output_in_json()
        assert json.dumps(model)
        assert model['@id'] == self.kwargs['model_id']
        assert len(model['implements']) > 0

        # Success: Update Capability-Model
        model = str(read_file_content(self.kwargs['model']))
        display_name = json.loads(model)['displayName']
        model_newContent = model.replace(display_name, '{}-Updated'.format(display_name))
        model_newContent = model_newContent.replace('\n', '')
        fo = open(self.kwargs['model-updated'], "w+", encoding='utf-8')
        fo.write(model_newContent)
        fo.close()
        self.cmd('iot pnp capability-model update -e {endpoint} -r {repo} --def {model-updated}', checks=self.is_empty())

        # Todo: Publish Capability-Model
        self.cmd('iot pnp capability-model publish -e {endpoint} -r {repo} -m {model_id}', checks=self.is_empty())

        # Success: Delete Capability-Model
        self.cmd('iot pnp capability-model delete -e {endpoint} -r {repo} -m {model_id}', checks=self.is_empty())
