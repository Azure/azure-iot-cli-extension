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
    """

    helps["iot device registration create"] = """
        type: command
        short-summary: Register an IoT Device with IoT Device Provisioning Service.
        examples:
        - name: Register an IoT Device using an individual enrollment
          text: az iot device registration create -n {dps_name} --rid {registration_id}
        - name: Register an IoT Device using a group enrollment
          text: az iot device registration create -n {dps_name} --rid {registration_id} --gid {group_enrollment_id}
        - name: Register an IoT Device using an individual enrollment and given device (individal enrollment) symmetric key. This will bypass retrieving the individal enrollment symmetric key.
          text: az iot device registration create -n {dps_name} --rid {registration_id} --key {device_symmetric_key}
        - name: Register an IoT Device using a group enrollment and given enrollment group symmetric key. This will bypass retrieving the enrollment group symmetric key.
          text: az iot device registration create -n {dps_name} --rid {registration_id} --gid {group_enrollment_id} --group-key {group_symmetric_key}
        - name: Register an IoT Device using a group enrollment and given device symmetric key. This will bypass generating the device symmetric key from the enrollment group symmetric key.
          text: az iot device registration create -n {dps_name} --rid {registration_id} --gid {group_enrollment_id} --key {device_symmetric_key}
    """

    helps["iot device registration show"] = """
        type: command
        short-summary: Show the registration state of an IoT Device within IoT Device Provisioning Service.
        examples:
        - name: Show the registration state of an IoT Device using an individual enrollment
          text: az iot device registration show -n {dps_name} --rid {registration_id}
        - name: Show the registration state of an IoT Device using a group enrollment
          text: az iot device registration show -n {dps_name} --rid {registration_id} --gid {group_enrollment_id}
        - name: Show the registration state of an IoT Device using an individual enrollment and given device (individal enrollment) symmetric key. This will bypass retrieving the individal enrollment symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --key {device_symmetric_key}
        - name: Show the registration state of an IoT Device using a group enrollment and given enrollment group symmetric key. This will bypass retrieving the enrollment group symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --gid {group_enrollment_id} --group-key {group_symmetric_key}
        - name: Show the registration state of an IoT Device using a group enrollment and given device symmetric key. This will bypass generating the device symmetric key from the enrollment group symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --gid {group_enrollment_id} --key {device_symmetric_key}
    """

    helps["iot device registration operation"] = """
        type: group
        short-summary: Manage IoT Device registration operations through IoT Device Provisioning Service.
    """

    helps["iot device registration operation show"] = """
        type: command
        short-summary: Show the registration operation state of an IoT Device within IoT Device Provisioning Service.
        examples:
        - name: Show the registration operation state of an IoT Device using an individual enrollment
          text: az iot device registration show -n {dps_name} --rid {registration_id} --oid {operation_id}
        - name: Show the registration operation state of an IoT Device using a group enrollment
          text: az iot device registration show -n {dps_name} --rid {registration_id} --oid {operation_id} --gid {group_enrollment_id}
        - name: Show the registration operation state of an IoT Device using an individual enrollment and given device (individal enrollment) symmetric key. This will bypass retrieving the individal enrollment symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --oid {operation_id} --key {device_symmetric_key}
        - name: Show the registration operation state of an IoT Device using a group enrollment and given enrollment group symmetric key. This will bypass retrieving the enrollment group symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --oid {operation_id} --gid {group_enrollment_id} --group-key {group_symmetric_key}
        - name: Show the registration operation state of an IoT Device using a group enrollment and given device symmetric key. This will bypass generating the device symmetric key from the enrollment group symmetric key.
          text: az iot device registration show -n {dps_name} --rid {registration_id} --oid {operation_id} --gid {group_enrollment_id} --key {device_symmetric_key}
    """