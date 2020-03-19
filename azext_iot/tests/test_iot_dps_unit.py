# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

'''
NOTICE: These tests are to be phased out and introduced in more modern form.
        Try not to add any new content, only fixes if necessary.
        Look at IoT Hub jobs or configuration tests for a better example. Also use responses fixtures
        like mocked_response for http request mocking.
'''

import pytest
import json
from azext_iot.operations import dps as subject
from knack.util import CLIError
from azext_iot.common.sas_token_auth import SasTokenAuthentication
from .conftest import build_mock_response

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
    service_client.return_value = build_mock_response(mocker, request.param, {'error': 'something failed'})
    return service_client


def generate_enrollment_create_req(attestation_type=None, endorsement_key=None,
                                   certificate_path=None, secondary_certificate_path=None,
                                   device_Id=None, iot_hub_host_name=None,
                                   initial_twin_tags=None, initial_twin_properties=None,
                                   provisioning_status=None, reprovision_policy=None,
                                   primary_key=None, secondary_key=None, allocation_policy=None,
                                   iot_hubs=None, edge_enabled=False):
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
            'provisioning_status': provisioning_status,
            'reprovision_policy': reprovision_policy,
            'primary_key': primary_key,
            'secondary_key': secondary_key,
            'allocation_policy': allocation_policy,
            'iot_hubs': iot_hubs,
            'edge_enabled': edge_enabled}


class TestEnrollmentCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
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
                                        initial_twin_properties={'key': 'value'})),
        (generate_enrollment_create_req(attestation_type='symmetricKey')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey')),
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey',
                                        reprovision_policy='reprovisionandmigratedata')),
        (generate_enrollment_create_req(attestation_type='x509',
                                        certificate_path='myCert',
                                        reprovision_policy='reprovisionandresetdata')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never',
                                        allocation_policy='static',
                                        iot_hubs='hub1')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never',
                                        allocation_policy='hashed',
                                        iot_hubs='hub1 hub2')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never',
                                        allocation_policy='geolatency')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        edge_enabled=True)),
    ])
    def test_enrollment_create(self, serviceclient, req):
        subject.iot_dps_device_enrollment_create(None,
                                                 req['enrollment_id'],
                                                 req['attestation_type'],
                                                 req['dps_name'], req['rg'],
                                                 req['endorsement_key'],
                                                 req['certificate_path'],
                                                 req['secondary_certificate_path'],
                                                 req['primary_key'],
                                                 req['secondary_key'],
                                                 req['device_id'],
                                                 req['iot_hub_host_name'],
                                                 req['initial_twin_tags'],
                                                 req['initial_twin_properties'],
                                                 req['provisioning_status'],
                                                 req['reprovision_policy'],
                                                 req['allocation_policy'],
                                                 req['iot_hubs'],
                                                 req['edge_enabled'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['registrationId'] == req['enrollment_id']
        if req['attestation_type'] == 'tpm':
            assert body['attestation']['type'] == req['attestation_type']
            assert body['attestation']['tpm']['endorsementKey'] == req['endorsement_key']
        elif req['attestation_type'] == 'x509':
            assert body['attestation']['type'] == req['attestation_type']
            assert body['attestation']['x509']['clientCertificates'] is not None
            if req['certificate_path']:
                assert body['attestation']['x509']['clientCertificates']['primary'] is not None
            if req['secondary_certificate_path']:
                assert body['attestation']['x509']['clientCertificates']['secondary'] is not None
        else:
            assert body['attestation']['type'] == req['attestation_type']
            assert body['attestation']['symmetricKey'] is not None
            if req['primary_key']:
                assert body['attestation']['symmetricKey']['primaryKey'] is not None
            if req['secondary_key']:
                assert body['attestation']['symmetricKey']['secondaryKey'] is not None

        if req['device_id']:
            assert body['deviceId'] == req['device_id']
        if req['iot_hub_host_name']:
            assert body['allocationPolicy'] == 'static'
            assert body['iotHubs'] == req['iot_hub_host_name'].split()
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']
        if not req['reprovision_policy']:
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandmigratedata':
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandresetdata':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'never':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert not body['reprovisionPolicy']['updateHubAssignment']
        if req['allocation_policy']:
            assert body['allocationPolicy'] == req['allocation_policy']
        if req['iot_hubs']:
            assert body['iotHubs'] == req['iot_hubs'].split()
        if req['edge_enabled']:
            assert body['capabilities']['iotEdge']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='x509')),
        (generate_enrollment_create_req(attestation_type='x509', endorsement_key='myKey')),
        (generate_enrollment_create_req(attestation_type='tpm')),
        (generate_enrollment_create_req(attestation_type='tpm', certificate_path='myCert')),
        (generate_enrollment_create_req(reprovision_policy='invalid')),
        (generate_enrollment_create_req(allocation_policy='invalid')),
        (generate_enrollment_create_req(allocation_policy='static')),
        (generate_enrollment_create_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_create_req(allocation_policy='static', iot_hub_host_name='hubname')),
        (generate_enrollment_create_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_create_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(None, req['enrollment_id'],
                                                     req['attestation_type'],
                                                     req['dps_name'], req['rg'],
                                                     req['endorsement_key'],
                                                     req['certificate_path'],
                                                     None,
                                                     req['primary_key'],
                                                     None,
                                                     None,
                                                     req['iot_hub_host_name'],
                                                     None,
                                                     None,
                                                     None,
                                                     req['reprovision_policy'],
                                                     req['allocation_policy'],
                                                     req['iot_hubs'])

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


def generate_enrollment_update_req(certificate_path=None, iot_hub_host_name=None,
                                   initial_twin_tags=None,
                                   secondary_certificate_path=None,
                                   remove_certificate_path=None,
                                   remove_secondary_certificate_path=None,
                                   initial_twin_properties=None, provisioning_status=None,
                                   device_id=None,
                                   etag=None, reprovision_policy=None,
                                   allocation_policy=None, iot_hubs=None,
                                   edge_enabled=None):
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
            'device_id': device_id,
            'etag': etag,
            'reprovision_policy': reprovision_policy,
            'allocation_policy': allocation_policy,
            'iot_hubs': iot_hubs,
            'edge_enabled': edge_enabled}


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
        (generate_enrollment_update_req(etag=etag, secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_update_req(certificate_path='newCertPath', secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_update_req(remove_certificate_path='true')),
        (generate_enrollment_update_req(iot_hub_host_name='someOtherHubName',
                                        initial_twin_tags={'newKey': 'newValue'},
                                        initial_twin_properties={'newKey': 'newValue'},
                                        provisioning_status='enabled',
                                        device_id='newId')),
        (generate_enrollment_update_req(reprovision_policy='reprovisionandmigratedata')),
        (generate_enrollment_update_req(reprovision_policy='reprovisionandresetdata')),
        (generate_enrollment_update_req(reprovision_policy='never')),
        (generate_enrollment_update_req(allocation_policy='static', iot_hubs='hub1')),
        (generate_enrollment_update_req(allocation_policy='hashed', iot_hubs='hub1 hub2')),
        (generate_enrollment_update_req(allocation_policy='geolatency')),
        (generate_enrollment_update_req(edge_enabled=True)),
        (generate_enrollment_update_req(edge_enabled=False))
    ])
    def test_enrollment_update(self, serviceclient, req):
        subject.iot_dps_device_enrollment_update(None,
                                                 req['enrollment_id'],
                                                 req['dps_name'],
                                                 req['rg'],
                                                 req['etag'],
                                                 None,
                                                 req['certificate_path'],
                                                 req['secondary_certificate_path'],
                                                 req['remove_certificate_path'],
                                                 req['remove_secondary_certificate_path'],
                                                 None,
                                                 None,
                                                 req['device_id'],
                                                 req['iot_hub_host_name'],
                                                 req['initial_twin_tags'],
                                                 req['initial_twin_properties'],
                                                 req['provisioning_status'],
                                                 req['reprovision_policy'],
                                                 req['allocation_policy'],
                                                 req['iot_hubs'],
                                                 edge_enabled=req['edge_enabled'])
        # Index 1 is the update args
        args = serviceclient.call_args_list[1]
        url = args[0][0].url

        assert "{}/enrollments/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        if not req['certificate_path']:
            if req['remove_certificate_path']:
                assert body['attestation']['x509']['clientCertificates'].get('primary') is None
            else:
                assert body['attestation']['x509']['clientCertificates']['primary']['info'] is not None
        if req['certificate_path']:
            assert body['attestation']['x509']['clientCertificates']['primary']['certificate'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['x509']['clientCertificates']['secondary']['certificate'] is not None
        if req['iot_hub_host_name']:
            assert body['allocationPolicy'] == 'static'
            assert body['iotHubs'] == req['iot_hub_host_name'].split()
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']
        if req['device_id']:
            assert body['deviceId'] == req['device_id']
        if req['reprovision_policy'] == 'reprovisionandmigratedata':
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandresetdata':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'never':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert not body['reprovisionPolicy']['updateHubAssignment']
        if req['allocation_policy']:
            assert body['allocationPolicy'] == req['allocation_policy']
        if req['iot_hubs']:
            assert body['iotHubs'] == req['iot_hubs'].split()
        if req['edge_enabled'] is not None:
            assert body['capabilities']['iotEdge'] == req['edge_enabled']


class TestEnrollmentShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, generate_enrollment_show())
        return service_client

    def test_enrollment_show(self, serviceclient):
        result = subject.iot_dps_device_enrollment_get(None, enrollment_id,
                                                       mock_target['entity'], resource_group)

        assert result.registration_id == enrollment_id
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
        service_client.return_value = build_mock_response(mocker, request.param, [generate_enrollment_show()])
        return service_client

    @pytest.mark.parametrize("top", [3, None])
    def test_enrollment_list(self, serviceclient, top):
        result = subject.iot_dps_device_enrollment_list(None, mock_target['entity'], resource_group, top)
        args = serviceclient.call_args_list[0]
        headers = args[0][1]
        url = args[0][0].url
        method = args[0][0].method

        assert str(headers.get("x-ms-max-item-count")) == str(top)
        assert "{}/enrollments/query?".format(mock_target['entity']) in url
        assert method == "POST"
        assert json.dumps(result)

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


def generate_enrollment_group_create_req(iot_hub_host_name=None,
                                         initial_twin_tags=None,
                                         certificate_path=None,
                                         secondary_certificate_path=None,
                                         root_ca_name=None,
                                         secondary_root_ca_name=None,
                                         primary_key=None,
                                         secondary_key=None,
                                         initial_twin_properties=None,
                                         provisioning_status=None,
                                         reprovision_policy=None,
                                         allocation_policy=None,
                                         iot_hubs=None,
                                         edge_enabled=False):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'root_ca_name': root_ca_name,
            'secondary_root_ca_name': secondary_root_ca_name,
            'primary_key': primary_key,
            'secondary_key': secondary_key,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status,
            'reprovision_policy': reprovision_policy,
            'allocation_policy': allocation_policy,
            'iot_hubs': iot_hubs,
            'edge_enabled': edge_enabled}


class TestEnrollmentGroupCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
        return service_client

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(primary_key='primarykey',
                                              secondary_key='secondarykey')),
        (generate_enrollment_group_create_req(certificate_path='myCert')),
        (generate_enrollment_group_create_req(secondary_certificate_path='myCert2')),
        (generate_enrollment_group_create_req(root_ca_name='myCert')),
        (generate_enrollment_group_create_req(secondary_root_ca_name='myCert2')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              iot_hub_host_name='myHub',
                                              provisioning_status='disabled')),
        (generate_enrollment_group_create_req(root_ca_name='myCert',
                                              provisioning_status='enabled',
                                              initial_twin_properties={'key': 'value'})),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              reprovision_policy='reprovisionandmigratedata')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              reprovision_policy='reprovisionandresetdata')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              reprovision_policy='never')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              allocation_policy='static',
                                              iot_hubs='hub1')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              allocation_policy='hashed',
                                              iot_hubs='hub1 hub2')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              allocation_policy='geolatency')),
        (generate_enrollment_group_create_req(primary_key='primarykey',
                                              secondary_key='secondarykey',
                                              edge_enabled=True)),
    ])
    def test_enrollment_group_create(self, serviceclient, req):
        subject.iot_dps_device_enrollment_group_create(None,
                                                       req['enrollment_id'],
                                                       req['dps_name'],
                                                       req['rg'],
                                                       req['certificate_path'],
                                                       req['secondary_certificate_path'],
                                                       req['root_ca_name'],
                                                       req['secondary_root_ca_name'],
                                                       req['primary_key'],
                                                       req['secondary_key'],
                                                       req['iot_hub_host_name'],
                                                       req['initial_twin_tags'],
                                                       req['initial_twin_properties'],
                                                       req['provisioning_status'],
                                                       req['reprovision_policy'],
                                                       req['allocation_policy'],
                                                       req['iot_hubs'],
                                                       edge_enabled=req['edge_enabled'])
        args = serviceclient.call_args
        url = args[0][0].url
        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        assert body['enrollmentGroupId'] == req['enrollment_id']
        if req['certificate_path']:
            assert body['attestation']['type'] == 'x509'
            assert body['attestation']['x509']['signingCertificates']['primary'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['type'] == 'x509'
            assert body['attestation']['x509']['signingCertificates']['secondary'] is not None
        if req['root_ca_name']:
            assert body['attestation']['type'] == 'x509'
            assert body['attestation']['x509']['caReferences']['primary'] is not None
        if req['secondary_root_ca_name']:
            assert body['attestation']['type'] == 'x509'
            assert body['attestation']['x509']['caReferences']['secondary'] is not None

        if not req['certificate_path'] and not req['secondary_certificate_path']:
            if not req['root_ca_name'] and not req['secondary_root_ca_name']:
                assert body['attestation']['type'] == 'symmetricKey'
                assert body['attestation']['symmetricKey']['primaryKey'] is not None
                assert body['attestation']['symmetricKey']['secondaryKey'] is not None

        if req['iot_hub_host_name']:
            assert body['allocationPolicy'] == 'static'
            assert body['iotHubs'] == req['iot_hub_host_name'].split()
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']
        if not req['reprovision_policy']:
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandmigratedata':
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandresetdata':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'never':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert not body['reprovisionPolicy']['updateHubAssignment']
        if req['allocation_policy']:
            assert body['allocationPolicy'] == req['allocation_policy']
        if req['iot_hubs']:
            assert body['iotHubs'] == req['iot_hubs'].split()
        if req['edge_enabled']:
            assert body['capabilities']['iotEdge']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              root_ca_name='myCert')),
        (generate_enrollment_group_create_req(secondary_certificate_path='myCert2',
                                              root_ca_name='myCert',
                                              secondary_root_ca_name='myCert2')),
        (generate_enrollment_group_create_req(root_ca_name='myCert',
                                              secondary_certificate_path='myCert2')),
        (generate_enrollment_group_create_req(reprovision_policy='invalid')),
        (generate_enrollment_group_create_req(allocation_policy='invalid')),
        (generate_enrollment_group_create_req(allocation_policy='static', iot_hub_host_name='hub')),
        (generate_enrollment_group_create_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_create_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_group_create_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(None,
                                                           req['enrollment_id'],
                                                           req['dps_name'],
                                                           req['rg'],
                                                           req['certificate_path'],
                                                           req['secondary_certificate_path'],
                                                           req['root_ca_name'],
                                                           req['secondary_root_ca_name'],
                                                           req['primary_key'],
                                                           req['secondary_key'],
                                                           req['iot_hub_host_name'],
                                                           req['initial_twin_tags'],
                                                           req['initial_twin_properties'],
                                                           req['provisioning_status'],
                                                           req['reprovision_policy'],
                                                           req['allocation_policy'],
                                                           req['iot_hubs'])

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(certificate_path='myCert'))
    ])
    def test_enrollment_group_show_error(self, serviceclient_generic_error, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(None,
                                                           req['enrollment_id'],
                                                           req['dps_name'],
                                                           req['rg'],
                                                           req['certificate_path'],
                                                           req['secondary_certificate_path'],
                                                           req['root_ca_name'],
                                                           req['secondary_root_ca_name'],
                                                           req['primary_key'],
                                                           req['secondary_key'],
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


def generate_enrollment_group_update_req(iot_hub_host_name=None,
                                         initial_twin_tags=None,
                                         certificate_path=None,
                                         secondary_certificate_path=None,
                                         root_ca_name=None,
                                         secondary_root_ca_name=None,
                                         remove_certificate=None,
                                         remove_secondary_certificate=None,
                                         primary_key=None,
                                         secondary_key=None,
                                         initial_twin_properties=None,
                                         provisioning_status=None,
                                         etag=None,
                                         reprovision_policy=None,
                                         allocation_policy=None,
                                         iot_hubs=None,
                                         edge_enabled=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_target['entity'],
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'root_ca_name': root_ca_name,
            'secondary_root_ca_name': secondary_root_ca_name,
            'remove_certificate': remove_certificate,
            'remove_secondary_certificate': remove_secondary_certificate,
            'primary_key': primary_key,
            'secondary_key': secondary_key,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status,
            'etag': etag,
            'reprovision_policy': reprovision_policy,
            'allocation_policy': allocation_policy,
            'iot_hubs': iot_hubs,
            'edge_enabled': edge_enabled}


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
        (generate_enrollment_group_update_req(etag=etag, secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_group_update_req(certificate_path='newCertPath', secondary_certificate_path='someOtherCertPath')),
        (generate_enrollment_group_update_req(root_ca_name='someOtherCertName')),
        (generate_enrollment_group_update_req(secondary_root_ca_name='someOtherCertName')),
        (generate_enrollment_group_update_req(remove_certificate='true', root_ca_name='newCertName')),
        (generate_enrollment_group_update_req(iot_hub_host_name='someOtherHubName',
                                              initial_twin_tags={'newKey': 'newValue'},
                                              initial_twin_properties={'newKey': 'newValue'},
                                              provisioning_status='enabled')),
        (generate_enrollment_group_update_req(reprovision_policy='reprovisionandmigratedata')),
        (generate_enrollment_group_update_req(reprovision_policy='reprovisionandresetdata')),
        (generate_enrollment_group_update_req(reprovision_policy='never')),
        (generate_enrollment_group_update_req(allocation_policy='static', iot_hubs='hub1')),
        (generate_enrollment_group_update_req(allocation_policy='hashed', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_update_req(allocation_policy='geolatency')),
        (generate_enrollment_group_update_req(iot_hub_host_name='hub1')),
        (generate_enrollment_group_update_req(edge_enabled=True)),
        (generate_enrollment_group_update_req(edge_enabled=False))
    ])
    def test_enrollment_group_update(self, serviceclient, req):
        subject.iot_dps_device_enrollment_group_update(None,
                                                       req['enrollment_id'],
                                                       req['dps_name'],
                                                       req['rg'],
                                                       req['etag'],
                                                       req['certificate_path'],
                                                       req['secondary_certificate_path'],
                                                       req['root_ca_name'],
                                                       req['secondary_root_ca_name'],
                                                       req['remove_certificate'],
                                                       req['remove_secondary_certificate'],
                                                       req['primary_key'],
                                                       req['secondary_key'],
                                                       req['iot_hub_host_name'],
                                                       req['initial_twin_tags'],
                                                       req['initial_twin_properties'],
                                                       req['provisioning_status'],
                                                       req['reprovision_policy'],
                                                       req['allocation_policy'],
                                                       req['iot_hubs'],
                                                       edge_enabled=req['edge_enabled'])
        # Index 1 is the update args
        args = serviceclient.call_args_list[1]
        url = args[0][0].url

        assert "{}/enrollmentGroups/{}?".format(mock_target['entity'], enrollment_id) in url
        assert args[0][0].method == 'PUT'

        body = args[0][2]
        if not req['certificate_path']:
            if not req['root_ca_name'] and not req['secondary_root_ca_name']:
                assert body['attestation']['x509']['signingCertificates']['primary']['info'] is not None

        if req['certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['primary']['certificate'] is not None
        if req['secondary_certificate_path']:
            assert body['attestation']['x509']['signingCertificates']['secondary']['certificate'] is not None

        if req['root_ca_name']:
            assert body['attestation']['x509']['caReferences']['primary'] is not None
        if req['secondary_root_ca_name']:
            assert body['attestation']['x509']['caReferences']['secondary'] is not None

        if req['iot_hub_host_name']:
            assert body['allocationPolicy'] == 'static'
            assert body['iotHubs'] == req['iot_hub_host_name'].split()
        if req['provisioning_status']:
            assert body['provisioningStatus'] == req['provisioning_status']
        if req['initial_twin_properties']:
            assert body['initialTwin']['properties']['desired'] == req['initial_twin_properties']
        if req['initial_twin_tags']:
            assert body['initialTwin']['tags'] == req['initial_twin_tags']
        if req['reprovision_policy'] == 'reprovisionandmigratedata':
            assert body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'reprovisionandresetdata':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert body['reprovisionPolicy']['updateHubAssignment']
        if req['reprovision_policy'] == 'never':
            assert not body['reprovisionPolicy']['migrateDeviceData']
            assert not body['reprovisionPolicy']['updateHubAssignment']
        if req['allocation_policy']:
            assert body['allocationPolicy'] == req['allocation_policy']
        if req['iot_hubs']:
            assert body['iotHubs'] == req['iot_hubs'].split()
        if req['edge_enabled'] is not None:
            assert body['capabilities']['iotEdge'] == req['edge_enabled']

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_update_req(certificate_path='myCert',
                                              root_ca_name='myCert')),
        (generate_enrollment_group_update_req(secondary_certificate_path='myCert2',
                                              root_ca_name='myCert',
                                              secondary_root_ca_name='myCert2')),
        (generate_enrollment_group_update_req(root_ca_name='myCert',
                                              secondary_certificate_path='myCert2')),
        (generate_enrollment_group_update_req(remove_certificate='true',
                                              remove_secondary_certificate='true')),
        (generate_enrollment_group_update_req(remove_certificate='true')),
        (generate_enrollment_group_update_req(reprovision_policy='invalid')),
        (generate_enrollment_group_update_req(allocation_policy='invalid')),
        (generate_enrollment_group_update_req(allocation_policy='static', iot_hub_host_name='hub')),
        (generate_enrollment_group_update_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_update_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_group_update_invalid_args(self, serviceclient, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_update(None,
                                                           req['enrollment_id'],
                                                           req['dps_name'],
                                                           req['rg'],
                                                           etag,
                                                           req['certificate_path'],
                                                           req['secondary_certificate_path'],
                                                           req['root_ca_name'],
                                                           req['secondary_root_ca_name'],
                                                           req['remove_certificate'],
                                                           req['remove_secondary_certificate'],
                                                           req['primary_key'],
                                                           req['secondary_key'],
                                                           req['iot_hub_host_name'],
                                                           req['initial_twin_tags'],
                                                           req['initial_twin_properties'],
                                                           req['provisioning_status'],
                                                           req['reprovision_policy'],
                                                           req['allocation_policy'],
                                                           req['iot_hubs'])


class TestEnrollmentGroupShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, generate_enrollment_group_show())
        return service_client

    def test_enrollment_group_show(self, serviceclient):
        result = subject.iot_dps_device_enrollment_group_get(None, enrollment_id,
                                                             mock_target['entity'], resource_group)
        assert result.enrollment_group_id == enrollment_id
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
        service_client.return_value = build_mock_response(mocker, request.param, [generate_enrollment_group_show()])
        return service_client

    @pytest.mark.parametrize("top", [5, None])
    def test_enrollment_group_list(self, serviceclient, top):
        result = subject.iot_dps_device_enrollment_group_list(None, mock_target['entity'],
                                                              resource_group, top)
        args = serviceclient.call_args_list[0]
        headers = args[0][1]
        url = args[0][0].url
        method = args[0][0].method
        assert "{}/enrollmentGroups/query?".format(mock_target['entity']) in url
        assert method == 'POST'
        assert json.dumps(result)
        assert str(headers.get("x-ms-max-item-count")) == str(top)

    def test_enrollment_group_list_error(self, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_list(None,
                                                         mock_target['entity'],
                                                         resource_group)


class TestEnrollmentGroupDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, {})
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
    payload = {'registrationId': registration_id, 'status': 'assigned', 'etag': etag, 'assignedHub': 'myHub',
               'deviceId': 'myDevice'}
    return payload


class TestRegistrationShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocker, fixture_gdcs, fixture_sas, request):
        service_client = mocker.patch(path_service_client)
        service_client.return_value = build_mock_response(mocker, request.param, generate_registration_state_show())
        return service_client

    def test_registration_show(self, serviceclient):
        result = subject.iot_dps_registration_get(None, mock_target['entity'],
                                                  resource_group, registration_id)
        assert result.registration_id == registration_id
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
        result = []
        result.append(generate_registration_state_show())
        service_client.return_value = build_mock_response(mocker, request.param, result)
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
        service_client.return_value = build_mock_response(mocker, request.param, {})
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

        from azext_iot.common._azure import get_iot_dps_connection_string

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
