# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps


def load_central_help():
    helps[
        "iot central"
    ] = """
        type: group
        short-summary: Manage Azure Central (IoT Central) solutions & infrastructure
    """

    helps[
        "iot central app"
    ] = """
        type: group
        short-summary: |
                    Manage Azure IoT Central applications.

                    To use this command group, the user must be logged through the `az login` command,
                    have the correct tenant set (the users home tenant) and
                    have access to the application through http://apps.azureiotcentral.com"
        """

    _load_central_devices_help()
    _load_central_device_templates_help()
    _load_central_device_twin_help()
    _load_central_monitors_help()

    # TODO: Delete this by end of July 2020
    _load_central_deprecated_commands()


def _load_central_devices_help():
    helps[
        "iot central app device"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central devices
    """

    helps[
        "iot central app device create"
    ] = """
        type: command
        short-summary: Create a device in IoT Central

        examples:
        - name: Create a device
          text: >
            az iot central app device create
            --app-id {appid}
            --device-id {deviceid}

        - name: Create a simulated device
          text: >
            az iot central app device create
            --app-id {appid}
            --device-id {deviceid}
            --instance-of {devicetemplateid}
            --simulated
    """

    helps[
        "iot central app device show"
    ] = """
        type: command
        short-summary: Get a device from IoT Central

        examples:
        - name: Get a device
          text: >
            az iot central app device show
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central app device list"
    ] = """
        type: command
        short-summary: List all devices in IoT Central

        examples:
        - name: List all devices in IoT Central
          text: >
            az iot central app device list
            --app-id {appid}
    """

    helps[
        "iot central app device delete"
    ] = """
        type: command
        short-summary: Delete a device from IoT Central

        examples:
        - name: Delete a device
          text: >
            az iot central app device delete
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central app device registration-info"
    ] = """
        type: command
        short-summary: Get registration info on device(s) from IoT Central
        long-summary: |
            Note: This command can take a significant amount of time to return
            if no device id is specified and your app contains a lot of devices

        examples:
        - name: Get registration info on all devices. This command may take a long time to complete execution.
          text: >
            az iot central app device registration-info
            --app-id {appid}

        - name: Get registration info on specified device
          text: >
            az iot central app device registration-info
            --app-id {appid}
            --device-id {deviceid}
    """


def _load_central_device_templates_help():
    helps[
        "iot central app device-template"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device templates
    """

    helps[
        "iot central app device-template create"
    ] = """
        type: command
        short-summary: Create a device template in IoT Central

        examples:
        - name: Create a device template with payload read from a file
          text: >
            az iot central app device-template create
            --app-id {appid}
            --content {pathtofile}
            --device-template-id {devicetemplateid}

        - name: Create a device template with payload read from raw json
          text: >
            az iot central app device-template create
            --app-id {appid}
            --content {json}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central app device-template show"
    ] = """
        type: command
        short-summary: Get a device template from IoT Central

        examples:
        - name: Get a device template
          text: >
            az iot central app device-template show
            --app-id {appid}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central app device-template list"
    ] = """
        type: command
        short-summary: List all device templates in IoT Central

        examples:
        - name: List all device templates
          text: >
            az iot central app device-template list
            --app-id {appid}
    """

    helps[
        "iot central app device-template map"
    ] = """
        type: command
        short-summary: Returns a mapping of device template name to device template id

        examples:
        - name: Get device template name to id mapping
          text: >
            az iot central app device-template map
            --app-id {appid}
    """

    helps[
        "iot central app device-template delete"
    ] = """
        type: command
        short-summary: Delete a device template from IoT Central
        long-summary: |
            Note: this is expected to fail if any devices are still associated to this template.

        examples:
        - name: Delete a device template from IoT Central
          text: >
            az iot central app device-template delete
            --app-id {appid}
            --device-template-id {devicetemplateid}
    """


def _load_central_device_twin_help():
    helps[
        "iot central app device-twin"
    ] = """
        type: group
        short-summary: Manage IoT Central device twins.
    """

    helps[
        "iot central app device-twin show"
    ] = """
        type: command
        short-summary: Get the device twin from IoT Hub.
    """


def _load_central_monitors_help():
    helps[
        "iot central app monitor-events"
    ] = """
        type: command
        short-summary: Monitor device telemetry & messages sent to the IoT Hub for an IoT Central app.
        long-summary: |
                    EXPERIMENTAL requires Python 3.5+
                    This command relies on and may install dependent Cython package (uamqp) upon first execution.
                    https://github.com/Azure/azure-uamqp-python
        examples:
        - name: Basic usage
          text: >
            az iot central app monitor-events --app-id {app_id}
        - name: Basic usage when filtering on target device
          text: >
            az iot central app monitor-events --app-id {app_id} -d {device_id}
        - name: Basic usage when filtering targeted devices with a wildcard in the ID
          text: >
            az iot central app monitor-events --app-id {app_id} -d Device*
        - name: Filter device and specify an Event Hub consumer group to bind to.
          text: >
            az iot central app monitor-events --app-id {app_id} -d {device_id} --cg {consumer_group_name}
        - name: Receive message annotations (message headers)
          text: >
            az iot central app monitor-events --app-id {app_id} -d {device_id} --properties anno
        - name: Receive message annotations + system properties. Never time out.
          text: >
            az iot central app monitor-events --app-id {app_id} -d {device_id} --properties anno sys --timeout 0
        - name: Receive all message attributes from all device messages
          text: >
            az iot central app monitor-events --app-id {app_id} --props all
        - name: Receive all messages and parse message payload as JSON
          text: >
            az iot central app monitor-events --app-id {app_id} --output json
    """

    helps[
        "iot central app validate-messages"
    ] = """
        type: command
        short-summary: Validate messages sent to the IoT Hub for an IoT Central app.
        long-summary: |
                    EXPERIMENTAL requires Python 3.5+
                    This command relies on and may install dependent Cython package (uamqp) upon first execution.
                    https://github.com/Azure/azure-uamqp-python
        examples:
        - name: Basic usage
          text: >
            az iot central app validate-messages --app-id {app_id}
        - name: Output errors as they are detected
          text: >
            az iot central app validate-messages --app-id {app_id} --style scroll
        - name: Basic usage when filtering on target device
          text: >
            az iot central app validate-messages --app-id {app_id} -d {device_id}
        - name: Basic usage when filtering targeted devices with a wildcard in the ID
          text: >
            az iot central app validate-messages --app-id {app_id} -d Device*
        - name: Filter device and specify an Event Hub consumer group to bind to.
          text: >
            az iot central app validate-messages --app-id {app_id} -d {device_id} --cg {consumer_group_name}
    """


# TODO: Delete this by July 2020
def _load_central_deprecated_commands():
    helps[
        "iotcentral app monitor-events"
    ] = """
    type: command
    short-summary: Monitor device telemetry & messages sent to the IoT Hub for an IoT Central app.
    long-summary: |
                  EXPERIMENTAL requires Python 3.5+
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python

                  DEPRECATED. Use 'az iot central app monitor-events' instead.
    examples:
    - name: Basic usage
      text: >
        az iotcentral app monitor-events --app-id {app_id}
    - name: Basic usage when filtering on target device
      text: >
        az iotcentral app monitor-events --app-id {app_id} -d {device_id}
    - name: Basic usage when filtering targeted devices with a wildcard in the ID
      text: >
        az iotcentral app monitor-events --app-id {app_id} -d Device*
    - name: Filter device and specify an Event Hub consumer group to bind to.
      text: >
        az iotcentral app monitor-events --app-id {app_id} -d {device_id} --cg {consumer_group_name}
    - name: Receive message annotations (message headers)
      text: >
        az iotcentral app monitor-events --app-id {app_id} -d {device_id} --properties anno
    - name: Receive message annotations + system properties. Never time out.
      text: >
        az iotcentral app monitor-events --app-id {app_id} -d {device_id} --properties anno sys --timeout 0
    - name: Receive all message attributes from all device messages
      text: >
        az iotcentral app monitor-events --app-id {app_id} --props all
    - name: Receive all messages and parse message payload as JSON
      text: >
        az iotcentral app monitor-events --app-id {app_id} --output json
    """

    helps[
        "iotcentral device-twin"
    ] = """
        type: group
        short-summary: Manage IoT Central device twins.
        long-summary: DEPRECATED. Use 'az iot central device-twin' instead.
    """

    helps[
        "iotcentral device-twin show"
    ] = """
        type: command
        short-summary: Get the device twin from IoT Hub.
        long-summary: DEPRECATED. Use 'az iot central device-twin show' instead.
    """

    helps[
        "iot central device-twin"
    ] = """
        type: group
        short-summary: Manage IoT Central device twins.
    """

    helps[
        "iot central device-twin show"
    ] = """
        type: command
        short-summary: Get the device twin from IoT Hub.
    """

    helps[
        "iotcentral app device-twin"
    ] = """
        type: group
        short-summary: Manage IoT Central device twins.
    """

    helps[
        "iotcentral app device-twin show"
    ] = """
        type: command
        short-summary: Manage IoT Central device twins.
    """
