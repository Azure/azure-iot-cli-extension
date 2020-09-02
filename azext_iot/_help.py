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
                  EXPERIMENTAL requires Python 3.5+
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
                  EXPERIMENTAL requires Python 3.4+
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
    short-summary: Show the connection strings for an IoT Hub.
    examples:
    - name: Show the connection string for all IoT Hubs in a subscription using the default policy and primary key.
      text: >
          az iot hub connection-string show
    - name: Show the connection string for all IoT Hubs in a resource group using the default policy and primary key.
      text: >
          az iot hub connection-string show --resource-group MyResourceGroup
    - name: Show all the connection string of an IoT Hub using primary key.
      text: >
          az iot hub connection-string show -n MyIotHub --all
    - name: Show the connection string of an IoT Hub using default policy and primary key.
      text: >
          az iot hub connection-string show -n MyIotHub
    - name: Show the connection string of an IoT Hub using policy 'service' and secondary key.
      text: >
          az iot hub connection-string show -n MyIotHub --policy-name service --key-type secondary
    - name: Show the eventhub compatible connection string of an IoT Hub\'s default eventhub.
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
    examples:
    - name: Create an edge enabled IoT device with default authorization (shared private key).
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --ee
    - name: Create an edge enabled IoT device with default authorization (shared private key) and
            add child devices as well.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --ee --cl {child_device_id}
    - name: Create an IoT device with default authorization (shared private key) and
            set parent device as well.
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --pd {edge_device_id}
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
    - name: Create an IoT device with root CA authorization with disabled status and reason
      text: >
        az iot hub device-identity create -n {iothub_name} -d {device_id} --am x509_ca
        --status disabled --status-reason 'for reasons'
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
    "iot hub device-identity delete"
] = """
    type: command
    short-summary: Delete an IoT Hub device.
"""

helps[
    "iot hub device-identity show-connection-string"
] = """
    type: command
    short-summary: Show a given IoT Hub device connection string.
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
"""

helps[
    "iot hub device-identity get-parent"
] = """
    type: command
    short-summary: Get the parent device of the specified device.
    examples:
    - name: Get the parent device of the specified device.
      text: >
        az iot hub device-identity get-parent -d {non_edge_device_id} -n {iothub_name}
"""

helps[
    "iot hub device-identity set-parent"
] = """
    type: command
    short-summary: Set the parent device of the specified non-edge device.
    examples:
    - name: Set the parent device of the specified non-edge device.
      text: >
        az iot hub device-identity set-parent -d {non_edge_device_id} --pd {edge_device_id} -n {iothub_name}
    - name: Set the parent device of the specified non-edge device irrespectively the non-edge device is
            already a child of other edge device.
      text: >
        az iot hub device-identity set-parent -d {non_edge_device_id} --pd {edge_device_id} --force -n {iothub_name}
"""

helps[
    "iot hub device-identity add-children"
] = """
    type: command
    short-summary: Add specified comma-separated list of non edge device ids as children of specified edge device.
    examples:
    - name: Add non-edge devices as a children to the edge device.
      text: >
        az iot hub device-identity add-children -d {edge_device_id} --child-list {comma_separated_non_edge_device_id}
        -n {iothub_name}
    - name: Add non-edge devices as a children to the edge device irrespectively the non-edge device is
            already a child of other edge device.
      text: >
        az iot hub device-identity add-children -d {edge_device_id} --child-list {comma_separated_non_edge_device_id}
        -n {iothub_name} -f
"""

helps[
    "iot hub device-identity list-children"
] = """
    type: command
    short-summary: Print comma-separated list of assigned child devices.
    examples:
    - name: Show all assigned non-edge devices as comma-separated list.
      text: >
        az iot hub device-identity list-children -d {edge_device_id} -n {iothub_name}
"""

helps[
    "iot hub device-identity remove-children"
] = """
    type: command
    short-summary: Remove non edge devices as children from specified edge device.
    examples:
    - name: Remove all mentioned devices as children of specified device.
      text: >
        az iot hub device-identity remove-children -d {edge_device_id} --child-list {comma_separated_non_edge_device_id}
        -n {iothub_name}
    - name: Remove all non-edge devices as children specified edge device.
      text: >
        az iot hub device-identity remove-children -d {edge_device_id} --remove-all
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
    long-summary: Provide --desired or --tags arguments for PATCH behavior.
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
    "iot hub module-identity show-connection-string"
] = """
    type: command
    short-summary: Show a target IoT device module connection string.
"""

helps[
    "iot hub module-identity create"
] = """
    type: command
    short-summary: Create a module on a target IoT device in an IoT Hub.
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
    long-summary: Provide --desired or --tags arguments for PATCH behavior.
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
"""

helps[
    "iot hub invoke-module-method"
] = """
    type: command
    short-summary: Invoke an Edge module method.
"""

helps[
    "iot hub invoke-device-method"
] = """
    type: command
    short-summary: Invoke a device method.
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
                  EXPERIMENTAL requires Python 3.4+
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
    short-summary: Send an mqtt device-to-cloud message.
                   The command supports sending messages with application and system properties.
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
                   selection which can be complete, reject or abandon.

                   Note: The command by default will set content-type to application/json and content-encoding
                   to utf-8. This can be overriden.
    examples:
    - name: Basic usage (mqtt)
      text: az iot device simulate -n {iothub_name} -d {device_id}
    - name: Basic usage (mqtt) with sending mixed properties
      text: az iot device simulate -n {iothub_name} -d {device_id} --properties "myprop=myvalue;$.ct=application/json"
    - name: Basic usage (http)
      text: az iot device simulate -n {iothub_name} -d {device_id} --protocol http
    - name: Basic usage (http) with sending mixed properties
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
    short-summary: Manage entities in an Azure IoT Hub Device Provisioning Service.
                   Augmented with the IoT extension.
"""

helps[
    "iot dps enrollment"
] = """
    type: group
    short-summary: Manage enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment list"
] = """
    type: command
    short-summary: List device enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment show"
] = """
    type: command
    short-summary: Get device enrollment details in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment create"
] = """
    type: command
    short-summary: Create a device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Create an enrollment '{enrollment_id}' with attestation type 'x509' in the Azure
            IoT provisioning service '{dps_name}' in the resource group '{resource_group_name}'
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type x509
        --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment '{enrollment_id}' with attestation type 'x509' in the Azure
            IoT Device Provisioning Service '{dps_name}' in the resource group
            '{resource_group_name}' with provisioning status 'disabled', target IoT Hub
            '{iothub_host_name}', device id '{device_id}' and initial twin
            properties '{"location":{"region":"US"}}'.
      text: >
        az iot dps enrollment create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --attestation-type x509
        --certificate-path /certificates/Certificate.pem --provisioning-status disabled
        --iot-hub-host-name {iothub_host_name}
        --initial-twin-properties "{'location':{'region':'US'}}" --device-id {device_id}
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
    short-summary: Update a device enrollment in an Azure IoT Hub Device Provisioning Service.
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
"""

helps[
    "iot dps enrollment delete"
] = """
    type: command
    short-summary: Delete a device enrollment in an Azure IoT Hub Device Provisioning Service.
"""

helps[
    "iot dps enrollment-group"
] = """
    type: group
    short-summary: Manage Azure IoT Hub Device Provisioning Service.
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
    short-summary: Get the details of an enrollment group in an Azure IoT Hub Device Provisioning Service.
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
            'enabled', target IoT Hub '{iothub_host_name}' and initial twin
            tags '{"location":{"region":"US"}} using an intermediate certificate as primary certificate'.
      text: >
        az iot dps enrollment-group create -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --certificate-path /certificates/Certificate.pem
        --provisioning-status enabled --iot-hub-host-name {iothub_host_name}
        --initial-twin-tags "{'location':{'region':'US'}}"
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
            in the resource group '{resource_group_name}' with new initial twin tags.
      text: >
        az iot dps enrollment-group update -g {resource_group_name} --dps-name {dps_name}
        --enrollment-id {enrollment_id} --initial-twin-tags "{'location':{'region':'US2'}}" --etag AAAAAAAAAAA=
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
    "iot dps registration"
] = """
    type: group
    short-summary: Manage Azure IoT Hub Device Provisioning Service registrations.
"""

helps[
    "iot dps registration list"
] = """
    type: command
    short-summary: List device registration state in an Azure IoT Hub Device Provisioning
        Service enrollment group.
"""

helps[
    "iot dps registration show"
] = """
    type: command
    short-summary: Get the device registration state in an Azure IoT Hub Device Provisioning Service.
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
    long-summary: Generate a derived device key from a DPS enrollment group symmetric key.
    examples:
    - name: Basic usage
      text: >
        az iot dps compute-device-key --key {enrollement_group_symmetric_key} --registration-id {registration_id}
"""
