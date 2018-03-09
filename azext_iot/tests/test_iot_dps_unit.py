# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
from azext_iot.operations import dps as subject
from knack.util import CLIError
from azext_iot.common.sas_token_auth import SasTokenAuthentication

enrollment_id = 'myenrollment'
resource_group = 'myrg'
registration_id = 'myregistration'
etag = 'AAAA=='

mock_target = {}
mock_target['cs'] = 'HostName=mydps;SharedAccessKeyName=name;SharedAccessKey=value'
mock_target['entity'] = 'mydps'
mock_target['primarykey'] = 'rJx/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['secondarykey'] = 'aCd/6rJ6rmG4ak890+eW5MYGH+A0uzRvjGNjg3Ve8sfo='
mock_target['policy'] = 'provisioningserviceowner'
mock_target['subscription'] = "5952cff8-bcd1-4235-9554-af2c0348bf23"


# Patch Paths #
path_service_client = 'msrest.service_client.ServiceClient.send'
path_gdcs = 'azext_iot.operations.dps.get_iot_dps_connection_string'
path_sas = 'azext_iot._factory.SasTokenAuthentication'


@pytest.fixture()
def fixture_gdcs(mocker):
    ghcs = mocker.patch(path_gdcs)
    ghcs.return_value = mock_target


@pytest.fixture()
def fixture_sas(mocker):
    r = SasTokenAuthentication(mock_target['entity'],
                               mock_target['policy'],
                               mock_target['primarykey'])
    sas = mocker.patch(path_sas)
    sas.return_value = r


@pytest.fixture(params=[400, 401, 500])
def serviceclient_generic_error(mocker, fixture_gdcs, fixture_sas, request):
    service_client = mocker.patch(path_service_client)
    response = mocker.MagicMock(name='response')
    response.status_code = request.param
    service_client.return_value = response
    return service_client


def generate_enrollment_create_req(attestation_type=None, endorsement_key=None,
                                   certificate_path=None, secondary_certificate_path=None,
                                   device_Id=None, iot_hub_host_name=None,
                                   initial_twin_tags=None, initial_twin_properties=None,
                                   provisioning_status=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'attestation_type': attestation_type,
            'endorsement_key': endorsement_key,
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'device_id': device_Id,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status}


class TestEnrollmentCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey')),
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey',
                                        device_Id='1',
                                        iot_hub_host_name='myHub',
                                        provisioning_status='disabled')),
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey',
                                        provisioning_status='enabled',
                                        initial_twin_tags={'key': 'value'})),
        (generate_enrollment_create_req(attestation_type='x509',
                                        certificate_path='myCert')),
        (generate_enrollment_create_req(attestation_type='x509',
                                        secondary_certificate_path='myCert2')),
        (generate_enrollment_create_req(attestation_type='x509',
                                        certificate_path='myCert',
                                        device_Id='1',
                                        iot_hub_host_name='myHub',
                                        provisioning_status='disabled')),
        (generate_enrollment_create_req(attestation_type='x509',
                                        certificate_path='myCert',
                                        provisioning_status='enabled',
                                        initial_twin_properties={'key': 'value'}))
    ])
    def test_enrollment_create(self, serviceclient, req):
        subject.iot_dps_device_enrollment_create(None,
                                                 req['enrollment_id'],
                                                 req['attestation_type'],
                                                 req['dps_name'], req['rg'],
                                                 req['endorsement_key'],
                                                 req['certificate_path'],
                                                 req['secondary_certificate_path'],
                                                 req['device_id'],
                                                 req['iot_hub_host_name'],
                                                 req['initial_twin_tags'],
                                                 req['initial_twin_properties'],
                                                 req['provisioning_status'])
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
            if req['certificate_path']:
                assert body['attestation']['x509']['clientCertificates']['primary'] is not None
            if req['secondary_certificate_path']:
                assert body['attestation']['x509']['clientCertificates']['secondary'] is not None

        if req['device_id']:
            assert body['deviceId'] == req['device_id']
        if req['iot_hub_host_name']:
            assert body['iotHubHostName'] == req['iot_hub_host_name']
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='x509')),
        (generate_enrollment_create_req(attestation_type='x509', endorsement_key='myKey')),
        (generate_enrollment_create_req(attestation_type='tpm')),
        (generate_enrollment_create_req(attestation_type='tpm', certificate_path='myCert')),
    ])
    def test_enrollment_create_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(None, req['enrollment_id'],
                                                     req['attestation_type'],
                                                     req['dps_name'], req['rg'],
                                                     req['endorsement_key'],
                                                     req['certificate_path'])

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='tpm', endorsement_key='mykey'))
    ])
    def test_enrollment_show_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(None,
                                                     req['enrollment_id'],
                                                     req['attestation_type'],
                                                     req['dps_name'], req['rg'],
                                                     req['endorsement_key'],
                                                     req['certificate_path'],
                                                     req['device_id'], req['iot_hub_host_name'],
                                                     req['initial_twin_tags'],
                                                     req['initial_twin_properties'],
                                                     req['provisioning_status'])


def generate_enrollment_show(**kvp):
    payload = {'attestation':
               {'x509': {'clientCertificates': {'primary':
                         {'info':
                          {'issuerName': 'test', 'notAfterUtc': '2037-01-01T00:00:00Z',
                           'notBeforeUtc': '2017-01-01T00:00:00Z',
                           'serialNumber': '1A2B3C4D5E',
                           'sha1Thumbprint': '109F2ED9D3FC92C88C1DE2203488B93D6B3F05F5',
                           'sha256Thumbprint': 'F7D272B400C88FAC2A12A990F14DD2E881CA1F',
                           'subjectName': 'test',
                           'version': '3'}}, 'secondary': None},
                         }, 'tpm': None, 'type': 'x509'},
               'registrationId': enrollment_id, 'etag': etag,
               'provisioningStatus': 'disabled', 'iotHubHostName': 'myHub',
               'deviceId': 'myDevice'}
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


def build_mock_response(mocker, status_code=200, payload=None):
    response = mocker.MagicMock(name='response')
    response.status_code = status_code
    response.text = json.dumps(payload)
    del response._attribute_map
    return response


def generate_enrollment_update_req(certificate_path=None, iot_hub_host_name=None,
                                   initial_twin_tags=None,
                                   secondary_certificate_path=None,
                                   remove_certificate_path=None,
                                   remove_secondary_certificate_path=None,
                                   initial_twin_properties=None, provisioning_status=None,
                                   device_id=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'remove_certificate_path': remove_certificate_path,
            'remove_secondary_certificate_path': remove_secondary_certificate_path,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status,
            'device_id': device_id}


class TestEnrollmentUpdate():
    @pytest.fixture(params=[(200, generate_enrollment_show(), 200)])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], request.param[1]),
            build_mock_response(mocker, request.param[2])
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_update_req(secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_update_req(certificate_path='newCertPath', secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_update_req(remove_certificate_path='true')),
        (generate_enrollment_update_req(iot_hub_host_name='someOtherHubName',
                                        initial_twin_tags={'newKey': 'newValue'},
                                        initial_twin_properties={'newKey': 'newValue'},
                                        provisioning_status='enabled',
                                        device_id='newId'))
    ])
    def test_enrollment_update(self, serviceclient, req):
        subject.iot_dps_device_enrollment_update(None,
                                                 req['enrollment_id'],
                                                 req['dps_name'],
                                                 req['rg'],
                                                 etag,
                                                 None,
                                                 req['certificate_path'],
                                                 req['secondary_certificate_path'],
                                                 req['remove_certificate_path'],
                                                 req['remove_secondary_certificate_path'],
                                                 req['device_id'],
                                                 req['iot_hub_host_name'],
                                                 req['initial_twin_tags'],
                                                 req['initial_twin_properties'],
                                                 req['provisioning_status'])
        # Index 1 is the update args
        args = serviceclient.call_args_list[1]
        url = args[0][0].url

        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]

        if not req['certificate_path']:
            if req['remove_certificate_path']:
                assert body['attestation']['x509']['clientCertificates']['primary'] is None
            else:
                assert body['attestation']['x509']['clientCertificates']['primary']['info'] is not None
        if req['certificate_path']:
            assert body['attestation']['x509']['clientCertificates']['primary']['certificate'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['x509']['clientCertificates']['secondary']['certificate'] is not None
        if req['iot_hub_host_name']:
            assert body['iotHubHostName'] == req['iot_hub_host_name']
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']
        if req['device_id']:
            assert body['deviceId'] == req['device_id']


class TestEnrollmentShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_enrollment_show())
        service_client.return_value = response
        return service_client

    def test_enrollment_show(self, serviceclient):
        result = subject.iot_dps_device_enrollment_get(None, enrollment_id,
                                                       mock_target['entity'], resource_group)
        assert json.dumps(result)
        assert result['registrationId'] == enrollment_id
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_enrollment_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_get(None, enrollment_id,
                                                  mock_target['entity'], resource_group)


class TestEnrollmentList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("servresult, servtotal, top", [
        ([generate_enrollment_show()], 6, 3),
        ([generate_enrollment_show(), generate_enrollment_show()], 5, 2),
        ([generate_enrollment_show(), generate_enrollment_show()], 6, None),
        ([generate_enrollment_show() for i in range(0, 12)], 100, 51),
        ([generate_enrollment_show()], 1, 100)
    ])
    def test_enrollment_list(self, serviceclient, servresult, servtotal, top):
        serviceclient.return_value.text = json.dumps(servresult)
        pagesize = len(servresult)
        continuation = []

        for i in range(int(servtotal / pagesize)):
            continuation.append({'x-ms-continuation': 'abcd'})
        if servtotal % pagesize != 0:
            continuation.append({'x-ms-continuation': 'abcd'})
        continuation[-1] = None

        serviceclient.return_value.headers.get.side_effect = continuation

        result = subject.iot_dps_device_enrollment_list(None, mock_target['entity'],
                                                        resource_group, top)

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
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/query?".format(mock_target['entity']) in url
        assert method == 'POST'

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

    def test_enrollment_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_list(None, mock_target['entity'], resource_group)


class TestEnrollmentDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    def test_enrollment_delete(self, serviceclient):
        subject.iot_dps_device_enrollment_delete(None, enrollment_id,
                                                 mock_target['entity'], resource_group)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'DELETE'

    def test_enrollment_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_delete(None, enrollment_id,
                                                     mock_target['entity'], resource_group)


def generate_enrollment_group_create_req(certificate_path=None, iot_hub_host_name=None,
                                         initial_twin_tags=None,
                                         secondary_certificate_path=None,
                                         initial_twin_properties=None, provisioning_status=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status}


class TestEnrollmentGroupCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(certificate_path='myCert')),
        (generate_enrollment_group_create_req(secondary_certificate_path='myCert2')),
        (generate_enrollment_group_create_req(certificate_path='myCert', iot_hub_host_name='myHub',
                                              provisioning_status='disabled')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              provisioning_status='enabled',
                                              initial_twin_properties={'key': 'value'}))
    ])
    def test_enrollment_group_create(self, serviceclient, req):
        subject.iot_dps_device_enrollment_group_create(None,
                                                       req['enrollment_id'],
                                                       req['dps_name'],
                                                       req['rg'],
                                                       req['certificate_path'],
                                                       req['secondary_certificate_path'],
                                                       req['iot_hub_host_name'],
                                                       req['initial_twin_tags'],
                                                       req['initial_twin_properties'],
                                                       req['provisioning_status'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['enrollmentGroupId'] == req['enrollment_id']
        assert body['attestation']['type'] == 'x509'
        if req['certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['primary'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['secondary'] is not None

        if req['iot_hub_host_name']:
            assert body['iotHubHostName'] == req['iot_hub_host_name']
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req())
    ])
    def test_enrollment_group_create_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(None, req['enrollment_id'],
                                                           req['dps_name'], req['rg'],
                                                           req['certificate_path'])

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(certificate_path='myCert'))
    ])
    def test_enrollment_group_show_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(None, req['enrollment_id'],
                                                           req['dps_name'], req['rg'],
                                                           req['certificate_path'],
                                                           req['iot_hub_host_name'],
                                                           req['initial_twin_tags'],
                                                           req['initial_twin_properties'],
                                                           req['provisioning_status'])


def generate_enrollment_group_show(**kvp):
    payload = {'attestation': {'x509':
                               {'signingCertificates': {'primary':
                                {'info':
                                 {'issuerName': 'test', 'notAfterUtc': '2037-01-01T00:00:00Z',
                                  'notBeforeUtc': '2017-01-01T00:00:00Z',
                                  'serialNumber': '1A2B3C4D5E',
                                  'sha1Thumbprint': '109F2ED9D3FC92C88C1DE2203488B93D6B3F05F5',
                                  'sha256Thumbprint': 'F7D272B400C88FAC2A12A990F14DD2E881CA1F',
                                  'subjectName': 'test',
                                  'version': '3'}}, 'secondary': None},
                                }, 'type': 'x509'},
               'enrollmentGroupId': enrollment_id, 'etag': etag,
               'provisioningStatus': 'disabled', 'iotHubHostName': 'myHub'}
    for k in kvp:
        if payload.get(k):
            payload[k] = kvp[k]
    return payload


def generate_enrollment_group_update_req(certificate_path=None, iot_hub_host_name=None,
                                         initial_twin_tags=None,
                                         secondary_certificate_path=None,
                                         remove_certificate_path=None,
                                         remove_secondary_certificate_path=None,
                                         initial_twin_properties=None, provisioning_status=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'remove_certificate_path': remove_certificate_path,
            'remove_secondary_certificate_path': remove_secondary_certificate_path,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status}


class TestEnrollmentGroupUpdate():
    @pytest.fixture(params=[(200, generate_enrollment_group_show(), 200)])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        test_side_effect = [
            build_mock_response(mocker, request.param[0], request.param[1]),
            build_mock_response(mocker, request.param[2])
        ]
        service_client.side_effect = test_side_effect
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_update_req(secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_group_update_req(certificate_path='newCertPath', secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_group_update_req(remove_certificate_path='true')),
        (generate_enrollment_group_update_req(iot_hub_host_name='someOtherHubName',
                                              initial_twin_tags={'newKey': 'newValue'},
                                              initial_twin_properties={'newKey': 'newValue'},
                                              provisioning_status='enabled')),
    ])
    def test_enrollment_group_update(self, serviceclient, req):
        subject.iot_dps_device_enrollment_group_update(None,
                                                       req['enrollment_id'],
                                                       req['dps_name'],
                                                       req['rg'],
                                                       etag,
                                                       req['certificate_path'],
                                                       req['secondary_certificate_path'],
                                                       req['remove_certificate_path'],
                                                       req['remove_secondary_certificate_path'],
                                                       req['iot_hub_host_name'],
                                                       req['initial_twin_tags'],
                                                       req['initial_twin_properties'],
                                                       req['provisioning_status'])
        # Index 1 is the update args
        args = serviceclient.call_args_list[1]
        url = args[0][0].url

        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]

        if not req['certificate_path']:
            if req['remove_certificate_path']:
                assert body['attestation']['x509']['signingCertificates']['primary'] is None
            else:
                assert body['attestation']['x509']['signingCertificates']['primary']['info'] is not None
        if req['certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['primary']['certificate'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['secondary']['certificate'] is not None
        if req['iot_hub_host_name']:
            assert body['iotHubHostName'] == req['iot_hub_host_name']
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']


class TestEnrollmentGroupShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_enrollment_group_show())
        service_client.return_value = response
        return service_client

    def test_enrollment_group_show(self, serviceclient):
        result = subject.iot_dps_device_enrollment_group_get(None, enrollment_id,
                                                             mock_target['entity'], resource_group)
        assert json.dumps(result)
        assert result['enrollmentGroupId'] == enrollment_id
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_enrollment_group_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_get(None, enrollment_id,
                                                        mock_target['entity'], resource_group)


class TestEnrollmentGroupList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    @pytest.mark.parametrize("servresult, servtotal, top", [
        ([generate_enrollment_group_show()], 6, 3),
        ([generate_enrollment_group_show(), generate_enrollment_show()], 5, 2),
        ([generate_enrollment_group_show(), generate_enrollment_show()], 6, None),
        ([generate_enrollment_group_show() for i in range(0, 12)], 100, 51),
        ([generate_enrollment_group_show()], 1, 100)
    ])
    def test_enrollment_group_list(self, serviceclient, servresult, servtotal, top):
        serviceclient.return_value.text = json.dumps(servresult)
        pagesize = len(servresult)
        continuation = []

        for i in range(int(servtotal / pagesize)):
            continuation.append({'x-ms-continuation': 'abcd'})
        if servtotal % pagesize != 0:
            continuation.append({'x-ms-continuation': 'abcd'})
        continuation[-1] = None

        serviceclient.return_value.headers.get.side_effect = continuation

        result = subject.iot_dps_device_enrollment_group_list(None, mock_target['entity'],
                                                              resource_group, top)

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
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollmentGroups/query?".format(mock_target['entity']) in url
        assert method == 'POST'

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

    def test_enrollment_group_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_list(None,
                                                         mock_target['entity'],
                                                         resource_group)


class TestEnrollmentGroupDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    def test_enrollment_group_delete(self, serviceclient):
        subject.iot_dps_device_enrollment_group_delete(None, enrollment_id,
                                                       mock_target['entity'], resource_group)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'DELETE'

    def test_enrollment_group_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_delete(None, enrollment_id,
                                                           mock_target['entity'], resource_group)


def generate_registration_state_show():
    payload = {'registrationId': registration_id, 'status': 'assigned', 'etag': 'AAAA=', 'assignedHub': 'myHub',
               'deviceId': 'myDevice'}
    return payload


class TestRegistrationShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        response.text = json.dumps(generate_registration_state_show())
        service_client.return_value = response
        return service_client

    def test_registration_show(self, serviceclient):
        result = subject.iot_dps_registration_get(None, mock_target['entity'],
                                                  resource_group, registration_id)
        assert json.dumps(result)
        assert result['registrationId'] == registration_id
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/registrations/{}?".format(mock_target['entity'], registration_id) in url
        assert method == 'GET'

    def test_registration_show_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_get(None, registration_id,
                                             mock_target['entity'], resource_group)


class TestRegistrationList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        result = []
        result.append(generate_registration_state_show())
        response.text = json.dumps(result)
        service_client.return_value = response
        return service_client

    def test_registration_list(self, serviceclient):
        subject.iot_dps_registration_list(None, mock_target['entity'],
                                          resource_group, enrollment_id)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/registrations/{}/query?".format(mock_target['entity'], enrollment_id) in url
        assert method == 'POST'

    def test_registration_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_list(None, mock_target['entity'],
                                              resource_group, enrollment_id)


class TestRegistrationDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        response = mocker.MagicMock(name='response')
        del response._attribute_map
        response.status_code = request.param
        service_client.return_value = response
        return service_client

    def test_registration_delete(self, serviceclient):
        subject.iot_dps_registration_delete(None, mock_target['entity'],
                                            resource_group, registration_id)
        args = serviceclient.call_args
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/registrations/{}?".format(mock_target['entity'], registration_id) in url
        assert method == 'DELETE'

    def test_registration_delete_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_delete(None, registration_id,
                                                mock_target['entity'], resource_group)


dps_suffix = "azure-devices.net"


class TestGetDpsConnString():
    @pytest.mark.parametrize("dpscount, targetdps, policy_name, rg_name, exp_success, why", [
        (5, 'dps1', 'provisioningserviceowner', 'myrg', True, None),
        (5, 'dps2', 'custompolicy', 'myrg', True, None),
        (1, 'dps3', 'provisioningserviceowner', 'myrg', False, 'policy'),
        (1, 'dps4', 'provisioningserviceowner', 'myrg', False, 'dps')
    ])
    def test_get_dps_conn_string(self, mocker, dpscount, targetdps,
                                 policy_name, rg_name, exp_success, why):
        def _build_dps(dps, name, rg=None):
            dps.name = name
            dps.properties.service_operations_host_name = "{}.{}".format(name, dps_suffix)
            dps.resourcegroup = rg
            client.config.subscription_id = mock_target['subscription']
            return dps

        def _build_policy(policy, name):
            policy.key_name = name
            policy.primary_key = mock_target['primarykey']
            policy.secondary_key = mock_target['secondarykey']
            return policy

        client = mocker.MagicMock(name='dpsclient')

        dps_list = []
        for i in range(0, dpscount):
            dps_list.append(_build_dps(mocker.MagicMock(), "dps{}".format(i), rg_name))
        client.list_by_subscription.return_value = dps_list

        if why == "dps":
            client.iot_dps_resource.get.side_effect = ValueError
        else:
            client.iot_dps_resource.get.return_value = _build_dps(mocker.MagicMock(),
                                                                  targetdps, rg_name)

        if why == "policy":
            client.iot_dps_resource.list_keys_for_key_name.side_effect = ValueError
        else:
            client.iot_dps_resource.list_keys_for_key_name.return_value = _build_policy(mocker.MagicMock(),
                                                                                        policy_name)

        from azext_iot.common.azure import get_iot_dps_connection_string

        if exp_success:
            result = get_iot_dps_connection_string(client, targetdps, rg_name, policy_name)
            expecting_dps = "{}.{}".format(targetdps, dps_suffix)
            assert result['entity'] == expecting_dps
            assert result['policy'] == policy_name
            assert result['subscription'] == mock_target['subscription']
            assert result['cs'] == "HostName={};SharedAccessKeyName={};SharedAccessKey={}".format(
                expecting_dps,
                policy_name,
                mock_target['primarykey'])

            client.iot_dps_resource.get.assert_called_with(targetdps, rg_name)
            client.iot_dps_resource.list_keys_for_key_name.assert_called_with(targetdps,
                                                                              policy_name,
                                                                              rg_name)

        else:
            with pytest.raises(CLIError):
                get_iot_dps_connection_string(client, targetdps, rg_name, policy_name)
