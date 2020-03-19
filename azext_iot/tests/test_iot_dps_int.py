# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.shared import EntityStatusType, AttestationType, AllocationType
from azext_iot.common.certops import create_self_signed_certificate

# Set these to the proper IoT Hub DPS, IoT Hub and Resource Group for Integration Tests.
dps = os.environ.get('azext_iot_testdps')
rg = os.environ.get('azext_iot_testrg')
hub = os.environ.get('azext_iot_testhub')

if not all([dps, rg, hub]):
    raise ValueError('Set azext_iot_testhub, azext_iot_testdps '
                     'and azext_iot_testrg to run integration tests.')

cert_name = 'test'
cert_path = cert_name + '-cert.pem'


class IoTDpsTest(LiveScenarioTest):

    provisioning_status = EntityStatusType.enabled.value
    provisioning_status_new = EntityStatusType.disabled.value

    def __init__(self, test_method):
        super(IoTDpsTest, self).__init__('test_dps_enrollment_tpm_lifecycle')
        output_dir = os.getcwd()
        create_self_signed_certificate(cert_name, 200, output_dir, True)
        self.kwargs['generic_dict'] = {'count': None, 'key': 'value', 'metadata': None, 'version': None}

    def __del__(self):
        if os.path.exists(cert_path):
            os.remove(cert_path)

    def test_dps_enrollment_tpm_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        endorsement_key = ('AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1Q'
                           'QsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3'
                           'CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRI'
                           'Dj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzB'
                           'QQ1NpOJVhrsTrhyJzO7KNw==')
        device_id = self.create_random_name('device-id-for-test', length=48)
        attestation_type = AttestationType.tpm.value
        hub_host_name = '{}.azure-devices.net'.format(hub)

        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {}'
                        ' -g {} --dps-name {} --endorsement-key {}'
                        ' --provisioning-status {} --device-id {} --initial-twin-tags {}'
                        ' --initial-twin-properties {} --allocation-policy {} --iot-hubs {}'
                        .format(enrollment_id, attestation_type, rg, dps, endorsement_key,
                                self.provisioning_status, device_id,
                                '"{generic_dict}"', '"{generic_dict}"', AllocationType.static.value, hub_host_name),
                        checks=[
                            self.check('attestation.type', attestation_type),
                            self.check('registrationId', enrollment_id),
                            self.check('provisioningStatus',
                                       self.provisioning_status),
                            self.check('deviceId', device_id),
                            self.check('allocationPolicy', AllocationType.static.value),
                            self.check('iotHubs', hub_host_name.split()),
                            self.check('initialTwin.tags',
                                       self.kwargs['generic_dict']),
                            self.check('initialTwin.properties.desired',
                                       self.kwargs['generic_dict']),
                            self.exists('reprovisionPolicy'),
                            self.check('reprovisionPolicy.migrateDeviceData', True),
                            self.check('reprovisionPolicy.updateHubAssignment', True)
                        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(rg, dps), checks=[
            self.check('length(@)', 1),
            self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id),
                 checks=[self.check('registrationId', enrollment_id)])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {}'
                 ' --provisioning-status {} --etag {}'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag),
                 checks=[
                     self.check('attestation.type', attestation_type),
                     self.check('registrationId', enrollment_id),
                     self.check('provisioningStatus',
                                self.provisioning_status_new),
                     self.check('deviceId', device_id),
                     self.check('allocationPolicy', AllocationType.static.value),
                     self.check('iotHubs', hub_host_name.split()),
                     self.exists('initialTwin.tags'),
                     self.exists('initialTwin.properties.desired')
                 ])

        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id))

    def test_dps_enrollment_x509_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        attestation_type = AttestationType.x509.value
        device_id = self.create_random_name('device-id-for-test', length=48)
        hub_host_name = '{}.azure-devices.net'.format(hub)

        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {}'
                        ' -g {} --dps-name {} --cp {} --scp {}'
                        ' --provisioning-status {} --device-id {}'
                        ' --initial-twin-tags {} --initial-twin-properties {}'
                        ' --allocation-policy {} --iot-hubs {}'
                        .format(enrollment_id, attestation_type, rg, dps, cert_path,
                                cert_path, self.provisioning_status, device_id,
                                '"{generic_dict}"', '"{generic_dict}"',
                                AllocationType.hashed.value,
                                hub_host_name),
                        checks=[
                            self.check('attestation.type', attestation_type),
                            self.check('registrationId', enrollment_id),
                            self.check('provisioningStatus',
                                       self.provisioning_status),
                            self.check('deviceId', device_id),
                            self.check('allocationPolicy', AllocationType.hashed.value),
                            self.check('iotHubs', hub_host_name.split()),
                            self.check('initialTwin.tags',
                                       self.kwargs['generic_dict']),
                            self.check('initialTwin.properties.desired',
                                       self.kwargs['generic_dict']),
                            self.exists('reprovisionPolicy'),
                            self.check('reprovisionPolicy.migrateDeviceData', True),
                            self.check('reprovisionPolicy.updateHubAssignment', True)
                        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(rg, dps),
                 checks=[
                     self.check('length(@)', 1),
                     self.check('[0].registrationId', enrollment_id)])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id),
                 checks=[self.check('registrationId', enrollment_id)])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {}'
                 ' --provisioning-status {} --etag {} --rc'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag),
                 checks=[
                     self.check('attestation.type', attestation_type),
                     self.check('registrationId', enrollment_id),
                     self.check('provisioningStatus',
                                self.provisioning_status_new),
                     self.check('deviceId', device_id),
                     self.check('allocationPolicy', AllocationType.hashed.value),
                     self.check('iotHubs', hub_host_name.split()),
                     self.exists('initialTwin.tags'),
                     self.exists('initialTwin.properties.desired'),
                     self.check(
                         'attestation.type.x509.clientCertificates.primary', None)
                 ])

        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id))

    def test_dps_enrollment_symmetrickey_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        attestation_type = AttestationType.symmetricKey.value
        primary_key = 'x3XNu1HeSw93rmtDXduRUZjhqdGbcqR/zloWYiyPUzw='
        secondary_key = 'PahMnOSBblv9CRn5B765iK35jTvnjDUjYP9hKBZa4Ug='
        device_id = self.create_random_name('device-id-for-test', length=48)
        reprovisionPolicy_reprovisionandresetdata = 'reprovisionandresetdata'
        hub_host_name = '{}.azure-devices.net'.format(hub)

        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {}'
                        ' -g {} --dps-name {} --pk {} --sk {}'
                        ' --provisioning-status {} --device-id {}'
                        ' --initial-twin-tags {} --initial-twin-properties {}'
                        ' --allocation-policy {} --rp {} --edge-enabled'
                        .format(enrollment_id, attestation_type, rg, dps, primary_key,
                                secondary_key, self.provisioning_status, device_id,
                                '"{generic_dict}"', '"{generic_dict}"',
                                AllocationType.geolatency.value,
                                reprovisionPolicy_reprovisionandresetdata,),
                        checks=[
                            self.check('attestation.type', attestation_type),
                            self.check('registrationId', enrollment_id),
                            self.check('provisioningStatus',
                                       self.provisioning_status),
                            self.check('deviceId', device_id),
                            self.check('allocationPolicy', AllocationType.geolatency.value),
                            self.check('iotHubHostName', hub_host_name),
                            self.check('initialTwin.tags',
                                       self.kwargs['generic_dict']),
                            self.check('initialTwin.properties.desired',
                                       self.kwargs['generic_dict']),
                            self.exists('reprovisionPolicy'),
                            self.check('reprovisionPolicy.migrateDeviceData', False),
                            self.check('reprovisionPolicy.updateHubAssignment', True),
                            self.check('capabilities.iotEdge', True)
                        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(rg, dps),
                 checks=[
                     self.check('length(@)', 1),
                     self.check('[0].registrationId', enrollment_id)])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id),
                 checks=[self.check('registrationId', enrollment_id)])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {}'
                 ' --provisioning-status {} --etag {} --rc --edge-enabled False'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag),
                 checks=[
                     self.check('attestation.type', attestation_type),
                     self.check('registrationId', enrollment_id),
                     self.check('provisioningStatus',
                                self.provisioning_status_new),
                     self.check('deviceId', device_id),
                     self.check('allocationPolicy', AllocationType.geolatency.value),
                     self.check('iotHubHostName', hub_host_name),
                     self.exists('initialTwin.tags'),
                     self.exists('initialTwin.properties.desired'),
                     self.check('attestation.symmetric_key.primary_key', primary_key),
                     self.check('capabilities.iotEdge', False)
                 ])

        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id))

    def test_dps_enrollment_group_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        reprovisionPolicy_never = 'never'
        hub_host_name = '{}.azure-devices.net'.format(hub)
        etag = self.cmd('iot dps enrollment-group create --enrollment-id {} -g {} --dps-name {}'
                        ' --cp {} --scp {} --provisioning-status {} --allocation-policy {}'
                        ' --iot-hubs {} --edge-enabled'
                        .format(enrollment_id, rg, dps, cert_path, cert_path,
                                self.provisioning_status, AllocationType.geolatency.value,
                                hub_host_name),
                        checks=[
                            self.check('enrollmentGroupId', enrollment_id),
                            self.check('provisioningStatus',
                                       self.provisioning_status),
                            self.exists('reprovisionPolicy'),
                            self.check('allocationPolicy', AllocationType.geolatency.value),
                            self.check('iotHubs', hub_host_name.split()),
                            self.check('reprovisionPolicy.migrateDeviceData', True),
                            self.check('reprovisionPolicy.updateHubAssignment', True),
                            self.check('capabilities.iotEdge', True)
                        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment-group list -g {} --dps-name {}'.format(rg, dps), checks=[
            self.check('length(@)', 1),
            self.check('[0].enrollmentGroupId', enrollment_id)
        ])

        self.cmd('iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id),
                 checks=[self.check('enrollmentGroupId', enrollment_id)])

        self.cmd('iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}'
                 ' --provisioning-status {} --rsc --etag {} --rp {} --allocation-policy {}'
                 '--edge-enabled False'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag,
                         reprovisionPolicy_never, AllocationType.hashed.value),
                 checks=[
                     self.check('attestation.type', AttestationType.x509.value),
                     self.check('enrollmentGroupId', enrollment_id),
                     self.check('provisioningStatus', self.provisioning_status_new),
                     self.check('attestation.type.x509.clientCertificates.secondary', None),
                     self.exists('reprovisionPolicy'),
                     self.check('allocationPolicy', AllocationType.hashed.value),
                     self.check('iotHubs', hub_host_name.split()),
                     self.check('reprovisionPolicy.migrateDeviceData', False),
                     self.check('reprovisionPolicy.updateHubAssignment', False),
                     self.check('capabilities.iotEdge', False)
                 ])

        self.cmd('iot dps registration list -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id),
                 checks=[self.check('length(@)', 0)])

        cert_name = self.create_random_name('certificate-for-test', length=48)
        cert_etag = self.cmd('iot dps certificate create -g {} --dps-name {} --name {} --p {}'
                             .format(rg, dps, cert_name, cert_path),
                             checks=[self.check('name', cert_name)]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {}'
                 ' --cn {} --etag {}'
                 .format(rg, dps, enrollment_id, cert_name, cert_etag),
                 checks=[
                     self.check('attestation.type',
                                AttestationType.x509.value),
                     self.check('enrollmentGroupId', enrollment_id),
                     self.check(
                         'attestation.x509.caReferences.primary', cert_name),
                     self.check(
                         'attestation.x509.caReferences.secondary', None)
                 ])

        self.cmd('iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}'
                 .format(rg, dps, enrollment_id))

        self.cmd('iot dps certificate delete -g {} --dps-name {} --name {} --etag {}'
                 .format(rg, dps, cert_name, cert_etag))
