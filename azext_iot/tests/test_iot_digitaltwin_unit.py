# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=W0613,W0621

import pytest
import json
import os
import sys

from azext_iot.operations import digitaltwin as subject
from azext_iot.operations.digitaltwin import INTERFACE_KEY_NAME
from azext_iot.common.utility import validate_min_python_version
from knack.util import CLIError
from azure.cli.core.util import read_file_content

# Path hack.
sys.path.insert(0, os.path.abspath('.'))

_device_digitaltwin_invoke_command_payload = 'test_device_digitaltwin_invoke_command.json'
_device_digitaltwin_payload_file = 'test_device_digitaltwin_interfaces.json'
_device_digitaltwin_property_update_payload_file = 'test_device_digitaltwin_property_update.json'
_pnp_show_interface_file = 'test_pnp_interface_show.json'
_pnp_list_interface_file = 'test_pnp_interface_list.json'
path_iot_hub_monitor_events = 'azext_iot.operations.digitaltwin._iot_hub_monitor_events'
device_id = 'mydevice'
hub_entity = 'myhub.azure-devices.net'

# Patch Paths #
path_mqtt_client = 'azext_iot.operations._mqtt.mqtt.Client'
path_service_client = 'msrest.service_client.ServiceClient.send'
path_ghcs = 'azext_iot.operations.hub.get_iot_hub_connection_string'
path_iot_hub_service_factory = 'azext_iot.common._azure.iot_hub_service_factory'
path_sas = 'azext_iot._factory.SasTokenAuthentication'

mock_target = {}
mock_target['entity'] = hub_entity
mock_target['primarykey'] = 'rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['secondarykey'] = 'aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['policy'] = 'iothubowner'
mock_target['subscription'] = "5952cff8-bcd1-4235-9554-af2c0348bf23"
mock_target['location'] = "westus2"
mock_target['sku_tier'] = "Standard"
generic_cs_template = 'HostName={};SharedAccessKeyName={};SharedAccessKey={}'


def generate_cs(hub=hub_entity, policy=mock_target['policy'], key=mock_target['primarykey']):
    return generic_cs_template.format(hub, policy, key)


mock_target['cs'] = generate_cs()


def change_dir():
    from inspect import getsourcefile
    os.chdir(os.path.dirname(os.path.abspath(getsourcefile(lambda: 0))))


def generate_device_interfaces_payload():
    change_dir()
    return json.loads(read_file_content(_device_digitaltwin_payload_file))


def generate_pnp_interface_show_payload():
    change_dir()
    return json.loads(read_file_content(_pnp_show_interface_file))


def generate_pnp_interface_list_payload():
    change_dir()
    return json.loads(read_file_content(_pnp_list_interface_file))


def generate_device_digitaltwin_property_update_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _device_digitaltwin_property_update_payload_file)

    return (str(read_file_content(_device_digitaltwin_property_update_payload_file)),
            _device_digitaltwin_property_update_payload_file)


def generate_device_digitaltwin_invoke_command_payload(content_from_file=False):
    change_dir()
    if content_from_file:
        return (None, _device_digitaltwin_invoke_command_payload)

    return (str(read_file_content(_device_digitaltwin_invoke_command_payload)),
            _device_digitaltwin_invoke_command_payload)


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


@pytest.fixture(params=[400, 401, 500])
def serviceclient_generic_error(mocker, fixture_ghcs, request):
    service_client = mocker.patch(path_service_client)
    service_client.return_value = build_mock_response(mocker, request.param, {'error': 'something failed'})
    return service_client


@pytest.fixture()
def fixture_monitor_events(mocker):
    mocker.patch(path_iot_hub_monitor_events)


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


class TestDTInterfaceList(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        service_client.return_value = build_mock_response(mocker, request.param, output)
        return service_client

    def test_iot_digitaltwin_interface_list(self, fixture_cmd, serviceclient):
        result = subject.iot_digitaltwin_interface_list(fixture_cmd, device_id=device_id,
                                                        login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'GET'
        assert '{}/digitalTwins/{}/interfaces/{}?'.format(mock_target['entity'], device_id,
                                                          INTERFACE_KEY_NAME) in url
        assert json.dumps(result)
        assert len(result['interfaces']) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_interface_list_error(self, fixture_cmd, serviceclient_generic_error, exp):
        with pytest.raises(exp):
            subject.iot_digitaltwin_interface_list(fixture_cmd, device_id=device_id,
                                                   login=mock_target['cs'])


class TestDTCommandList(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show)
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_iot_digitaltwin_command_list(self, fixture_cmd, serviceclient):
        result = subject.iot_digitaltwin_command_list(fixture_cmd, device_id=device_id, source_model='public',
                                                      interface='environmentalSensor', login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'GET'
        assert '/models/' in url
        assert json.dumps(result)
        assert len(result['interfaces']) == 1
        assert result['interfaces'][0]['name'] == 'environmentalSensor'
        assert len(result['interfaces'][0]['commands']) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_command_list_error(self, fixture_cmd, serviceclient_generic_error, exp):
        with pytest.raises(exp):
            subject.iot_digitaltwin_command_list(fixture_cmd, device_id=device_id, source_model='public',
                                                 login=mock_target['cs'])

    @pytest.mark.parametrize("interface, exp", [('inter1', CLIError)])
    def test_iot_digitaltwin_command_list_args_error(self, fixture_cmd, serviceclient, interface, exp):
        with pytest.raises(exp):
            subject.iot_digitaltwin_command_list(fixture_cmd, device_id=device_id, interface=interface,
                                                 login=mock_target['cs'], source_model='public')


class TestDTPropertiesList(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show)
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("target_interface", [('environmentalSensor')])
    def test_iot_digitaltwin_properties_list(self, fixture_cmd, serviceclient, target_interface):
        result = subject.iot_digitaltwin_properties_list(fixture_cmd, device_id=device_id, source_model='public',
                                                         interface=target_interface, login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'GET'
        assert '/models/' in url
        assert json.dumps(result)
        if target_interface:
            assert len(result['interfaces']) == 1
            assert result['interfaces'][0]['name'] == 'environmentalSensor'
            assert len(result['interfaces'][0]['properties']) == 3

    @pytest.mark.parametrize("exp", [(CLIError)])
    def test_iot_digitaltwin_properties_list_error(self, fixture_cmd, serviceclient_generic_error, exp):
        with pytest.raises(exp):
            subject.iot_digitaltwin_properties_list(fixture_cmd, device_id=device_id, source_model='public',
                                                    login=mock_target['cs'])

    @pytest.mark.parametrize("interface, exp", [('inter1', CLIError)])
    def test_iot_digitaltwin_properties_list_args_error(self, fixture_cmd, serviceclient, interface, exp):
        with pytest.raises(exp):
            subject.iot_digitaltwin_properties_list(fixture_cmd, device_id=device_id, interface=interface,
                                                    login=mock_target['cs'], source_model='public')


class TestDTPropertyUpdate(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("payload_scenario", [
        (generate_device_digitaltwin_property_update_payload()),
        (generate_device_digitaltwin_property_update_payload(content_from_file=True))])
    def test_iot_digitaltwin_property_update(self, fixture_cmd, serviceclient, payload_scenario):

        payload = None

        # If file path provided
        if not payload_scenario[0]:
            payload = payload_scenario[1]
        else:
            payload = str(read_file_content(_device_digitaltwin_property_update_payload_file))

        subject.iot_digitaltwin_property_update(fixture_cmd, device_id=device_id,
                                                interface_payload=payload, login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'PATCH'
        assert '{}/digitalTwins/{}/interfaces?'.format(mock_target['entity'], device_id) in url

    @pytest.mark.parametrize("payload_scenario", [(generate_device_digitaltwin_property_update_payload())])
    def test_iot_digitaltwin_property_update_error(self, fixture_cmd, serviceclient_generic_error, payload_scenario):
        with pytest.raises(CLIError):
            subject.iot_digitaltwin_property_update(fixture_cmd, device_id=device_id,
                                                    interface_payload=payload_scenario[0],
                                                    login=mock_target['cs'])


class TestDTInvokeCommand(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show),
            build_mock_response(mocker, request.param, {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("command_payload", [
        (generate_device_digitaltwin_invoke_command_payload()),
        (generate_device_digitaltwin_invoke_command_payload(content_from_file=True))])
    def test_iot_digitaltwin_invoke_command(self, fixture_cmd, serviceclient, command_payload):

        payload = None
        interface = 'environmentalSensor'
        command = 'blink'

        # If file path provided
        if not command_payload[0]:
            payload = command_payload[1]
        else:
            payload = str(read_file_content(_device_digitaltwin_invoke_command_payload))

        subject.iot_digitaltwin_invoke_command(fixture_cmd, device_id=device_id,
                                               interface=interface,
                                               command_name=command,
                                               command_payload=payload,
                                               login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'POST'
        assert '{}/digitalTwins/{}/interfaces/{}/commands/{}?'.format(mock_target['entity'], device_id,
                                                                      interface, command) in url

    @pytest.fixture(params=[(200, 400), (200, 401), (200, 500)])
    def serviceclient_error(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param[0], payload=output),
            build_mock_response(mocker, request.param[1], {})
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("command_payload, interface, command", [
        (generate_device_digitaltwin_invoke_command_payload(), 'environmentalSensor', 'blink'),
        (generate_device_digitaltwin_invoke_command_payload(content_from_file=True), 'environmentalSensor', 'blink'),
        (generate_device_digitaltwin_invoke_command_payload(), 'test', 'blink'),
        (generate_device_digitaltwin_invoke_command_payload(), 'environmentalSensor', 'test')])
    def test_iot_digitaltwin_property_update_error(self, fixture_cmd, serviceclient_error,
                                                   command_payload, interface, command):
        payload = None
        if not command_payload[0]:
            payload = command_payload[1]
        else:
            payload = str(read_file_content(_device_digitaltwin_invoke_command_payload))
        with pytest.raises(CLIError):
            subject.iot_digitaltwin_invoke_command(fixture_cmd, device_id=device_id,
                                                   interface=interface,
                                                   command_name=command,
                                                   command_payload=payload,
                                                   login=mock_target['cs'])


@pytest.mark.skipif(not validate_min_python_version(3, 5, exit_on_fail=False), reason="minimum python version not satisfied")
class TestDTMonitorEvents(object):

    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_monitor_events, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show)
        ]
        service_client.side_effect = test_side_effect
        return service_client

    def test_iot_digitaltwin_monitor_events(self, fixture_cmd, serviceclient):
        subject.iot_digitaltwin_monitor_events(fixture_cmd, device_id=device_id,
                                               interface='environmentalSensor', source_model='public',
                                               yes=True, properties='all', login=mock_target['cs'])
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method

        assert method == 'GET'
        assert '/models/' in url

    @pytest.fixture(params=[200])
    def serviceclienterror(self, mocker, fixture_ghcs, request):
        service_client = mocker.patch(path_service_client)
        output = generate_device_interfaces_payload()
        payload_list = generate_pnp_interface_list_payload()
        payload_show = generate_pnp_interface_show_payload()
        test_side_effect = [
            build_mock_response(mocker, request.param, payload=output),
            build_mock_response(mocker, request.param, payload=payload_list),
            build_mock_response(mocker, request.param, payload=payload_show)
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("interface, timeout", [('inter1', 0), ('environmentalSensor', -1)])
    def test_iot_digitaltwin_monitor_events_error(self, fixture_cmd, serviceclienterror, interface, timeout):
        with pytest.raises(CLIError):
            subject.iot_digitaltwin_monitor_events(fixture_cmd, device_id=device_id, source_model='public',
                                                   interface=interface, timeout=timeout,
                                                   yes=True, properties='all', login=mock_target['cs'])
