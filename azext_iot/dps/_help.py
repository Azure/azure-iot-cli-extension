# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for IoT Hub commands.
"""

from knack.help_files import helps


def load_deviceprovisioningservice_help():
    helps["iot device registration"] = """
        type: group
        short-summary: Manage IoT Device registrations through IoT Device Provisioning Service.
        long-summary: Use `az iot dps enrollment registration` or `az iot dps enrollment-group registration` to view and delete registrations.
    """

    helps["iot device registration create"] = """
        type: command
        short-summary: Register an IoT Device with IoT Device Provisioning Service.
        long-summary: |
          The following attestation mechanisms are supported:
          - Symmetric key
          - x509 certificate
          If using x509 authentication methods, the certificate and key files must be provided.
        examples:
        - name: Register an IoT Device using an individual enrollment.
          text: az iot device registration create -n {dps_name} --rid {registration_id}
        - name: Register an IoT Device using a group enrollment.
          text: az iot device registration create -n {dps_name} --rid {registration_id} --gid {group_enrollment_id}
        - name: Register an IoT Device using an individual enrollment, the Device Provisioning Service
            ID Scope, and given symmetric key. This will bypass retrieving the ID Scope and individal
            enrollment symmetric key.
          text: az iot device registration create --id-scope {id_scope} --rid {registration_id} --key {symmetric_key}
        - name: Register an IoT Device using a group enrollment, the Device Provisioning Service ID Scope,
            and given enrollment group symmetric key. This will bypass retrieving the ID Scope and
            enrollment-group symmetric key. The symmetric key used for the device registration will be
            computed from the given symmetric key.
          text: az iot device registration create --id-scope {id_scope} --rid {registration_id} --gid {group_enrollment_id} --key {symmetric_key} --ck
        - name: Register an IoT Device using a group enrollment, the Device Provisioning Service ID Scope,
            and given symmetric key. This will bypass retrieving the ID Scope. Note that since the symmetric key
            should be the computed device key, the enrollment group id is not needed.
          text: az iot device registration create --id-scope {id_scope} --rid {registration_id} --key {symmetric_key}
        - name: Register an IoT Device using an individual enrollment, the Device Provisioning Service
            ID Scope, and given certificate and key files. This will bypass retrieving the ID Scope.
          text: az iot device registration create --id-scope {id_scope} --rid {registration_id} --cp {certificate_file} --kp {key_file}
        - name: Register an IoT Device using a group enrollment, the Device Provisioning Service
            ID Scope, and given certificate and key files. This will bypass retrieving the ID Scope.
            Note that the group enrollment id is not needed for x509 attestations.
          text: az iot device registration create --id-scope {id_scope} --rid {registration_id} --cp {certificate_file} --kp {key_file}
    """
