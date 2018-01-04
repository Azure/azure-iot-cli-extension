# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

import random
import os
from OpenSSL import crypto
from azure.cli.testsdk import LiveScenarioTest, ResourceGroupPreparer, ResourceGroupPreparer
from azext_iot.common.shared import EntityStatusType, AttestationType
from azext_iot.common.certops import create_self_signed_certificate

# Set these to the proper IoT DPS and Resource Group for Integration Tests.
dps = os.environ.get('azext_iot_testdps')
rg = os.environ.get('azext_iot_testrg')

if not any([dps, rg]):
    raise ValueError('Set azext_iot_testhub and azext_iot_testrg to run integration tests.')

cert_name = 'test'
cert_path = cert_name + '-cert.pem'

class IoTDpsTest(LiveScenarioTest):

    provisioning_status = EntityStatusType.enabled.value
    provisioning_status_new = EntityStatusType.disabled.value
    
    def __init__(self, test_method):
        super(IoTDpsTest, self).__init__('test_dps_enrollment_x509_lifecycle')
        output_dir = os.getcwd()
        create_self_signed_certificate(cert_name, 200, output_dir, True)

    def __del__(self):
        import os.path
        if os.path.exists(cert_path):
            os.remove(cert_path)

    def test_dps_enrollment_tpm_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        endorsement_key = 'AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1QQsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRIDj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzBQQ1NpOJVhrsTrhyJzO7KNw=='
        device_id = self.create_random_name('device-id-for-test', length=48)
        attestation_type = AttestationType.tpm.value
        initial_twin = "\"{'key':'value'}\""
        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {} -g {} --dps-name {}  --endorsement-key {}'
                        ' --provisioning-status {} --device-id {} --initial-twin-tags {} --initial-twin-properties {}'
                        .format(enrollment_id, attestation_type, rg, dps, endorsement_key, self.provisioning_status, device_id, initial_twin, initial_twin),
                        checks=[self.check('attestation.type', attestation_type),
                                self.check('registrationId', enrollment_id),
                                self.check('provisioningStatus', self.provisioning_status),
                                self.check('deviceId', device_id),
                                self.check('initialTwin.tags.additionalProperties', {'key': 'value'}),
                                self.check('initialTwin.properties.desired.additionalProperties', {'key': 'value'})
        ]).get_output_in_json()['etag']
              
        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(rg, dps),
            checks=[self.check('length(@)', 1),
                    self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id),
            checks=[self.check('registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {} --provisioning-status {} --etag {}'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag),
                 checks=[self.check('attestation.type', attestation_type),
                         self.check('registrationId', enrollment_id),
                         self.check('provisioningStatus', self.provisioning_status_new),
                         self.check('deviceId', device_id),
                         self.exists('initialTwin.tags.additionalProperties'),
                         self.exists('initialTwin.properties.desired.additionalProperties')
        ])
        
        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id))

    def test_dps_enrollment_x509_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)   
        attestation_type = AttestationType.x509.value
        device_id = self.create_random_name('device-id-for-test', length=48)
        initial_twin = "\"{'key':'value'}\""
        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {} -g {} --dps-name {}  -p {}'
                        ' --provisioning-status {} --device-id {} --initial-twin-tags {} --initial-twin-properties {}'
                        .format(enrollment_id, attestation_type, rg, dps, cert_path, self.provisioning_status, device_id, initial_twin, initial_twin),
                        checks=[self.check('attestation.type', attestation_type),
                                self.check('registrationId', enrollment_id),
                                self.check('provisioningStatus', self.provisioning_status),
                                self.check('deviceId', device_id),
                                self.check('initialTwin.tags.additionalProperties', {'key': 'value'}),
                                self.check('initialTwin.properties.desired.additionalProperties', {'key': 'value'})
        ]).get_output_in_json()['etag']
              
        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(rg, dps),
            checks=[self.check('length(@)', 1),
                    self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id),
            checks=[self.check('registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {} --provisioning-status {} --etag {} -p {}'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, etag, cert_path),
                 checks=[self.check('attestation.type', attestation_type),
                         self.check('registrationId', enrollment_id),
                         self.check('provisioningStatus', self.provisioning_status_new),
                         self.check('deviceId', device_id),
                         self.exists('initialTwin.tags.additionalProperties'),
                         self.exists('initialTwin.properties.desired.additionalProperties')
        ])
        
        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id))    

    # Enrollment Group
    def test_dps_enrollment_group_lifecycle(self):
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        etag = self.cmd('iot dps enrollment-group create --enrollment-id {} -g {} --dps-name {}  -p {} --provisioning-status {}'
            .format(enrollment_id, rg, dps, cert_path, self.provisioning_status),
            checks=[self.check('enrollmentGroupId', enrollment_id),
                    self.check('provisioningStatus', self.provisioning_status)
        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment-group list -g {} --dps-name {}'.format(rg, dps),
            checks=[self.check('length(@)', 1),
                    self.check('[0].enrollmentGroupId', enrollment_id)
        ])

        self.cmd('iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id),
            checks=[self.check('enrollmentGroupId', enrollment_id)
        ])

        self.cmd('iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {} --provisioning-status {} -p {} --etag {}'
                 .format(rg, dps, enrollment_id, self.provisioning_status_new, cert_path, etag),
                 checks=[self.check('attestation.type', AttestationType.x509.value),
                         self.check('enrollmentGroupId', enrollment_id),
                         self.check('provisioningStatus', self.provisioning_status_new)
        ])

        self.cmd('iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}'.format(rg, dps, enrollment_id))
