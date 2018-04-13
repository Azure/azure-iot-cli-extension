# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import os
from uuid import uuid4
from azext_iot._constants import EVENT_LIB
from azext_iot.operations import hub as subject
from azext_iot.common.utility import evaluate_literal
from knack.util import CLIError
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azure.cli.core.util import read_file_content


device_id = 'mydevice'
module_id = 'mymod'
config_id = 'myconfig'

hub_entity = 'myhub.azure-devices.net'

mock_target = {}
mock_target['entity'] = hub_entity
mock_target['primarykey'] = 'rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['secondarykey'] = 'aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['policy'] = 'iothubowner'
mock_target['subscription'] = "5952cff8-bcd1-4235-9554-af2c0348bf23"

generic_cs_template = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


def generate_cs(hub=hub_entity, policy=mock_target['policy'], key=mock_target['primarykey']):
    return generic_cs_template.format(hub, policy, key)


mock_target['cs'] = generate_cs()

# Patch Paths #
path_mqtt_client = 'azext_iot.operations._mqtt.mqtt.Client'
path_service_client = 'msrest.service_client.ServiceClient.send'
path_ghcs = 'azext_iot.operations.hub.get_iot_hub_connection_string'
path_iot_hub_service_factory = 'azext_iot.common.azure.iot_hub_service_factory'
path_sas = 'azext_iot._factory.SasTokenAuthentication'


@pytest.fixture()
def fixture_cmd(mocker):
    # Placeholder for later use
    mocker.patch(path_iot_hub_service_factory)
    cmd = mocker.MagicMock(name='cli cmd context')
    return cmd


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker.patch(path_ghcs)
    ghcs.return_value = mock_target
    return ghcs


@pytest.fixture()
def fixture_sas(mocker):
    r = SasTokenAuthentication(mock_target['entity'], mock_target['policy'], mock_target['primarykey'])
    sas = mocker.patch(path_sas)
    sas.return_value = r
    return sas


@pytest.fixture(params=[400, 401, 500])
def serviceclient_generic_error(mocker, fixture_ghcs, fixture_sas, request):
    service_client = mocker.patch(path_service_client)
    response = mocker.MagicMock(name='response')
    response.status_code = request.param
    service_client.return_value = response
    return service_client


@pytest.fixture()
def mqttclient_generic_error(mocker, fixture_ghcs, fixture_sas):
    mqtt_client = mocker.patch(path_mqtt_client)
    mqtt_client().connect.side_effect = Exception('something happened')
    return mqtt_client


def generate_device_create_req(ee=True, auth='shared_private_key', ptp='123',
                               stp='321', status='enabled', status_reason=None,
                               valid_days=None, output_dir=None):
    return {'client': None, 'device_id': device_id,
            'hub_name': mock_target['entity'], 'ee': ee, 'auth': auth,
            'ptp': ptp, 'stp': stp, 'status': status, 'status_reason': status_reason,
            'valid_days': valid_days, 'output_dir': output_dir}


class TestDeviceCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_create_req()),
        (generate_device_create_req(auth='x509_ca')),
        (generate_device_create_req(auth='x509_thumbprint')),
        (generate_device_create_req(auth='x509_thumbprint', stp=None)),
        (generate_device_create_req(auth='x509_thumbprint', ptp=None, stp=None, valid_days=30)),
        (generate_device_create_req(status='disabled', status_reason='reasons'))
    ])
    def test_device_create(self, serviceclient, req):
        subject.iot_device_create(None, req['device_id'], req['hub_name'],
                                  req['ee'], req['auth'], req['ptp'], req['stp'], req['status'],
                                  req['status_reason'], req['valid_days'], req['output_dir'])

        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target['entity'], device_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['deviceId'] == req['device_id']
        assert body['status'] == req['status']
        if req.get('status_reason'):
            assert body['statusReason'] == req['status_reason']
        assert body['capabilities']['iotEdge'] == req['ee']

        if req['auth'] == 'shared_private_key':
            assert body['authentication']['type'] == 'sas'
        elif req['auth'] == 'x509_ca':
            assert body['authentication']['type'] == 'certificateAuthority'
            assert not body['authentication'].get('x509Thumbprint')
            assert not body['authentication'].get('symmetricKey')
        elif req['auth'] == 'x509_thumbprint':
            assert body['authentication']['type'] == 'selfSigned'
            x509tp = body['authentication']['x509Thumbprint']
            assert x509tp['primaryThumbprint']
            if req['stp'] is None:
                assert x509tp.get('secondaryThumbprint') is None
            else:
                assert x509tp['secondaryThumbprint']

    @pytest.mark.parametrize("req, exp", [
        (generate_device_create_req(auth='doesnotexist'), ValueError),
        (generate_device_create_req(auth='x509_thumbprint', ptp=None, stp=''), ValueError)
    ])
    def test_device_create_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_create(None, req['device_id'], req['hub_name'],
                                      req['ee'], req['auth'], req['ptp'], req['stp'], req['status'])

    @pytest.mark.parametrize("req", [
        (generate_device_create_req())
    ])
    def test_device_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_create(None, req['device_id'], req['hub_name'],
                                      req['ee'], req['auth'], req['ptp'], req['stp'], req['status'])


def generate_device_show(**kvp):
    payload = {'authentication': {'symmetricKey': {'primaryKey': '123', 'secondaryKey': '321'},
                                  'type': 'sas'}, 'etag': 'abcd', 'capabilities': {'iotEdge': True},
               'deviceId': device_id, 'status': 'disabled'}
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


class TestDeviceUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_show(authentication={'symmetricKey': {'primaryKey': '', 'secondaryKey': ''}, 'type': 'sas'})),
        (generate_device_show(authentication={'x509Thumbprint': {'primaryThumbprint': '123', 'secondaryThumbprint': '321'},
                                              'type': 'selfSigned'})),
        (generate_device_show(authentication={'type': 'certificateAuthority'}))
    ])
    def test_device_update(self, fixture_cmd, serviceclient, req):
        subject.iot_device_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)
        args = serviceclient.call_args
        assert "{}/devices/{}?".format(mock_target['entity'], device_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['deviceId'] == req['deviceId']
        assert body['status'] == req['status']
        assert body['capabilities']['iotEdge'] == req['capabilities']['iotEdge']
        assert req['authentication']['type'] == body['authentication']['type']
        if req['authentication']['type'] == 'certificateAuthority':
            assert not body['authentication'].get('x509Thumbprint')
            assert not body['authentication'].get('symmetricKey')
        elif req['authentication']['type'] == 'selfSigned':
            assert body['authentication']['x509Thumbprint']['primaryThumbprint']
            assert body['authentication']['x509Thumbprint']['secondaryThumbprint']
        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(req['etag'])

    @pytest.mark.parametrize("req, exp", [
        (generate_device_show(authentication={'x509Thumbprint': {'primaryThumbprint': '',
                                                                 'secondaryThumbprint': ''}, 'type': 'selfSigned'}), ValueError),
        (generate_device_show(authentication={'type': 'doesnotexist'}), ValueError),
        (generate_device_show(etag=None), LookupError)
    ])
    def test_device_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_show())
    ])
    def test_device_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)


class TestDeviceDelete():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("etag", [{'etag': 'abcd'}])
    def test_device_delete(self, serviceclient, etag):
        serviceclient.return_value.text = json.dumps(etag)
        subject.iot_device_delete(None, device_id, mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert '{}/devices/{}?'.format(mock_target['entity'], device_id) in url
        assert args[0][0].method == 'DELETE'
        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(etag['etag'])

    @pytest.mark.parametrize("etag, exp", [({'etag': ''}, LookupError), ({}, LookupError)])
    def test_device_delete_invalid_args(self, serviceclient, etag, exp):
        serviceclient.return_value.text = json.dumps(etag)
        with pytest.raises(exp):
            subject.iot_device_delete(None, device_id, mock_target['entity'])

    def test_device_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_delete(None, device_id, mock_target['entity'])


class TestDeviceShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_device_show())
        service_client.return_value = response
        return service_client

    def test_device_show(self, serviceclient):
        result = subject.iot_device_show(None, device_id, mock_target['entity'])
        assert json.dumps(result)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert 'devices/{}?'.format(device_id) in url
        assert method == 'GET'

    def test_device_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_show(None, device_id, mock_target['entity'])


class TestDeviceList():
    @pytest.fixture(params=[(200, 10), (200, 0)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param[0]
        del response._attribute_map
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_show())
        service_client.expected_size = size
        response.text = json.dumps(result)
        response.headers = {'x-ms-continuation': None}
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("top, edge", [(10, True), (1000, False)])
    def test_device_list(self, serviceclient, top, edge):
        result = subject.iot_device_list(None, mock_target['entity'], top, edge)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]
        assert '{}/devices/query?'.format(mock_target['entity']) in url

        if edge:
            assert body['query'] == 'select * from devices where capabilities.iotEdge = true'
        else:
            assert body['query'] == 'select * from devices'

        assert method == 'POST'

        assert json.dumps(result)
        assert len(result) == serviceclient.expected_size

        headers = args[0][1]
        assert headers['x-ms-max-item-count'] == str(top)

    @pytest.mark.parametrize("top", [-1, 0])
    def test_device_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_device_list(None, mock_target['entity'], top)

    def test_device_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_list(None, mock_target['entity'])


def generate_module_create_req(mid=module_id, auth='shared_private_key', ptp='123', stp='321'):
    r = generate_device_create_req(auth=auth, ptp=ptp, stp=stp)
    r['module_id'] = mid
    return r


class TestDeviceModuleCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_module_create_req(auth='shared_private_key')),
        (generate_module_create_req(auth='x509_ca')),
        (generate_module_create_req(auth='x509_thumbprint'))
    ])
    def test_device_module_create(self, serviceclient, req):
        subject.iot_device_module_create(fixture_cmd, req['device_id'], hub_name=req['hub_name'],
                                         module_id=req['module_id'])
        args = serviceclient.call_args
        assert "{}/devices/{}/modules/{}?".format(mock_target['entity'], device_id, module_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['deviceId'] == req['device_id']
        assert body['moduleId'] == req['module_id']

        if req['auth'] == 'shared_private_key':
            assert body['authentication']['type'] == 'sas'

    @pytest.mark.parametrize("req", [
        (generate_module_create_req())
    ])
    def test_device_module_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_create(fixture_cmd, req['device_id'], hub_name=req['hub_name'], module_id=req['module_id'])


def generate_device_module_show(**kvp):
    payload = generate_device_show(**kvp)
    payload['moduleId'] = module_id
    return payload


class TestDeviceModuleUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_module_show(authentication={'symmetricKey': {'primaryKey': '', 'secondaryKey': ''}, 'type': 'sas'})),
        (generate_device_module_show(authentication={'x509Thumbprint': {'primaryThumbprint': '123', 'secondaryThumbprint': '321'},
                                                     'type': 'selfSigned'})),
        (generate_device_module_show(authentication={'type': 'certificateAuthority'}))
    ])
    def test_device_module_update(self, serviceclient, req):
        subject.iot_device_module_update(fixture_cmd, req['deviceId'], module_id=req['moduleId'],
                                         hub_name=mock_target['entity'], parameters=req)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert '{}/devices/{}/modules/{}?'.format(mock_target['entity'], device_id, module_id) in url
        assert method == 'PUT'
        assert body['deviceId'] == req['deviceId']
        assert body['moduleId'] == req['moduleId']
        assert not body.get('capabilities')
        assert req['authentication']['type'] == body['authentication']['type']
        if req['authentication']['type'] == 'certificateAuthority':
            assert not body['authentication'].get('x509Thumbprint')
            assert not body['authentication'].get('symmetricKey')
        elif req['authentication']['type'] == 'selfSigned':
            assert body['authentication']['x509Thumbprint']['primaryThumbprint']
            assert body['authentication']['x509Thumbprint']['secondaryThumbprint']
        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(req['etag'])

    @pytest.mark.parametrize("req, exp", [
        (generate_device_module_show(authentication={'x509Thumbprint': {'primaryThumbprint': '', 'secondaryThumbprint': ''},
                                                     'type': 'selfSigned'}), ValueError),
        (generate_device_module_show(authentication={'type': 'doesnotexist'}), ValueError),
        (generate_device_module_show(etag=None), LookupError)
    ])
    def test_device_module_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_module_update(fixture_cmd, req['deviceId'], module_id=req['moduleId'],
                                             hub_name=mock_target['entity'], parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_module_show())
    ])
    def test_device_module_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'],
                                             module_id=req['moduleId'], parameters=req)


class TestDeviceModuleDelete():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        del response._attribute_map
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("etag", [{'etag': 'abcd'}])
    def test_device_module_delete(self, serviceclient, etag):
        serviceclient.return_value.text = json.dumps(etag)
        subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert 'devices/{}/modules/{}?'.format(device_id, module_id) in url
        assert method == 'DELETE'
        assert headers['If-Match'] == '"{}"'.format(etag['etag'])

    @pytest.mark.parametrize("etag, exp", [({'etag': ''}, LookupError), ({}, LookupError)])
    def test_device_module_invalid_args(self, serviceclient, etag, exp):
        serviceclient.return_value.text = json.dumps(etag)
        with pytest.raises(exp):
            subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])

    def test_device_module_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])


class TestDeviceModuleShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_device_module_show())
        service_client.return_value = response
        return service_client

    def test_device_module_show(self, serviceclient):
        result = subject.iot_device_module_show(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])
        assert json.dumps(result)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert 'devices/{}/modules/{}?'.format(device_id, module_id) in url
        assert method == 'GET'

    def test_device_module_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_show(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])


class TestDeviceModuleList():
    @pytest.fixture(params=[(200, 10), (200, 0)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param[0]
        del response._attribute_map
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_module_show())
        service_client.expected_size = size
        response.text = json.dumps(result)
        response.headers = {'x-ms-continuation': None}
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("top", [10, 1000])
    def test_device_module_list(self, serviceclient, top):
        result = subject.iot_device_module_list(fixture_cmd, device_id, hub_name=mock_target['entity'], top=top)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]
        headers = args[0][1]

        assert method == 'POST'
        assert '{}/devices/query?'.format(mock_target['entity']) in url
        assert body['query'] == "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
        assert json.dumps(result)
        assert len(result) == serviceclient.expected_size
        assert headers['x-ms-max-item-count'] == str(top)

    @pytest.mark.parametrize("top", [-1, 0])
    def test_device_module_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_device_module_list(fixture_cmd, device_id, hub_name=mock_target['entity'], top=top)

    def test_device_module_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_list(fixture_cmd, device_id, hub_name=mock_target['entity'])


def change_dir():
    from inspect import getsourcefile
    import os
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


def generate_device_config(file_handle=False, condition='', priority=2, labels='{"key1":"value1"}', etag='abcd'):
    result = {}
    change_dir()
    path = 'test_config_content.json'

    if file_handle:
        result['content'] = path
    else:
        result['content'] = str(read_file_content(path))

    result['priority'] = priority
    result['condition'] = condition
    result['labels'] = labels
    result['etag'] = etag
    result['id'] = config_id

    # Update uses json params from get/show instead of cli params for create
    result['targetCondition'] = condition

    return result


class TestConfigCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config()),
        (generate_device_config(True)),
        (generate_device_config(condition="tags.building=43 and tags.environment='test'", priority=5)),
        (generate_device_config(labels='{"special":"value"}')),
    ])
    def test_config_create(self, serviceclient, req):
        subject.iot_device_configuration_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                content=req['content'], target_condition=req['condition'],
                                                priority=req['priority'], labels=req['labels'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert method == 'PUT'
        assert body['id'] == config_id

        if os.path.exists(req['content']):
            req['content'] = str(read_file_content(req['content']))

        assert body['content'] == json.loads(req['content'])['content']
        assert body['contentType'] == 'assignments'
        assert body.get('targetCondition') == req.get('condition')
        assert body.get('priority') == req.get('priority')
        assert body.get('labels') == evaluate_literal(req.get('labels'), dict)

    @pytest.mark.parametrize('req, arg', [
        (generate_device_config(), 'mangle'),
    ])
    def test_config_create_invalid_args(self, serviceclient, req, arg):
        with pytest.raises(CLIError):
            if arg == 'mangle':
                req['content'] = req['content'].replace('"content":', '"config":')
            subject.iot_device_configuration_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                    content=req['content'], target_condition=req['condition'],
                                                    priority=req['priority'], labels=req['labels'])

    @pytest.mark.parametrize("req", [
        (generate_device_config())
    ])
    def test_config_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                    content=req['content'], target_condition=req['condition'],
                                                    priority=req['priority'], labels=req['labels'])


class TestConfigUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config()),
        (generate_device_config(condition="tags.building=9 and tags.environment='Dev'", priority=1000)),
        (generate_device_config(labels=evaluate_literal('{"special":"value"}', dict))),
    ])
    def test_config_update(self, serviceclient, req):
        subject.iot_device_configuration_update(fixture_cmd, config_id=config_id,
                                                hub_name=mock_target['entity'], parameters=req)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert method == 'PUT'
        assert body['id'] == config_id

        assert body['content'] == req['content']
        assert body['contentType'] == 'assignments'
        assert body.get('targetCondition') == req.get('targetCondition')
        assert body.get('priority') == req.get('priority')
        assert body.get('labels') == req.get('labels')
        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(req['etag'])

    @pytest.mark.parametrize("req", [
        (generate_device_config(etag='')),
        (generate_device_config())
    ])
    def test_config_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_update(fixture_cmd, config_id=config_id,
                                                    hub_name=mock_target['entity'], parameters=req)


class TestConfigShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_device_config())
        service_client.return_value = response
        return service_client

    def test_config_show(self, serviceclient):
        result = subject.iot_device_configuration_show(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])

        assert result['id'] == config_id
        assert result == generate_device_config()
        assert json.dumps(result)

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert method == 'GET'

    def test_config_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_show(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])


class TestConfigList():
    @pytest.fixture(params=[(200, 10), (200, 0)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param[0]
        del response._attribute_map
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(json.loads(generate_device_config()['content']))
        service_client.expected_size = size
        response.text = json.dumps(result)
        response.headers = {'x-ms-continuation': None}
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("top", [10, 1000])
    def test_config_list(self, serviceclient, top):
        result = subject.iot_device_configuration_list(fixture_cmd, hub_name=mock_target['entity'], top=top)
        args = serviceclient.call_args
        url = args[0][0].url
        assert json.dumps(result)
        assert len(result) == serviceclient.expected_size
        assert '{}/configurations?'.format(mock_target['entity']) in url
        assert 'top={}'.format(top) in url

    @pytest.mark.parametrize("top", [-1, 0])
    def test_config_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_list(fixture_cmd, hub_name=mock_target['entity'], top=top)

    def test_config_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_list(fixture_cmd, hub_name=mock_target['entity'])


class TestConfigDelete():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        del response._attribute_map
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("etag", [{'etag': 'abcd'}])
    def test_config_delete(self, serviceclient, etag):
        serviceclient.return_value.text = json.dumps(etag)
        subject.iot_device_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert method == 'DELETE'
        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert headers['If-Match'] == '"{}"'.format(etag['etag'])

    @pytest.mark.parametrize("etag, exp", [({'etag': ''}, LookupError), ({}, LookupError)])
    def test_config_delete_invalid_args(self, serviceclient, etag, exp):
        serviceclient.return_value.text = json.dumps(etag)
        with pytest.raises(exp):
            subject.iot_device_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])

    def test_config_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])


def build_mock_response(mocker, status_code=200, payload=None, headers=None):
    response = mocker.MagicMock(name='response')
    response.status_code = status_code
    response.text = json.dumps(payload)
    if headers:
        response.headers = headers
    del response._attribute_map
    return response


class TestConfigApply():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.side_effect = [build_mock_response(mocker),
                                      build_mock_response(mocker, payload=[], headers={'x-ms-continuation': None})]
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config())
    ])
    def test_config_apply(self, serviceclient, req):
        result = subject.iot_device_configuration_apply(fixture_cmd, device_id,
                                                        hub_name=mock_target['entity'], content=req['content'])
        args = serviceclient.call_args_list[0]
        body = args[0][2]
        payload = json.loads(req['content'])
        assert body['moduleContent'] == payload['content']['moduleContent']
        mod_list_args = serviceclient.call_args_list[1]
        mod_list_body = mod_list_args[0][2]
        assert mod_list_body['query'] == "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
        assert result is not None

    @pytest.mark.parametrize('req, arg', [
        (generate_device_config(), 'mangle'),
    ])
    def test_config_apply_invalid_args(self, serviceclient, req, arg):
        with pytest.raises(CLIError):
            if arg == 'mangle':
                req['content'] = req['content'].replace('"moduleContent":', '"somethingelse":')
            subject.iot_device_configuration_apply(fixture_cmd, device_id,
                                                   hub_name=mock_target['entity'], content=req['content'])

    @pytest.mark.parametrize("req", [
        (generate_device_config())
    ])
    def test_config_apply_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_configuration_apply(fixture_cmd, device_id,
                                                   hub_name=mock_target['entity'], content=req['content'])


def generate_device_twin_show(file_handle=False, **kvp):
    if file_handle:
        change_dir()
        path = os.path.realpath('test_generic_twin.json')
        return path

    payload = {"deviceId": device_id, "etag": "abcd"}
    for k in kvp:
        payload[k] = kvp[k]
    return payload


class TestDeviceTwinShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps([generate_device_twin_show()])
        response.headers = {'x-ms-continuation': None}
        service_client.return_value = response
        return service_client

    def test_device_twin_show(self, serviceclient):
        result = subject.iot_device_twin_show(None, device_id, mock_target['entity'])
        args = serviceclient.call_args
        body = args[0][2]
        assert json.dumps(result)
        assert body['query'] == "SELECT * FROM devices where devices.deviceId='{}'".format(device_id)

    def test_device_twin_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_twin_show(None, device_id, mock_target['entity'])


class TestDeviceTwinUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_twin_show()),
        (generate_device_twin_show(properties={"desired": {"key": "value"}}))
    ])
    def test_device_twin_update(self, serviceclient, req):
        subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert 'twins/{}'.format(device_id) in args[0][0].url

    @pytest.mark.parametrize("req, exp", [
        (generate_device_show(etag=None), LookupError)
    ])
    def test_device_twin_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_show())
    ])
    def test_device_twin_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)


class TestDeviceTwinReplace():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        del response._attribute_map
        response.text = json.dumps(generate_device_twin_show(moduleId=module_id))
        service_client.return_value = response
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize("req, isfile", [
        (generate_device_twin_show(moduleId=module_id), False),
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}), False),
        (generate_device_twin_show(True), True)
    ])
    def test_device_twin_replace(self, serviceclient, req, isfile):
        if not isfile:
            req = json.dumps(req)
        subject.iot_device_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'], target_json=req)
        args = serviceclient.call_args
        body = args[0][2]
        if isfile:
            content = str(read_file_content(req))
            assert body == json.loads(content)
        else:
            assert body == json.loads(req)
        assert '{}/twins/{}?'.format(mock_target['entity'], device_id, module_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(moduleId=module_id, etag=None), LookupError),
        ({'invalid': 'payload'}, LookupError)
    ])
    def test_device_twin_replace_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            serviceclient.return_value.text = json.dumps(req)
            subject.iot_device_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                            target_json=json.dumps(req))

    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(moduleId=module_id))
    ])
    def test_device_twin_replace_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                            target_json=json.dumps(req))


class TestDeviceModuleTwinShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_device_twin_show())
        service_client.return_value = response
        return service_client

    def test_device_module_twin_show(self, serviceclient):
        result = subject.iot_device_module_twin_show(fixture_cmd, device_id, hub_name=mock_target['entity'], module_id=module_id)
        args = serviceclient.call_args
        assert 'twins/{}'.format(device_id) in args[0][0].url
        assert 'modules/{}'.format(module_id) in args[0][0].url
        assert json.dumps(result)

    def test_device_module_twin_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_show(fixture_cmd, device_id, hub_name=mock_target['entity'], module_id=module_id)


class TestDeviceModuleTwinUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(moduleId=module_id)),
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}))
    ])
    def test_device_module_twin_update(self, serviceclient, req):
        subject.iot_device_module_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'],
                                              module_id=module_id, parameters=req)
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert 'twins/{}'.format(req['deviceId']) in args[0][0].url
        assert 'modules/{}?'.format(module_id) in args[0][0].url

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(moduleId=module_id, etag=None), LookupError)
    ])
    def test_device_module_twin_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_module_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'],
                                                  module_id=module_id, parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(moduleId=module_id))
    ])
    def test_device_module_twin_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'],
                                                  module_id=module_id, parameters=req)


class TestDeviceModuleTwinReplace():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        del response._attribute_map
        response.text = json.dumps(generate_device_twin_show(moduleId=module_id))
        service_client.return_value = response
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize("req, isfile", [
        (generate_device_twin_show(moduleId=module_id), False),
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}), False),
        (generate_device_twin_show(True), True)
    ])
    def test_device_module_twin_replace(self, serviceclient, req, isfile):
        if not isfile:
            req = json.dumps(req)
        subject.iot_device_module_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                               module_id=module_id, target_json=req)
        args = serviceclient.call_args
        body = args[0][2]
        if isfile:
            content = str(read_file_content(req))
            assert body == json.loads(content)
        else:
            assert body == json.loads(req)
        assert 'twins/{}/modules/{}?'.format(device_id, module_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(moduleId=module_id, etag=None), LookupError),
        ({'invalid': 'payload'}, LookupError)
    ])
    def test_device_module_twin_replace_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            serviceclient.return_value.text = json.dumps(req)
            subject.iot_device_module_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                                   module_id=module_id, target_json=json.dumps(req))

    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(moduleId=module_id))
    ])
    def test_device_module_twin_replace_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_module_twin_replace(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                                   module_id=module_id, target_json=json.dumps(req))


generic_query = 'select * from devices'


class TestQuery():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        del response._attribute_map
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("query, servresult, servtotal, top", [
        (generic_query, [generate_device_twin_show()], 6, 3),
        (generic_query, [generate_device_twin_show(), generate_device_twin_show()], 5, 2),
        (generic_query, [generate_device_twin_show(), generate_device_twin_show()], 6, None),
        (generic_query, [generate_device_show() for i in range(0, 12)], 100, 51),
        (generic_query, [generate_device_twin_show()], 1, 100)
    ])
    def test_query_basic(self, serviceclient, query, servresult, servtotal, top):
        serviceclient.return_value.text = json.dumps(servresult)
        pagesize = len(servresult)
        continuation = []

        for i in range(int(servtotal / pagesize)):
            continuation.append({'x-ms-continuation': 'abcd'})
        if servtotal % pagesize != 0:
            continuation.append({'x-ms-continuation': 'abcd'})
        continuation[-1] = None

        serviceclient.return_value.headers.get.side_effect = continuation

        result = subject.iot_query(None, hub_name=mock_target['entity'], query_command=query, top=top)

        if top and top < servtotal:
            targetcount = top
        else:
            targetcount = servtotal

        assert len(result) == targetcount

        if pagesize >= targetcount:
            assert serviceclient.call_count == 1
        else:
            if targetcount % pagesize == 0:
                assert serviceclient.call_count == int(targetcount / pagesize)
            else:
                assert serviceclient.call_count == int(targetcount / pagesize) + 1

        args = serviceclient.call_args_list[0]
        headers = args[0][1]
        body = args[0][2]
        assert body['query'] == query

        if top:
            targetcount = top
            if pagesize < top:
                for i in range(1, len(serviceclient.call_args_list)):
                    headers = serviceclient.call_args_list[i][0][1]
                    targetcount = targetcount - pagesize
                    assert headers['x-ms-max-item-count'] == str(targetcount)
            else:
                assert headers['x-ms-max-item-count'] == str(targetcount)
        else:
            assert not headers.get('x-ms-max-item-count')

    @pytest.mark.parametrize("top", [-1, 0])
    def test_query_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_query(None, mock_target['entity'], generic_query, top)

    def test_query_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_query(None, mock_target['entity'], generic_query)


class TestDeviceMethodInvoke():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps({'payload': 'value', 'status': 0})
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("methodbody", ['{"key":"value"}', None])
    def test_device_method(self, serviceclient, methodbody):
        payload = methodbody
        device_method = 'mymethod'
        timeout = 100
        subject.iot_device_method(fixture_cmd, device_id=device_id, hub_name=mock_target['entity'],
                                  method_name=device_method, method_payload=payload, timeout=timeout)
        args = serviceclient.call_args
        body = args[0][2]
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'POST'
        assert body['methodName'] == device_method

        if methodbody:
            assert body['payload'] == json.loads(payload)
        else:
            assert body.get('payload') is None

        assert body['responseTimeoutInSeconds'] == timeout
        assert body['connectTimeoutInSeconds'] == timeout
        assert '{}/twins/{}/methods?'.format(mock_target['entity'], device_id, module_id) in url

    @pytest.mark.parametrize("req, type, exp", [
        ("badformat", 'payload', CLIError),
        ('{"key":"valu', 'payload', CLIError),
        (1000, 'timeout', CLIError),
        (5, 'timeout', CLIError),
    ])
    def test_device_method_invalid_args(self, serviceclient, req, type, exp):
        with pytest.raises(exp):
            if type == 'payload':
                subject.iot_device_method(fixture_cmd, device_id=device_id, hub_name=mock_target['entity'],
                                          method_name='mymethod', method_payload=req)
            if type == 'timeout':
                subject.iot_device_method(fixture_cmd, device_id=device_id, hub_name=mock_target['entity'],
                                          method_name='mymethod', method_payload='{"key":"value"}', timeout=req)

    def test_device_method_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_method(fixture_cmd, device_id=device_id, hub_name=mock_target['entity'],
                                      method_name='mymethod', method_payload='{"key":"value"}')


class TestDeviceModuleMethodInvoke():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps({'payload': 'value', 'status': 0})
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("methodbody", ['{"key":"value"}', None])
    def test_device_module_method(self, serviceclient, methodbody):
        payload = methodbody
        module_method = 'mymethod'
        timeout = 100
        subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name=module_method,
                                         hub_name=mock_target['entity'], method_payload=payload, timeout=timeout)
        args = serviceclient.call_args
        body = args[0][2]
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'POST'
        assert body['methodName'] == module_method

        if methodbody:
            assert body['payload'] == json.loads(payload)
        else:
            assert body.get('payload') is None

        assert body['responseTimeoutInSeconds'] == timeout
        assert body['connectTimeoutInSeconds'] == timeout
        assert '{}/twins/{}/modules/{}/methods?'.format(mock_target['entity'], device_id, module_id) in url

    @pytest.mark.parametrize("req, type, exp", [
        ("doesnotexist", 'payload', CLIError),
        ('{"key":"valu', 'payload', CLIError),
        (1000, 'timeout', CLIError),
        (5, 'timeout', CLIError),
    ])
    def test_device_module_method_invalid_args(self, serviceclient, req, type, exp):
        with pytest.raises(exp):
            if type == 'payload':
                subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                                 hub_name=mock_target['entity'], method_payload=req)
            if type == 'timeout':
                subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                                 hub_name=mock_target['entity'], method_payload='{"key":"value"}', timeout=req)

    def test_device_method_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                             hub_name=mock_target['entity'], method_payload='{"key":"value"}')


hub_suffix = "awesome-azure.net"


class TestGetIoTHubConnString():
    @pytest.mark.parametrize("hubcount, targethub, policy_name, rg_name, include_events, login, failure_reason", [
        (5, 'hub1', 'iothubowner', None, False, None, None),
        (0, 'hub1', 'iothubowner', None, False, True, None),
        (1, 'hub0', 'iothubowner', None, True, None, None),
        (10, 'hub3', 'custompolicy', 'myrg', False, None, None),
        (1, 'hub0', 'custompolicy', None, False, None, None),
        (3, 'hub4', 'iothubowner', None, False, None, 'subscription'),
        (1, 'hub1', 'iothubowner', 'myrg', False, None, 'policy'),
        (1, 'myhub', 'iothubowner', 'myrg', False, None, 'resource')
    ])
    def test_get_hub_conn_string(self, mocker, hubcount, targethub, policy_name, rg_name, include_events, login, failure_reason):
        from azext_iot.common.azure import get_iot_hub_connection_string

        def _build_hub(hub, name, rg=None):
            hub.name = name
            hub.properties.host_name = "{}.{}".format(name, hub_suffix)
            hub.resourcegroup = rg
            client.config.subscription_id = mock_target['subscription']
            return hub

        def _build_policy(policy, name):
            policy.key_name = name
            policy.primary_key = mock_target['primarykey']
            policy.secondary_key = mock_target['secondarykey']
            return policy

        def _build_event(hub):
            hub.properties.event_hub_endpoints['events'].endpoint = ('sb://' + str(uuid4()))
            hub.properties.event_hub_endpoints['events'].partition_count = '2'
            hub.properties.event_hub_endpoints['events'].path = hub_entity
            hub.properties.event_hub_endpoints['events'].partition_ids = ['0', '1']
            return hub

        cmd = mocker.MagicMock(name='cmd')
        ihsf = mocker.patch(path_iot_hub_service_factory)
        client = mocker.MagicMock(name='hubclient')

        hub_list = []
        for i in range(0, hubcount):
            hub_list.append(_build_hub(mocker.MagicMock(), "hub{}".format(i), rg_name))
        client.list_by_subscription.return_value = hub_list

        if rg_name:
            if failure_reason == "resource":
                client.get.side_effect = ValueError
            else:
                client.get.return_value = _build_hub(mocker.MagicMock(), targethub, rg_name)

        if failure_reason == "policy":
            client.get_keys_for_key_name.side_effect = ValueError
        else:
            client.get_keys_for_key_name.return_value = _build_policy(mocker.MagicMock(), policy_name)

        if include_events:
            _build_event(hub_list[0])

        ihsf.return_value = client

        if not failure_reason:
            if not login:
                result = get_iot_hub_connection_string(cmd, targethub, rg_name, policy_name, include_events=include_events)

                expecting_hub = "{}.{}".format(targethub, hub_suffix)
                assert result['entity'] == expecting_hub
                assert result['policy'] == policy_name
                assert result['resourcegroup'] == rg_name
                assert result['subscription'] == mock_target['subscription']
                assert result['cs'] == generic_cs_template.format(
                    expecting_hub,
                    policy_name,
                    mock_target['primarykey'])

                if rg_name:
                    client.get.assert_called_with(rg_name, targethub)
                client.get_keys_for_key_name.assert_called_with(rg_name, targethub, policy_name)

                if include_events:
                    assert result['events']['endpoint']
                    assert result['events']['partition_count']
                    assert result['events']['path']
                    assert result['events']['partition_ids']
            else:
                hub = str(uuid4())
                policy = str(uuid4())
                key = str(uuid4())
                cs = generate_cs(hub, policy, key)

                result = get_iot_hub_connection_string(cmd, targethub, rg_name, policy_name, login=cs)

                assert result['entity'] == hub
                assert result['policy'] == policy
                assert result['primarykey'] == key
                assert not result.get('resourcegroup')
                assert not result.get('subscription')
                assert result['cs'] == generic_cs_template.format(
                    hub,
                    policy,
                    key)
        else:
            with pytest.raises(CLIError):
                get_iot_hub_connection_string(client, targethub, rg_name, policy_name)


sample_c2d_receive = {
    "iothub-ack": "full",
    "iothub-correlationid": "",
    "iothub-deliverycount": "0",
    "iothub-enqueuedtime": "12/22/2017 12:14:12 AM",
    "ETag": '"3k28zb44-0d00-4ddd-ade3-6110eb94c476"',
    "iothub-expiry": "",
    "iothub-messageid": "13z9ag46-d0z4-4527-36cf-0144d87fe32e",
    "iothub-sequencenumber": "1",
    "iothub-to": "/devices/sensor1/messages/deviceBound",
    "iothub-userid": ""
}


class TestDeviceMessaging():
    @pytest.fixture
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        service_client.return_value = response
        return service_client

    def test_c2d_receive(self, serviceclient):
        data = "sample data"
        serviceclient.return_value.status_code = 200
        serviceclient.return_value.headers = sample_c2d_receive
        serviceclient.return_value.content = data
        timeout = 120
        result = subject.iot_c2d_message_receive(None, device_id, mock_target['entity'], timeout)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert method == 'GET'
        assert '{}/devices/{}/messages/devicebound?'.format(mock_target['entity'], device_id) in url
        assert headers['IotHub-MessageLockTimeout'] == str(timeout)

        assert result['ack'] == sample_c2d_receive['iothub-ack']
        assert result['correlationId'] == sample_c2d_receive['iothub-correlationid']
        assert result['data'] == data
        assert result['deliveryCount'] == sample_c2d_receive['iothub-deliverycount']
        assert result['enqueuedTime'] == sample_c2d_receive['iothub-enqueuedtime']
        assert result['etag'] == sample_c2d_receive['ETag'].strip('"')
        assert result['expiry'] == sample_c2d_receive['iothub-expiry']
        assert result['messageId'] == sample_c2d_receive['iothub-messageid']
        assert result['sequenceNumber'] == sample_c2d_receive['iothub-sequencenumber']
        assert result['to'] == sample_c2d_receive['iothub-to']
        assert result['userId'] == sample_c2d_receive['iothub-userid']

    def test_c2d_complete(self, serviceclient):
        etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
        serviceclient.return_value.status_code = 204
        result = subject.iot_c2d_message_complete(fixture_cmd, device_id, etag, hub_name=mock_target['entity'])

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert result is None
        assert method == 'DELETE'
        assert '{}/devices/{}/messages/devicebound/{}?'.format(mock_target['entity'], device_id, etag) in url

    def test_c2d_reject(self, serviceclient):
        etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
        serviceclient.return_value.status_code = 204
        result = subject.iot_c2d_message_reject(fixture_cmd, device_id, etag, hub_name=mock_target['entity'])

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert result is None
        assert method == 'DELETE'
        assert '{}/devices/{}/messages/devicebound/{}?'.format(mock_target['entity'], device_id, etag) in url
        assert 'reject=' in url

    def test_c2d_abandon(self, serviceclient):
        etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
        serviceclient.return_value.status_code = 204
        result = subject.iot_c2d_message_abandon(fixture_cmd, device_id, etag, hub_name=mock_target['entity'])

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert result is None
        assert method == 'POST'
        assert '{}/devices/{}/messages/devicebound/{}/abandon?'.format(mock_target['entity'], device_id, etag) in url

    def test_c2d_errors(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_c2d_message_receive(fixture_cmd, device_id, hub_name=mock_target['entity'])
            subject.iot_c2d_message_abandon(fixture_cmd, device_id, hub_name=mock_target['entity'], etag='')
            subject.iot_c2d_message_complete(fixture_cmd, device_id, hub_name=mock_target['entity'], etag='')
            subject.iot_c2d_message_reject(fixture_cmd, device_id, hub_name=mock_target['entity'], etag='')


class TestSasTokenAuth():
    def test_generate_sas_token(self):
        # Prepare parameters
        uri = 'iot-hub-for-test.azure-devices.net/devices/iot-device-for-test'
        policy_name = 'iothubowner'
        access_key = '+XLy+MVZ+aTeOnVzN2kLeB16O+kSxmz6g3rS6fAf6rw='
        expiry = 1471940363

        # Action
        sas_auth = SasTokenAuthentication(uri, policy_name, access_key, expiry)
        token = sas_auth.generate_sas_token()

        # Assertion
        assert 'SharedAccessSignature ' in token
        assert 'sig=SIumZ1ACqqPJZ2okHDlW9MSYKykEpqsQY3z6FMOICd4%3D' in token
        assert 'se=1471940363' in token
        assert 'sr=iot-hub-for-test.azure-devices.net%2Fdevices%2Fiot-device-for-test' in token
        assert 'skn=iothubowner' in token

        # Prepare parameters
        uri = 'iot-hub-for-test.azure-devices.net'

        # Action
        sas_auth = SasTokenAuthentication(uri, None, access_key, expiry)
        token = sas_auth.generate_sas_token()

        # Assertion
        assert ('SharedAccessSignature sr=iot-hub-for-test.azure-devices.net&'
                'sig=770sPjjYxRYpNz8%2FhEN7XR5XU5KDGYGTinSP8YyeTXw%3D&se=1471940363') == token


class TestDeviceSimulate():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = ""
        service_client.return_value = response
        return service_client

    @pytest.fixture()
    def mqttclient(self, mocker, fixture_ghcs, fixture_sas):
        client = mocker.patch(path_mqtt_client)
        mock_conn = mocker.patch('azext_iot.operations._mqtt.mqtt_client_wrap.is_connected')
        mock_conn.return_value = True
        return client

    @pytest.mark.parametrize("rs, mc, mi, protocol", [
        ('complete', 1, 1, 'http'),
        ('abandon', 2, 1, 'http'),
        ('complete', 3, 1, 'mqtt'),
    ])
    def test_device_simulate(self, serviceclient, mqttclient, rs, mc, mi, protocol):
        subject.iot_simulate_device(fixture_cmd, device_id, mock_target['entity'],
                                    receive_settle=rs, msg_count=mc, msg_interval=mi, protocol_type=protocol)
        if protocol == 'http':
            args = serviceclient.call_args_list
            result = [d2c_calls for calls in args for d2c_calls in calls if len(d2c_calls) > 0 and d2c_calls[0].method == 'POST']
            assert len(result) == mc
        if protocol == 'mqtt':
            assert mc == mqttclient().publish.call_count
            assert mqttclient().publish.call_args[0][0] == 'devices/{}/messages/events/'.format(device_id)
            assert 1 == mqttclient().tls_set.call_count
            assert 1 == mqttclient().username_pw_set.call_count

    @pytest.mark.parametrize("rs, mc, mi, protocol, exception", [
        ('reject', 4, 0, 'mqtt', CLIError),
        ('complete', 0, 1, 'mqtt', CLIError)
    ])
    def test_device_simulate_invalid_args(self, serviceclient, rs, mc, mi, protocol, exception):
        with pytest.raises(exception):
            subject.iot_simulate_device(fixture_cmd, device_id, hub_name=mock_target['entity'],
                                        receive_settle=rs, msg_count=mc, msg_interval=mi, protocol_type=protocol)

    def test_device_simulate_http_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_simulate_device(fixture_cmd, device_id, hub_name=mock_target['entity'], protocol_type='http')

    def test_device_simulate_mqtt_error(self, mqttclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_simulate_device(fixture_cmd, device_id, hub_name=mock_target['entity'])


@pytest.mark.skipif(True, reason='not ready')
class TestMonitorEvents():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        existing_target = fixture_ghcs.return_value
        existing_target['events'] = {}
        existing_target['events']['partition_ids'] = []
        return service_client

    @pytest.fixture()
    def uamqp_scenario(self, mocker, request):
        get_uamqp = mocker.patch('azext_iot.common.config.get_uamqp_ext_version')
        update_uamqp = mocker.patch('azext_iot.common.config.update_uamqp_ext_version')
        installer = mocker.patch('azext_iot.common.pip.install')
        installer.return_value = True
        get_uamqp.return_value = EVENT_LIB[1]
        test_import = mocker.patch('azext_iot.common.utility.test_import')
        test_import.return_value = True
        m_exit = mocker.patch('sys.exit')

        return {'get_uamqp': get_uamqp, 'update_uamqp': update_uamqp,
                'installer': installer, 'test_import': test_import, 'exit': m_exit}

    @pytest.mark.parametrize("timeout, exception", [
        (-1, CLIError),
    ])
    def test_monitor_events_invalid_args(self, fixture_cmd, serviceclient, timeout, exception):
        with pytest.raises(exception):
            subject.iot_hub_monitor_events(fixture_cmd, mock_target['entity'], device_id, timeout=timeout)

    @pytest.mark.parametrize("pymajor, pyminor, exception", [
        (3, 3, SystemExit),
        (3, 4, SystemExit),
        (2, 7, SystemExit)
    ])
    def test_monitor_events_invalid_python(self, fixture_cmd, serviceclient, mocker, pymajor, pyminor, exception):
        version_mock = mocker.patch('azext_iot.common.utility.sys.version_info')
        version_mock.major = pymajor
        version_mock.minor = pyminor

        with pytest.raises(exception):
            subject.iot_hub_monitor_events(fixture_cmd, mock_target['entity'], device_id)

    @pytest.mark.parametrize("case, extra_input, external_input", [
        ('importerror', None, 'y'),
        ('importerror', None, 'n'),
        ('importerror', 'yes;', None),
        ('compatibility', None, 'y'),
        ('compatibility', None, 'n'),
        ('compatibility', 'yes;', None),
        ('repair', 'repair;', 'y'),
        ('repair', 'repair;yes;', None),
        ('repair', 'repair;', 'n')
    ])
    def test_monitor_events_uamqp_version(self, mocker, uamqp_scenario, fixture_cmd, serviceclient,
                                          case, extra_input, external_input):
        if case == 'importerror':
            uamqp_scenario['test_import'].return_value = False
        elif case == 'compatibility':
            uamqp_scenario['get_uamqp'].return_value = '0.0.0'

        from functools import partial
        kwargs = {}
        user_cancelled = True
        if extra_input and 'yes;' in extra_input:
            kwargs['yes'] = True
            user_cancelled = False
        if extra_input and 'repair;' in extra_input:
            kwargs['repair'] = True
        if external_input:
            mocked_input = mocker.patch('six.moves.input')
            mocked_input.return_value = external_input
            if external_input.lower() == 'y':
                user_cancelled = False

        method = partial(subject.iot_hub_monitor_events, fixture_cmd, mock_target['entity'], **kwargs)
        method()

        if user_cancelled:
            assert uamqp_scenario['exit'].call_args
        else:
            install_args = uamqp_scenario['installer'].call_args
            assert install_args[0][0] == EVENT_LIB[0]
            assert install_args[1]['compatible_version'] == EVENT_LIB[1]
