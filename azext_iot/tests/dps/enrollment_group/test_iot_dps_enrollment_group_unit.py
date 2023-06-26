# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


import pytest
import json
import responses
from azext_iot.operations import dps as subject
from knack.util import CLIError
from azext_iot.tests.conftest import mock_dps_target, mock_symmetric_key_attestation
from azext_iot.tests.dps import GENERATED_KEY, TEST_ENDORSEMENT_KEY, TEST_KEY_REGISTRATION_ID


enrollment_id = 'myenrollment'
resource_group = 'myrg'
registration_id = 'myregistration'
etag = 'AAAA=='


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
                                         edge_enabled=False,
                                         webhook_url=None,
                                         api_version=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name_or_hostname': mock_dps_target['entity'],
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
            'edge_enabled': edge_enabled,
            'webhook_url': webhook_url,
            'api_version': api_version}


class TestEnrollmentGroupCreate():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body='{}',
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

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
                                              allocation_policy='geoLatency')),
        (generate_enrollment_group_create_req(certificate_path='myCert',
                                              allocation_policy='custom',
                                              webhook_url="https://www.test.test",
                                              api_version="2019-03-31")),
        (generate_enrollment_group_create_req(primary_key='primarykey',
                                              secondary_key='secondarykey',
                                              edge_enabled=True)),
        (generate_enrollment_group_create_req(primary_key='primarykey',
                                              secondary_key='secondarykey',
                                              edge_enabled=True,
                                              initial_twin_properties={'key': ['value1', 'value2']})),
        (generate_enrollment_group_create_req(primary_key='primarykey',
                                              secondary_key='secondarykey',
                                              edge_enabled=True,
                                              initial_twin_properties={'key': ['value1', 'value2']})),
    ])
    def test_enrollment_group_create(self, serviceclient, fixture_cmd, req):
        subject.iot_dps_device_enrollment_group_create(
            cmd=fixture_cmd,
            enrollment_id=req['enrollment_id'],
            dps_name_or_hostname=req['dps_name_or_hostname'],
            resource_group_name=req['rg'],
            certificate_path=req['certificate_path'],
            secondary_certificate_path=req['secondary_certificate_path'],
            root_ca_name=req['root_ca_name'],
            secondary_root_ca_name=req['secondary_root_ca_name'],
            primary_key=req['primary_key'],
            secondary_key=req['secondary_key'],
            iot_hub_host_name=req['iot_hub_host_name'],
            initial_twin_tags=req['initial_twin_tags'],
            initial_twin_properties=req['initial_twin_properties'],
            provisioning_status=req['provisioning_status'],
            reprovision_policy=req['reprovision_policy'],
            allocation_policy=req['allocation_policy'],
            iot_hubs=req['iot_hubs'],
            edge_enabled=req['edge_enabled'],
            webhook_url=req['webhook_url'],
            api_version=req['api_version']
        )
        request = serviceclient.calls[0].request
        url = request.url
        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert request.method == 'PUT'

        body = json.loads(request.body)
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
            if body['allocationPolicy'] == 'custom':
                assert body['customAllocationDefinition']['webhookUrl'] == req['webhook_url']
                assert body['customAllocationDefinition']['apiVersion'] == req['api_version']
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
        (generate_enrollment_group_create_req(allocation_policy='custom')),
        (generate_enrollment_group_create_req(allocation_policy='custom', webhook_url="https://www.test.test")),
        (generate_enrollment_group_create_req(allocation_policy='static', iot_hub_host_name='hub')),
        (generate_enrollment_group_create_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_create_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_group_create_invalid_args(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(
                cmd=fixture_cmd,
                enrollment_id=req['enrollment_id'],
                dps_name_or_hostname=req['dps_name_or_hostname'],
                resource_group_name=req['rg'],
                certificate_path=req['certificate_path'],
                secondary_certificate_path=req['secondary_certificate_path'],
                root_ca_name=req['root_ca_name'],
                secondary_root_ca_name=req['secondary_root_ca_name'],
                primary_key=req['primary_key'],
                secondary_key=req['secondary_key'],
                iot_hub_host_name=req['iot_hub_host_name'],
                initial_twin_tags=req['initial_twin_tags'],
                initial_twin_properties=req['initial_twin_properties'],
                provisioning_status=req['provisioning_status'],
                reprovision_policy=req['reprovision_policy'],
                allocation_policy=req['allocation_policy'],
                iot_hubs=req['iot_hubs'],
                edge_enabled=req['edge_enabled'],
                webhook_url=req['webhook_url'],
            )

    @pytest.mark.parametrize("req", [
        (generate_enrollment_group_create_req(certificate_path='myCert'))
    ])
    def test_enrollment_group_show_error(self, serviceclient_generic_error, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_create(
                cmd=fixture_cmd,
                enrollment_id=req['enrollment_id'],
                dps_name_or_hostname=req['dps_name_or_hostname'],
                resource_group_name=req['rg'],
                certificate_path=req['certificate_path'],
                secondary_certificate_path=req['secondary_certificate_path'],
                root_ca_name=req['root_ca_name'],
                secondary_root_ca_name=req['secondary_root_ca_name'],
                primary_key=req['primary_key'],
                secondary_key=req['secondary_key'],
                iot_hub_host_name=req['iot_hub_host_name'],
                initial_twin_tags=req['initial_twin_tags'],
                initial_twin_properties=req['initial_twin_properties'],
                provisioning_status=req['provisioning_status'],
            )


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
                                         edge_enabled=None,
                                         webhook_url=None,
                                         api_version=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name_or_hostname': mock_dps_target['entity'],
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
            'edge_enabled': edge_enabled,
            'webhook_url': webhook_url,
            'api_version': api_version}


class TestEnrollmentGroupUpdate():
    @pytest.fixture(params=[(200, generate_enrollment_group_show(), 200)])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        # Initial GET
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_group_show()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        # Update PUT
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_group_show()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

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
        (generate_enrollment_group_update_req(allocation_policy='custom',
                                              webhook_url="https://www.test.test",
                                              api_version="2019-03-31")),
        (generate_enrollment_group_update_req(allocation_policy='hashed', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_update_req(allocation_policy='geoLatency')),
        (generate_enrollment_group_update_req(iot_hub_host_name='hub1')),
        (generate_enrollment_group_update_req(edge_enabled=True)),
        (generate_enrollment_group_update_req(edge_enabled=False))
    ])
    def test_enrollment_group_update(self, serviceclient, fixture_cmd, req):
        subject.iot_dps_device_enrollment_group_update(
            cmd=fixture_cmd,
            enrollment_id=req['enrollment_id'],
            dps_name_or_hostname=req['dps_name_or_hostname'],
            resource_group_name=req['rg'],
            etag=req['etag'],
            certificate_path=req['certificate_path'],
            secondary_certificate_path=req['secondary_certificate_path'],
            root_ca_name=req['root_ca_name'],
            secondary_root_ca_name=req['secondary_root_ca_name'],
            remove_certificate=req['remove_certificate'],
            remove_secondary_certificate=req['remove_secondary_certificate'],
            primary_key=req['primary_key'],
            secondary_key=req['secondary_key'],
            iot_hub_host_name=req['iot_hub_host_name'],
            initial_twin_tags=req['initial_twin_tags'],
            initial_twin_properties=req['initial_twin_properties'],
            provisioning_status=req['provisioning_status'],
            reprovision_policy=req['reprovision_policy'],
            allocation_policy=req['allocation_policy'],
            iot_hubs=req['iot_hubs'],
            edge_enabled=req['edge_enabled'],
            webhook_url=req['webhook_url'],
            api_version=req['api_version']
        )
        # test initial GET
        request = serviceclient.calls[0].request
        url = request.url
        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert request.method == 'GET'

        request = serviceclient.calls[1].request
        url = request.url

        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert request.method == 'PUT'
        assert request.headers["If-Match"] == req['etag'] if req['etag'] else "*"

        body = json.loads(request.body)
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
            if body['allocationPolicy'] == 'custom':
                assert body['customAllocationDefinition']['webhookUrl'] == req['webhook_url']
                assert body['customAllocationDefinition']['apiVersion'] == req['api_version']
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
        (generate_enrollment_group_update_req(allocation_policy='custom')),
        (generate_enrollment_group_update_req(allocation_policy='custom', webhook_url="https://www.test.test")),
        (generate_enrollment_group_update_req(allocation_policy='static', iot_hub_host_name='hub')),
        (generate_enrollment_group_update_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_group_update_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_group_update_invalid_args(self, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_update(
                cmd=fixture_cmd,
                enrollment_id=req['enrollment_id'],
                dps_name_or_hostname=req['dps_name_or_hostname'],
                resource_group_name=req['rg'],
                etag=req['etag'],
                certificate_path=req['certificate_path'],
                secondary_certificate_path=req['secondary_certificate_path'],
                root_ca_name=req['root_ca_name'],
                secondary_root_ca_name=req['secondary_root_ca_name'],
                remove_certificate=req['remove_certificate'],
                remove_secondary_certificate=req['remove_secondary_certificate'],
                primary_key=req['primary_key'],
                secondary_key=req['secondary_key'],
                iot_hub_host_name=req['iot_hub_host_name'],
                initial_twin_tags=req['initial_twin_tags'],
                initial_twin_properties=req['initial_twin_properties'],
                provisioning_status=req['provisioning_status'],
                reprovision_policy=req['reprovision_policy'],
                allocation_policy=req['allocation_policy'],
                iot_hubs=req['iot_hubs'],
                edge_enabled=req['edge_enabled'],
                webhook_url=None,
                api_version=req['api_version']
            )


class TestEnrollmentGroupShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_group_show()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.fixture()
    def serviceclient_attestation(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_group_show(attestation=mock_symmetric_key_attestation)),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/enrollmentGroups/{}/attestationmechanism".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(mock_symmetric_key_attestation),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    def test_enrollment_group_show(self, serviceclient, fixture_cmd):
        result = subject.iot_dps_device_enrollment_group_get(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            enrollment_id=enrollment_id,
            resource_group_name=resource_group
        )
        assert result['enrollmentGroupId'] == enrollment_id
        assert result['attestation']
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method

        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_enrollment_group_show_with_keys(self, fixture_cmd, serviceclient_attestation):
        result = subject.iot_dps_device_enrollment_group_get(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            enrollment_id=enrollment_id,
            resource_group_name=resource_group,
            show_keys=True
        )
        assert result['enrollmentGroupId'] == enrollment_id
        assert result['attestation']

        request = serviceclient_attestation.calls[0].request
        url = request.url
        method = request.method

        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'GET'

        request = serviceclient_attestation.calls[1].request
        url = request.url
        method = request.method

        assert "{}/enrollmentGroups/{}/attestationmechanism?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'POST'

    def test_enrollment_group_show_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_get(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                enrollment_id=enrollment_id,
                resource_group_name=resource_group
            )


class TestEnrollmentGroupList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/enrollmentGroups/query?".format(mock_dps_target['entity']),
            body=json.dumps([generate_enrollment_group_show()]),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.mark.parametrize("top", [5, None])
    def test_enrollment_group_list(self, serviceclient, fixture_cmd, top):
        result = subject.iot_dps_device_enrollment_group_list(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            resource_group_name=resource_group,
            top=top
        )
        request = serviceclient.calls[0].request
        headers = request.headers
        url = request.url
        method = request.method
        assert "{}/enrollmentGroups/query?".format(mock_dps_target['entity']) in url
        assert method == 'POST'
        assert json.dumps(result)
        assert str(headers.get("x-ms-max-item-count")) == str(top)

    def test_enrollment_group_list_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_list(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                resource_group_name=resource_group
            )


class TestEnrollmentGroupDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/enrollmentGroups/{}".format(mock_dps_target['entity'], enrollment_id),
            body='{}',
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.mark.parametrize(
        "etag",
        [None, etag]
    )
    def test_enrollment_group_delete(self, serviceclient, fixture_cmd, etag):
        subject.iot_dps_device_enrollment_group_delete(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            enrollment_id=enrollment_id,
            resource_group_name=resource_group,
            etag=etag,
        )
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/enrollmentGroups/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'DELETE'
        assert request.headers["If-Match"] == etag if etag else "*"

    def test_enrollment_group_delete_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_group_delete(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                enrollment_id=enrollment_id,
                resource_group_name=resource_group,
            )


def generate_registration_state_show():
    payload = {'registrationId': registration_id, 'status': 'assigned', 'etag': etag, 'assignedHub': 'myHub',
               'deviceId': 'myDevice'}
    return payload


class TestRegistrationShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/registrations/{}?".format(mock_dps_target['entity'], registration_id),
            body=json.dumps(generate_registration_state_show()),
            status=request.param,
            content_type="application/json",
            match_querystring=False
        )
        yield mocked_response

    def test_registration_show(self, fixture_cmd, serviceclient):
        result = subject.iot_dps_registration_get(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            registration_id=registration_id,
            resource_group_name=resource_group,
        )
        assert result['registrationId'] == registration_id
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/registrations/{}?".format(mock_dps_target['entity'], registration_id) in url
        assert method == 'GET'

    def test_registration_show_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_get(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                registration_id=registration_id,
                resource_group_name=resource_group,
            )


class TestRegistrationList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/registrations/{}/query?".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps([generate_registration_state_show()]),
            status=request.param,
            content_type="application/json",
            match_querystring=False
        )
        yield mocked_response

    def test_registration_list(self, serviceclient, fixture_cmd):
        subject.iot_dps_registration_list(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            enrollment_id=enrollment_id,
            resource_group_name=resource_group,
        )
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/registrations/{}/query?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'POST'

    def test_registration_list_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_list(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                enrollment_id=enrollment_id,
                resource_group_name=resource_group,
            )


class TestRegistrationDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/registrations/{}".format(mock_dps_target['entity'], registration_id),
            body='{}',
            status=request.param,
            content_type="application/json",
            match_querystring=False
        )
        yield mocked_response

    @pytest.mark.parametrize(
        "etag",
        [None, etag]
    )
    def test_registration_delete(self, serviceclient, fixture_cmd, etag):
        subject.iot_dps_registration_delete(
            cmd=fixture_cmd,
            dps_name_or_hostname=mock_dps_target['entity'],
            registration_id=registration_id,
            resource_group_name=resource_group,
            etag=etag
        )
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/registrations/{}?".format(mock_dps_target['entity'], registration_id) in url
        assert method == 'DELETE'
        assert request.headers["If-Match"] == etag if etag else "*"

    def test_registration_delete_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_delete(
                cmd=fixture_cmd,
                dps_name_or_hostname=mock_dps_target['entity'],
                registration_id=registration_id,
                resource_group_name=resource_group,
            )


class TestComputeDeviceKey():
    def test_offline_compute_device_key(self, fixture_cmd):
        offline_device_key = subject.iot_dps_compute_device_key(
            cmd=fixture_cmd,
            registration_id=TEST_KEY_REGISTRATION_ID,
            symmetric_key=TEST_ENDORSEMENT_KEY
        ).decode()
        offline_device_key = offline_device_key.strip("\"'\n")
        assert offline_device_key == GENERATED_KEY
