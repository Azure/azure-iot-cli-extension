# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for CLI.
"""

from knack.help_files import helps


helps[
    "iot"
] = """
    type: group
    short-summary: Manage Internet of Things (IoT) assets.
                   Augmented with the IoT extension.
    long-summary: |
                  Review the extension wiki tips to maximize usage
                  https://github.com/Azure/azure-iot-cli-extension/wiki/Tips
"""

helps[
    "iot hub"
] = """
    type: group
    short-summary: Manage entities in an Azure IoT Hub.
"""

helps[
    "iot hub monitor-events"
] = """
    type: command
    short-summary: Monitor device telemetry & messages sent to an IoT Hub.
    long-summary: |
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python
    examples:
    - name: Basic usage
      text: >
        az iot hub monitor-events -n {iothub_name}
    - name: Basic usage with an IoT Hub connection string
      text: >
        az iot hub monitor-events -n {iothub_name}
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Basic usage when filtering on target device
      text: >
        az iot hub monitor-events -n {iothub_name} -d {device_id}
    - name: Basic usage when filtering targeted devices with a wildcard in the ID
      text: >
        az iot hub monitor-events -n {iothub_name} -d Device*
    - name: Filter devices using IoT Hub query language
      text: >
        az iot hub monitor-events -n {iothub_name} -q "select * from devices where tags.location.region = 'US'"
    - name: Filter device and specify an Event Hub consumer group to bind to.
      text: >
        az iot hub monitor-events -n {iothub_name} -d {device_id} --cg {consumer_group_name}
    - name: Receive message annotations (message headers)
      text: >
        az iot hub monitor-events -n {iothub_name} -d {device_id} --properties anno
    - name: Receive message annotations + system properties. Never time out.
      text: >
        az iot hub monitor-events -n {iothub_name} -d {device_id} --properties anno sys --timeout 0
    - name: Receive all message attributes from all device messages
      text: >
        az iot hub monitor-events -n {iothub_name} --props all
    - name: Receive all messages and parse message payload as JSON
      text: >
        az iot hub monitor-events -n {iothub_name} --content-type application/json
"""

helps[
    "iot hub monitor-feedback"
] = """
    type: command
    short-summary: Monitor feedback sent by devices to acknowledge cloud-to-device (C2D) messages.
    long-summary: |
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python
    examples:
    - name: Basic usage
      text: >
        az iot hub monitor-feedback -n {iothub_name}
    - name: Basic usage with an IoT Hub connection string
      text: >
        az iot hub monitor-feedback -n {iothub_name}
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Basic usage when filtering on target device
      text: >
        az iot hub monitor-feedback -n {iothub_name} -d {device_id}
    - name: Exit feedback monitor upon receiving a message with specific id (uuid)
      text: >
        az iot hub monitor-feedback -n {iothub_name} -d {device_id} -w {message_id}
"""

helps[
    "iot hub connection-string"
] = """
    type: group
    short-summary: Manage IoT Hub connection strings.
"""

helps[
    "iot hub connection-string show"
] = """
    type: command
    short-summary: Show the connection strings for the specified IoT Hubs using the given policy name and key.
    examples:
    - name: Show the connection strings for all active state IoT Hubs in a subscription using the default policy and primary key.
      text: >
          az iot hub connection-string show
    - name: Show the connection strings for all active state IoT Hubs in a resource group using the default policy and primary key.
      text: >
          az iot hub connection-string show --resource-group MyResourceGroup
    - name: Show all connection strings of the given IoT Hub using primary key.
      text: >
          az iot hub connection-string show -n MyIotHub --all
    - name: Show the connection string of the given IoT Hub using the default policy and primary key.
      text: >
          az iot hub connection-string show -n MyIotHub
    - name: Show the connection string of the given IoT Hub using policy 'service' and secondary key.
      text: >
          az iot hub connection-string show -n MyIotHub --policy-name service --key-type secondary
    - name: Show the eventhub compatible connection string of the given IoT Hub\'s default eventhub.
      text: >
          az iot hub connection-string show -n MyIotHub --default-eventhub
"""

helps[
    "iot hub device-identity"
] = """
    type: group
    short-summary: Manage IoT devices.
"""

helps[
    "iot hub device-identity create"
] = """
    type: command
    short-summary: Create a device in an IoT Hub.
    long-summary: |
                  When using the auth method of shared_private_key (also known as symmetric keys),
                  if no custom keys are provided the service will generate them for the device.

                  If a device scope is provided for an edge device, the value will automatically be
                  converted to a parent scope.
    examples:
    - name: Create an edge enabled IoT device with default authorization (shared private key).
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --ee
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert valid for 10 days then use its thumbprint.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id}
        --am x509_thumbprint --valid-days 10
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert of default expiration (365 days) and output to target directory.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --am x509_thumbprint
        --output-dir /path/to/output
    - name: Create an IoT device with self-signed certificate authorization and
            explicitly provide primary and secondary thumbprints.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --am x509_thumbprint
        --ptp {thumbprint_1} --stp {thumbprint_2}
    - name: Create an IoT device with root CA authorization with disabled status and reason.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --am x509_ca
        --status disabled --status-reason 'for reasons'
    - name: Create an IoT device with a device scope.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --device-scope 'ms-azure-iot-edge://edge0-123456789123456789'
"""

helps[
    "iot hub device-identity show"
] = """
    type: command
    short-summary: Get the details of an IoT Hub device.
"""

helps[
    "iot hub device-identity list"
] = """
    type: command
    short-summary: List devices in an IoT Hub.
"""

helps[
    "iot hub device-identity update"
] = """
    type: command
    short-summary: Update an IoT Hub device.
    long-summary: Use --set followed by property assignments for updating a device.
                  Leverage parameters returned from 'iot hub device-identity show'.
    examples:
    - name: Turn on edge capabilities for device
      text: >
        az iot hub device-identity update -d {device_id} -n {iothub_name}
        --set capabilities.iotEdge=true
    - name: Turn on edge capabilities for device using convenience argument.
      text: >
        az iot hub device-identity update -d {device_id} -n {iothub_name} --ee
    - name: Disable device status
      text: >
        az iot hub device-identity update -d {device_id} -n {iothub_name} --set status=disabled
    - name: Disable device status using convenience argument.
      text: >
        az iot hub device-identity update -d {device_id} -n {iothub_name} --status disabled
    - name: In one command
      text: >
        az iot hub device-identity update -d {device_id} -n {iothub_name}
        --set status=disabled capabilities.iotEdge=true
"""

helps[
    "iot hub device-identity renew-key"
] = """
    type: command
    short-summary: Renew target keys of an IoT Hub device with sas authentication.
    examples:
      - name: Renew the primary key.
        text: az iot hub device-identity renew-key -d {device_id} -n {iothub_name} --kt primary
      - name: Swap the primary and secondary keys.
        text: az iot hub device-identity renew-key -d {device_id} -n {iothub_name} --kt swap
"""

helps[
    "iot hub device-identity delete"
] = """
    type: command
    short-summary: Delete an IoT Hub device.
"""

helps[
    "iot hub device-identity connection-string"
] = """
    type: group
    short-summary: Manage IoT device\'s connection string.
"""

helps[
    "iot hub device-identity connection-string show"
] = """
    type: command
    short-summary: Show a given IoT Hub device connection string.
"""

helps[
    "iot hub device-identity export"
] = """
    type: command
    short-summary: Export all device identities from an IoT Hub to an Azure Storage blob container. For inline
                   blob container SAS uri input, please review the input rules of your environment.
    long-summary: For more information, see
                  https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-identity-registry#import-and-export-device-identities
    examples:
    - name: Export all device identities to a configured blob container and include device keys. Uses an inline SAS uri example.
      text: >
        az iot hub device-identity export -n {iothub_name} --ik --bcu
        'https://mystorageaccount.blob.core.windows.net/devices?sv=2019-02-02&st=2020-08-23T22%3A35%3A00Z&se=2020-08-24T22%3A35%3A00Z&sr=c&sp=rwd&sig=VrmJ5sQtW3kLzYg10VqmALGCp4vtYKSLNjZDDJBSh9s%3D'
    - name: Export all device identities to a configured blob container using a file path which contains the SAS uri.
      text: >
        az iot hub device-identity export -n {iothub_name} --bcu {sas_uri_filepath}
    - name: Export all device identities to a configured blob container and include device keys. Uses system assigned identity that has
            Storage Blob Data Contributor roles for the storage account. The blob container uri does not need the blob SAS token.
      text: >
        az iot hub device-identity export -n {iothub_name} --ik --bcu
        'https://mystorageaccount.blob.core.windows.net/devices' --auth-type identity --identity [system]
    - name: Export all device identities to a configured blob container and include device keys. Uses user assigned managed identity
            that has Storage Blob Data Contributor roles for the storage account and contributor for the IoT hub. The blob container
            uri does not need the blob SAS token.
      text: >
        az iot hub device-identity export -n {iothub_name} --ik --bcu
        'https://mystorageaccount.blob.core.windows.net/devices' --auth-type identity --identity {managed_identity_resource_id}
"""

helps[
    "iot hub device-identity import"
] = """
    type: command
    short-summary: Import device identities to an IoT Hub from a blob. For inline
                   blob container SAS uri input, please review the input rules of your environment.
    long-summary: For more information, see
                  https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-identity-registry#import-and-export-device-identities
    examples:
    - name: Import all device identities from a blob using an inline SAS uri.
      text: >
        az iot hub device-identity import -n {iothub_name} --ibcu {input_sas_uri} --obcu {output_sas_uri}
    - name: Import all device identities from a blob using a file path which contains SAS uri.
      text: >
        az iot hub device-identity import -n {iothub_name} --ibcu {input_sas_uri_filepath} --obcu {output_sas_uri_filepath}
    - name: Import all device identities from a blob using system assigned identity that has Storage Blob Data Contributor
            roles for both storage accounts. The blob container uri does not need the blob SAS token.
      text: >
        az iot hub device-identity import -n {iothub_name} --ibcu {input_sas_uri} --obcu {output_sas_uri} --auth-type identity --identity [system]
    - name: Import all device identities from a blob using user assigned managed identity that has Storage Blob Data Contributor
            roles for both storage accounts and contributor for the IoT hub. The blob container uri does not need the blob SAS token.
      text: >
        az iot hub device-identity import -n {iothub_name} --ibcu {input_sas_uri} --obcu {output_sas_uri}
        --auth-type identity --identity {managed_identity_resource_id}
"""

helps[
    "iot hub device-identity parent"
] = """
    type: group
    short-summary: Manage parent device relationships for IoT devices.
"""

helps[
    "iot hub device-identity parent show"
] = """
    type: command
    short-summary: Get the parent device of a target device.
    examples:
    - name: Get the parent device of a target device.
      text: >
        az iot hub device-identity parent show -d {device_id} -n {iothub_name}
"""

helps[
    "iot hub device-identity parent set"
] = """
    type: command
    short-summary: Set the parent device of a target device.
    examples:
    - name: Set the parent device of a target device.
      text: >
        az iot hub device-identity parent set -d {device_id} --pd {edge_device_id} -n {iothub_name}
    - name: Set the parent device of a target device and overwrite the existing parent.
      text: >
        az iot hub device-identity parent set -d {device_id} --pd {edge_device_id} -n {iothub_name} --force
"""

helps[
    "iot hub device-identity children"
] = """
    type: group
    short-summary: Manage children device relationships for IoT edge devices.
"""

helps[
    "iot hub device-identity children add"
] = """
    type: command
    short-summary: Add devices as children to a target edge device.
    examples:
    - name: Add a space-separated list of device Ids as children to the target edge device.
      text: >
        az iot hub device-identity children add -d {edge_device_id} --child-list {child_device_id_1} {child_device_id_2}
        -n {iothub_name}
    - name: Add devices as children to the edge device and overwrite the children devices' existing parent.
      text: >
        az iot hub device-identity children add -d {edge_device_id} --child-list {child_device_id_1} {child_device_id_2}
        -n {iothub_name} -f
"""

helps[
    "iot hub device-identity children list"
] = """
    type: command
    short-summary: Outputs the collection of assigned child devices.
    examples:
    - name: List all assigned children devices.
      text: >
        az iot hub device-identity children list -d {edge_device_id} -n {iothub_name}
    - name: List all assigned children devices whose device Id contains a substring of 'test'.
      text: >
        az iot hub device-identity children list -d {edge_device_id} -n {iothub_name} --query "[?contains(@,'test')]"
"""

helps[
    "iot hub device-identity children remove"
] = """
    type: command
    short-summary: Remove child devices from a target edge device.
    examples:
    - name: Remove a space-seperated list of child devices from a target parent device.
      text: >
        az iot hub device-identity children remove -d {edge_device_id} --child-list {space_separated_device_id}
        -n {iothub_name}
    - name: Remove all child devices from a target parent device.
      text: >
        az iot hub device-identity children remove -d {edge_device_id} --remove-all
"""

helps[
    "iot hub device-twin"
] = """
    type: group
    short-summary: Manage IoT device twin configuration.
"""

helps[
    "iot hub device-twin show"
] = """
    type: command
    short-summary: Get a device twin definition.
"""

helps[
    "iot hub device-twin update"
] = """
    type: command
    short-summary: Update device twin desired properties and tags.
    long-summary: Provide --desired or --tags arguments for PATCH behavior. Both parameters
                  support inline json or a file path to json content.

                  Usage of generic update args (i.e. --set) will reflect PUT behavior
                  and are deprecated.
    examples:
    - name: Patch device twin desired properties.
      text: >
        az iot hub device-twin update -n {iothub_name} -d {device_id}
        --desired '{"conditions":{"temperature":{"warning":70, "critical":100}}}'
    - name: Patch device twin tags.
      text: >
        az iot hub device-twin update -n {iothub_name} -d {device_id}
        --tags '{"country": "USA"}'
    - name: Patch device twin tags with json file content.
      text: >
        az iot hub device-twin update -n {iothub_name} -d {device_id}
        --tags /path/to/file
    - name: Patch removal of 'critical' desired property from parent 'temperature'
      text: >
        az iot hub device-twin update -n {iothub_name} -d {device_id}
        --desired '{"condition":{"temperature":{"critical": null}}}'
"""

helps[
    "iot hub device-twin replace"
] = """
    type: command
    short-summary: Replace device twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace device twin with file contents.
      text: >
        az iot hub device-twin replace -d {device_id} -n {iothub_name} -j ../mydevicetwin.json
"""

helps[
    "iot hub module-identity"
] = """
    type: group
    short-summary: Manage IoT device modules.
"""

helps[
    "iot hub module-identity create"
] = """
    type: command
    short-summary: Create a module on a target IoT device in an IoT Hub.
    long-summary: |
                  When using the auth method of shared_private_key (also known as symmetric keys),
                  if no custom keys are provided the service will generate them for the module.
"""

helps[
    "iot hub module-identity show"
] = """
    type: command
    short-summary: Get the details of an IoT device module in an IoT Hub.
"""

helps[
    "iot hub module-identity list"
] = """
    type: command
    short-summary: List modules located on an IoT device in an IoT Hub.
"""

helps[
    "iot hub module-identity update"
] = """
    type: command
    short-summary: Update an IoT Hub device module.
    long-summary: Use --set followed by property assignments for updating a module.
                  Leverage properties returned from 'iot hub module-identity show'.
    examples:
    - name: Regenerate module symmetric authentication keys
      text: >
        az iot hub module-identity update -m {module_name} -d {device_id} -n {iothub_name}
        --set authentication.symmetricKey.primaryKey=""
        authentication.symmetricKey.secondaryKey=""
"""

helps[
    "iot hub module-identity renew-key"
] = """
    type: command
    short-summary: Renew target keys of an IoT Hub device module with sas authentication.
    examples:
      - name: Renew the primary key.
        text: az iot hub module-identity renew-key -m {module_name} -d {device_id} -n {iothub_name} --kt primary
      - name: Swap the primary and secondary keys.
        text: az iot hub module-identity renew-key -m {module_name} -d {device_id} -n {iothub_name} --kt swap
"""

helps[
    "iot hub module-identity delete"
] = """
    type: command
    short-summary: Delete a device in an IoT Hub.
"""

helps[
    "iot hub module-identity connection-string"
] = """
    type: group
    short-summary: Manage IoT device module\'s connection string.
"""

helps[
    "iot hub module-identity connection-string show"
] = """
    type: command
    short-summary: Show a target IoT device module connection string.
"""

helps[
    "iot hub module-twin"
] = """
    type: group
    short-summary: Manage IoT device module twin configuration.
"""

helps[
    "iot hub module-twin show"
] = """
    type: command
    short-summary: Show a module twin definition.
"""

helps[
    "iot hub module-twin update"
] = """
    type: command
    short-summary: Update module twin desired properties and tags.
    long-summary: Provide --desired or --tags arguments for PATCH behavior. Both parameters
                  support inline json or a file path to json content.

                  Usage of generic update args (i.e. --set) will reflect PUT behavior
                  and are deprecated.
    examples:
    - name: Patch module twin desired properties.
      text: >
        az iot hub module-twin update -n {iothub_name} -d {device_id} -m {module_id}
        --desired '{"conditions":{"temperature":{"warning":70, "critical":100}}}'
    - name: Patch module twin tags.
      text: >
        az iot hub module-twin update -n {iothub_name} -d {device_id} -m {module_id}
        --tags '{"country": "USA"}'
    - name: Patch module twin tags with json file content.
      text: >
        az iot hub module-twin update -n {iothub_name} -d {device_id} -m {module_id}
        --tags /path/to/file
    - name: Patch removal of 'critical' desired property from parent 'temperature'
      text: >
        az iot hub module-twin update -n {iothub_name} -d {device_id} -m {module_id}
        --desired '{"condition":{"temperature":{"critical": null}}}'
"""

helps[
    "iot hub module-twin replace"
] = """
    type: command
    short-summary: Replace a module twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace a module twin with file contents.
      text: >
        az iot hub module-twin replace -d {device_id} -n {iothub_name}
        -m {module_name} -j ../mymodtwin.json
"""

helps[
    "iot hub state"
] = """
    type: group
    short-summary: Manage the state of an IoT Hub.
"""

helps[
    "iot hub state export"
] = """
    type: command
    short-summary: Export the state of an IoT Hub to a file.
    long-summary: The exported state will include hub configurations, edge deployments, device identities and twins, and module
                  identities and twins.
    examples:
    - name: Export the state of the specified hub to the specified file.
      text: >
        az iot hub state export -n {iothub_name} -f {filename}
    - name: Export the state of the specified hub to the specified file, overwriting the file contents.
      text: >
        az iot hub state export -n {iothub_name} -f {filename} --of
"""

helps[
    "iot hub state import"
] = """
    type: command
    short-summary: Import a Hub state from a file to an IoT Hub.
    long-summary: The imported state will include hub configurations, edge deployments, device identities and twins, and module
                  identities and twins.
    examples:
    - name: Import the state from the specified file to the specified hub.
      text: >
        az iot hub state import -n {iothub_name} -f {filename}
    - name: Import the state from the default file to the specified hub, overwriting the previous state of the hub.
      text: >
        az iot hub state import -n {iothub_name} -f {filename} -r
"""

helps[
    "iot hub state migrate"
] = """
    type: command
    short-summary: Copy the state of one hub to another hub without saving to a file.
    long-summary: The migrated state will include hub configurations, edge deployments, device identities and twins, and module
                  identities and twins.
    examples:
    - name: Migrate the state of the original hub to the destination hub.
      text: >
        az iot hub state migrate --destination-hub {dest_hub_name} --origin-hub {orig_hub_name}
    - name: Migrate the state of the original hub to the destination hub, overwriting the previous state of the hub.
      text: >
        az iot hub state migrate --destination-hub {dest_hub_name} --origin-hub {orig_hub_name} -r
"""

helps[
    "iot hub generate-sas-token"
] = """
    type: command
    short-summary: Generate a SAS token for a target IoT Hub, device or module.
    long-summary: For device SAS tokens, the policy parameter is used to
                  access the the device registry only. Therefore the policy should have
                  read access to the registry. For IoT Hub tokens the policy is part of the SAS.
    examples:
    - name: Generate an IoT Hub SAS token using the iothubowner policy and primary key.
      text: >
        az iot hub generate-sas-token -n {iothub_name}
    - name: Generate an IoT Hub SAS token using the registryRead policy and secondary key.
      text: >
        az iot hub generate-sas-token -n {iothub_name} --policy registryRead --key-type secondary
    - name: Generate a device SAS token using the iothubowner policy to access the {iothub_name} device registry.
      text: >
        az iot hub generate-sas-token -d {device_id} -n {iothub_name}
    - name: Generate a device SAS token using an IoT Hub connection string (with registry access)
      text: >
        az iot hub generate-sas-token -d {device_id}
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Generate an Iot Hub SAS token using an IoT Hub connection string
      text: >
        az iot hub generate-sas-token
        --connection-string 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Generate a Device SAS token using a Device connection string
      text: >
        az iot hub generate-sas-token --connection-string
        'HostName=myhub.azure-devices.net;DeviceId=mydevice;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Generate a Module SAS token using a Module connection string
      text: >
        az iot hub generate-sas-token --connection-string
        'HostName=myhub.azure-devices.net;DeviceId=mydevice;ModuleId=mymodule;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
"""

helps[
    "iot hub invoke-module-method"
] = """
    type: command
    short-summary: Invoke an Edge module method.
    examples:
    - name: Invoke a direct method on edge device using a module from the cloud.
      text: >
        az iot hub invoke-module-method -n {iothub_name} -d {device_id}
        -m '$edgeAgent' --method-name 'RestartModule' --method-payload '{"schemaVersion": "1.0"}'
"""

helps[
    "iot hub invoke-device-method"
] = """
    type: command
    short-summary: Invoke a device method.
    examples:
    - name: Invoke a direct method on device from the cloud.
      text: >
        az iot hub invoke-device-method --hub-name {iothub_name} --device-id {device_id}
        --method-name Reboot --method-payload '{"version":"1.0"}'
"""

helps[
    "iot hub query"
] = """
    type: command
    short-summary: Query an IoT Hub using a powerful SQL-like language.
    long-summary: Query an IoT Hub using a powerful SQL-like language to retrieve information
                  regarding device and module twins, jobs and message routing.
                  See https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-query-language
                  for more information.
    examples:
    - name: Query all device twin data in an Azure IoT Hub.
      text: >
        az iot hub query -n {iothub_name} -q "select * from devices"
    - name: Query all module twin data on target device.
      text: >
        az iot hub query -n {iothub_name} -q "select * from devices.modules where devices.deviceId = '{device_id}'"
"""

helps[
    "iot hub configuration"
] = """
    type: group
    short-summary: Manage IoT automatic device management configuration at scale.
"""

helps[
    "iot hub configuration create"
] = """
    type: command
    short-summary: Create an IoT automatic device management configuration in a target IoT Hub.
    long-summary: |
                  Configuration content is json and slighty varies based on device or module intent.

                  Device configurations are in the form of {"deviceContent":{...}} or {"content":{"deviceContent":{...}}}

                  Module configurations are in the form of {"moduleContent":{...}} or {"content":{"moduleContent":{...}}}

                  Configurations can be defined with user provided metrics for on demand evaluation.
                  User metrics are json and in the form of {"queries":{...}} or {"metrics":{"queries":{...}}}.

                  Note: Target condition for modules must start with "from devices.modules where".
    examples:
    - name: Create a device configuration with a priority of 3 that applies on condition when a device is
            tagged in building 9 and the environment is 'test'.
      text: >
        az iot hub configuration create -c {config_name} -n {iothub_name} --content device_content.json
        --target-condition "tags.building=9 and tags.environment='test'" --priority 3
    - name: Create a device configuration with labels and provide user metrics inline (bash syntax example)
      text: >
        az iot hub configuration create -c {config_name} -n {iothub_name} --content device_content.json
        --target-condition "tags.building=9" --labels '{"key0":"value0", "key1":"value1"}' --priority 10
        --metrics '{"metrics": {"queries": {"mymetric": "select deviceId from devices where tags.location='US'"}}}'
    - name: Create a module configuration with labels and provide user metrics inline (cmd syntax example)
      text: >
        az iot hub configuration create -c {config_name} -n {iothub_name} --content module_content.json
        --target-condition "from devices.modules where tags.building=9" --labels "{\\"key0\\":\\"value0\\", \\"key1\\":\\"value1\\"}"
        --metrics "{\\"metrics\\": {\\"queries\\": {\\"mymetric\\": \\"select moduleId from devices.modules where tags.location='US'\\"}}}"
    - name: Create a module configuration with content and user metrics inline (powershell syntax example)
      text: >
        az iot hub configuration create -c {config_name} -n {iothub_name}
        --content '{\\"moduleContent\\": {\\"properties.desired.chillerWaterSettings\\": {\\"temperature\\": 38, \\"pressure\\": 78}}}'
        --target-condition "from devices.modules where tags.building=9" --priority 1
        --metrics '{\\"metrics\\": {\\"queries\\": {\\"mymetric\\":\\"select moduleId from devices.modules where tags.location=''US''\\"}}}'
"""

helps[
    "iot hub configuration show"
] = """
    type: command
    short-summary: Get the details of an IoT automatic device management configuration.
"""

helps[
    "iot hub configuration list"
] = """
    type: command
    short-summary: List IoT automatic device management configurations in an IoT Hub.
"""

helps[
    "iot hub configuration update"
] = """
    type: command
    short-summary: |
                  Update specified properties of an IoT automatic device management configuration.

                  Use --set followed by property assignments for updating a configuration.

                  Note: Configuration content is immutable. Configuration properties that can be
                  updated are 'labels', 'metrics', 'priority' and 'targetCondition'.
    examples:
    - name: Alter the priority of a device configuration and update its target condition
      text: >
        az iot hub configuration update -c {configuration_name} -n {iothub_name} --set priority=10
        targetCondition="tags.building=43 and tags.environment='dev'"
"""

helps[
    "iot hub configuration delete"
] = """
    type: command
    short-summary: Delete an IoT device configuration.
"""

helps[
    "iot hub configuration show-metric"
] = """
    type: command
    short-summary: Evaluate a target user or system metric defined in an IoT device configuration
    examples:
    - name: Evaluate the user defined 'warningLimit' metric
      text: >
        az iot hub configuration show-metric -m warningLimit -c {configuration_name} -n {iothub_name}
    - name: Evaluate the system 'appliedCount' metric
      text: >
        az iot hub configuration show-metric --metric-id appliedCount -c {configuration_name} -n {iothub_name}
        --metric-type system
"""

helps[
    "iot hub distributed-tracing"
] = """
    type: group
    short-summary: Manage distributed settings per-device.
"""

helps[
    "iot hub distributed-tracing show"
] = """
    type: command
    short-summary: Get the distributed tracing settings for a device.
    examples:
    - name: Get the distributed tracing settings for a device
      text: >
        az iot hub distributed-tracing show -d {device_id} -n {iothub_name}
"""

helps[
    "iot hub distributed-tracing update"
] = """
    type: command
    short-summary: Update the distributed tracing options for a device.
    examples:
    - name: Update the distributed tracing options for a device
      text: >
        az iot hub distributed-tracing update -d {device_id} --sm on --sr 50 -n {iothub_name}
"""

helps[
    "iot device"
] = """
    type: group
    short-summary: Leverage device-to-cloud and cloud-to-device messaging capabilities.
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

                   Note: The command only works for symmetric key auth (SAS) based devices
    examples:
    - name: Basic usage
      text: az iot device send-d2c-message -n {iothub_name} -d {device_id}
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

                   Note: MQTT simulation is only supported for symmetric key auth (SAS) based devices.

                   Note: The command by default will set content-type to application/json and content-encoding
                   to utf-8. This can be overriden.
    examples:
    - name: Basic usage (mqtt)
      text: az iot device simulate -n {iothub_name} -d {device_id}
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

helps[
    "iot edge"
] = """
    type: group
    short-summary: Manage IoT solutions on the Edge.
    long-summmary: |
                   Azure IoT Edge moves cloud analytics and custom business logic to devices so that your organization
                   can focus on business insights instead of data management. Enable your solution to truly scale by
                   configuring your IoT software, deploying it to devices via standard containers, and monitoring it
                   all from the cloud.

                   Read more about Azure IoT Edge here:
                   https://docs.microsoft.com/en-us/azure/iot-edge/
"""

helps[
    "iot edge set-modules"
] = """
    type: command
    short-summary: Set edge modules on a single device.
    long-summary: |
                  Modules content is json and in the form of {"modulesContent":{...}} or {"content":{"modulesContent":{...}}}.

                  By default properties of system modules $edgeAgent and $edgeHub are validated against schemas installed with the IoT extension.
                  This can be disabled by using the --no-validation switch.

                  Note: Upon execution the command will output the collection of modules applied to the device.
    examples:
    - name: Test edge modules while in development by setting modules on a target device.
      text: >
        az iot edge set-modules --hub-name {iothub_name} --device-id {device_id} --content ../modules_content.json
"""

helps[
    "iot edge deployment"
] = """
    type: group
    short-summary: Manage IoT Edge deployments at scale.
"""

helps[
    "iot edge deployment create"
] = """
    type: command
    short-summary: Create an IoT Edge deployment in a target IoT Hub.
    long-summary: |
                  Deployment content is json and in the form of {"modulesContent":{...}} or {"content":{"modulesContent":{...}}}.

                  By default properties of system modules $edgeAgent and $edgeHub are validated against schemas installed with the IoT extension.
                  This can be disabled by using the --no-validation switch.

                  Edge deployments can be created with user defined metrics for on demand evaluation.
                  User metrics are json and in the form of {"queries":{...}} or {"metrics":{"queries":{...}}}.
    examples:
    - name: Create a deployment with labels (bash syntax example) that applies for devices in 'building 9' and
            the environment is 'test'.
      text: >
        az iot edge deployment create -d {deployment_name} -n {iothub_name}
        --content modules_content.json
        --labels '{"key0":"value0", "key1":"value1"}'
        --target-condition "tags.building=9 and tags.environment='test'"
        --priority 3
    - name: Create a deployment with labels (powershell syntax example) that applies for devices tagged with environment 'dev'.
      text: >
        az iot edge deployment create -d {deployment_name} -n {iothub_name}
        --content modules_content.json
        --labels "{'key':'value'}"
        --target-condition "tags.environment='dev'"
    - name: Create a layered deployment that applies for devices tagged with environment 'dev'.
            Both user metrics and modules content defined inline (powershell syntax example).
      text: >
        az iot edge deployment create -d {deployment_name} -n {iothub_name}
        --content "{'modulesContent':{'`$edgeAgent':{'properties.desired.modules.mymodule0':{ }},'`$edgeHub':{'properties.desired.routes.myroute0':'FROM /messages/* INTO `$upstream'}}}"
        --target-condition "tags.environment='dev'"
        --priority 10
        --metrics "{'queries':{'mymetrik':'SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200'}}"
        --layered
    - name: Create a layered deployment that applies for devices in 'building 9' and environment 'test'.
            Both user metrics and modules content defined inline (bash syntax example).
      text: >
        az iot edge deployment create -d {deployment_name} -n {iothub_name}
        --content '{"modulesContent":{"$edgeAgent":{"properties.desired.modules.mymodule0":{ }},"$edgeHub":{"properties.desired.routes.myroute0":"FROM /messages/* INTO $upstream"}}}'
        --target-condition "tags.building=9 and tags.environment='test'"
        --metrics '{"queries":{"mymetrik":"SELECT deviceId from devices where properties.reported.lastDesiredStatus.code = 200"}}'
        --layered
    - name: Create a layered deployment that applies for devices in 'building 9' and environment 'test'.
            Both user metrics and modules content defined from file.
      text: >
        az iot edge deployment create -d {deployment_name} -n {iothub_name}
        --content layered_modules_content.json
        --target-condition "tags.building=9 and tags.environment='test'"
        --metrics metrics_content.json
        --layered
"""

helps[
    "iot edge deployment show"
] = """
    type: command
    short-summary: Get the details of an IoT Edge deployment.
"""

helps[
    "iot edge deployment list"
] = """
    type: command
    short-summary: List IoT Edge deployments in an IoT Hub.
"""

helps[
    "iot edge deployment update"
] = """
    type: command
    short-summary: |
                  Update specified properties of an IoT Edge deployment.

                  Use --set followed by property assignments for updating a deployment.

                  Note: IoT Edge deployment content is immutable. Deployment properties that can be
                  updated are 'labels', 'metrics', 'priority' and 'targetCondition'.
    examples:
    - name: Alter the labels and target condition of an existing edge deployment
      text: >
        az iot edge deployment update -d {deployment_name} -n {iothub_name}
        --set labels='{"purpose":"dev", "owners":"IoTEngineering"}' targetCondition='tags.building=9'
"""

helps[
    "iot edge deployment delete"
] = """
    type: command
    short-summary: Delete an IoT Edge deployment.
"""

helps[
    "iot edge deployment show-metric"
] = """
    type: command
    short-summary: Evaluate a target system metric defined in an IoT Edge deployment.
    examples:
    - name: Evaluate the 'appliedCount' system metric
      text: >
        az iot edge deployment show-metric -m appliedCount -d {deployment_name} -n {iothub_name} --mt system
    - name: Evaluate the 'myCustomMetric' user metric
      text: >
        az iot edge deployment show-metric -m myCustomMetric -d {deployment_name} -n {iothub_name}
"""

helps[
    "iot dps"
] = """
    type: group
    short-summary: Manage entities in an Azure IoT Hub Device Provisioning Service (DPS).
                   Augmented with the IoT extension.
"""

helps[
    "iot dps enrollment"
] = """
    type: group
    short-summary: Manage individual device enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment list"
] = """
    type: command
    short-summary: List individual device enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment show"
] = """
    type: command
    short-summary: Get individual device enrollment details in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Basic usage
      text: >
        az iot dps enrollment show --dps-name {dps_name} -g {resource_group} --enrollment-id {enrollment_id}
    - name: Include full attestation information in results for a symmetric key enrollment
      text: >
        az iot dps enrollment show --dps-name {dps_name} -g {resource_group} --enrollment-id {symmetric_key_enrollment_id} --show-keys
"""

helps[
    "iot dps enrollment create"
] = """
    type: command
    short-summary: Create an individual device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Create an enrollment '{enrollment_id}' with attestation type 'x509' in the Azure
            IoT Device Provisioning Service '{dps_name}' in the resource group
            '{resource_group_name}' with provisioning status 'disabled',
            device id '{device_id}', initial twin properties '{"location":{"region":"US"}}',
            initial twin tags '{"version":"1"}', and device information '{"color":"red"}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type x509
        --certificate-path /certificates/Certificate.pem --provisioning-status disabled
        --initial-twin-properties "{'location':{'region':'US'}}"
        --initial-twin-tags "{'version':'1'}" --device-info "{'color':'red'}" --device-id {device_id}
    - name: Create an enrollment 'MyEnrollment' with attestation type 'tpm' in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type tpm
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
    - name: Create an enrollment 'MyEnrollment' with attestation type 'symmetrickey' in the Azure
            IoT Device Provisioning service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type symmetrickey
        --primary-key {primary_key} --secondary-key {secondary_key}
    - name: Create an enrollment 'MyEnrollment' with reprovision in the Azure IoT Device Provisioning
            service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type tpm
        --reprovision-policy {reprovision_type} --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
    - name: Create an enrollment 'MyEnrollment' with static allocation policy in the Azure
            IoT Device Provisioning service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type tpm --allocation-policy static
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89 --iot-hubs {iot_hub_host_name}
    - name: Create an enrollment 'MyEnrollment' with hashed allocation policy and multiple hubs in the Azure
            IoT Device Provisioning service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type tpm --allocation-policy hashed
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89 --iot-hubs "{iot_hub_host_name1} {iot_hub_host_name2}"
    - name: Create an enrollment 'MyEnrollment' with custom allocation policy,
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type symmetrickey --allocation-policy custom
        --webhook-url {webhook_url} --api-version {api_version}
"""

helps[
    "iot dps enrollment update"
] = """
    type: command
    short-summary: Update an individual device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment '{enrollment_id}' with a new x509 certificate in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --certificate-path /certificates/NewCertificate.pem
        --etag AAAAAAAAAAA=
    - name: Update enrollment '{enrollment_id}' with a new endorsement key in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
        --etag AAAAAAAAAAA=
    - name: Update enrollment '{enrollment_id}' with a new primary key in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --primary-key {new_primary_key}
        --etag AAAAAAAAAAA=
    - name: Update enrollment '{enrollment_id}' with a new reprovision type in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --reprovision-policy {reprovision_type}
        --etag AAAAAAAAAAA=
    - name: Update enrollment '{enrollment_id}' with a new allocation policy in the Azure IoT
            Device Provisioning Service '{dps_name}' in the resource group '{resource_group_name}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --allocation-policy geolatency
        --etag AAAAAAAAAAA= --iot-hubs "{iot_hub_host_name1} {iot_hub_host_name2} {iot_hub_host_name3}"
    - name: Update enrollment '{enrollment_id}' in the Azure IoT Device Provisioning Service '{dps_name}'
            in the resource group '{resource_group_name}' with
            initial twin properties '{"location":{"region":"USA"}}', initial twin tags '{"version":"2"}',
            and device information '{"color":"red"}'.
      text: >
        az iot dps enrollment update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --initial-twin-properties "{'location':{'region':'USA'}}"
        --initial-twin-tags "{'version1':'2'}" --device-info "{'color':'red'}"
"""

helps[
    "iot dps enrollment delete"
] = """
    type: command
    short-summary: Delete an individual device enrollment in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment registration"
] = """
    type: group
    short-summary: Manage service-side device registrations for an individual enrollment in an Azure IoT Hub Device
        Provisioning Service.
    long-summary: Use `az iot device registration create` to simulate device registration.
"""

helps[
    "iot dps enrollment registration show"
] = """
    type: command
    short-summary: Get a device registration for an individual enrollment in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps enrollment registration delete"
] = """
    type: command
    short-summary: Delete a device registration for an individual enrollment in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps enrollment-group"
] = """
    type: group
    short-summary: Manage enrollment groups in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment-group list"
] = """
    type: command
    short-summary: List enrollments groups in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment-group show"
] = """
    type: command
    short-summary: Get an enrollment group's details in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Basic usage
      text: >
        az iot dps enrollment-group show --dps-name {dps_name} -g {resource_group} --enrollment-id {enrollment_id}
    - name: Include full attestation information in results for a symmetric key enrollment-group
      text: >
        az iot dps enrollment-group show --dps-name {dps_name} -g {resource_group} --enrollment-id {symmetric_key_enrollment_id} --show-keys
"""

helps[
    "iot dps enrollment-group create"
] = """
    type: command
    short-summary: Create an enrollment group in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Create an enrollment group '{enrollment_id}' in the Azure IoT provisioning service
            '{dps_name}' in the resource group '{resource_group_name} using an intermediate certificate as primary certificate'.
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment group '{enrollment_id}' in the Azure IoT provisioning service
            '{dps_name}' in the resource group '{resource_group_name} using a CA certificate {certificate_name}
            as secondary certificate'.
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --secondary-ca-name {certificate_name}
    - name: Create an enrollment group '{enrollment_id}' in the Azure IoT provisioning service
            'MyDps' in the resource group '{resource_group_name}' with provisioning status
            'enabled', initial twin properties
            '{"location":{"region":"US"}}' and initial twin tags '{"version_dps":"1"}'
            using an intermediate certificate as primary certificate'.
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --certificate-path /certificates/Certificate.pem
        --provisioning-status enabled --initial-twin-properties "{'location':{'region':'US'}}"
        --initial-twin-tags "{'version_dps':'1'}"
    - name: Create an enrollment group '{enrollment_id}' in the Azure IoT provisioning service
            '{dps_name}' in the resource group '{resource_group_name} with attestation type 'symmetrickey'.
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --primary-key {primary_key} --secondary-key {secondary_key}
    - name: Create an enrollment group '{enrollment_id}' with custom allocation policy,
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --allocation-policy custom --webhook-url {webhook_url}
        --api-version {api_version}

"""

helps[
    "iot dps enrollment-group update"
] = """
    type: command
    short-summary: Update an enrollment group in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment group '{enrollment_id}' in the Azure IoT provisioning service '{dps_name}'
            in the resource group '{resource_group_name}' with initial twin properties and initial twin tags.
      text: >
        az iot dps enrollment-group update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --initial-twin-properties "{'location':{'region':'USA'}}"
        --initial-twin-tags "{'version_dps':'2'}" --etag AAAAAAAAAAA=
    - name: Update enrollment group '{enrollment_id}' in the Azure IoT provisioning service '{dps_name}'
            in the resource group '{resource_group_name}' with new primary intermediate certificate
            and remove existing secondary intermediate certificate.
      text: >
        az iot dps enrollment-group update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --certificate-path /certificates/NewCertificate.pem
        --remove-secondary-certificate --etag AAAAAAAAAAA=
    - name: Update enrollment group '{enrollment_id}' in the Azure IoT provisioning service '{dps_name}'
            in the resource group '{resource_group_name}' with new secondary CA certificate
            '{certificate_name}' and remove existing primary CA certificate.
      text: >
        az iot dps enrollment-group update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --secondary-ca-name {certificate_name}
        --remove-certificate --etag AAAAAAAAAAA=
    - name: Update enrollment group '{enrollment_id}' in the Azure IoT provisioning service '{dps_name}'
            in the resource group '{resource_group_name}' with new primary key.
      text: >
        az iot dps enrollment-group update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --primary-key {new_primary_key} --etag AAAAAAAAAAA=
"""

helps[
    "iot dps enrollment-group delete"
] = """
    type: command
    short-summary: Delete an enrollment group in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment-group registration"
] = """
    type: group
    short-summary: Manage service-side device registrations for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
    long-summary: Use `az iot device registration create` to simulate device registration.
"""

helps[
    "iot dps enrollment-group registration list"
] = """
    type: command
    short-summary: List device registrations for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps enrollment-group registration show"
] = """
    type: command
    short-summary: Get a device registration for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps enrollment-group registration delete"
] = """
    type: command
    short-summary: Delete a device registration for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps enrollment-group compute-device-key"
] = """
    type: command
    short-summary: Generate a derived device SAS key for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
    examples:
    - name: Compute the device key with the given symmetric key.
      text: >
        az iot dps enrollment-group compute-device-key --key {enrollement_group_symmetric_key} --registration-id {registration_id}
    - name: Compute the device key with the given enrollment group.
      text: >
        az iot dps enrollment-group compute-device-key -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --registration-id {registration_id}
"""

helps[
    "iot dps registration"
] = """
    type: group
    short-summary: Manage device registrations for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps registration list"
] = """
    type: command
    short-summary: List device registrations for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps registration show"
] = """
    type: command
    short-summary: Get a device registration for an enrollment group in an Azure IoT Hub Device
        Provisioning Service.
"""

helps[
    "iot dps registration delete"
] = """
    type: command
    short-summary: Delete a device registration in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps compute-device-key"
] = """
    type: command
    short-summary: Generate a derived device SAS key.
    long-summary: Generate a derived device key for a DPS enrollment group.
    examples:
    - name: Compute the device key with the given symmetric key.
      text: >
        az iot dps compute-device-key --key {enrollement_group_symmetric_key} --registration-id {registration_id}
    - name: Compute the device key with the given enrollment group.
      text: >
        az iot dps compute-device-key -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --registration-id {registration_id}
"""

helps[
    "iot dps connection-string"
] = """
    type: group
    short-summary: Manage connection strings for an Azure IoT Hub Device Provisioning Service instance.
"""

helps[
    "iot dps connection-string show"
] = """
    type: command
    short-summary: Show the connection strings for the specified Device Provisioning Services using the given
                   policy name and key.
    examples:
    - name: Show the connection strings for all active state DPS instances in a subscription
            using the default policy and primary key.
      text: >
          az iot dps connection-string show
    - name: Show the connection strings for all active state DPS instances in a resource group
            using the default policy and primary key.
      text: >
          az iot dps connection-string show --resource-group MyResourceGroup
    - name: Show all connection strings of the given DPS using primary key.
      text: >
          az iot dps connection-string show -n MyDPS --all
    - name: Show the connection string of the given DPS using the default policy and primary key.
      text: >
          az iot dps connection-string show -n MyDPS
    - name: Show the connection string of the given DPS using policy 'service' and secondary key.
      text: >
          az iot dps connection-string show -n MyDPS --policy-name service --key-type secondary
"""
