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
    _load_central_users_help()
    _load_central_device_templates_help()
    _load_central_device_twin_help()
    _load_central_monitors_help()


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
        "iot central app device show-credentials"
    ] = """
        type: command
        short-summary: Get device credentials from IoT Central

        examples:
        - name: Get device credentials for a device
          text: >
            az iot central app device show-credentials
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
        - name: Get registration info on specified device
          text: >
            az iot central app device registration-info --app-id {appid} --device-id {deviceid}
    """

    helps[
        "iot central app device registration-summary"
    ] = """
            type: command
            short-summary: Provides a registration summary of all the devices in an app.
            long-summary: |
                Note: This command can take a significant amount of time to return
                if your app contains a lot of devices
            examples:
            - name: Registration summary
              text: >
                az iot central app device registration-summary --app-id {appid}
        """

    helps[
        "iot central app device run-command"
    ] = """
            type: command
            short-summary: Run a command on a device and view associated response. Does NOT monitor property updates that the command may perform.
            long-summary: |
                Note: payload should be nested under "request".
                i.e. if your device expects the payload in a shape {"key": "value"}
                payload should be {"request": {"key": "value"}}.
                --content can be pointed at a filepath too (.../path/to/payload.json)
            examples:
            - name: Run command response
              text: >
                az iot central app device run-command
                --app-id {appid}
                --device-id {deviceid}
                --interface-id {interfaceid}
                --command-name {commandname}
                --content {payload}

            - name: Short Run command response
              text: >
                az iot central app device run-command
                -n {appid}
                -d {deviceid}
                -i {interfaceid}
                --cn {commandname}
                -k {payload}
        """

    helps[
        "iot central app device show-command-history"
    ] = """
            type: command
            short-summary: Get most recent command-response request and response payload.
            examples:
            - name: Show command response
              text: >
                az iot central app device show-command-history
                --app-id {appid}
                --device-id {deviceid}
                --interface-id {interfaceid}
                --command-name {commandname}
        """


def _load_central_users_help():
    helps[
        "iot central app user"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central users
    """

    helps[
        "iot central app user create"
    ] = """
        type: command
        short-summary: Add a user to the application
        examples:
        - name: Add a user by email to the application
          text: >
            az iot central app user create
            --user-id {userId}
            --app-id {appId}
            --email {emailAddress}
            --role admin

        - name: Add a service-principal to the application
          text: >
            az iot central app user create
            --user-id {userId}
            --app-id {appId}
            --tenant-id {tenantId}
            --object-id {objectId}
            --role operator
    """
    helps[
        "iot central app user show"
    ] = """
    type: command
    short-summary: Get the details of a user by ID
    examples:
      - name: Get details of user
        text: >
          az iot central app user show
          --app-id {appid}
          --user-id {userId}
    """

    helps[
        "iot central app user delete"
    ] = """
    type: command
    short-summary: Delete a user from the application
    examples:
      - name: Delete a user
        text: >
          az iot central app user delete
          --app-id {appid}
          --user-id {userId}

    """

    helps[
        "iot central app user list"
    ] = """
    type: command
    short-summary: Get list of users in an application
    examples:
      - name: List of users
        text: >
          az iot central app user list
          --app-id {appid}

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
            az iot central app monitor-events --app-id {app_id} -d Device*d
        - name: Basic usage when filtering on module.
          text: >
            az iot central app monitor-events --app-id {app_id} -m {module_id}
        - name: Basic usage when filtering targeted modules with a wildcard in the ID
          text: >
            az iot central app monitor-events --app-id {app_id} -m Module*
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
        - name: Basic usage when filtering on module.
          text: >
            az iot central app validate-messages --app-id {app_id} -m {module_id}
        - name: Basic usage when filtering targeted modules with a wildcard in the ID
          text: >
            az iot central app validate-messages --app-id {app_id} -m Module*
        - name: Filter device and specify an Event Hub consumer group to bind to.
          text: >
            az iot central app validate-messages --app-id {app_id} -d {device_id} --cg {consumer_group_name}
    """

    helps[
        "iot central app monitor-properties"
    ] = """
        type: command
        short-summary: Monitor desired and reported properties sent to/from the IoT Hub for an IoT Central app.
        long-summary: |
                    Polls device-twin from central and compares it to the last device-twin
                    Parses out properties from device-twin, and detects if changes were made
                    Prints subset of properties that were changed within the polling interval
        examples:
        - name: Basic usage
          text: >
            az iot central app monitor-properties --app-id {app_id} -d {device_id}
    """

    helps[
        "iot central app validate-properties"
    ] = """
        type: command
        short-summary: Validate reported properties sent to IoT Central app.
        long-summary: |
                    Performs validations on reported property updates:
                    1) Warning - Properties sent by device that are not modeled in central.
                    2) Warning - Properties with same name declared in multiple interfaces
                       should have interface name included as part of the property update.
        examples:
        - name: Basic usage
          text: >
            az iot central app validate-properties --app-id {app_id} -d {device_id}
    """
