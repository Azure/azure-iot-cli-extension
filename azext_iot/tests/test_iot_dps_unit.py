# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import os
from azext_iot import custom as subject
from azext_iot.common.utility import evaluate_literal
from knack.util import CLIError
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from azure.cli.core.util import read_file_content

device_id = 'mydevice'
enrollment_id = 'myEnrollment'
resource_group = 'myrg'

mock_target = {}
mock_target['cs'] = 'HostName=mydps;SharedAccessKeyName=name;SharedAccessKey=value'
mock_target['entity'] = 'mydps'
mock_target['primarykey'] = 'rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['secondarykey'] = 'aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['policy'] = 'provisioningserviceowner'
mock_target['subscription'] = "5952cff8-bcd1-4235-9554-af2c0348bf23"


# Patch Paths #
path_service_client = 'msrest.service_client.ServiceClient.send'
path_ghcs = 'azext_iot.custom.get_iot_dps_connection_string'
path_sas = 'azext_iot._factory.SasTokenAuthentication'


@pytest.fixture()
def fixture_ghcs(mocker):
    ghcs = mocker.patch(path_ghcs)
    ghcs.return_value = mock_target


@pytest.fixture()
def fixture_sas(mocker):
    r = SasTokenAuthentication(mock_target['entity'], mock_target['policy'], mock_target['primarykey'])
    sas = mocker.patch(path_sas)
    sas.return_value = r


@pytest.fixture(params=[400, 401, 500])
def serviceclient_generic_error(mocker, fixture_ghcs, fixture_sas, request):
    service_client = mocker.patch(path_service_client)
    response = mocker.MagicMock(name='response')
    response.status_code = request.param
    service_client.return_value = response
    return service_client


def generate_enrollment_create_req(attestation_type = None, endorsement_key = None, certificate_path = None,
                                   device_id = None, iot_hub_host_name = None, initial_twin_tags = None,
                                   initial_twin_properties = None, provisioning_status = None):
    return {'client': None, 
            'enrollment_id': enrollment_id,
            'rg': resource_group, 
            'dps_name': mock_target['entity'], 
            'attestation_type': attestation_type,
            'endorsement_key': endorsement_key, 
            'certificate_path': certificate_path,
            'device_id': device_id,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status}

class TestEnrollmentCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type = 'tpm', endorsement_key = 'mykey')),
        (generate_enrollment_create_req(attestation_type = 'tpm', endorsement_key = 'mykey', device_id = '1', iot_hub_host_name = 'myHub', provisioning_status = 'disabled')),
        (generate_enrollment_create_req(attestation_type = 'tpm', endorsement_key = 'mykey', provisioning_status = 'enabled', initial_twin_tags = "\"{'key':'value'}\"")),
        (generate_enrollment_create_req(attestation_type = 'x509', certificate_path = 'myCert')),
        (generate_enrollment_create_req(attestation_type = 'x509', certificate_path = 'myCert', device_id = '1', iot_hub_host_name = 'myHub', provisioning_status = 'disabled')),
        (generate_enrollment_create_req(attestation_type = 'x509', certificate_path = 'myCert', provisioning_status = 'enabled', initial_twin_properties = "\"{'key':'value'}\""))
    ])
    def test_enrollment_create(self, serviceclient, req):       
        subject.iot_dps_device_enrollment_create(None, req['enrollment_id'], req['attestation_type'],
                                                 req['dps_name'], req['rg'], req['endorsement_key'], req['certificate_path'],
                                                 req['device_id'], req['iot_hub_host_name'], req['initial_twin_tags'],
                                                 req['initial_twin_properties'], req['provisioning_status'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        
        body = args[0][2]
        assert body['registrationId'] == req['enrollment_id']
        if req['attestation_type'] == 'tpm':
            assert body['attestation']['type'] == req['attestation_type']
            assert body['attestation']['tpm']['endorsementKey'] == req['endorsement_key']
        else:
            assert body['attestation']['type'] == req['attestation_type']
            assert body['attestation']['x509']['clientCertificates'] is not None

        if not req['device_id'] ==None:
            assert body['deviceId'] == req['device_id']
        if not req['iot_hub_host_name'] == None:
            assert body['iotHubHostName'] == req['iot_hub_host_name']
        if not req['provisioning_status'] == None:
            assert body['provisioningStatus'] == req['provisioning_status']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type = 'x509')),
        (generate_enrollment_create_req(attestation_type = 'x509', endorsement_key = 'myKey')),
        (generate_enrollment_create_req(attestation_type = 'tpm')),
        (generate_enrollment_create_req(attestation_type = 'tpm', certificate_path = 'myCert')),
    ])
    def test_enrollment_create_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(None, req['enrollment_id'], req['attestation_type'],
                                  req['dps_name'], req['rg'], req['endorsement_key'], req['certificate_path'])

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type = 'tpm', endorsement_key = 'mykey'))
    ])       
    def test_enrollment_show_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(None, req['enrollment_id'], req['attestation_type'],
                                                 req['dps_name'], req['rg'], req['endorsement_key'], req['certificate_path'],
                                                 req['device_id'], req['iot_hub_host_name'], req['initial_twin_tags'],
                                                 req['initial_twin_properties'], req['provisioning_status'])


def generate_enrollment_show(**kvp): 
    payload = {'attestation': {'x509': {'clientCertificates': None, 'signingCertificates': None}, 'tpm': None, 'type': 'x509'}, 'registrationId': enrollment_id, 'etag': 'AAAA==',
               'provisioningStatus': 'disabled', 'iotHubHostName': 'myHub', 'deviceId': 'myDevice'}
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload

class TestEnrollmentUpdate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_show(attestation = {'type': 'x509'})),
    ])
    def test_enrollment_update(self, serviceclient, req):       
        subject.iot_dps_device_enrollment_update(None, enrollment_id, mock_target['entity'], resource_group, 'AAAA==', None, 'newCertPath') #Cannot serialize into Individual Enrollment
 
        args = serviceclient.call_args_list[1]
        url = args[0][0].url
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['registrationId'] == req['enrollment_id']


class TestEnrollmentShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_enrollment_show())
        service_client.return_value = response
        return service_client

    def test_enrollment_show(self, serviceclient):
        result = subject.iot_dps_device_enrollment_get(None, enrollment_id, mock_target['entity'], resource_group)
        #assert result('registrationId') == enrollment_id #Individual enrollment is not callable
        #assert result['registrationId'] == enrollment_id #Individual enrollment is not scriptable
        #assert result == generate_enrollment_show() #Not exactly equal as Attestion has been serialized into the object
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_enrollment_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_get(None, enrollment_id, mock_target['entity'], resource_group)


class TestEnrollmentList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        result = []
        result.append(generate_enrollment_show())
        response.text = json.dumps(result)
        service_client.return_value = response
        return service_client

    def test_enrollment_list(self, serviceclient):
        result = subject.iot_dps_device_enrollment_list(None, mock_target['entity'], resource_group)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/query?".format(mock_target['entity']) in url
        assert method == 'POST'

    def test_enrollment_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_list(None, mock_target['entity'], resource_group)


class TestEnrollmentDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_ghcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    def test_enrollment_delete(self, serviceclient):
        result = subject.iot_dps_device_enrollment_delete(None, enrollment_id, mock_target['entity'], resource_group)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'DELETE'

    def test_enrollment_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_delete(None, enrollment_id, mock_target['entity'], resource_group)
