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

    helps["iot hub job create"] = """
        type: command
        short-summary: Create and schedule an IoT Hub job for execution.
        long-summary: |
                      When scheduling a twin update job, the twin patch is a required argument.
                      When scheduling a device method job, the method name and payload are required arguments.
                      PLEASE NOTE: Using a custom start time that's in the past may cause the operation to fail.

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
            --start-time "2050-01-08T12:19:56.868Z" --query-condition "deviceId IN ['MyDevice1', 'MyDevice2', 'MyDevice3']"

        - name: Create and schedule a job to invoke a device method for a set of devices meeting a query condition.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleDeviceMethod -n {iothub_name} --method-name setSyncIntervalSec --method-payload 30
            --query-condition "properties.reported.settings.syncIntervalSec != 30"

        - name:  Create and schedule a job to invoke a device method for all devices.
          text: >
            az iot hub job create --job-id {job_name} --job-type scheduleDeviceMethod -q "*" -n {iothub_name}
            --method-name setSyncIntervalSec --method-payload '{"version":"1.0"}'
    """

    helps["iot hub job show"] = """
        type: command
        short-summary: Show details of an existing IoT Hub job.

        examples:
        - name: Show the details of a created job.
          text: >
            az iot hub job show --hub-name {iothub_name} --job-id {job_id}
    """

    helps["iot hub job list"] = """
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

    helps["iot hub job cancel"] = """
        type: command
        short-summary: Cancel an IoT Hub job.

        examples:
        - name: Cancel an IoT Hub job.
          text: >
            az iot hub job cancel --hub-name {iothub_name} --job-id {job_id}
    """

    helps["iot hub digital-twin"] = """
        type: group
        short-summary: Manipulate and interact with the digital twin of an IoT Hub device.
    """

    helps["iot hub digital-twin invoke-command"] = """
        type: command
        short-summary: Invoke a root or component level command of a digital twin device.

        examples:
        - name: Invoke root level command "reboot" which takes a payload that includes the "delay" property.
          text: >
            az iot hub digital-twin invoke-command --command-name reboot -n {iothub_name} -d {device_id} --payload '{"delay":5}'

        - name: Invoke command "getMaxMinReport" on component "thermostat1" that takes no input.
          text: >
            az iot hub digital-twin invoke-command --cn getMaxMinReport -n {iothub_name} -d {device_id} --component-path thermostat1
    """

    helps["iot hub digital-twin show"] = """
        type: command
        short-summary: Show the digital twin of an IoT Hub device.

        examples:
        - name: Show the target device digital twin.
          text: >
            az iot hub digital-twin show -n {iothub_name} -d {device_id}
    """

    helps["iot hub digital-twin update"] = """
        type: command
        short-summary: Update the read-write properties of a digital twin device via JSON patch specification.
        long-summary: Currently operations are limited to add, replace and remove.

        examples:
        - name: Update a digital twin via JSON patch specification.
          text: >
            az iot hub digital-twin update --hub-name {iothub_name} --device-id {device_id}
            --json-patch '{"op":"add", "path":"/thermostat1/targetTemperature", "value": 54}'

        - name: Update a digital twin via JSON patch specification.
          text: >
            az iot hub digital-twin update -n {iothub_name} -d {device_id}
            --json-patch '[
              {"op":"remove", "path":"/thermostat1/targetTemperature"},
              {"op":"add", "path":"/thermostat2/targetTemperature", "value": 22}
            ]'

        - name: Update a digital twin property via JSON patch specification defined in a file.
          text: >
            az iot hub digital-twin update -n {iothub_name} -d {device_id}
            --json-patch ./my/patch/document.json
    """

    helps[
        "iot device"
    ] = """
        type: group
        short-summary: Leverage device simulation and other device-centric operations such as device-to-cloud or
          cloud-to-device messaging capabilities.
    """

    helps[
        "iot device c2d-message"
    ] = """
        type: group
        short-summary: Cloud-to-device messaging commands.
    """

    helps[
        "iot device c2d-message abandon"
    ] = """
        type: command
        short-summary: Abandon a cloud-to-device message.
    """

    helps[
        "iot device c2d-message complete"
    ] = """
        type: command
        short-summary: Complete a cloud-to-device message.
    """

    helps[
        "iot device c2d-message receive"
    ] = """
        type: command
        short-summary: Receive a cloud-to-device message.
        long-summary: |
          Note: Only one message ack argument [--complete, --reject, --abandon] will be accepted.
        examples:
        - name: Basic usage
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group}
        - name: Receive a message and set a lock timeout of 30 seconds for that message
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --lt {30}
        - name: Receive a message and ack it as 'complete' after it is received
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --complete
        - name: Receive a message and reject it after it is received
          text: >
            az iot device c2d-message receive -d {device_id} -n {hub_name} -g {resource_group} --reject
    """

    helps[
        "iot device c2d-message reject"
    ] = """
        type: command
        short-summary: Reject or deadletter a cloud-to-device message.
    """

    helps[
        "iot device c2d-message purge"
    ] = """
        type: command
        short-summary: Purge cloud-to-device message queue for a target device.
    """

    helps[
        "iot device c2d-message send"
    ] = """
        type: command
        short-summary: Send a cloud-to-device message.
        long-summary: |
                      This command relies on and may install dependent Cython package (uamqp) upon first execution.
                      https://github.com/Azure/azure-uamqp-python
        examples:
        - name: Basic usage with default message body
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name}
        - name: Send cloud-to-device message with custom data and properties.
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --data 'Hello World' --props 'key0=value0;key1=value1'
        - name: Send a C2D message and wait for device acknowledgement
          text: >
            az iot device c2d-message send -d {device_id} -n {iothub_name} --ack full --wait
    """

    helps[
        "iot device send-d2c-message"
    ] = """
        type: command
        short-summary: |
                        Send an mqtt device-to-cloud message.
                        The command supports sending messages with application and system properties.
                        Note: If using x509 authentication methods, the certificate and key files (and passphrase if needed) must be provided.
        examples:
        - name: Basic usage
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id}
        - name: Basic usage for device registering the model Id of 'dtmi:com:example:Thermostat;1' upon connection
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --model-id 'dtmi:com:example:Thermostat;1'
        - name: Basic usage for device with x509 authentication
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path}
        - name: Basic usage for device with x509 authentication in which the key file has a passphrase
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path} --pass {passphrase}
        - name: Basic usage with custom data
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --data {message_body}
        - name: Send application properties
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props 'key0=value0;key1=value1'
        - name: Send system properties (Message Id and Correlation Id)
          text: az iot device send-d2c-message -n {iothub_name} -d {device_id} --props '$.mid=<id>;$.cid=<id>'
    """

    helps[
        "iot device simulate"
    ] = """
        type: command
        short-summary: |
                        Simulate a device in an Azure IoT Hub.
                        While the device simulation is running, the device will automatically receive
                        and acknowledge cloud-to-device (c2d) messages. For mqtt simulation, all c2d messages will
                        be acknowledged with completion. For http simulation c2d acknowledgement is based on user
                        selection which can be complete, reject or abandon. The mqtt simulation also supports direct
                        method invocation which can be acknowledged by a response status code and response payload.
                        Note: The command by default will set content-type to application/json and content-encoding
                        to utf-8. This can be overriden.
                        Note: If using x509 authentication methods, the certificate and key files (and passphrase if needed) must be provided.
        examples:
        - name: Basic usage (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id}
        - name: Basic usage for device registering the model Id of 'dtmi:com:example:Thermostat;1' upon connection (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --model-id 'dtmi:com:example:Thermostat;1'
        - name: Basic usage for device with x509 authentication (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path}
        - name: Basic usage for device with x509 authentication (mqtt) in which the key file has a passphrase
          text: az iot device simulate -n {iothub_name} -d {device_id} --cp {certificate_file_path} --kp {key_file_path} --pass {passphrase}
        - name: Send mixed properties (mqtt)
          text: az iot device simulate -n {iothub_name} -d {device_id} --properties "myprop=myvalue;$.ct=application/json"
        - name: Send direct method response status code and direct method response payload as raw json (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --method-response-code 201 --method-response-payload '{"result":"Direct method successful"}'
        - name: Send direct method response status code and direct method response payload as path to local file (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --method-response-code 201 --method-response-payload '../my_direct_method_payload.json'
        - name: Send the initial state of device twin reported properties as raw json for the target device (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --init-reported-properties '{"reported_prop_1":"val_1", "reported_prop_2":val_2}'
        - name: Send the initial state of device twin reported properties as path to local file for the target device (mqtt only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --init-reported-properties '../my_device_twin_reported_properties.json'
        - name: Basic usage (http)
          text: az iot device simulate -n {iothub_name} -d {device_id} --protocol http
        - name: Send mixed properties (http)
          text: az iot device simulate -n {iothub_name} -d {device_id} --protocol http --properties
                "iothub-app-myprop=myvalue;content-type=application/json;iothub-correlationid=12345"
        - name: Choose total message count and interval between messages
          text: az iot device simulate -n {iothub_name} -d {device_id} --msg-count 1000 --msg-interval 5
        - name: Reject c2d messages (http only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --rs reject --protocol http
        - name: Abandon c2d messages (http only)
          text: az iot device simulate -n {iothub_name} -d {device_id} --rs abandon --protocol http
    """

    helps[
        "iot device upload-file"
    ] = """
        type: command
        short-summary: Upload a local file as a device to a pre-configured blob storage container.
    """

    helps["iot hub certificate root-authority"] = """
        type: group
        short-summary: Manage the certificate root-authority for an IoT Hub instance.
    """

    helps["iot hub certificate root-authority set"] = """
        type: command
        short-summary: Set the certificate root-authority for an IoT Hub instance to a specific version.
        long-summary: Transition this resource to a certificate on the DigiCert Global G2 root or revert to Baltimore root.
          Before making this transition, please ensure all devices are updated to contain the public portion of the root
          that the IoT Hub will be transitioned to. Devices will disconnect and reconnect using the new root.
          We suggest monitoring current connections but an user defined metric may be more appropriate for your situation.
        examples:
        - name: Transition the target IoT Hub certificate root authority to Digicert.
          text: >
            az iot hub certificate root-authority set --hub-name {iothub_name} --certificate-authority v2
        - name: Revert the target IoT Hub certificate root authority to Baltimore.
          text: >
            az iot hub certificate root-authority set --hub-name {iothub_name} --certificate-authority v1
    """

    helps["iot hub certificate root-authority show"] = """
        type: command
        short-summary: Show the current certificate root-authority for an IoT Hub instance.
        examples:
        - name: Show the target IoT Hub certificate root authority.
          text: >
            az iot hub certificate root-authority show --hub-name {iothub_name}
    """
