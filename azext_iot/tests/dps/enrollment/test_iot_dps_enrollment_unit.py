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


enrollment_id = 'myenrollment'
resource_group = 'myrg'
etag = 'AAAA=='


def generate_enrollment_create_req(attestation_type=None, endorsement_key=None,
                                   certificate_path=None, secondary_certificate_path=None,
                                   device_id=None, iot_hub_host_name=None,
                                   initial_twin_tags=None, initial_twin_properties=None,
                                   provisioning_status=None, reprovision_policy=None,
                                   primary_key=None, secondary_key=None, allocation_policy=None,
                                   iot_hubs=None, edge_enabled=False, webhook_url=None, api_version=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_dps_target['entity'],
            'attestation_type': attestation_type,
            'endorsement_key': endorsement_key,
            'certificate_path': certificate_path,
            'secondary_certificate_path': secondary_certificate_path,
            'device_id': device_id,
            'iot_hub_host_name': iot_hub_host_name,
            'initial_twin_tags': initial_twin_tags,
            'initial_twin_properties': initial_twin_properties,
            'provisioning_status': provisioning_status,
            'reprovision_policy': reprovision_policy,
            'primary_key': primary_key,
            'secondary_key': secondary_key,
            'allocation_policy': allocation_policy,
            'iot_hubs': iot_hubs,
            'edge_enabled': edge_enabled,
            'webhook_url': webhook_url,
            'api_version': api_version}


class TestEnrollmentCreate():
    @pytest.fixture()
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body='{}',
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.fixture(params=[400, 401, 500])
    def serviceclient_generic_error(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body='{}',
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey')),
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey',
                                        device_id='1',
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
                                        device_id='1',
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
                                        allocation_policy='hashed',
                                        iot_hubs=['hub1', 'hub2'])),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never',
                                        allocation_policy='geoLatency')),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        reprovision_policy='never',
                                        allocation_policy='custom',
                                        webhook_url="https://www.test.test",
                                        api_version="2019-03-31")),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        edge_enabled=True)),
        (generate_enrollment_create_req(attestation_type='symmetricKey',
                                        primary_key='primarykey',
                                        secondary_key='secondarykey',
                                        edge_enabled=True,
                                        initial_twin_properties={'key': ['value1', 'value2']})),
        (generate_enrollment_create_req(attestation_type='tpm',
                                        endorsement_key='mykey',
                                        provisioning_status='enabled',
                                        initial_twin_properties={'key': ['value1', 'value2']}))
    ])
    def test_enrollment_create(self, serviceclient, fixture_cmd, req):
        subject.iot_dps_device_enrollment_create(
            cmd=fixture_cmd,
            enrollment_id=req['enrollment_id'],
            attestation_type=req['attestation_type'],
            dps_name=req['dps_name'],
            resource_group_name=req['rg'],
            endorsement_key=req['endorsement_key'],
            certificate_path=req['certificate_path'],
            secondary_certificate_path=req['secondary_certificate_path'],
            primary_key=req['primary_key'],
            secondary_key=req['secondary_key'],
            device_id=req['device_id'],
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
        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert request.method == 'PUT'

        body = json.loads(request.body)
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
            if body['allocationPolicy'] == 'custom':
                assert body['customAllocationDefinition']['webhookUrl'] == req['webhook_url']
                assert body['customAllocationDefinition']['apiVersion'] == req['api_version']
        if req['iot_hubs']:
            assert body['iotHubs'] == (
                req['iot_hubs'].split() if isinstance(req['iot_hubs'], str) else req['iot_hubs']
            )
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
        (generate_enrollment_create_req(allocation_policy='custom')),
        (generate_enrollment_create_req(allocation_policy='custom', webhook_url="https://www.test.test")),
        (generate_enrollment_create_req(allocation_policy='static', iot_hubs='hub1 hub2')),
        (generate_enrollment_create_req(allocation_policy='static', iot_hub_host_name='hubname')),
        (generate_enrollment_create_req(iot_hubs='hub1 hub2'))
    ])
    def test_enrollment_create_invalid_args(self, fixture_gdcs, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(
                cmd=fixture_cmd,
                enrollment_id=req['enrollment_id'],
                attestation_type=req['attestation_type'],
                dps_name=req['dps_name'],
                resource_group_name=req['rg'],
                endorsement_key=req['endorsement_key'],
                certificate_path=req['certificate_path'],
                primary_key=req['primary_key'],
                iot_hub_host_name=req['iot_hub_host_name'],
                reprovision_policy=req['reprovision_policy'],
                allocation_policy=req['allocation_policy'],
                iot_hubs=req['iot_hubs'],
                edge_enabled=req['edge_enabled'],
                webhook_url=req['webhook_url'],
                api_version=req['api_version']
            )

    @pytest.mark.parametrize("req", [
        (generate_enrollment_create_req(attestation_type='tpm', endorsement_key='mykey'))
    ])
    def test_enrollment_show_error(self, serviceclient_generic_error, fixture_cmd, req):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_create(
                cmd=fixture_cmd,
                enrollment_id=req['enrollment_id'],
                attestation_type=req['attestation_type'],
                dps_name=req['dps_name'],
                resource_group_name=req['rg'],
                endorsement_key=req['endorsement_key'],
                device_id=req['device_id'],
                iot_hub_host_name=req['iot_hub_host_name'],
                initial_twin_tags=req['initial_twin_tags'],
                initial_twin_properties=req['initial_twin_properties'],
                provisioning_status=req['provisioning_status'],
            )


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
                                   edge_enabled=None, webhook_url=None, api_version=None):
    return {'client': None,
            'enrollment_id': enrollment_id,
            'rg': resource_group,
            'dps_name': mock_dps_target['entity'],
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
            'edge_enabled': edge_enabled,
            'webhook_url': webhook_url,
            'api_version': api_version}


class TestEnrollmentUpdate():
    @pytest.fixture()
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        # Initial GET
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_show()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        # Update PUT
        mocked_response.add(
            method=responses.PUT,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_show()),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

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
        (generate_enrollment_update_req(allocation_policy='hashed', iot_hubs=['hub1', 'hub2'])),
        (generate_enrollment_update_req(allocation_policy='geoLatency')),
        (generate_enrollment_update_req(allocation_policy='custom',
                                        webhook_url="https://www.test.test",
                                        api_version="2019-03-31")),
        (generate_enrollment_update_req(edge_enabled=True)),
        (generate_enrollment_update_req(edge_enabled=False))
    ])
    def test_enrollment_update(self, mocker, serviceclient, fixture_cmd, req):
        mocker.patch("azext_iot.operations.dps._validate_allocation_policy_for_enrollment")
        subject.iot_dps_device_enrollment_update(
            cmd=fixture_cmd,
            enrollment_id=req['enrollment_id'],
            dps_name=req['dps_name'],
            resource_group_name=req['rg'],
            etag=req['etag'],
            endorsement_key=None,
            certificate_path=req['certificate_path'],
            secondary_certificate_path=req['secondary_certificate_path'],
            remove_certificate=req['remove_certificate_path'],
            remove_secondary_certificate=req['remove_secondary_certificate_path'],
            primary_key=None,
            secondary_key=None,
            device_id=req['device_id'],
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
        get_request = serviceclient.calls[0].request
        assert get_request.method == 'GET'
        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in get_request.url

        update_request = serviceclient.calls[1].request
        url = update_request.url

        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert update_request.method == 'PUT'

        assert update_request.headers["If-Match"] == req['etag'] if req['etag'] else "*"

        body = json.loads(update_request.body)
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
            if body['allocationPolicy'] == 'custom':
                assert body['customAllocationDefinition']['webhookUrl'] == req['webhook_url']
                assert body['customAllocationDefinition']['apiVersion'] == req['api_version']
        if req['iot_hubs']:
            assert body['iotHubs'] == (
                req['iot_hubs'].split() if isinstance(req['iot_hubs'], str) else req['iot_hubs']
            )
        if req['edge_enabled'] is not None:
            assert body['capabilities']['iotEdge'] == req['edge_enabled']


class TestEnrollmentShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_show()),
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )

        yield mocked_response

    @pytest.fixture()
    def serviceclient_attestation(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_enrollment_show(attestation=mock_symmetric_key_attestation)),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )

        mocked_response.add(
            method=responses.POST,
            url="https://{}/enrollments/{}/attestationmechanism".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(mock_symmetric_key_attestation),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    def test_enrollment_show(self, fixture_cmd, serviceclient):
        result = subject.iot_dps_device_enrollment_get(
            cmd=fixture_cmd,
            enrollment_id=enrollment_id,
            dps_name=mock_dps_target['entity'],
            resource_group_name=resource_group,
        )

        assert result['registrationId'] == enrollment_id

        request = serviceclient.calls[0].request
        url = request.url
        method = request.method

        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_enrollment_show_with_keys(self, fixture_cmd, serviceclient_attestation):
        result = subject.iot_dps_device_enrollment_get(
            cmd=fixture_cmd,
            enrollment_id=enrollment_id,
            dps_name=mock_dps_target['entity'],
            resource_group_name=resource_group,
            show_keys=True
        )

        assert result['registrationId'] == enrollment_id
        assert result['attestation']

        request = serviceclient_attestation.calls[0].request
        url = request.url
        method = request.method

        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'GET'

        request = serviceclient_attestation.calls[1].request
        url = request.url
        method = request.method

        assert "{}/enrollments/{}/attestationmechanism?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'POST'

    def test_enrollment_show_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_get(
                cmd=fixture_cmd,
                enrollment_id=enrollment_id,
                dps_name=mock_dps_target['entity'],
                resource_group_name=resource_group,
            )


class TestEnrollmentList():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.POST,
            url="https://{}/enrollments/query?".format(mock_dps_target['entity']),
            body=json.dumps([generate_enrollment_show()]),
            status=200,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.mark.parametrize("top", [3, None])
    def test_enrollment_list(self, serviceclient, fixture_cmd, top):
        result = subject.iot_dps_device_enrollment_list(
            cmd=fixture_cmd,
            dps_name=mock_dps_target['entity'],
            resource_group_name=resource_group,
            top=top
        )
        request = serviceclient.calls[0].request
        headers = request.headers
        url = request.url
        method = request.method

        assert str(headers.get("x-ms-max-item-count")) == str(top)
        assert "{}/enrollments/query?".format(mock_dps_target['entity']) in url
        assert method == "POST"
        assert json.dumps(result)

    def test_enrollment_list_error(self, fixture_cmd, serviceclient_generic_error):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_list(
                cmd=fixture_cmd,
                dps_name=mock_dps_target['entity'],
                resource_group_name=resource_group,
            )


class TestEnrollmentDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/enrollments/{}".format(mock_dps_target['entity'], enrollment_id),
            body=None,
            status=request.param,
            content_type="application/json",
            match_querystring=False,
        )
        yield mocked_response

    @pytest.mark.parametrize(
        "etag",
        [None, etag]
    )
    def test_enrollment_delete(self, serviceclient, fixture_cmd, etag):
        subject.iot_dps_device_enrollment_delete(
            cmd=fixture_cmd,
            enrollment_id=enrollment_id,
            dps_name=mock_dps_target['entity'],
            resource_group_name=resource_group,
            etag=etag
        )
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/enrollments/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'DELETE'
        assert request.headers["If-Match"] == etag if etag else "*"

    def test_enrollment_delete_error(self, serviceclient_generic_error, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_device_enrollment_delete(
                cmd=fixture_cmd,
                enrollment_id=enrollment_id,
                dps_name=mock_dps_target['entity'],
                resource_group_name=resource_group,
            )


def generate_registration_state_show():
    payload = {'registrationId': enrollment_id, 'status': 'assigned', 'etag': etag, 'assignedHub': 'myHub',
               'deviceId': 'myDevice'}
    return payload


class TestRegistrationShow():
    @pytest.fixture(params=[200])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.GET,
            url="https://{}/registrations/{}?".format(mock_dps_target['entity'], enrollment_id),
            body=json.dumps(generate_registration_state_show()),
            status=request.param,
            content_type="application/json",
            match_querystring=False
        )
        yield mocked_response

    def test_registration_show(self, fixture_cmd, serviceclient):
        result = subject.iot_dps_registration_get(
            cmd=fixture_cmd,
            dps_name=mock_dps_target['entity'],
            registration_id=enrollment_id,
            resource_group_name=resource_group,
        )
        assert result['registrationId'] == enrollment_id
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/registrations/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'GET'

    def test_registration_show_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_get(
                cmd=fixture_cmd,
                dps_name=mock_dps_target['entity'],
                registration_id=enrollment_id,
                resource_group_name=resource_group,
            )


class TestRegistrationDelete():
    @pytest.fixture(params=[204])
    def serviceclient(self, mocked_response, fixture_gdcs, fixture_dps_sas, patch_certificate_open, request):
        mocked_response.add(
            method=responses.DELETE,
            url="https://{}/registrations/{}".format(mock_dps_target['entity'], enrollment_id),
            body=None,
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
            dps_name=mock_dps_target['entity'],
            registration_id=enrollment_id,
            resource_group_name=resource_group,
            etag=etag
        )
        request = serviceclient.calls[0].request
        url = request.url
        method = request.method
        assert "{}/registrations/{}?".format(mock_dps_target['entity'], enrollment_id) in url
        assert method == 'DELETE'
        assert request.headers["If-Match"] == etag if etag else "*"

    def test_registration_delete_error(self, fixture_cmd):
        with pytest.raises(CLIError):
            subject.iot_dps_registration_delete(
                cmd=fixture_cmd,
                dps_name=mock_dps_target['entity'],
                registration_id=enrollment_id,
                resource_group_name=resource_group,
            )
