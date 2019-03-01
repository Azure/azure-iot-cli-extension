# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=W0613,W0621

import pytest
import json
import copy
import os
import six
from uuid import uuid4
from random import randint
from azext_iot.operations import hub as subject
from azext_iot.common.utility import evaluate_literal, validate_min_python_version
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from knack.util import CLIError
from azure.cli.core.util import read_file_content


device_id = 'mydevice'
child_device_id = 'child_device1'
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
generic_lower_cs_template = 'hostname={};sharedaccesskeyname={};sharedaccesskey={}'


def generate_cs(hub=hub_entity, policy=mock_target['policy'], key=mock_target['primarykey']):
    return generic_cs_template.format(hub, policy, key)


def generate_lower_cs(hub=hub_entity, policy=mock_target['policy'], key=mock_target['primarykey']):
    return generic_lower_cs_template.format(hub, policy, key)


mock_target['cs'] = generate_cs()

# Patch Paths #
path_mqtt_client = 'azext_iot.operations._mqtt.mqtt.Client'
path_service_client = 'msrest.service_client.ServiceClient.send'
path_ghcs = 'azext_iot.operations.hub.get_iot_hub_connection_string'
path_iot_hub_service_factory = 'azext_iot.common._azure.iot_hub_service_factory'
path_sas = 'azext_iot._factory.SasTokenAuthentication'

# TODO generalize all fixtures across DPS/Hub unit tests


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
    service_client.return_value = build_mock_response(mocker, request.param, {'error': 'something failed'})
    return service_client


@pytest.fixture(params=[{'etag': None}, {}])
def serviceclient_generic_invalid_or_missing_etag(mocker, fixture_ghcs, fixture_sas, request):
    service_client = mocker.patch(path_service_client)
    service_client.return_value = build_mock_response(mocker, 200, request.param)
    return service_client


@pytest.fixture()
def mqttclient_generic_error(mocker, fixture_ghcs, fixture_sas):
    mqtt_client = mocker.patch(path_mqtt_client)
    mqtt_client().connect.side_effect = Exception('something happened')
    return mqtt_client


def build_mock_response(mocker, status_code=200, payload=None, headers=None, raw=False):
    response = mocker.MagicMock(name='response')
    response.status_code = status_code
    del response.context
    del response._attribute_map

    if raw:
        response.text = payload
    else:
        response.text.return_value = json.dumps(payload)

    if headers:
        response.headers = headers
    return response


def generate_device_create_req(ee=False, auth='shared_private_key', ptp='123',
                               stp='321', status='enabled', status_reason=None,
                               valid_days=None, output_dir=None, set_parent_id=None,
                               add_children=None, force=False):
    return {'client': None, 'device_id': device_id,
            'hub_name': mock_target['entity'], 'ee': ee, 'auth': auth,
            'ptp': ptp, 'stp': stp, 'status': status, 'status_reason': status_reason,
            'valid_days': valid_days, 'output_dir': output_dir, 'set_parent_id': set_parent_id,
            'add_children': add_children, 'force': force}


class TestDeviceCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_create_req()),
        (generate_device_create_req(ee=True)),
        (generate_device_create_req(auth='x509_ca')),
        (generate_device_create_req(auth='x509_thumbprint')),
        (generate_device_create_req(auth='x509_thumbprint', stp=None)),
        (generate_device_create_req(auth='x509_thumbprint', ptp=None, stp=None, valid_days=30)),
        (generate_device_create_req(status='disabled', status_reason='reasons'))
    ])
    def test_device_create(self, serviceclient, req):
        subject.iot_device_create(fixture_cmd, req['device_id'], req['hub_name'],
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
                assert x509tp['secondaryThumbprint'] == req['stp']

    @pytest.fixture(params=[(200, 200)])
    def sc_device_create_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_create_req(set_parent_id=device_id))
    ])
    def test_device_create_setparent(self, sc_device_create_setparent, req):
        subject.iot_device_create(fixture_cmd, child_device_id, req['hub_name'],
                                  req['ee'], req['auth'], req['ptp'], req['stp'], req['status'],
                                  req['status_reason'], req['valid_days'], req['output_dir'],
                                  req['set_parent_id'])

        args = sc_device_create_setparent.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['deviceId'] == child_device_id
        assert body['deviceScope'] == generate_parent_device().get('deviceScope')

    @pytest.fixture(params=[(200, 0)])
    def sc_invalid_args_device_create_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req, exp", [
        (generate_device_create_req(), CLIError)
    ])
    def test_device_create_setparent_invalid_args(self, sc_invalid_args_device_create_setparent, req, exp):
        with pytest.raises(exp):
            subject.iot_device_create(fixture_cmd, child_device_id, req['hub_name'],
                                      req['ee'], req['auth'], req['ptp'], req['stp'], req['status'],
                                      req['status_reason'], req['valid_days'], req['output_dir'],
                                      device_id)

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_device_create_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        if request.param[1] == 1:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_create_req())
    ])
    def test_device_create_addchildren(self, sc_device_create_addchildren, req):
        subject.iot_device_create(fixture_cmd, req['device_id'], req['hub_name'],
                                  True, req['auth'], req['ptp'], req['stp'], req['status'],
                                  req['status_reason'], req['valid_days'], req['output_dir'],
                                  None, child_device_id, True)

        args = sc_device_create_addchildren.call_args
        url = args[0][0].url
        body = args[0][2]
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'
        assert body['deviceId'] == child_device_id
        assert body['deviceScope'] == generate_parent_device().get('deviceScope')

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_device_create_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        if request.param[1] == 0:
            nonedge_kvp.setdefault('capabilities', {'iotEdge': True})
        if request.param[1] == 1:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req, exp", [
        (generate_device_create_req(), CLIError)
    ])
    def test_device_create_addchildren_invalid_args(self, sc_invalid_args_device_create_addchildren, req, exp):
        with pytest.raises(exp):
            subject.iot_device_create(fixture_cmd, req['device_id'], req['hub_name'],
                                      True, req['auth'], req['ptp'], req['stp'], req['status'],
                                      req['status_reason'], req['valid_days'], req['output_dir'],
                                      None, child_device_id, False)

    @pytest.mark.parametrize("req, exp", [
        (generate_device_create_req(ee=True, auth='x509_thumbprint'), CLIError),
        (generate_device_create_req(ee=True, auth='x509_ca'), CLIError),
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
        service_client.return_value = build_mock_response(mocker, request.param, {})
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
    @pytest.fixture(params=[(200, 204)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        etag = str(uuid4())
        service_client.expected_etag = etag
        test_side_effect = [
            build_mock_response(mocker, request.param[0], {'etag': etag}),
            build_mock_response(mocker, request.param[1])
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_delete(self, serviceclient):
        subject.iot_device_delete(fixture_cmd, device_id, mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert '{}/devices/{}?'.format(mock_target['entity'], device_id) in url
        assert args[0][0].method == 'DELETE'
        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(serviceclient.expected_etag)

    @pytest.mark.parametrize("exception", [LookupError])
    def test_device_delete_invalid_args(self, serviceclient_generic_invalid_or_missing_etag, exception):
        with pytest.raises(exception):
            subject.iot_device_delete(fixture_cmd, device_id, mock_target['entity'])

    def test_device_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_delete(fixture_cmd, device_id, mock_target['entity'])


class TestDeviceShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, generate_device_show())
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
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_show())
        service_client.expected_size = size
        service_client.return_value = build_mock_response(mocker,
                                                          request.param[0],
                                                          result,
                                                          {'x-ms-continuation': None})
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

    @pytest.mark.parametrize("top", [-2, 0])
    def test_device_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_device_list(None, mock_target['entity'], top)

    def test_device_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_list(None, mock_target['entity'])


def generate_module_create_req(mid=module_id, auth='shared_private_key', ptp='123', stp='321', **kwargs):
    r = generate_device_create_req(auth=auth, ptp=ptp, stp=stp, **kwargs)
    r['module_id'] = mid
    return r


class TestDeviceModuleCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_module_create_req(auth='shared_private_key')),
        (generate_module_create_req(auth='x509_ca')),
        (generate_module_create_req(auth='x509_thumbprint')),
        (generate_module_create_req(auth='x509_thumbprint', stp=None)),
        (generate_module_create_req(auth='x509_thumbprint', ptp=None, stp=None, valid_days=30))
    ])
    def test_device_module_create(self, serviceclient, req):
        subject.iot_device_module_create(fixture_cmd, req['device_id'], hub_name=req['hub_name'],
                                         module_id=req['module_id'], auth_method=req['auth'],
                                         primary_thumbprint=req['ptp'], secondary_thumbprint=req['stp'],
                                         valid_days=req.get('valid_days'))

        args = serviceclient.call_args
        assert "{}/devices/{}/modules/{}?".format(mock_target['entity'], device_id, module_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['deviceId'] == req['device_id']
        assert body['moduleId'] == req['module_id']

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
                assert x509tp['secondaryThumbprint'] == req['stp']

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
        service_client.return_value = build_mock_response(mocker, request.param, {})
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
    @pytest.fixture(params=[(200, 204)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        etag = str(uuid4())
        service_client.expected_etag = etag
        test_side_effect = [
            build_mock_response(mocker, request.param[0], {'etag': etag}),
            build_mock_response(mocker, request.param[1])
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_module_delete(self, serviceclient):
        subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert 'devices/{}/modules/{}?'.format(device_id, module_id) in url
        assert method == 'DELETE'
        assert headers['If-Match'] == '"{}"'.format(serviceclient.expected_etag)

    @pytest.mark.parametrize("exception", [LookupError])
    def test_device_module_invalid_args(self, serviceclient_generic_invalid_or_missing_etag, exception):
        with pytest.raises(exception):
            subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])

    def test_device_module_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_delete(fixture_cmd, device_id, module_id=module_id, hub_name=mock_target['entity'])


class TestDeviceModuleShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
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
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_module_show())
        service_client.expected_size = size
        service_client.return_value = build_mock_response(mocker,
                                                          request.param[0],
                                                          result,
                                                          {'x-ms-continuation': None})
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

    @pytest.mark.parametrize("top", [-2, 0])
    def test_device_module_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_device_module_list(fixture_cmd, device_id, hub_name=mock_target['entity'], top=top)

    def test_device_module_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_list(fixture_cmd, device_id, hub_name=mock_target['entity'])


def change_dir():
    from inspect import getsourcefile
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


def generate_device_config(condition="tags.building=43 and tags.environment='test'", priority=randint(0, 100), scenario='create',
                           labels='{"key1":"value1"}', etag=str(uuid4()), content_type='modules', include_metrics=True,
                           metrics_from_file=False, content_from_file=False, metrics_short_form=False,
                           content_short_form=False, modules_schema='2.0', config_id=None):
    result = {}
    change_dir()

    if include_metrics and content_type != 'modules':
        if metrics_from_file:
            result['metrics'] = 'test_config_device_metrics.json'
        else:
            result['metrics'] = {'metrics': {'queries': {
                "mymetric": "SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200"}}}
            if metrics_short_form or scenario == 'update':
                result['metrics'] = result['metrics']['metrics']
            if scenario == 'create':
                result['metrics'] = json.dumps(result['metrics'])
    elif content_type == 'modules' and scenario == 'update':
        result['metrics'] = {'queries': {}, 'results': {}}

    content_path = 'test_config_modules_content.json' if content_type == 'modules' else 'test_config_device_content.json'
    if content_from_file:
        result['content'] = content_path
    else:
        result['content'] = json.loads(str(read_file_content(content_path)))
        if content_type == 'modules':
            content_key = 'moduleContent' if modules_schema == '1.0' else 'modulesContent'
            payload = result['content']['content']['modulesContent']
            del result['content']['content']['modulesContent']
            result['content']['content'][content_key] = payload
        else:
            content_key = 'deviceContent'

        if content_short_form or scenario == 'update':
            result['content'] = result['content']['content']

        if scenario == 'create':
            result['content'] = json.dumps(result['content'])

    result['priority'] = priority
    result['labels'] = labels if scenario == 'create' else json.loads(labels)
    result['etag'] = etag
    result['id'] = str(uuid4()) if not config_id else config_id
    result['targetCondition'] = condition
    result['content_type'] = content_type
    result['schemaVersion'] = '2.0' if modules_schema == '2.0' else '1.0'
    result['content_short_form'] = content_short_form
    result['metrics_short_form'] = metrics_short_form
    result['content_from_file'] = content_from_file
    result['metrics_from_file'] = metrics_from_file

    return result


class TestConfigCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config()),
        (generate_device_config(content_from_file=True)),
        (generate_device_config(content_short_form=True)),
        (generate_device_config(modules_schema='1.0')),
        (generate_device_config(modules_schema='1.0', content_short_form=True)),
        (generate_device_config(content_type='device')),
        (generate_device_config(content_type='device', content_short_form=True)),
        (generate_device_config(content_type='device', content_from_file=True)),
        (generate_device_config(content_type='device', include_metrics=False)),
        (generate_device_config(content_type='device', metrics_from_file=True)),
        (generate_device_config(content_type='device', metrics_short_form=True))
    ])
    def test_config_create(self, serviceclient, req):
        if req['content_type'] == 'device':
            subject.iot_hub_configuration_create(fixture_cmd, config_id=req['id'], hub_name=mock_target['entity'],
                                                 content=req['content'], target_condition=req['targetCondition'],
                                                 priority=req['priority'], labels=req['labels'], metrics=req.get('metrics'))
        else:
            subject.iot_edge_deployment_create(fixture_cmd, config_id=req['id'], hub_name=mock_target['entity'],
                                               content=req['content'], target_condition=req['targetCondition'],
                                               priority=req['priority'], labels=req['labels'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert '{}/configurations/{}?'.format(mock_target['entity'], req['id']) in url
        assert method == 'PUT'
        assert body['id'] == req['id']

        if os.path.exists(req['content']):
            js = json.loads(str(read_file_content(req['content'])))
            req['content'] = str(json.dumps(js))

        if req.get('metrics'):
            if os.path.exists(req['metrics']):
                js = json.loads(str(read_file_content(req['metrics'])))
                req['metrics'] = json.dumps(js)

        if req.get('content_short_form'):
            if req['schemaVersion'] == '1.0' and req['content_type'] == 'modules':
                assert body['content']['modulesContent'] == json.loads(req['content'])['moduleContent']
            else:
                assert body['content'] == json.loads(req['content'])
        else:
            if req['schemaVersion'] == '1.0' and req['content_type'] == 'modules':
                assert body['content']['modulesContent'] == json.loads(req['content'])['content']['moduleContent']
            else:
                assert body['content'] == json.loads(req['content'])['content']

        if req.get('metrics'):
            if req.get('metrics_short_form') or req.get('metrics_from_file'):
                assert body['metrics'] == json.loads(req['metrics'])
            else:
                assert body['metrics'] == json.loads(req['metrics'])['metrics']

        assert body['contentType'] == 'assignment'
        assert body['targetCondition'] == req.get('targetCondition')
        assert body['priority'] == req['priority']
        assert body.get('labels') == evaluate_literal(req.get('labels'), dict)

    @pytest.mark.parametrize('req, arg', [
        (generate_device_config(), 'mangle'),
        (generate_device_config(content_type='device'), 'mangle')
    ])
    def test_config_create_invalid_args(self, serviceclient, req, arg):
        with pytest.raises(CLIError):
            if arg == 'mangle':
                if req['content_type'] == 'device':
                    req['content'] = req['content'].replace('"deviceContent":', '"deviceConfig":')
                    subject.iot_hub_configuration_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                         content=req['content'], target_condition=req['targetCondition'],
                                                         priority=req['priority'], labels=req['labels'],
                                                         metrics=req.get('metrics'))
                else:
                    req['content'] = req['content'].replace('"modulesContent":', '"moduleConfig":')
                    subject.iot_edge_deployment_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                       content=req['content'], target_condition=req['targetCondition'],
                                                       priority=req['priority'], labels=req['labels'])

    @pytest.mark.parametrize("req", [
        (generate_device_config(content_type='device'))
    ])
    def test_config_create_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_create(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'],
                                                 content=req['content'], target_condition=req['targetCondition'],
                                                 priority=req['priority'], labels=req['labels'], metrics=req.get('metrics'))


class TestConfigUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config(scenario='update')),
        (generate_device_config(scenario='update', content_type='device', include_metrics=True))
    ])
    def test_config_update(self, serviceclient, req):
        req_copy = copy.deepcopy(req)
        subject.iot_hub_configuration_update(fixture_cmd, config_id=req['id'],
                                             hub_name=mock_target['entity'], parameters=req_copy)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        body = args[0][2]

        assert '{}/configurations/{}?'.format(mock_target['entity'], req['id']) in url
        assert method == 'PUT'
        assert body['id'] == req['id']

        assert body['content'] == req['content']

        if req.get('metrics'):
            assert body['metrics'] == req['metrics']

        assert body['contentType'] == 'assignment'
        assert body['targetCondition'] == req.get('targetCondition')
        assert body['priority'] == req.get('priority')
        assert body.get('labels') == req.get('labels')

        headers = args[0][1]
        assert headers['If-Match'] == '"{}"'.format(req['etag'])

    @pytest.mark.parametrize("req", [
        (generate_device_config(scenario='update', etag=''))
    ])
    def test_config_update_invalid_args(self, serviceclient, req):
        with pytest.raises(LookupError):
            subject.iot_hub_configuration_update(fixture_cmd, config_id=config_id,
                                                 hub_name=mock_target['entity'], parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_config(scenario='update'))
    ])
    def test_config_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_update(fixture_cmd, config_id=config_id,
                                                 hub_name=mock_target['entity'], parameters=req)


class TestConfigShow():
    @pytest.fixture(params=[(200, 'device'), (200, 'modules')])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(
            mocker, request.param[0],
            generate_device_config(scenario='update', content_type=request.param[1], config_id=config_id)
        )
        service_client.test_meta = request.param[1]
        return service_client

    def test_config_show(self, serviceclient):
        result = subject.iot_hub_configuration_show(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])

        assert result['id'] == config_id
        assert result == generate_device_config(scenario='update', content_type=serviceclient.test_meta, config_id=config_id)
        assert json.dumps(result)

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert method == 'GET'

    def test_config_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_show(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])


class TestConfigList():
    @pytest.fixture(params=[(200, 10)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        result = []
        size = request.param[1]
        for _ in range(size):
            result.append(generate_device_config(scenario='update'))
        for _ in range(size):
            result.append(generate_device_config(content_type='device', scenario='update'))
        service_client.expected_size = size
        service_client.return_value = build_mock_response(mocker,
                                                          request.param[0],
                                                          result,
                                                          {'x-ms-continuation': None})
        return service_client

    @pytest.mark.parametrize("top", [1, 10])
    def test_config_list(self, serviceclient, top):
        result = subject.iot_hub_configuration_list(fixture_cmd, hub_name=mock_target['entity'], top=top)
        args = serviceclient.call_args
        url = args[0][0].url
        assert json.dumps(result)
        assert len(result) == top
        assert '{}/configurations?'.format(mock_target['entity']) in url
        assert 'top={}'.format(top) in url

    @pytest.mark.parametrize("top", [1, 10])
    def test_deployment_list(self, serviceclient, top):
        result = subject.iot_edge_deployment_list(fixture_cmd, hub_name=mock_target['entity'], top=top)
        args = serviceclient.call_args
        url = args[0][0].url
        assert json.dumps(result)
        assert len(result) == top
        assert '{}/configurations?'.format(mock_target['entity']) in url
        assert 'top={}'.format(top) in url

    @pytest.mark.parametrize("top", [-1, 0])
    def test_config_list_invalid_args(self, serviceclient, top):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_list(fixture_cmd, hub_name=mock_target['entity'], top=top)

    def test_config_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_list(fixture_cmd, hub_name=mock_target['entity'])


class TestConfigDelete():
    @pytest.fixture(params=[(200, 204)])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        etag = str(uuid4())
        service_client.expected_etag = etag
        test_side_effect = [
            build_mock_response(mocker, request.param[0], {'etag': etag}),
            build_mock_response(mocker, request.param[1])
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_config_delete(self, serviceclient):
        subject.iot_hub_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert method == 'DELETE'
        assert '{}/configurations/{}?'.format(mock_target['entity'], config_id) in url
        assert headers['If-Match'] == '"{}"'.format(serviceclient.expected_etag)

    @pytest.mark.parametrize("expected", [LookupError])
    def test_config_delete_invalid_args(self, serviceclient_generic_invalid_or_missing_etag, expected):
        with pytest.raises(expected):
            subject.iot_hub_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])

    def test_config_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_hub_configuration_delete(fixture_cmd, config_id=config_id, hub_name=mock_target['entity'])


def generate_config_metrics(content_type='modules'):
    change_dir()
    path = None

    if content_type == 'modules':
        path = 'test_config_modules_show.json'

    return json.loads(str(read_file_content(path)))


class TestConfigMetricShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.side_effect = [build_mock_response(mocker, payload=generate_config_metrics()),
                                      build_mock_response(mocker, payload=[], headers={'x-ms-continuation': None})]
        return service_client

    @pytest.mark.parametrize("metric_id, content_type, metric_type", [
        ('appliedCount', 'modules', 'systemMetrics'),
        ('reportedSuccessfulCount', 'modules', 'systemMetrics'),
        ('mymetric', 'device', 'metrics'),
        ('reportedFailedCount', 'device', 'systemMetrics')
    ])
    def test_config_metric_show(self, serviceclient, metric_id, content_type, metric_type):

        if content_type == 'modules':
            result = subject.iot_edge_deployment_metric_show(fixture_cmd, config_id=config_id,
                                                             metric_id=metric_id, hub_name=mock_target['entity'])
        else:
            mt = 'user' if metric_type == 'metrics' else 'system'
            result = subject.iot_hub_configuration_metric_show(fixture_cmd, config_id=config_id, metric_type=mt,
                                                               metric_id=metric_id, hub_name=mock_target['entity'])

        expected = generate_config_metrics()

        assert result['metric'] == metric_id
        assert result['query'] == expected[metric_type]['queries'][metric_id]

        query_args = serviceclient.call_args_list[1]
        query_body = query_args[0][2]

        assert query_body['query'] == expected[metric_type]['queries'][metric_id]

    @pytest.mark.parametrize("metric_id, content_type, metric_type", [
        ('doesnotexist0', 'modules', 'systemMetrics'),
        ('doesnotexist1', 'modules', 'metrics'),
        ('doesnotexist2', 'device', 'metrics'),
        ('doesnotexist3', 'device', 'systemMetrics')
    ])
    def test_config_metric_show_invalid_args(self, serviceclient, metric_id, content_type, metric_type):
        with pytest.raises(CLIError):
            if content_type == 'modules':
                subject.iot_edge_deployment_metric_show(fixture_cmd, config_id=config_id,
                                                        metric_id=metric_id, hub_name=mock_target['entity'])
            else:
                mt = 'user' if metric_type == 'metrics' else 'system'
                subject.iot_hub_configuration_metric_show(fixture_cmd, config_id=config_id, metric_type=mt,
                                                          metric_id=metric_id, hub_name=mock_target['entity'])

    @pytest.mark.parametrize("metric_id, content_type, metric_type", [
        ('doesnotexist0', 'modules', 'systemMetrics'),
        ('doesnotexist1', 'device', 'metrics')
    ])
    def test_config_metric_show_error(self, serviceclient_generic_error, metric_id, content_type, metric_type):
        with pytest.raises(CLIError):
            if content_type == 'modules':
                subject.iot_edge_deployment_metric_show(fixture_cmd, config_id=config_id,
                                                        metric_id=metric_id, hub_name=mock_target['entity'])
            else:
                mt = 'user' if metric_type == 'metrics' else 'system'
                subject.iot_hub_configuration_metric_show(fixture_cmd, config_id=config_id, metric_type=mt,
                                                          metric_id=metric_id, hub_name=mock_target['entity'])


class TestConfigApply():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.side_effect = [build_mock_response(mocker),
                                      build_mock_response(mocker, payload=[], headers={'x-ms-continuation': None})]
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_device_config()),
        (generate_device_config(content_short_form=True)),
        (generate_device_config(content_from_file=True))
    ])
    def test_config_apply(self, serviceclient, req):
        result = subject.iot_edge_set_modules(fixture_cmd, device_id,
                                              hub_name=mock_target['entity'], content=req['content'])
        args = serviceclient.call_args_list[0]
        body = args[0][2]

        if os.path.exists(req['content']):
            js = json.loads(str(read_file_content(req['content'])))
            req['content'] = str(json.dumps(js))

        if req.get('content_short_form'):
            if req['schemaVersion'] == '1.0' and req['content_type'] == 'modules':
                assert body['modulesContent'] == json.loads(req['content'])['moduleContent']
            else:
                assert body == json.loads(req['content'])
        else:
            if req['schemaVersion'] == '1.0' and req['content_type'] == 'modules':
                assert body['modulesContent'] == json.loads(req['content'])['content']['moduleContent']
            else:
                assert body == json.loads(req['content'])['content']

        mod_list_args = serviceclient.call_args_list[1]
        mod_list_body = mod_list_args[0][2]

        assert mod_list_body['query'] == "select * from devices.modules where devices.deviceId = '{}'".format(device_id)
        assert result is not None

    @pytest.mark.parametrize('req, arg', [
        (generate_device_config(), 'mangle'),
        (generate_device_config(content_type='device'), ''),
    ])
    def test_config_apply_invalid_args(self, serviceclient, req, arg):
        with pytest.raises(CLIError):
            if arg == 'mangle':
                req['content'] = req['content'].replace('"modulesContent":', '"somethingelse":')
            subject.iot_edge_set_modules(fixture_cmd, device_id,
                                         hub_name=mock_target['entity'], content=req['content'])

    @pytest.mark.parametrize("req", [
        (generate_device_config())
    ])
    def test_config_apply_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_edge_set_modules(fixture_cmd, device_id,
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
        service_client.return_value = build_mock_response(mocker, request.param,
                                                          [generate_device_twin_show()],
                                                          {'x-ms-continuation': None})
        return service_client

    def test_device_twin_show(self, serviceclient):
        result = subject.iot_device_twin_show(None, device_id, mock_target['entity'])
        args = serviceclient.call_args
        body = args[0][2]
        assert json.dumps(result)
        assert body['query'] == "select * from devices where devices.deviceId='{}'".format(device_id)

    def test_device_twin_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_twin_show(None, device_id, mock_target['entity'])


class TestDeviceTwinUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param,
                                                          payload=generate_device_twin_show())
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(properties={"desired": {"key": "value"}}))
    ])
    def test_device_twin_update(self, serviceclient, req):
        subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert 'twins/{}'.format(device_id) in args[0][0].url

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(etag=None), LookupError)
    ])
    def test_device_twin_update_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)

    @pytest.mark.parametrize("req", [
        (generate_device_twin_show()),
        (generate_device_twin_show(tags=''))
    ])
    def test_device_twin_update_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_device_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'], parameters=req)


class TestDeviceTwinReplace():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker,
                                                          request.param,
                                                          generate_device_twin_show(moduleId=module_id))
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize("req, isfile", [
        (generate_device_twin_show(moduleId=module_id), False),
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}), False),
        (generate_device_twin_show(file_handle=True), True)
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
        assert '{}/twins/{}?'.format(mock_target['entity'], device_id) in args[0][0].url
        assert args[0][0].method == 'PUT'

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(etag=None), LookupError),
        ({'invalid': 'payload'}, LookupError),
    ])
    def test_device_twin_replace_invalid_args(self, serviceclient, req, exp):
        with pytest.raises(exp):
            serviceclient.return_value.text.return_value = json.dumps(req)
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
        service_client.return_value = build_mock_response(mocker, request.param,
                                                          payload=generate_device_twin_show())
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
        service_client.return_value = build_mock_response(mocker, request.param,
                                                          payload=generate_device_twin_show(moduleId=module_id))
        return service_client

    # Update does a GET/SHOW first
    @pytest.mark.parametrize("req", [
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}))
    ])
    def test_device_module_twin_update(self, serviceclient, req):
        subject.iot_device_module_twin_update(fixture_cmd, req['deviceId'], hub_name=mock_target['entity'],
                                              module_id=module_id, parameters=req)
        args = serviceclient.call_args
        body = args[0][2]
        assert body == req
        assert 'twins/{}/modules/{}?'.format(req['deviceId'], module_id) in args[0][0].url

    @pytest.mark.parametrize("req, exp", [
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}, etag=None), LookupError),
        (generate_device_twin_show(moduleId=module_id), CLIError)
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
        service_client.return_value = build_mock_response(mocker,
                                                          request.param,
                                                          payload=generate_device_twin_show(moduleId=module_id))
        return service_client

    # Replace does a GET/SHOW first
    @pytest.mark.parametrize("req, isfile", [
        (generate_device_twin_show(moduleId=module_id), False),
        (generate_device_twin_show(moduleId=module_id, properties={"desired": {"key": "value"}}), False),
        (generate_device_twin_show(file_handle=True), True)
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
            serviceclient.return_value.text.return_value = json.dumps(req)
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
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("query, servresult, servtotal, top", [
        (generic_query, [generate_device_twin_show()], 6, 3),
        (generic_query, [generate_device_twin_show(), generate_device_twin_show()], 5, 2),
        (generic_query, [generate_device_twin_show(), generate_device_twin_show()], 6, None),
        (generic_query, [generate_device_show() for i in range(0, 12)], 100, 51),
        (generic_query, [generate_device_twin_show()], 1, 100)
    ])
    def test_query_basic(self, serviceclient, query, servresult, servtotal, top):
        serviceclient.return_value.text.return_value = json.dumps(servresult)
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

    @pytest.mark.parametrize("top", [-2, 0])
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
        service_client.return_value = build_mock_response(mocker,
                                                          request.param,
                                                          {'payload': 'value', 'status': 0})
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
        assert '{}/twins/{}/methods?'.format(mock_target['entity'], device_id) in url

    @pytest.mark.parametrize("req, etype, exp", [
        ("badformat", 'payload', CLIError),
        ('{"key":"valu', 'payload', CLIError),
        (1000, 'timeout', CLIError),
        (5, 'timeout', CLIError),
    ])
    def test_device_method_invalid_args(self, serviceclient, req, etype, exp):
        with pytest.raises(exp):
            if etype == 'payload':
                subject.iot_device_method(fixture_cmd, device_id=device_id, hub_name=mock_target['entity'],
                                          method_name='mymethod', method_payload=req)
            if etype == 'timeout':
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
        service_client.return_value = build_mock_response(mocker, request.param, {'payload': 'value', 'status': 0})
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

    @pytest.mark.parametrize("req, etype, exp", [
        ("doesnotexist", 'payload', CLIError),
        ('{"key":"valu', 'payload', CLIError),
        (1000, 'timeout', CLIError),
        (5, 'timeout', CLIError),
    ])
    def test_device_module_method_invalid_args(self, serviceclient, req, etype, exp):
        with pytest.raises(exp):
            if etype == 'payload':
                subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                                 hub_name=mock_target['entity'], method_payload=req)
            if etype == 'timeout':
                subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                                 hub_name=mock_target['entity'], method_payload='{"key":"value"}', timeout=req)

    def test_device_method_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_module_method(fixture_cmd, device_id=device_id, module_id=module_id, method_name='mymethod',
                                             hub_name=mock_target['entity'], method_payload='{"key":"value"}')


hub_suffix = "awesome-azure.net"


# TODO: Refactor to leverage fixture pattern and reduce redundent params
class TestGetIoTHubConnString():
    @pytest.mark.parametrize("hubcount, targethub, policy_name, rg_name, include_events, login, failure_reason, mgmt_sdk_ver", [
        (5, 'hub1', 'iothubowner', str(uuid4()), False, None, None, '0.4'),
        (0, 'hub1', 'iothubowner', None, False, True, None, '0.4'),
        (5, 'hub1', 'iothubowner', str(uuid4()), False, None, None, None),
        (0, 'hub1', 'iothubowner', None, False, True, None, None),
        (1, 'hub0', 'iothubowner', None, True, None, None, None),
        (10, 'hub3', 'custompolicy', 'myrg', False, None, None, None),
        (1, 'hub0', 'custompolicy', None, False, None, None, None),
        (3, 'hub4', 'iothubowner', None, False, None, 'subscription', None),
        (1, 'hub1', 'iothubowner', 'myrg', False, None, 'policy', None),
        (1, 'myhub', 'iothubowner', 'myrg', False, None, 'resource', None)
    ])
    def test_get_hub_conn_string(self, mocker, hubcount, targethub, policy_name, rg_name,
                                 include_events, login, failure_reason, mgmt_sdk_ver):
        from azext_iot.common._azure import get_iot_hub_connection_string

        def _build_hub(hub, name, rg):
            hub.name = name
            hub.properties.host_name = "{}.{}".format(name, hub_suffix)

            if mgmt_sdk_ver == '0.4':
                hub.resourcegroup = rg
                hub.additional_properties = None
            else:
                d = {}
                d['resourcegroup'] = rg
                hub.additional_properties.return_value = d
                hub.additional_properties.get.return_value = rg

            return hub

        def _build_policy(policy, name):
            policy.key_name = name
            policy.primary_key = mock_target['primarykey']
            policy.secondary_key = mock_target['secondarykey']
            return policy

        def _build_event(hub):
            hub.properties.event_hub_endpoints = {'events': mocker.Mock()}
            hub.properties.event_hub_endpoints['events'].endpoint = ('sb://' + str(uuid4()))
            hub.properties.event_hub_endpoints['events'].partition_count = '2'
            hub.properties.event_hub_endpoints['events'].path = hub_entity
            hub.properties.event_hub_endpoints['events'].partition_ids = ['0', '1']
            return hub

        cmd = mocker.Mock(name='cmd')
        ihsf = mocker.patch(path_iot_hub_service_factory)
        client = mocker.Mock(name='hubclient')

        if not rg_name:
            hub_list = []
            for i in range(0, hubcount):
                hub_list.append(_build_hub(mocker.Mock(), "hub{}".format(i), str(uuid4())))
            client.list_by_subscription.return_value = hub_list
        else:
            client.get.return_value = _build_hub(mocker.Mock(), targethub, rg_name)

        if failure_reason == "resource":
            client.get.side_effect = ValueError
        elif failure_reason == "policy":
            client.get_keys_for_key_name.side_effect = ValueError
        else:
            client.get_keys_for_key_name.return_value = _build_policy(mocker.Mock(), policy_name)

        if include_events:
            _build_event(hub_list[0])

        client.config.subscription_id = mock_target['subscription']
        ihsf.return_value = client

        if not failure_reason:
            if not login:
                result = get_iot_hub_connection_string(cmd, targethub, rg_name, policy_name, include_events=include_events)

                expecting_hub = "{}.{}".format(targethub, hub_suffix)
                assert result['entity'] == expecting_hub
                assert result['policy'] == policy_name
                assert result['subscription'] == mock_target['subscription']
                assert result['cs'] == generic_cs_template.format(
                    expecting_hub,
                    policy_name,
                    mock_target['primarykey'])

                if rg_name:
                    client.get.assert_called_with(rg_name, targethub)
                    assert result['resourcegroup'] == rg_name
                else:
                    assert result['resourcegroup']

                client.get_keys_for_key_name.assert_called_with(mocker.ANY, targethub, policy_name)

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
                lower_cs = generate_lower_cs(hub, policy, key)

                result = get_iot_hub_connection_string(cmd, targethub, rg_name, policy_name, login=cs)
                result_lower = get_iot_hub_connection_string(cmd, targethub, rg_name, policy_name, login=lower_cs)

                assert result['entity'] == hub
                assert result['policy'] == policy
                assert result['primarykey'] == key
                assert not result.get('resourcegroup')
                assert not result.get('subscription')
                assert result['cs'] == generic_cs_template.format(
                    hub,
                    policy,
                    key)
                assert result_lower['entity'] == hub
                assert result_lower['policy'] == policy
                assert result_lower['primarykey'] == key
                assert not result_lower.get('resourcegroup')
                assert not result_lower.get('subscription')
                assert result_lower['cs'] == generic_lower_cs_template.format(
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
    data = '{"data": "value"}'

    @pytest.fixture
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, 200, TestDeviceMessaging.data, sample_c2d_receive, raw=True)
        return service_client

    def test_c2d_receive(self, serviceclient):
        timeout = 120
        result = subject.iot_c2d_message_receive(fixture_cmd, device_id, mock_target['entity'], timeout)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        headers = args[0][1]

        assert method == 'GET'
        assert '{}/devices/{}/messages/deviceBound?'.format(mock_target['entity'], device_id) in url
        assert headers['IotHub-MessageLockTimeout'] == str(timeout)

        assert result['ack'] == sample_c2d_receive['iothub-ack']
        assert result['correlationId'] == sample_c2d_receive['iothub-correlationid']
        assert result['data'] == TestDeviceMessaging.data
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
        assert '{}/devices/{}/messages/deviceBound/{}?'.format(mock_target['entity'], device_id, etag) in url

    def test_c2d_reject(self, serviceclient):
        etag = "3k28zb44-0d00-4ddd-ade3-6110eb94c476"
        serviceclient.return_value.status_code = 204
        result = subject.iot_c2d_message_reject(fixture_cmd, device_id, etag, hub_name=mock_target['entity'])

        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert result is None
        assert method == 'DELETE'
        assert '{}/devices/{}/messages/deviceBound/{}?'.format(mock_target['entity'], device_id, etag) in url
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
        assert '{}/devices/{}/messages/deviceBound/{}/abandon?'.format(mock_target['entity'], device_id, etag) in url

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
        sas_auth = SasTokenAuthentication(uri, None, access_key, expiry)
        token = sas_auth.generate_sas_token()

        # Assertion
        assert 'SharedAccessSignature ' in token
        assert 'sig=SIumZ1ACqqPJZ2okHDlW9MSYKykEpqsQY3z6FMOICd4%3D' in token
        assert 'se=1471940363' in token
        assert 'sr=iot-hub-for-test.azure-devices.net%2Fdevices%2Fiot-device-for-test' in token
        assert 'skn=' not in token

        # Prepare parameters
        uri = 'iot-hub-for-test.azure-devices.net'

        # Action
        sas_auth = SasTokenAuthentication(uri, policy_name, access_key, expiry)
        token = sas_auth.generate_sas_token()

        # Assertion
        assert 'SharedAccessSignature ' in token
        assert 'sig=770sPjjYxRYpNz8%2FhEN7XR5XU5KDGYGTinSP8YyeTXw%3D' in token
        assert 'se=1471940363' in token
        assert 'sr=iot-hub-for-test.azure-devices.net' in token
        assert 'skn=iothubowner' in token

        # Prepare parameters
        uri = 'iot-hub-for-test.azure-devices.net/devices/iot-device-for-test/modules/module-for-test'

        # Action
        sas_auth = SasTokenAuthentication(uri, policy_name, access_key, expiry)
        token = sas_auth.generate_sas_token()

        # Assertion
        assert 'SharedAccessSignature ' in token
        assert 'sig=JwAxBBBPYA0E%2FTHdnrXzUfBfuZ7deH6pppCniJ23Uu0%3D' in token
        assert 'se=1471940363' in token
        assert 'sr=iot-hub-for-test.azure-devices.net%2Fdevices%2Fiot-device-for-test%2Fmodules%2Fmodule-for-test' in token
        assert 'skn=iothubowner' in token


class TestDeviceSimulate():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, "")
        return service_client

    @pytest.fixture()
    def mqttclient(self, mocker, fixture_ghcs, fixture_sas):
        client = mocker.patch(path_mqtt_client)
        mock_conn = mocker.patch('azext_iot.operations._mqtt.mqtt_client_wrap.is_connected')
        mock_conn.return_value = True
        return client

    @pytest.mark.parametrize("rs, mc, mi, protocol", [
        ('complete', 1, 1, 'http'),
        ('reject', 1, 1, 'http'),
        ('abandon', 2, 1, 'http'),
        ('complete', 3, 1, 'mqtt'),
    ])
    def test_device_simulate(self, serviceclient, mqttclient, rs, mc, mi, protocol):
        subject.iot_simulate_device(fixture_cmd, device_id, mock_target['entity'],
                                    receive_settle=rs, msg_count=mc, msg_interval=mi, protocol_type=protocol)
        if protocol == 'http':
            args = serviceclient.call_args_list
            result = []
            for call in args:
                call = call[0]
                if call[0].method == 'POST':
                    result.append(call)

            assert len(result) == mc
        if protocol == 'mqtt':
            assert mc == mqttclient().publish.call_count
            assert mqttclient().publish.call_args[0][0] == 'devices/{}/messages/events/'.format(device_id)
            assert mqttclient().tls_set.call_count == 1
            assert mqttclient().username_pw_set.call_count == 1

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


@pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
class TestMonitorEvents():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param)
        existing_target = fixture_ghcs.return_value
        existing_target['events'] = {}
        existing_target['events']['partition_ids'] = []
        return service_client

    @pytest.mark.parametrize("timeout, exception", [
        (-1, CLIError),
    ])
    def test_monitor_events_invalid_args(self, fixture_cmd, serviceclient, timeout, exception):
        with pytest.raises(exception):
            subject.iot_hub_monitor_events(fixture_cmd, mock_target['entity'], device_id, timeout=timeout)


def generate_parent_device(**kvp):
    payload = {'etag': 'abcd', 'capabilities': {'iotEdge': True},
               'deviceId': device_id, 'status': 'disabled',
               'deviceScope': 'ms-azure-iot-edge://{}-1234'.format(device_id)}
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


def generate_child_device(**kvp):
    payload = {'etag': 'abcd', 'capabilities': {'iotEdge': False},
               'deviceId': child_device_id, 'status': 'disabled',
               'deviceScope': ''}
    for k in kvp:
        payload[k] = kvp[k]
    return payload


class TestEdgeOffline():

    # get-parent
    @pytest.fixture(params=[(200, 200)])
    def sc_getparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], generate_parent_device())
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_get_parent(self, sc_getparent):
        result = subject.iot_device_get_parent(fixture_cmd, child_device_id, mock_target['entity'])
        args = sc_getparent.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target['entity'], device_id) in url
        assert args[0][0].method == 'GET'
        assert json.dumps(result)

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_getparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        if request.param[1] == 0:
            nonedge_kvp.setdefault('capabilities', {'iotEdge': True})
        if request.param[1] == 1:
            nonedge_kvp.setdefault('deviceId', '')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_getparent_invalid_args(self, sc_invalid_args_getparent, exp):
        with pytest.raises(exp):
            subject.iot_device_get_parent(fixture_cmd, device_id, mock_target['entity'])

    def test_device_getparent_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_get_parent(fixture_cmd, device_id, mock_target['entity'])

    # set-parent
    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        if request.param[1] == 1:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_set_parent(self, sc_setparent):
        subject.iot_device_set_parent(fixture_cmd, child_device_id, device_id, True, mock_target['entity'])
        args = sc_setparent.call_args
        url = args[0][0].url
        body = args[0][2]
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'
        assert body['deviceId'] == child_device_id
        assert body['deviceScope'] == generate_parent_device().get('deviceScope')

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_invalid_args_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        nonedge_kvp = {}
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        if request.param[1] == 1:
            nonedge_kvp.setdefault('capabilities', {'iotEdge': True})
        if request.param[1] == 2:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp)),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_setparent_invalid_args(self, sc_invalid_args_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_set_parent(fixture_cmd, child_device_id, device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_setparent_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device()),
            build_mock_response(mocker, request.param[1], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_setparent_error(self, sc_setparent_error):
        with pytest.raises(CLIError):
            subject.iot_device_set_parent(fixture_cmd, child_device_id, device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_setparent(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('etag', None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [LookupError])
    def test_device_setparent_invalid_etag(self, sc_invalid_etag_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_set_parent(fixture_cmd, child_device_id, device_id, True, mock_target['entity'])

    # add-children
    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        if request.param[1] == 1:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_add(self, sc_addchildren):
        subject.iot_device_children_add(None, device_id, child_device_id, True, mock_target['entity'])
        args = sc_addchildren.call_args
        url = args[0][0].url
        body = args[0][2]
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'
        assert body['deviceId'] == child_device_id
        assert body['deviceScope'] == generate_parent_device().get('deviceScope')

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2)])
    def sc_invalid_args_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        nonedge_kvp = {}
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        if request.param[1] == 1:
            nonedge_kvp.setdefault('capabilities', {'iotEdge': True})
        if request.param[1] == 2:
            nonedge_kvp.setdefault('deviceScope', 'abcd')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp)),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_addchildren_invalid_args(self, sc_invalid_args_addchildren, exp):
        with pytest.raises(exp):
            subject.iot_device_children_add(fixture_cmd, device_id, child_device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_addchildren_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device()),
            build_mock_response(mocker, request.param[1], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_addchildren_error(self, sc_addchildren_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_add(fixture_cmd, device_id, child_device_id, True, mock_target['entity'])

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_addchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('etag', None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [LookupError])
    def test_device_addchildren_invalid_etag(self, sc_invalid_etag_setparent, exp):
        with pytest.raises(exp):
            subject.iot_device_children_add(fixture_cmd, device_id, child_device_id, True, mock_target['entity'])

    # list-children
    @pytest.fixture(params=[(200, 200)])
    def sc_listchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        result = []
        result.append(generate_child_device(**nonedge_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], result, {'x-ms-continuation': None})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_list(self, sc_listchildren):
        result = subject.iot_device_children_list(fixture_cmd, device_id, mock_target['entity'])
        args = sc_listchildren.call_args
        url = args[0][0].url
        assert "{}/devices/query?".format(mock_target['entity']) in url
        assert args[0][0].method == 'POST'
        assert result == child_device_id

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_listchildren(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp)),
            build_mock_response(mocker, request.param[0], [], {'x-ms-continuation': None})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_listchildren_invalid_args(self, sc_invalid_args_listchildren, exp):
        with pytest.raises(exp):
            subject.iot_device_children_list(fixture_cmd, device_id, mock_target['entity'])

    def test_device_listchildren_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_list(fixture_cmd, device_id, mock_target['entity'])

    # remove-children
    @pytest.fixture(params=[(200, 200)])
    def sc_removechildrenlist(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_remove_list(self, sc_removechildrenlist):
        subject.iot_device_children_remove(fixture_cmd, device_id, child_device_id, False, mock_target['entity'])
        args = sc_removechildrenlist.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'

    @pytest.fixture(params=[(200, 0), (200, 1), (200, 2), (200, 3)])
    def sc_invalid_args_removechildrenlist(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        nonedge_kvp = {}
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        if request.param[1] == 1:
            nonedge_kvp.setdefault('capabilities', {'iotEdge': True})
        if request.param[1] == 2:
            nonedge_kvp.setdefault('deviceScope', '')
        if request.param[1] == 3:
            nonedge_kvp.setdefault('deviceScope', 'other')
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp)),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp))
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenlist_invalid_args(self, sc_invalid_args_removechildrenlist, exp):
        with pytest.raises(exp):
            subject.iot_device_children_remove(fixture_cmd, device_id, child_device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_removechildrenlist(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        nonedge_kvp.setdefault('etag', None)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [LookupError])
    def test_device_removechildrenlist_invalid_etag(self, sc_invalid_etag_removechildrenlist, exp):
        with pytest.raises(exp):
            subject.iot_device_children_remove(fixture_cmd, device_id, child_device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_removechildrenlist_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[1], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_removechildrenlist_error(self, sc_removechildrenlist_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_remove(fixture_cmd, device_id, child_device_id, False, mock_target['entity'])

    @pytest.fixture(params=[(200, 200)])
    def sc_removechildrenall(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        result = []
        result.append(generate_child_device(**nonedge_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], result, {'x-ms-continuation': None}),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_children_remove_all(self, sc_removechildrenall):
        subject.iot_device_children_remove(fixture_cmd, device_id, None, True, mock_target['entity'])
        args = sc_removechildrenall.call_args
        url = args[0][0].url
        assert "{}/devices/{}?".format(mock_target['entity'], child_device_id) in url
        assert args[0][0].method == 'PUT'

    @pytest.fixture(params=[(200, 0), (200, 1)])
    def sc_invalid_args_removechildrenall(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        edge_kvp = {}
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        result = []
        result.append(generate_child_device(**nonedge_kvp))
        if request.param[1] == 0:
            edge_kvp.setdefault('capabilities', {'iotEdge': False})
        if request.param[1] == 1:
            result = []
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device(**edge_kvp)),
            build_mock_response(mocker, request.param[0], result, {'x-ms-continuation': None})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [CLIError])
    def test_device_removechildrenall_invalid_args(self, sc_invalid_args_removechildrenall, exp):
        with pytest.raises(exp):
            subject.iot_device_children_remove(fixture_cmd, device_id, None, True, mock_target['entity'])

    @pytest.fixture(params=[(200, 200)])
    def sc_invalid_etag_removechildrenall(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        nonedge_kvp.setdefault('etag', None)
        result = []
        result.append(generate_child_device(**nonedge_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], result, {'x-ms-continuation': None}),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[0], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("exp", [LookupError])
    def test_device_removechildrenall_invalid_etag(self, sc_invalid_etag_removechildrenall, exp):
        with pytest.raises(exp):
            subject.iot_device_children_remove(fixture_cmd, device_id, None, True, mock_target['entity'])

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def sc_removechildrenall_error(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        nonedge_kvp = {}
        nonedge_kvp.setdefault('deviceScope', generate_parent_device().get('deviceScope'))
        result = []
        result.append(generate_child_device(**nonedge_kvp))
        test_side_effect = [
            build_mock_response(mocker, request.param[0], generate_parent_device()),
            build_mock_response(mocker, request.param[0], result, {'x-ms-continuation': None}),
            build_mock_response(mocker, request.param[0], generate_child_device(**nonedge_kvp)),
            build_mock_response(mocker, request.param[1], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_device_removechildrenall_error(self, sc_removechildrenall_error):
        with pytest.raises(CLIError):
            subject.iot_device_children_remove(fixture_cmd, device_id, None, True, mock_target['entity'])
