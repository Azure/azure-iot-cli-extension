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
        short-summary: Manage IoT Central resources.
        long-summary: |
            IoT Central is an IoT application platform that reduces the burden and cost of developing,
            managing, and maintaining enterprise-grade IoT solutions. Choosing to build with IoT Central
            gives you the opportunity to focus time, money, and energy on transforming your business
            with IoT data, rather than just maintaining and updating a complex and continually evolving
            IoT infrastructure.

            IoT Central documentation is available at https://aka.ms/iotcentral-documentation
            Additional information on CLI commands is available at https://aka.ms/azure-cli-iot-ext
        """

    helps[
        "iot central app"
    ] = """
        type: group
        short-summary: Manage IoT Central applications.
        long-summary: Create, delete, view, and update your IoT Central apps.
        """

    _load_central_devices_help()
    _load_central_users_help()
    _load_central_api_token_help()
    _load_central_device_templates_help()
    _load_central_monitors_help()
    _load_central_command_help()
    _load_central_compute_device_key()


def _load_central_devices_help():
    helps[
        "iot central device"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central devices
    """

    helps[
        "iot central device create"
    ] = """
        type: command
        short-summary: Create a device in IoT Central.

        examples:
        - name: Create a device
          text: >
            az iot central device create
            --app-id {appid}
            --device-id {deviceid}

        - name: Create a simulated device
          text: >
            az iot central device create
            --app-id {appid}
            --device-id {deviceid}
            --instance-of {devicetemplateid}
            --simulated
    """

    helps[
        "iot central device show"
    ] = """
        type: command
        short-summary: Get a device from IoT Central.

        examples:
        - name: Get a device
          text: >
            az iot central device show
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device delete"
    ] = """
        type: command
        short-summary: Delete a device from IoT Central.

        examples:
        - name: Delete a device
          text: >
            az iot central device delete
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device show-credentials"
    ] = """
        type: command
        short-summary: Get device credentials from IoT Central.

        examples:
        - name: Get device credentials for a device
          text: >
            az iot central device show-credentials
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device registration-info"
    ] = """
        type: command
        short-summary: Get registration info on device(s) from IoT Central.
        long-summary: |
            Note: This command can take a significant amount of time to return if no device id is specified and your app contains a lot of devices.

        examples:
        - name: Get registration info on specified device
          text: >
            az iot central device registration-info --app-id {appid} --device-id {deviceid}
    """


def _load_central_compute_device_key():
    helps[
        "iot central device compute-device-key"
    ] = """
        type: command
        short-summary: Generate a derived device SAS key.
        long-summary: Generate a derived device key from a group-level SAS key.
        examples:
        - name: Basic usage
          text: >
            az iot central device compute-device-key --pk {primaryKey} --device-id {deviceid}
      """


def _load_central_command_help():
    helps[
        "iot central device command"
    ] = """
          type: group
          short-summary: Run device commands.
      """

    helps[
        "iot central device command history"
    ] = """
            type: command
            short-summary: Get the details for the latest command request and response sent to the device.
            long-summary: |
              Lists the most recent command request and response that was sent to the device from IoT Central.
              Any update that the device performs to the device properties as a result of the command execution are not included in the response.
            examples:
            - name: Show command response
              text: >
                az iot central device command history
                --app-id {appid}
                --device-id {deviceid}
                --interface-id {interfaceid}
                --command-name {commandname}
        """

    helps[
        "iot central device command run"
    ] = """
            type: command
            short-summary: Run a command on a device and view associated response. Does NOT monitor property updates that the command may perform.
            long-summary: |
                Note: payload should be nested under "request".
                i.e. if your device expects the payload in a shape {"key": "value"}
                payload should be {"request": {"key": "value"}}.
                --content can also be pointed at a filepath like this (.../path/to/payload.json)
            examples:
            - name: Run command response
              text: >
                az iot central device command run
                --app-id {appid}
                --device-id {deviceid}
                --interface-id {interfaceid}
                --command-name {commandname}
                --content {payload}

            - name: Short Run command response
              text: >
                az iot central device command run
                -n {appid}
                -d {deviceid}
                -i {interfaceid}
                --cn {commandname}
                -k {payload}
        """


def _load_central_users_help():
    helps[
        "iot central user"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central users
    """

    helps[
        "iot central user create"
    ] = """
        type: command
        short-summary: Add a user to the application
        examples:
        - name: Add a user by email to the application
          text: >
            az iot central user create
            --user-id {userId}
            --app-id {appId}
            --email {emailAddress}
            --role admin

        - name: Add a service-principal to the application
          text: >
            az iot central user create
            --user-id {userId}
            --app-id {appId}
            --tenant-id {tenantId}
            --object-id {objectId}
            --role operator
    """
    helps[
        "iot central user show"
    ] = """
    type: command
    short-summary: Get the details of a user by ID
    examples:
      - name: Get details of user
        text: >
          az iot central user show
          --app-id {appid}
          --user-id {userId}
    """

    helps[
        "iot central user delete"
    ] = """
    type: command
    short-summary: Delete a user from the application
    examples:
      - name: Delete a user
        text: >
          az iot central user delete
          --app-id {appid}
          --user-id {userId}

    """

    helps[
        "iot central user list"
    ] = """
    type: command
    short-summary: Get list of users in an application
    examples:
      - name: List of users
        text: >
          az iot central user list
          --app-id {appid}

    """


def _load_central_api_token_help():
    helps[
        "iot central api-token"
    ] = """
        type: group
        short-summary: Manage API tokens for your IoT Central application.
        long-summary: IoT Central allows you to generate and manage API tokens to be used to access the IoT Central API. More information about APIs can be found at https://aka.ms/iotcentraldocsapi.
    """

    helps[
        "iot central api-token create"
    ] = """
        type: command
        short-summary: Generate an API token associated with your IoT Central application.
        long-summary: |
          Note: Write down your token once it's been generated as you won't be able to retrieve it again.
        examples:
        - name: Add new API token
          text: >
            az iot central api-token create
            --token-id {tokenId}
            --app-id {appId}
            --role admin
    """
    helps[
        "iot central api-token show"
    ] = """
    type: command
    short-summary: Get details for an API token associated with your IoT Central application.
    long-summary: List details, like its associated role, for an API token in your IoT Central app.
    examples:
      - name: Get API token
        text: >
          az iot central api-token show
          --app-id {appid}
          --token-id {tokenId}
    """

    helps[
        "iot central api-token delete"
    ] = """
    type: command
    short-summary: Delete an API token associated with your IoT Central application.
    examples:
      - name: Delete an API token
        text: >
          az iot central api-token delete
          --app-id {appid}
          --token-id {tokenId}
    """

    helps[
        "iot central api-token list"
    ] = """
    type: command
    short-summary: List all API tokens associated with your IoT Central application.
    long-summary: Information in the list contains basic information about the tokens in the application and does not include token values.
    examples:
      - name: List of API tokens
        text: >
          az iot central api-token list
          --app-id {appid}

    """


def _load_central_device_templates_help():
    helps[
        "iot central device-template"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device templates
    """

    helps[
        "iot central device-template create"
    ] = """
        type: command
        short-summary: Create a device template in IoT Central.

        examples:
        - name: Create a device template with payload read from a file
          text: >
            az iot central device-template create
            --app-id {appid}
            --content {pathtofile}
            --device-template-id {devicetemplateid}

        - name: Create a device template with payload read from raw json
          text: >
            az iot central device-template create
            --app-id {appid}
            --content {json}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central device-template show"
    ] = """
        type: command
        short-summary: Get a device template from IoT Central.

        examples:
        - name: Get a device template
          text: >
            az iot central device-template show
            --app-id {appid}
            --device-template-id {devicetemplateid}
    """

    helps[
        "iot central device-template delete"
    ] = """
        type: command
        short-summary: Delete a device template from IoT Central.
        long-summary: |
          Note: this is expected to fail if any devices are still associated to this template.

        examples:
        - name: Delete a device template from IoT Central
          text: >
            az iot central device-template delete
            --app-id {appid}
            --device-template-id {devicetemplateid}
    """


def _load_central_monitors_help():

    helps[
        "iot central diagnostics"
    ] = """
        type: group
        short-summary: Perform application and device level diagnostics.
    """

    helps[
        "iot central diagnostics monitor-events"
    ] = """
        type: command
        short-summary: View device telemetry messages sent to the IoT Central app.
        long-summary: |
                    Shows the telemetry data sent to IoT Central application. By default,
                    it shows all the data sent by all devices. Use the --device-id parameter
                    to filter to a specific device.

        examples:
        - name: Basic usage
          text: >
            az iot central diagnostics monitor-events --app-id {app_id}
        - name: Basic usage when filtering on target device
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -d {device_id}
        - name: Basic usage when filtering targeted devices with a wildcard in the ID
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -d Device*d
        - name: Basic usage when filtering on module.
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -m {module_id}
        - name: Basic usage when filtering targeted modules with a wildcard in the ID
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -m Module*
        - name: Filter device and specify an Event Hub consumer group to bind to.
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -d {device_id} --cg {consumer_group_name}
        - name: Receive message annotations (message headers)
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -d {device_id} --properties anno
        - name: Receive message annotations + system properties. Never time out.
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} -d {device_id} --properties anno sys --timeout 0
        - name: Receive all message attributes from all device messages
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} --props all
        - name: Receive all messages and parse message payload as JSON
          text: >
            az iot central diagnostics monitor-events --app-id {app_id} --output json
    """

    helps[
        "iot central diagnostics validate-messages"
    ] = """
        type: command
        short-summary: Validate messages sent to the IoT Hub for an IoT Central app.
        long-summary: |
                    Performs validations on the telemetry messages and reports back data that is not modeled in the device template or data where the data type doesn’t match what is defined in the device template.
        examples:
        - name: Basic usage
          text: >
            az iot central diagnostics validate-messages --app-id {app_id}
        - name: Output errors as they are detected
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} --style scroll
        - name: Basic usage when filtering on target device
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} -d {device_id}
        - name: Basic usage when filtering targeted devices with a wildcard in the ID
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} -d Device*
        - name: Basic usage when filtering on module.
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} -m {module_id}
        - name: Basic usage when filtering targeted modules with a wildcard in the ID
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} -m Module*
        - name: Filter device and specify an Event Hub consumer group to bind to.
          text: >
            az iot central diagnostics validate-messages --app-id {app_id} -d {device_id} --cg {consumer_group_name}
    """

    helps[
        "iot central diagnostics monitor-properties"
    ] = """
        type: command
        short-summary: View desired and reported properties sent to/from the IoT Central app.
        long-summary: |
                    Polls device-twin from central and compares it to the last device-twin
                    Parses out properties from device-twin, and detects if changes were made
                    Prints subset of properties that were changed within the polling interval
        examples:
        - name: Basic usage
          text: >
            az iot central diagnostics monitor-properties --app-id {app_id} -d {device_id}
    """

    helps[
        "iot central diagnostics validate-properties"
    ] = """
        type: command
        short-summary: Validate reported properties sent to the IoT Central application.
        long-summary: |
                    Performs validations on reported property updates:
                    1) Warning - Properties sent by device that are not modeled in central.
                    2) Warning - Properties with same name declared in multiple interfaces
                    should have interface name included as part of the property update.
        examples:
        - name: Basic usage
          text: >
            az iot central diagnostics validate-properties --app-id {app_id} -d {device_id}
    """

    helps[
        "iot central diagnostics registration-summary"
    ] = """
            type: command
            short-summary: View the registration summary of all the devices in an app.
            long-summary: |
                Note: This command can take a significant amount of time to return
                if your app contains a lot of devices
            examples:
            - name: Registration summary
              text: >
                az iot central diagnostics registration-summary --app-id {appid}
        """

    helps[
        "iot central device twin"
    ] = """
        type: group
        short-summary: Manage IoT Central device twins.
    """

    helps[
        "iot central device twin show"
    ] = """
        type: command
        short-summary: Get the device twin from IoT Hub.
    """
