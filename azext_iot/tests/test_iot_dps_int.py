# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# pylint: disable=too-many-statements

from azure.cli.testsdk import ScenarioTest, ResourceGroupPreparer, ResourceGroupPreparer

#from ._test_utils import _create_test_cert, _delete_test_cert
import random
import os

class IoTDpsTest(ScenarioTest):

    @ResourceGroupPreparer(parameter_name='group_name', parameter_name_for_location='group_location')
    def test_dps_device_enrollment_lifecycle(self, group_name, group_location):
        # Set up a provisioning service
        dps_name = self._create_test_dps(group_name, group_location)

        # Set up cert file for test
        cert_file = "testcert.cer"
        max_int = 9223372036854775807
        _create_test_cert(cert_file, self.create_random_name(prefix='TESTCERT', length=24), 3, random.randint(0, max_int))
        
        enrollment_id = self.create_random_name('enrollment-for-test', length=48)
        attestation_type = "x509"
        provisioning_status = "enabled"
        provisioning_status_new = "disabled"
        device_id = self.create_random_name('device-id-for-test', length=48)

        endorsement_key = 'AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1QQsAGe021aUGJ'
                          'zNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3CJVjXmdGoz9Y/j3/NwLndBxQ'
                          'C+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRIDj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmS'
                          'dpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzBQQ1NpOJVhrsTrhyJzO7KNw=='
        
        # Enrollment (x509)
        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {} -g {} --dps-name {}  -p {}'
                        ' --provisioning-status {} --device-id {}'
                        .format(enrollment_id, attestation_type, group_name, dps_name, cert_file, provisioning_status, device_id),
                        checks=[self.check('attestation.type', attestation_type),
                                self.check('registrationId', enrollment_id),
                                self.check('provisioningStatus', provisioning_status),
                                self.check('deviceId', device_id)
        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(group_name, dps_name),
            checks=[self.check('length[*]', 1),
                    self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id),
            checks=[self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {} --provisioning_status {} --etag {}'
                 .format(group_name, dps_name, enrollment_id, provisioning_status, etag),
                 checks=[self.check('attestation.type', attestation_type),
                         self.check('registrationId', enrollment_id),
                         self.check('provisioningStatus', provisioning_status_new),
                         self.check('deviceId', device_id)
        ])

        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id))

        # Enrollment (tpm)
        attestation_type = "tpm"
        etag = self.cmd('iot dps enrollment create --enrollment-id {} --attestation-type {} -g {} --dps-name {}  --endorsement-key {}'
                        ' --provisioning-status {} --device-id {}'
                        .format(enrollment_id, attestation_type, group_name, dps_name, endorsement_key, provisioning_status, device_id),
                        checks=[self.check('attestation.type', attestation_type),
                                self.check('registrationId', enrollment_id),
                                self.check('provisioningStatus', provisioning_status),
                                self.check('deviceId', device_id)
        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment list -g {} --dps-name {}'.format(group_name, dps_name),
            checks=[self.check('length[*]', 1),
                    self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment show -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id),
            checks=[self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment update -g {} --dps-name {} --enrollment-id {} --provisioning_status {} --etag {}'
                 .format(group_name, dps_name, enrollment_id, provisioning_status, etag),
                 checks=[self.check('attestation.type', attestation_type),
                         self.check('registrationId', enrollment_id),
                         self.check('provisioningStatus', provisioning_status_new),
                         self.check('deviceId', device_id)
        ])

        self.cmd('iot dps enrollment delete -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id))

        # Enrollment Group
        etag = self.cmd('iot dps enrollment-group create --enrollment-id {} -g {} --dps-name {}  -p {} --provisioning-status {}'
            .format(enrollment_id, group_name, dps_name, cert_file, provisioning_status),
            checks=[self.check('registrationId', enrollment_id),
                    self.check('provisioningStatus', provisioning_status)
        ]).get_output_in_json()['etag']

        self.cmd('iot dps enrollment-group list -g {} --dps-name {}'.format(group_name, dps_name),
            checks=[self.check('length[*]', 1),
                    self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment-group show -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id),
            checks=[self.check('[0].registrationId', enrollment_id)
        ])

        self.cmd('iot dps enrollment-group update -g {} --dps-name {} --enrollment-id {} --provisioning_status {} --etag {}'
                 .format(group_name, dps_name, enrollment_id, provisioning_status, etag),
                 checks=[self.check('attestation.type', attestation_type),
                         self.check('registrationId', enrollment_id),
                         self.check('provisioningStatus', provisioning_status_new)
        ])

        self.cmd('iot dps enrollment-group delete -g {} --dps-name {} --enrollment-id {}'.format(group_name, dps_name, enrollment_id))

        # Tear down the provisioning service
        self._delete_test_dps(dps_name, group_name)
        _delete_test_cert(cert_file)

    def _create_test_dps(self, group_name, group_location):
        dps_name = dps_name = self.create_random_name('iot-dps-for-dps-test', length=48)
        self.cmd('az iot dps create -g {} -n {}'.format(group_name, dps_name), checks=[
            self.check('name', dps_name),
            self.check('location', group_location)
        ])
        return dps_name

    def _delete_test_dps(self, dps_name, group_name):
        self.cmd('az iot dps delete -g {} -n {}'.format(group_name, dps_name))

    def _create_test_cert(cert_file, subject, valid_days, serial_number):
        # create a key pair
        k = crypto.PKey()
        k.generate_key(crypto.TYPE_RSA, 2046)

        # create a self-signed cert with some basic constraints
        cert = crypto.X509()
        cert.get_subject().CN = subject
        cert.gmtime_adj_notBefore(-1 * 24 * 60 * 60)
        cert.gmtime_adj_notAfter(valid_days * 24 * 60 * 60)
        cert.set_version(2)
        cert.set_serial_number(serial_number)
        cert.add_extensions([
            crypto.X509Extension(b"basicConstraints", True, b"CA:TRUE, pathlen:1"),
            crypto.X509Extension(b"subjectKeyIdentifier", False, b"hash",
                                 subject=cert),
        ])
        cert.add_extensions([
            crypto.X509Extension(b"authorityKeyIdentifier", False, b"keyid:always",
                                 issuer=cert)
        ])
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(k)
        cert.sign(k, 'sha256')

        cert_str = crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode('ascii')
        open(cert_file, 'w').write(cert_str)

    def _delete_test_cert(cert_file):
        if exists(cert_file):
            os.remove(cert_file)
