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
    helps[
        "iot central query"
    ] = """
        type: command
        short-summary: Query device telemetry or property data with IoT Central Query Language.
        long-summary: For query syntax details, visit https://docs.microsoft.com/en-us/azure/iot-central/core/howto-query-with-rest-api.
        examples:
          - name: Query device telemetry
            text: >
              az iot central query
              --app-id {appid}
              --query-string {query_string}
        """

    _load_central_devices_help()
    _load_central_users_help()
    _load_central_api_token_help()
    _load_central_device_templates_help()
    _load_central_device_groups_help()
    _load_central_roles_help()
    _load_central_file_upload_configuration_help()
    _load_central_organizations_help()
    _load_central_jobs_help()
    _load_central_monitors_help()
    _load_central_command_help()
    _load_central_compute_device_key()
    _load_central_export_help()
    _load_central_c2d_message_help()
    _load_central_edge_help()


def _load_central_export_help():
    helps[
        "iot central export"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central data exports.
    """

    helps[
        "iot central export list"
    ] = """
        type: command
        short-summary: Get the full list of exports for an IoT Central application.
        examples:
        - name: List all exports in an application
          text: >
            az iot central export list
            --app-id {appid}
    """

    helps[
        "iot central export show"
    ] = """
        type: command
        short-summary: Get an export details
        examples:
        - name: Get an export details
          text: >
            az iot central export show
            --app-id {appid}
            --export-id {exportid}
    """

    helps[
        "iot central export create"
    ] = """
        type: command
        short-summary: Create an export for an IoT Central application.
        examples:
        - name: Create an export with filter, enrichments, destinations
          text: >
            az iot central export create
            --app-id {appid}
            --export-id {exportid}
            --enabled {enabled}
            --display-name {displayname}
            --source {source}
            --filter "SELECT * FROM devices WHERE $displayName != \"abc\" AND $id = \"a\""
            --enrichments '{
              "simulated": {
                "path": "$simulated"
              }
            }'
            --destinations '[
              {
                "id": "{destinationid}",
                "transform": "{ ApplicationId: .applicationId, Component: .component, DeviceName: .device.name }"
              }
            ]'
    """

    helps[
        "iot central export update"
    ] = """
        type: command
        short-summary: Update an export for an IoT Central application.
        long-summary: Source is immutable once an export is created.
        examples:
        - name: Update an export from file
          text: >
            az iot central export update
            --app-id {appid}
            --export-id {exportid}
            --content './filepath/payload.json'

        - name: Update an export's display name and enable export from json payload
          text: >
            az iot central export update
            --app-id {appid}
            --export-id {exportid}
            --content "{'displayName': 'Updated Export Name', 'enabled': true}"
    """

    helps[
        "iot central export delete"
    ] = """
        type: command
        short-summary: Delete an export for an IoT Central application.
        examples:
        - name: Delete an export
          text: >
            az iot central export delete
            --app-id {appid}
            --export-id {exportid}
    """
    _load_central_destination_help()


def _load_central_destination_help():
    helps[
        "iot central export destination"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central export destinations.
    """

    helps[
        "iot central export destination list"
    ] = """
        type: command
        short-summary: Get the full list of export destinations for an IoT Central application.
        examples:
        - name: List all export destinations in an application
          text: >
            az iot central export destination list
            --app-id {appid}
    """

    helps[
        "iot central export destination show"
    ] = """
        type: command
        short-summary: Get an export destination details
        examples:
        - name: Get an export destination details
          text: >
            az iot central export destination show
            --app-id {appid}
            --dest-id {destinationid}
    """

    helps[
        "iot central export destination create"
    ] = """
        type: command
        short-summary: Create an export destination for an IoT Central application.
        examples:
        - name: Create a webhook export destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destinationid}
            --name {displayname}
            --url {url}
            --type webhook@v1
            --header '{"x-custom-region":{"value":"westus", "secret": false}}'

        - name: Create a blob storage export destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destintionid}
            --type blobstorage@v1
            --name {displayname}
            --authorization '{
              "type": "connectionString",
              "connectionString":"DefaultEndpointsProtocol=https;AccountName=[accountName];AccountKey=[key];EndpointSuffix=core.windows.net",
              "containerName": "test"
            }'

        - name: Create an Azure Data Explorer export destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destintionid}
            --type dataexplorer@v1
            --name {displayname}
            --cluster-url {clusterurl}
            --database {database}
            --table {table}
            --authorization '{
              "type": "servicePrincipal",
              "clientId": "3b420743-2020-44c6-9b70-cc42f945db0x",
              "tenantId": "72f988bf-86f1-41af-91ab-2d7cd011db47",
              "clientSecret": "[Secret]"
            }'

        - name: Create an Event Hub export destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destintionid}
            --type eventhubs@v1
            --name {displayname}
            --authorization '{
              "type": "connectionString",
              "connectionString": "Endpoint=sb://[hubName].servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=*****;EntityPath=entityPath1"
            }'

        - name: Create a Service Bus Queue destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destintionid}
            --type servicebusqueue@v1
            --name {displayname}
            --authorization '{
              "type": "connectionString",
              "connectionString": "Endpoint=sb://[namespance].servicebus.windows.net/;SharedAccessKeyName=xxx;SharedAccessKey=[key];EntityPath=[name]"
            }'

        - name: Create a Service Bus Topic destination with json payload
          text: >
            az iot central export destination create
            --app-id {appid}
            --dest-id {destintionid}
            --type servicebustopic@v1
            --name {displayname}
            --authorization '{
              "type": "connectionString",
              "connectionString": "Endpoint=sb://[namespace].servicebus.windows.net/;SharedAccessKeyName=xxx;SharedAccessKey=[key];EntityPath=[name]"
            }'
    """

    helps[
        "iot central export destination update"
    ] = """
        type: command
        short-summary: Update an export destination for an IoT Central application.
        long-summary: The destination type is immutable once it is created. A new destination must be created with the new type.
        examples:
        - name: Update an export destination from file
          text: >
            az iot central export destination update
            --app-id {appid}
            --dest-id {destinationid}
            --content './filepath/payload.json'

        - name: Update an export destination with json-patch payload
          text: >
            az iot central export destination update
            --app-id {appid}
            --dest-id {destinationid}
            --content '{"displayName": "Web Hook Updated"}'
    """

    helps[
        "iot central export destination delete"
    ] = """
        type: command
        short-summary: Delete an export destination for an IoT Central application.
        examples:
        - name: Delete an export destination
          text: >
            az iot central export destination delete
            --app-id {appid}
            --dest-id {destinationid}
    """


def _load_central_devices_help():
    helps[
        "iot central device"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central devices
    """

    helps[
        "iot central device list"
    ] = """
        type: command
        short-summary: Get the list of devices for an IoT Central application.
        examples:
        - name: List all devices in an application, sorted by device Id (default)
          text: >
            az iot central device list
            --app-id {appid}
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
            --template {devicetemplateid}
            --simulated
    """

    helps[
        "iot central device update"
    ] = """
        type: command
        short-summary: Update a device in IoT Central.
        long-summary: |
                    Allows to change the following properties of a device: "displayName", "template" and "simulated" and "enabled" flags.
                    Device Id cannot be changed.
                    If specified api version is "1.1-preview", organizations for the device can also be updated.

        examples:
        - name: Update a device display name
          text: >
            az iot central device update
            --app-id {appid}
            --device-id {deviceid}
            --device-name {deviceName}

        - name: Turn a simulated device to a real one
          text: >
            az iot central device update
            --app-id {appid}
            --device-id {deviceid}
            --simulated false

        - name: Update organizations for the device
          text: >
            az iot central device update
            --app-id {appid}
            --device-id {deviceid}
            --organizations {organizations}

        - name: Disable a device
          text: >
            az iot central device update
            --app-id {appid}
            --device-id {deviceid}
            --enable false
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
        "iot central device manual-failover"
    ] = """
        type: command
        short-summary: Execute a manual failover of device across multiple IoT Hubs to validate device firmware's ability to reconnect using DPS to a different IoT Hub.
        long-summary: For more information about high availability and default value for ttl-minutes visit https://github.com/iot-for-all/iot-central-high-availability-clients#readme

        examples:
        - name: Execute a manual failover of device across multiple IoT Hubs to validate device firmware's ability to reconnect using DPS to a different IoT Hub.
          text: >
            az iot central device manual-failover
            --app-id {appid}
            --device-id {deviceid}
            --ttl-minutes {ttl_minutes}
    """

    helps[
        "iot central device manual-failback"
    ] = """
        type: command
        short-summary: Reverts the previously executed failover command by moving the device back to it's original IoT Hub
        long-summary: For more information about high availability visit https://github.com/iot-for-all/iot-central-high-availability-clients#readme

        examples:
        - name: Reverts the previously executed failover command by moving the device back to it's original IoT Hub
          text: >
            az iot central device manual-failback
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
            az iot central device registration-info
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device attestation"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device attestation.
    """

    helps[
        "iot central device attestation show"
    ] = """
        type: command
        short-summary: Get device attestation.

        examples:
        - name: Get device attestation on specified device
          text: >
            az iot central device attestation show
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device attestation delete"
    ] = """
        type: command
        short-summary: Remove an individual device attestation.

        examples:
        - name: Remove an individual device attestation on specified device
          text: >
            az iot central device attestation delete
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device attestation update"
    ] = """
        type: command
        short-summary: Update an individual device attestation via patch.

        examples:
        - name: Update an individual device attestation via patch on specified device
          text: >
            az iot central device attestation update
            --app-id {appid}
            --device-id {deviceid}
            --content {attestation}
    """

    helps[
        "iot central device attestation create"
    ] = """
        type: command
        short-summary: Create an individual device attestation.

        examples:
        - name: Create an individual device attestation on specified device
          text: >
            az iot central device attestation create
            --app-id {appid}
            --device-id {deviceid}
            --content {attestation}
    """

    helps[
        "iot central device list-components"
    ] = """
        type: command
        short-summary: List the components present in a device.

        examples:
        - name: List the components present in a device
          text: >
            az iot central device list-components
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device properties"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device properties.
    """

    helps[
        "iot central device properties show"
    ] = """
        type: command
        short-summary: Get all property values of a device by device ID.

        examples:
        - name: Get device properties
          text: >
            az iot central device properties show
            --app-id {appid}
            --device-id {deviceid}
    """

    helps[
        "iot central device properties replace"
    ] = """
        type: command
        short-summary: Replace all property values of a device by device ID.

        examples:
        - name: Replace device properties
          text: >
            az iot central device properties replace
            --app-id {appid}
            --device-id {deviceid}
            --content {json}
    """

    helps[
        "iot central device properties update"
    ] = """
        type: command
        short-summary: Update property values of a device by device ID.

        examples:
        - name: Update device properties via patch
          text: >
            az iot central device properties update
            --app-id {appid}
            --device-id {deviceid}
            --content {json}
    """

    helps[
        "iot central device telemetry"
    ] = """
        type: group
        short-summary: Query IoT Central devices telemetry value
    """

    helps[
        "iot central device telemetry show"
    ] = """
        type: command
        short-summary: Get the last telemetry value from a device.

        examples:
        - name:  Get device telemetry value.
          text: >
            az iot central device telemetry show
            --app-id {appid}
            --device-id {deviceid}
            --telemetry-name {telemetryname}
    """

    helps[
        "iot central device component-properties"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device component properties.
    """

    helps[
        "iot central device component-properties show"
    ] = """
        type: command
        short-summary: Get device properties for a specific component.

        examples:
        - name:  Get device properties for a specific component.
          text: >
            az iot central device component-properties show
            --app-id {appid}
            --device-id {deviceid}
            --component-name {componentname}
    """

    helps[
        "iot central device component-properties replace"
    ] = """
        type: command
        short-summary: Replace device properties for a specific component.

        examples:
        - name:  Replace device properties for a specific component.
          text: >
            az iot central device component-properties replace
            --app-id {appid}
            --device-id {deviceid}
            --component-name {componentname}
            --content {json}
    """

    helps[
        "iot central device component-properties update"
    ] = """
        type: command
        short-summary: Update device properties for a specific component via patch.

        examples:
        - name:  Update device properties for a specific component via patch.
          text: >
            az iot central device component-properties update
            --app-id {appid}
            --device-id {deviceid}
            --component-name {componentname}
            --content {json}
    """

    helps[
        "iot central device component-telemetry"
    ] = """
        type: group
        short-summary: Query IoT Central devices component telemetry value
    """

    helps[
        "iot central device component-telemetry show"
    ] = """
        type: command
        short-summary: Get component telemetry value.
        long-summary: Get the last telemetry value from a component.

        examples:
        - name:  Get component telemetry value.
          text: >
            az iot central device component-telemetry show
            --app-id {appid}
            --device-id {deviceid}
            --component-name {componentname}
            --telemetry-name {telemetryname}
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


def _load_central_c2d_message_help():
    helps[
        "iot central device c2d-message"
    ] = """
          type: group
          short-summary: Run device cloud-to-device messaging commands.
      """
    helps[
        "iot central device c2d-message purge"
    ] = """
        type: command
        short-summary: Purges the cloud-to-device message queue for the target device.
        long-summary: Purges the cloud-to-device message queue for the target device.

        examples:
        - name: Purges the cloud to device message queue for the target device.
          text: >
            az iot central device c2d-message purge
            --app-id {appid}
            --device-id {deviceid}
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
        "iot central user update"
    ] = """
        type: command
        short-summary: Update roles for a user in the application.
        long-summary: |
                    Update a user with a different roles.
                    Updating the tenantId or objectId for a service principal user is not allowed.
                    Updating the email address for an email user is not allowed.

        examples:
        - name: Update roles for a user by email or service principal in the application.
          text: >
            az iot central user update
            --user-id {userId}
            --app-id {appId}
            --roles "org1\\admin"
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
    short-summary: Get list of users for an IoT Central application
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
    short-summary: Get the list of API tokens associated with your IoT Central application.
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
        "iot central device-template list"
    ] = """
        type: command
        short-summary: Get the list of device templates for an IoT Central application.
        examples:
        - name: List all device templates in an application, sorted by template Id (default)
          text: >
            az iot central device-template list
            --app-id {appid}
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
        "iot central device-template update"
    ] = """
        type: command
        short-summary: Update a device template in IoT Central.

        examples:
        - name: Update a device template with payload read from a file
          text: >
            az iot central device-template update
            --app-id {appid}
            --content {pathtofile}
            --device-template-id {devicetemplateid}

        - name: Update a device template with payload read from raw json
          text: >
            az iot central device-template update
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


def _load_central_device_groups_help():
    helps[
        "iot central device-group"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device groups
    """

    helps[
        "iot central device-group list"
    ] = """
        type: command
        short-summary: Get the list of device groups for an IoT Central application.

        examples:
        - name: List device groups in an application
          text: >
            az iot central device-group list
            --app-id {appid}
    """

    helps[
        "iot central device-group show"
    ] = """
        type: command
        short-summary: Get the device group by ID.

        examples:
        - name: Get the device group by ID
          text: >
            az iot central device-group show
            --app-id {appid}
            --device-group-id {devicegroupid}
    """

    helps[
        "iot central device-group create"
    ] = """
        type: command
        short-summary: Create or update a device group.

        examples:
        - name: Create or update a device group.
          text: >
            az iot central device-group create
            --app-id {appid}
            --device-group-id {devicegroupid}
            --display-name {displayname}
            --filter {filter}
            --description {description}
            --organizations {organizations}
    """

    helps[
        "iot central device-group update"
    ] = """
        type: command
        short-summary: Update an existing device group by ID.

        examples:
        - name: Update a device group via patch
          text: >
            az iot central device-group update
            --app-id {appid}
            --device-group-id {devicegroupid}
            --display-name {displayname}
            --filter {filter}
            --description {description}
            --organizations {organizations}
    """

    helps[
        "iot central device-group delete"
    ] = """
        type: command
        short-summary: Delete a device group.

        examples:
        - name: Delete a device group
          text: >
            az iot central device-group delete
            --app-id {appid}
            --device-group-id {devicegroupid}
    """


def _load_central_file_upload_configuration_help():
    helps[
        "iot central file-upload-config"
    ] = """
          type: group
          short-summary: Manage and configure IoT Central file upload
      """

    helps[
        "iot central file-upload-config show"
    ] = """
    type: command
    short-summary: Get the details of file upload storage account configuration
    examples:
      - name: Get details of file upload configuration
        text: >
          az iot central file-upload-config show
          --app-id {appid}
    """

    helps[
        "iot central file-upload-config delete"
    ] = """
    type: command
    short-summary: Delete file upload storage account configuration
    examples:
      - name: Delete file upload
        text: >
          az iot central file-upload-config delete
          --app-id {appid}
    """

    helps[
        "iot central file-upload-config create"
    ] = """
    type: command
    short-summary: Create file upload storage account configuration
    examples:
      - name: Create file upload
        text: >
          az iot central file-upload-config create
          --app-id {appid}
          --connection-string {conn_string}
          --container {container}
    """

    helps[
        "iot central file-upload-config update"
    ] = """
    type: command
    short-summary: Update file upload storage account configuration
    examples:
      - name: Update file upload
        text: >
          az iot central file-upload-config update
          --app-id {appid}
          --container {container}
    """


def _load_central_roles_help():
    helps[
        "iot central role"
    ] = """
        type: group
        short-summary: Manage and configure roles for an IoT Central application.
    """

    helps[
        "iot central role list"
    ] = """
        type: command
        short-summary: Get the list of roles for an IoT Central application.

        examples:
        - name: List roles in an application
          text: >
            az iot central role list
            --app-id {appid}
    """

    helps[
        "iot central role show"
    ] = """
    type: command
    short-summary: Get the details of a role by ID.
    examples:
      - name: Get details of role
        text: >
          az iot central role show
          --app-id {appid}
          --role-id {roleId}
    """


def _load_central_organizations_help():
    helps[
        "iot central organization"
    ] = """
        type: group
        short-summary: Manage and configure organizations for an IoT Central application.
    """

    helps[
        "iot central organization list"
    ] = """
        type: command
        short-summary: Get the list of organizations for an IoT Central application.

        examples:
        - name: List organizations in an application
          text: >
            az iot central organization list
            --app-id {appid}
    """

    helps[
        "iot central organization show"
    ] = """
    type: command
    short-summary: Get the details of a organization by ID.
    examples:
      - name: Get details of organization
        text: >
          az iot central organization show
          --app-id {appid}
          --org-id {organizationId}
    """

    helps[
        "iot central organization delete"
    ] = """
    type: command
    short-summary: Delete an organization by ID.
    examples:
      - name: Delete an organization
        text: >
          az iot central organization delete
          --app-id {appid}
          --org-id {organizationId}
    """

    helps[
        "iot central organization create"
    ] = """
    type: command
    short-summary: Create an organization in the application.
    examples:
      - name: Create an organization
        text: >
          az iot central organization create
          --app-id {appid}
          --org-id {organizationId}

      - name: Create an organization, child of a parent one in the application.
        text: >
          az iot central organization create
          --app-id {appid}
          --org-id {organizationId}
          --parent-id {parentId}
        """

    helps[
        "iot central organization update"
    ] = """
    type: command
    short-summary: Update an organization in the application.
    examples:
      - name: Update parent of an organization
        text: >
          az iot central organization update
          --app-id {appid}
          --org-id {organizationId}
          --parent-id {parentId}

      - name: Update name of an organization
        text: >
          az iot central organization update
          --app-id {appid}
          --org-id {organizationId}
          --org-name {organizationName}
        """


def _load_central_jobs_help():
    helps[
        "iot central job"
    ] = """
        type: group
        short-summary: Manage and configure jobs for an IoT Central application.
    """

    helps[
        "iot central job list"
    ] = """
        type: command
        short-summary: Get the list of jobs for an IoT Central application.

        examples:
        - name: List jobs in an application
          text: >
            az iot central job list
            --app-id {appid}
    """

    helps[
        "iot central job create"
    ] = """
    type: command
    short-summary: Create and execute a job via its job definition.
    examples:
      - name: Create a job with name
        text: >
          az iot central job create
          --app-id {appid}
          --job-id {jobId}
          --group-id {groupId}
          --job-name {jobName}
          --content {creationJSONPath}

      - name: Create a job with name and batch configuration.
        text: >
          az iot central job create
          --app-id {appid}
          --job-id {jobId}
          --group-id {groupId}
          --job-name {jobName}
          --content {creationJSONPath}
          --batch {jobBatchValue}
          --batch-type {jobBatchType}

      - name: Create a job with name and cancellation threshold configuration with no batch.
        text: >
          az iot central job create
          --app-id {appid}
          --job-id {jobId}
          --group-id {groupId}
          --job-name {jobName}
          --content {creationJSONPath}
          --cancellation-threshold {jobCancellationThresholdValue}
          --cancellation-threshold-type {jobCancellationThresholdType}
          --description {jobDesc}
    """

    helps[
        "iot central job show"
    ] = """
    type: command
    short-summary: Get the details of a job by ID.
    examples:
      - name: Get details of job
        text: >
          az iot central job show
          --app-id {appid}
          --job-id {jobId}
    """

    helps[
        "iot central job stop"
    ] = """
    type: command
    short-summary: Stop a running job.
    examples:
      - name: Stop a job
        text: >
          az iot central job stop
          --app-id {appid}
          --job-id {jobId}
    """

    helps[
        "iot central job resume"
    ] = """
    type: command
    short-summary: Resume a stopped job.
    examples:
      - name: Resume a job
        text: >
          az iot central job resume
          --app-id {appid}
          --job-id {jobId}
    """

    helps[
        "iot central job rerun"
    ] = """
    type: command
    short-summary: Re-run a job on all failed devices.
    examples:
      - name: Rerun a job
        text: >
          az iot central job rerun
          --app-id {appid}
          --job-id {jobId}
          --rerun-id {rerunId}
    """

    helps[
        "iot central job get-devices"
    ] = """
    type: command
    short-summary: Get job device statuses.
    examples:
      - name: Get the list of individual device statuses by job ID
        text: >
          az iot central job get-devices
          --app-id {appid}
          --job-id {jobId}
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


def _load_central_edge_help():
    helps[
        "iot central device edge"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central edge devices
    """

    helps[
        "iot central device edge module"
    ] = """
        type: group
        short-summary: Manage IoT Edge device modules.
    """

    helps[
        "iot central device edge children"
    ] = """
        type: group
        short-summary: Manage IoT Edge device children devices.
    """

    helps[
        "iot central device edge manifest"
    ] = """
        type: group
        short-summary: Manage IoT Edge device manifests.
    """

    helps[
        "iot central device edge module list"
    ] = """
        type: command
        short-summary: Get the list of modules in an IoT Edge device.
        examples:
        - name: List all modules in a device. (default)
          text: >
            az iot central device edge module list
            --app-id {appid}
            --device-id {deviceId}
    """

    helps[
        "iot central device edge module restart"
    ] = """
        type: command
        short-summary: Restart a module in an IoT Edge device.
        examples:
        - name: Restart a module in a device.
          text: >
            az iot central device edge module restart
            --app-id {appid}
            --device-id {deviceId}
            --module-id {moduleId}
    """

    helps[
        "iot central device edge module show"
    ] = """
        type: command
        short-summary: Get a module in an IoT Edge device.
        examples:
        - name: Get a module in a device.
          text: >
            az iot central device edge module show
            --app-id {appid}
            --device-id {deviceId}
            --module-id {moduleId}
    """

    helps[
        "iot central device edge module list-components"
    ] = """
        type: command
        short-summary: List the components present in a module.
        examples:
        - name: List the components present in a module.
          text: >
            az iot central device edge module list-components
            --app-id {appid}
            --device-id {deviceId}
            --module-name {moduleName}
    """

    helps[
        "iot central device edge module properties"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device properties in a module.
    """

    helps[
        "iot central device edge module component-properties"
    ] = """
        type: group
        short-summary: Manage and configure IoT Central device component properties in a module.
    """

    helps[
        "iot central device edge module component-properties show"
    ] = """
        type: command
        short-summary: Get module properties for a specific component.
        examples:
        - name: Get module properties for a specific component.
          text: >
            az iot central device edge module component-properties show
            --app-id {appid}
            --device-id {deviceId}
            --component-name {componentName}
            --module-name {moduleName}
    """

    helps[
        "iot central device edge module component-properties update"
    ] = """
        type: command
        short-summary: Update module properties for a specific component via patch.

        examples:
        - name: Update module properties for a specific component via patch.
          text: >
            az iot central device edge module component-properties update
            --app-id {appid}
            --device-id {deviceId}
            --component-name {componentName}
            --module-name {moduleName}
            --content {json}
    """

    helps[
        "iot central device edge module component-properties replace"
    ] = """
        type: command
        short-summary: Replace module properties for a specific component.

        examples:
        - name: Replace module properties for a specific component.
          text: >
            az iot central device edge module component-properties replace
            --app-id {appid}
            --device-id {deviceId}
            --component-name {componentName}
            --module-name {moduleName}
            --content {json}
    """

    helps[
        "iot central device edge module component-telemetry"
    ] = """
        type: group
        short-summary: Query IoT Edge device component telemetry value.
    """

    helps[
        "iot central device edge module component-telemetry show"
    ] = """
        type: command
        short-summary: Get the last telemetry value from a module component.
        examples:
        - name: Get module component telemetry value.
          text: >
            az iot central device edge module component-telemetry show
            --app-id {appid}
            --device-id {deviceId}
            --component-name {componentName}
            --module-name {moduleName}
            --telemetry-name {telemetryName}
    """

    helps[
        "iot central device edge module properties show"
    ] = """
        type: command
        short-summary: Get all property values of a module.
        examples:
        - name: Get module properties.
          text: >
            az iot central device edge module properties show
            --app-id {appid}
            --device-id {deviceId}
            --module-name {moduleName}
    """

    helps[
        "iot central device edge module properties update"
    ] = """
        type: command
        short-summary: Update property values of a module.
        examples:
        - name: Update module properties via patch.
          text: >
            az iot central device edge module properties update
            --app-id {appid}
            --device-id {deviceId}
            --module-name {moduleName}
            --content {json}
    """

    helps[
        "iot central device edge module properties replace"
    ] = """
        type: command
        short-summary: Replace all property values of a module.
        examples:
        - name: Replace module properties.
          text: >
            az iot central device edge module properties replace
            --app-id {appid}
            --device-id {deviceId}
            --module-name {moduleName}
            --content {json}
    """

    helps[
        "iot central device edge module telemetry"
    ] = """
        type: group
        short-summary: Query IoT Edge device telemetry value.
    """

    helps[
        "iot central device edge module telemetry show"
    ] = """
        type: command
        short-summary: Get the last telemetry value from a module.
        examples:
        - name: Get module telemetry value.
          text: >
            az iot central device edge module telemetry show
            --app-id {appid}
            --device-id {deviceId}
            --module-name {moduleName}
            --telemetry-name {telemetryName}
    """

    helps[
        "iot central device edge module command"
    ] = """
        type: group
        short-summary: Run module commands.
    """

    helps[
        "iot central device edge module command run"
    ] = """
            type: command
            short-summary: Run a module command.
            long-summary: |
                Note: payload should be nested under "request".
                i.e. if your device expects the payload in a shape {"key": "value"}
                payload should be {"request": {"key": "value"}}.
                --content can also be pointed at a filepath like this (.../path/to/payload.json)
            examples:
            - name: Run a module command
              text: >
                az iot central device edge module command run
                --app-id {appid}
                --device-id {deviceid}
                --module-name {modulename}
                --component-name {componentname}
                --command-name {commandname}
                --content {payload}
        """

    helps[
        "iot central device edge module command history"
    ] = """
            type: command
            short-summary: Get module command history.
            examples:
            - name: Get module command history
              text: >
                az iot central device edge module command history
                --app-id {appid}
                --device-id {deviceid}
                --module-name {modulename}
                --command-name {commandname}
        """

    helps[
        "iot central device edge module command component-history"
    ] = """
            type: command
            short-summary: Get module component command history.
            examples:
            - name: Get module component command history
              text: >
                az iot central device edge module command component-history
                --app-id {appid}
                --device-id {deviceid}
                --module-name {modulename}
                --component-name {componentname}
                --command-name {commandname}
        """

    helps[
        "iot central device edge manifest show"
    ] = """
        type: command
        short-summary: Get the deployment manifest associated to the specified IoT Edge device.
        examples:
        - name: Get a deployment manifest.
          text: >
            az iot central device edge manifest show
            --app-id {appid}
            --device-id {deviceId}
    """

    helps[
        "iot central device edge children list"
    ] = """
        type: command
        short-summary: Get the list of children of an IoT Edge device.
        examples:
        - name: List all children of a device.
          text: >
            az iot central device edge children list
            --app-id {appid}
            --device-id {deviceId}
    """

    helps[
        "iot central device edge children add"
    ] = """
        type: command
        short-summary: Add devices as children to a target edge device.
        examples:
        - name: Add space-separated list of device Ids as children to the target edge device.
          text: >
            az iot central device edge children add
            --app-id {appid}
            --device-id {deviceId}
            --children-ids {child_1} {child_2}
    """

    helps[
        "iot central device edge children remove"
    ] = """
        type: command
        short-summary: Remove child devices from a target edge device.
        examples:
        - name: Remove children.
          text: >
            az iot central device edge children remove
            --app-id {appid}
            --device-id {deviceId}
            --children-ids {child_1} {child_2}
    """
