# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for IoT Hub commands.
"""

from knack.help_files import helps


def load_iothub_help():

    helps["iot hub job"] = """
        type: group
        short-summary: Manage IoT Hub jobs (v2).
    """

    helps['iot hub job create'] = """
        type: command
        short-summary: Create and schedule an IoT Hub job for execution.
        long-summary: |
                      When scheduling a twin update job, the twin patch is a required argument.
                      When scheduling a device method job, the method name and payload are required arguments.

        examples:
        - name: Create and schedule a job to update the twin tags of all devices.
          text: >
            az iot hub job create --job-id {job_id} --job-type scheduleUpdateTwin -n {iothub_name} -q "*" --twin-patch '{"tags": {"deviceType": "Type1, Type2, Type3"}}'

        - name: Schedule job and block for result of "completed", "failed" or "cancelled". Specify poll interval in seconds.
          text: >
            az iot hub job create --job-id {job_id} --job-type scheduleUpdateTwin -n {iothub_name} -q "*" --twin-patch '{"tags": {"deviceType": "Type1, Type2, Type3"}}'
            --wait --poll-interval 30

        - name: Create a job to update a desired twin property on a subset of devices, scheduled to run at an arbitrary future time.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleUpdateTwin -n {iothub_name} --twin-patch '{"properties":{"desired": {"temperatureF": 65}}}'
            --start-time "2020-01-08T12:19:56.868Z" --query-condition "deviceId IN ['MyDevice1', 'MyDevice2', 'MyDevice3']"

        - name: Create and schedule a job to invoke a device method for a set of devices meeting a query condition.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleDeviceMethod -n {iothub_name} --method-name setSyncIntervalSec --method-payload 30
            --query-condition "properties.reported.settings.syncIntervalSec != 30"
    """

    helps['iot hub job show'] = """
        type: command
        short-summary: Show details of an existing IoT Hub job.

        examples:
        - name: Show the details of a created job.
          text: >
            az iot hub job show --hub-name {iothub_name} --job-id {job_id}
    """

    helps['iot hub job list'] = """
        type: command
        short-summary: List the historical jobs of an IoT Hub.

        examples:
        - name: List all archived jobs within retention period (max of 30 days).
          text: >
            az iot hub job list --hub-name {iothub_name}
        - name: List all archived jobs projecting specific properties
          text: >
            az iot hub job list --hub-name {iothub_name} --query "[*].[jobId,type,status,startTime,endTime]"
        - name: List only update twin type jobs
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type scheduleDeviceMethod
        - name: List device method jobs which have status "scheduled"
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type scheduleDeviceMethod --job-status scheduled
        - name: List device export jobs which have status "completed"
          text: >
            az iot hub job list --hub-name {iothub_name} --job-type export --job-status completed
    """

    helps['iot hub job cancel'] = """
        type: command
        short-summary: Cancel an IoT Hub job.

        examples:
        - name: Cancel an IoT Hub job.
          text: >
            az iot hub job cancel --hub-name {iothub_name} --job-id {job_id}
    """
