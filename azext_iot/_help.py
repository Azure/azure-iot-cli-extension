# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
Help definitions for CLI.
"""

from knack.help_files import helps


helps['iot'] = """
    type: group
    short-summary: Manage Internet of Things (IoT) assets.
                   Augmented with the IoT extension.
    long-summary: |
                  Review the extension wiki tips to maximize usage
                  https://github.com/Azure/azure-iot-cli-extension/wiki/Tips
"""

helps['iot hub'] = """
    type: group
    short-summary: Manage entities in an Azure IoT Hub.
"""

helps['iot hub monitor-events'] = """
    type: command
    short-summary: Monitor device telemetry & messages sent to an IoT Hub.
    long-summary: |
                  EXPERIMENTAL requires Python 3.5+
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python
    examples:
    - name: Basic usage
      text: >
        az iot hub monitor-events -n [IoTHub_Name]
    - name: Basic usage with an IoT Hub connection string
      text: >
        az iot hub monitor-events -n [IoTHub_Name]
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Basic usage when filtering on target device
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -d [Device_Id]
    - name: Basic usage when filtering targeted devices with a wildcard in the ID
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -d Device*
    - name: Filter devices using IoT Hub query language
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -q "select * from devices where tags.location.region = 'US'"
    - name: Filter device and specify an Event Hub consumer group to bind to.
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -d [Device_Id] --cg [Consumer_Group_Name]
    - name: Receive message annotations (message headers)
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -d [Device_Id] --properties anno
    - name: Receive message annotations + system properties. Never time out.
      text: >
        az iot hub monitor-events -n [IoTHub_Name] -d [Device_Id] --properties anno sys --timeout 0
    - name: Receive all message attributes from all device messages
      text: >
        az iot hub monitor-events -n [IoTHub_Name] --props all
    - name: Receive all messages and parse message payload as JSON
      text: >
        az iot hub monitor-events -n [IoTHub_Name] --content-type application/json
"""

helps['iot hub monitor-feedback'] = """
    type: command
    short-summary: Monitor feedback sent by devices to acknowledge cloud-to-device (C2D) messages.
    long-summary: |
                  EXPERIMENTAL requires Python 3.4+
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python
    examples:
    - name: Basic usage
      text: >
        az iot hub monitor-feedback -n [IoTHub_Name]
    - name: Basic usage with an IoT Hub connection string
      text: >
        az iot hub monitor-feedback -n [IoTHub_Name]
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
    - name: Basic usage when filtering on target device
      text: >
        az iot hub monitor-feedback -n [IoTHub_Name] -d [Device_Id]
    - name: Exit feedback monitor upon receiving a message with specific id (uuid)
      text: >
        az iot hub monitor-feedback -n [IoTHub_Name] -d [Device_Id] -w [Message_Id]
"""

helps['iot hub device-identity'] = """
    type: group
    short-summary: Manage IoT devices.
"""

helps['iot hub device-identity create'] = """
    type: command
    short-summary: Create a device in an IoT Hub.
    examples:
    - name: Create an edge enabled IoT device with default authorization (shared private key).
      text: >
        az iot hub device-identity create -n [IoTHub_Name] -d [Device_Id] --ee
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert valid for 10 days then use its thumbprint.
      text: >
        az iot hub device-identity create -n [IoTHub_Name] -d [Device_Id]
        --am x509_thumbprint --valid-days 10
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert of default expiration (365 days) and output to target directory.
      text: >
        az iot hub device-identity create -n [IoTHub_Name] -d [Device_Id] --am x509_thumbprint
        --output-dir /path/to/output
    - name: Create an IoT device with self-signed certificate authorization and
            explicitly provide primary and secondary thumbprints.
      text: >
        az iot hub device-identity create -n [IoTHub_Name] -d [Device_Id] --am x509_thumbprint
        --ptp [Thumbprint_1] --stp [Thumbprint_2]
    - name: Create an IoT device with root CA authorization with disabled status and reason
      text: >
        az iot hub device-identity create -n [IoTHub_Name] -d [Device_Id] --am x509_ca
        --status disabled --status-reason 'for reasons'
"""

helps['iot hub device-identity show'] = """
    type: command
    short-summary: Get the details of an IoT Hub device.
"""

helps['iot hub device-identity list'] = """
    type: command
    short-summary: List devices in an IoT Hub.
"""

helps['iot hub device-identity update'] = """
    type: command
    short-summary: Update an IoT Hub device.
    long-summary: Use --set followed by property assignments for updating a device.
                  Leverage parameters returned from 'iot hub device-identity show'.
    examples:
    - name: Turn on edge capabilities for device
      text: >
        az iot hub device-identity update -d [Device_Id] -n [IoTHub_Name]
        --set capabilities.iotEdge=true
    - name: Disable device status
      text: >
        az iot hub device-identity update -d [Device_Id] -n [IoTHub_Name] --set status=disabled
    - name: In one command
      text: >
        az iot hub device-identity update -d [Device_Id] -n [IoTHub_Name]
        --set status=disabled capabilities.iotEdge=true
"""

helps['iot hub device-identity delete'] = """
    type: command
    short-summary: Delete an IoT Hub device.
"""

helps['iot hub device-identity show-connection-string'] = """
    type: command
    short-summary: Show a given IoT Hub device connection string.
"""

helps['iot hub device-identity export'] = """
    type: command
    short-summary: Export all device identities from an IoT Hub to an Azure Storage blob container.
    long-summary: For more information, see
                  https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-identity-registry#import-and-export-device-identities
"""

helps['iot hub device-identity import'] = """
    type: command
    short-summary: Import device identities to an IoT Hub from a blob.
    long-summary: For more information, see
                  https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-identity-registry#import-and-export-device-identities
"""

helps['iot hub device-twin'] = """
    type: group
    short-summary: Manage IoT device twin configuration.
"""

helps['iot hub device-twin show'] = """
    type: command
    short-summary: Get a device twin definition.
"""

helps['iot hub device-twin update'] = """
    type: command
    short-summary: Update device twin definition.
    long-summary: Use --set followed by property assignments for updating a device twin.
                  Leverage properties returned from 'iot hub device-twin show'.
    examples:
    - name: Add nested tags to device twin.
      text: >
        az iot hub device-twin update --device-id [Device_Id] --hub-name [IoTHub_Name]
        --set tags='{"location":{"region":"US"}}'
    - name: Remove the 'region' property from parent 'location' property
      text: >
        az iot hub device-twin update --device-id [Device_Id] --hub-name [IoTHub_Name]
        --set tags.location.region='null'
"""

helps['iot hub device-twin replace'] = """
    type: command
    short-summary: Replace device twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace device twin with file contents.
      text: >
        az iot hub device-twin replace -d [Device_Id] -n [IoTHub_Name] -j ../mydevicetwin.json
"""

helps['iot hub module-identity'] = """
    type: group
    short-summary: Manage IoT device modules.
"""

helps['iot hub module-identity show-connection-string'] = """
    type: command
    short-summary: Show a target IoT device module connection string.
"""

helps['iot hub module-identity create'] = """
    type: command
    short-summary: Create a module on a target IoT device in an IoT Hub.
"""

helps['iot hub module-identity show'] = """
    type: command
    short-summary: Get the details of an IoT device module in an IoT Hub.
"""

helps['iot hub module-identity list'] = """
    type: command
    short-summary: List modules located on an IoT device in an IoT Hub.
"""

helps['iot hub module-identity update'] = """
    type: command
    short-summary: Update an IoT Hub device module.
    long-summary: Use --set followed by property assignments for updating a module.
                  Leverage properties returned from 'iot hub module-identity show'.
    examples:
    - name: Regenerate module symmetric authentication keys
      text: >
        az iot hub module-identity update -m [Module_Name] -d [Device_Id] -n [IoTHub_Name]
        --set authentication.symmetricKey.primaryKey=""
        authentication.symmetricKey.secondaryKey=""
"""

helps['iot hub module-identity delete'] = """
    type: command
    short-summary: Delete a device in an IoT Hub.
"""

helps['iot hub module-twin'] = """
    type: group
    short-summary: Manage IoT device module twin configuration.
"""

helps['iot hub module-twin show'] = """
    type: command
    short-summary: Show a module twin definition.
"""

helps['iot hub module-twin update'] = """
    type: command
    short-summary: Update module twin definition.
    long-summary: Use --set followed by property assignments for updating a module.
                  Leverage properties returned from 'iot hub module-twin show'.
    examples:
    - name: Add desired properties to module twin.
      text: >
        az iot hub module-twin update -d [Device_Id] -n [IoTHub_Name] -m [Module_Name] --set
        properties.desired='{"conditions":{"temperature":{"warning":70, "critical":100}}}'
    - name: Remove 'critical' property from parent 'temperature'
      text: >
        az iot hub module-twin update -d mydevice -n myhub -m mymod --set
        properties.desired.condition.temperature.critical='null'
"""

helps['iot hub module-twin replace'] = """
    type: command
    short-summary: Replace a module twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace a module twin with file contents.
      text: >
        az iot hub module-twin replace -d [Device_Id] -n [IoTHub_Name]
        -m [Module_Name] -j ../mymodtwin.json
"""

helps['iot hub apply-configuration'] = """
    type: command
    short-summary: Apply a deployment manifest to a single device.
    long-summary: DEPRECATED. Use 'az iot edge set-modules' instead.
                  Manifest content is json and must have root element of 'content' or 'moduleContent'
                  e.g. {"content":{...}} or {"moduleContent":{...}}
    examples:
    - name: Test modules while in development.
      text: >
        az iot hub apply-configuration --hub-name [IoTHub_Name] --device-id [Device_Id]
        --content ../mycontent.json
"""

helps['iot hub generate-sas-token'] = """
    type: command
    short-summary: Generate a SAS token for a target IoT Hub or device.
    long-summary: For device SAS tokens, the policy parameter is used to
                  access the the device registry only. Therefore the policy should have
                  read access to the registry. For IoT Hub tokens the policy is part of the SAS.
    examples:
    - name: Generate an IoT Hub SAS token using the iothubowner policy and primary key.
      text: >
        az iot hub generate-sas-token -n [IoTHub_Name]
    - name: Generate an IoT Hub SAS token using the registryRead policy and secondary key.
      text: >
        az iot hub generate-sas-token -n [IoTHub_Name] --policy registryRead --key-type secondary
    - name: Generate a device SAS token using the iothubowner policy to access the [IoTHub_Name] device registry.
      text: >
        az iot hub generate-sas-token -d [Device_Id] -n [IoTHub_Name]
    - name: Generate a device SAS token using an IoT Hub connection string (with registry access)
      text: >
        az iot hub generate-sas-token -d [Device_Id]
        --login 'HostName=myhub.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=12345'
"""

helps['iot hub invoke-module-method'] = """
    type: command
    short-summary: Invoke an Edge module method.
"""

helps['iot hub invoke-device-method'] = """
    type: command
    short-summary: Invoke a device method.
"""

helps['iot hub query'] = """
    type: command
    short-summary: Query an IoT Hub using a powerful SQL-like language.
    long-summary: Query an IoT Hub using a powerful SQL-like language to retrieve information
                  regarding device and module twins, jobs and message routing.
                  See https://docs.microsoft.com/azure/iot-hub/iot-hub-devguide-query-language
                  for more information.
    examples:
    - name: Query all device twin data in an Azure IoT Hub.
      text: >
        az iot hub query -n [IoTHub_Name] -q "select * from devices"
    - name: Query all module twin data on target device.
      text: >
        az iot hub query -n [IoTHub_Name] -q "select * from devices.modules where devices.deviceId = '[Device_Id]'"
"""

helps['iot hub show-connection-string'] = """
    type: command
    short-summary: Show a target IoT Hub Connection String.
"""

helps['iot hub configuration'] = """
    type: group
    short-summary: Manage IoT device configurations at scale
"""

helps['iot hub configuration create'] = """
    type: command
    short-summary: Create an IoT device configuration in the target IoT Hub.
    long-summary: |
                  The configuration content is json and must include a root object containing the "deviceContent" property.

                  Alternatively "deviceContent" can be nested in a "content" property.
                  E.g. {"deviceContent":{...}} or {"content":{"deviceContent":{...}}}

                  Device configurations can be created with user provided metrics for on demand evaluation.
                  User metrics are json and in the form of {"metrics":{"queries":{...}}}
    examples:
    - name: Create a device configuration that applies on condition where a device is in 'building 9' and
            the environment is 'test'.
      text: >
        az iot hub configuration create -c [Config_Name] -n [IoTHub_Name] --content ../device_content.json
        --target-condition "tags.building=9 and tags.environment='test'"
    - name: Create a device configuration with labels and provide user metrics inline (bash syntax example)
      text: >
        az iot hub configuration create -c [Config_Name] -n [IoTHub_Name] --content ../device_content.json
        --target-condition "tags.building=9" --labels '{"key0":"value0", "key1":"value1"}'
        --metrics '{"metrics": {"queries": {"mymetrik": "select deviceId from devices where tags.location='US'"}}}'
    - name: Create a device configuration with labels and provide user metrics inline (cmd syntax example)
      text: >
        az iot hub configuration create -c [Config_Name] -n [IoTHub_Name] --content ../device_content.json
        --target-condition "tags.building=9" --labels "{\\"key0\\":\\"value0\\", \\"key1\\":\\"value1\\"}"
        --metrics "{\\"metrics\\": {\\"queries\\": {\\"mymetrik\\":
        \\"select deviceId from devices where tags.location='US'\\"}}}"
"""

helps['iot hub configuration show'] = """
    type: command
    short-summary: Get the details of an IoT device configuration.
"""

helps['iot hub configuration list'] = """
    type: command
    short-summary: List IoT device configurations in an IoT Hub.
"""

helps['iot hub configuration update'] = """
    type: command
    short-summary: Update an IoT device configuration with the specified properties.
    long-summary: Use --set followed by property assignments for updating a configuration.
                  Leverage properties returned from 'az iot hub configuration show'.
    examples:
    - name: Alter the priority of a device configuration and update its target condition
      text: >
        az iot hub configuration update -c [Configuration_Name] -n [IoTHub_Name] --set priority=10
        targetCondition="tags.building=43 and tags.environment='dev'"
"""

helps['iot hub configuration delete'] = """
    type: command
    short-summary: Delete an IoT device configuration.
"""

helps['iot hub configuration show-metric'] = """
    type: command
    short-summary: Evaluate a target user or system metric defined in an IoT device configuration
    examples:
    - name: Evaluate the user defined 'warningLimit' metric
      text: >
        az iot hub configuration show-metric -m warningLimit -c [Configuration_Name] -n [IoTHub_Name]
    - name: Evaluate the system 'appliedCount' metric
      text: >
        az iot hub configuration show-metric --metric-id appliedCount -c [Configuration_Name] -n [IoTHub_Name]
        --metric-type system
"""

helps['iot device'] = """
    type: group
    short-summary: Leverage device-to-cloud and cloud-to-device messaging capabilities.
"""

helps['iot device c2d-message'] = """
    type: group
    short-summary: Cloud-to-device messaging commands.
"""

helps['iot device c2d-message abandon'] = """
    type: command
    short-summary: Abandon a cloud-to-device message.
"""

helps['iot device c2d-message complete'] = """
    type: command
    short-summary: Complete a cloud-to-device message.
"""

helps['iot device c2d-message receive'] = """
    type: command
    short-summary: Receive a cloud-to-device message.
"""

helps['iot device c2d-message reject'] = """
    type: command
    short-summary: Reject or deadletter a cloud-to-device message.
"""

helps['iot device c2d-message send'] = """
    type: command
    short-summary: Send a cloud-to-device message.
    long-summary: |
                  EXPERIMENTAL requires Python 3.4+
                  This command relies on and may install dependent Cython package (uamqp) upon first execution.
                  https://github.com/Azure/azure-uamqp-python
    examples:
    - name: Basic usage with default message body
      text: >
        az iot device c2d-message send -d [Device_Id] -n [IoTHub_Name]
    - name: Send cloud-to-device message with custom data and properties.
      text: >
        az iot device c2d-message send -d [Device_Id] -n [IoTHub_Name] --data 'Hello World' --props 'key0=value0;key1=value1'
    - name: Send a C2D message and wait for device acknowledgement
      text: >
        az iot device c2d-message send -d [Device_Id] -n [IoTHub_Name] --wait
"""

helps['iot device send-d2c-message'] = """
    type: command
    short-summary: Send an mqtt device-to-cloud message.
    long-summary: Supports application and system properties to send with message.
    examples:
    - name: Basic usage
      text: az iot device send-d2c-message -n [IoTHub_Name] -d [Device_Id]
    - name: Basic usage with custom data
      text: az iot device send-d2c-message -n [IoTHub_Name] -d [Device_Id] --data <message_body>
    - name: Send application properties
      text: az iot device send-d2c-message -n [IoTHub_Name] -d [Device_Id] --props 'key0=value0;key1=value1'
    - name: Send system properties (Message Id and Correlation Id)
      text: az iot device send-d2c-message -n [IoTHub_Name] -d [Device_Id] --props '$.mid=<id>;$.cid=<id>'
"""

helps['iot device simulate'] = """
    type: command
    short-summary: Simulate a device in an Azure IoT Hub.
    long-summary: While the device simulation is running, the device will automatically receive
                  and acknowledge cloud-to-device (c2d) messages. For mqtt simulation, all c2d messages will
                  be acknowledged with completion. For http simulation c2d acknowledgement is based on user
                  selection which can be complete, reject or abandon.
    examples:
    - name: Basic usage (mqtt).
      text: az iot device simulate -n [IoTHub_Name] -d [Device_Id]
    - name: Basic usage (http).
      text: az iot device simulate -n [IoTHub_Name] -d [Device_Id] --protocol http
    - name: Choose total message count and interval between messages.
      text: az iot device simulate -n [IoTHub_Name] -d [Device_Id] --msg-count 1000 --msg-interval 5
    - name: Reject or abandon c2d messages (http only)
      text: az iot device simulate -n [IoTHub_Name] -d [Device_Id] --rs [reject|abandon]
"""

helps['iot device upload-file'] = """
    type: command
    short-summary: Upload a local file as a device to a pre-configured blob storage container.
"""

helps['iot device get-parent'] = """
    type: command
    short-summary: Get the parent device of the specified device.
    examples:
    - name: Get the parent device of the specified device .
      text: >
        az iot device get-parent -d [Non_Edge_Device_Id] -n [IoTHub_Name]
"""

helps['iot device children'] = """
    type: group
    short-summary: Manage Edge offline.
"""

helps['iot device children add'] = """
    type: command
    short-summary: Add specified comma-separated list of non edge device ids as children of specified edge device.
    examples:
    - name: Add non-edge devices as a children to the edge device.
      text: >
        az iot device children add -d [Edge_Device_Id] --child-list [Comma_Separated_Non_Edge_Device_Id]
        -n [IoTHub_Name]
    - name: Add non-edge devices as a children to the edge device irrespectively the non-edge device is
            already a child of other edge device.
      text: >
        az iot device children add -d [Edge_Device_Id] --child-list [Comma_Separated_Non_Edge_Device_Id]
        -n [IoTHub_Name] -f
"""

helps['iot device children list'] = """
    type: command
    short-summary: Print comma-separated list of assigned child devices.
    examples:
    - name: Show all assigned non-edge devices as comma-separated list.
      text: >
        az iot device children list -d [Edge_Device_Id] -n [IoTHub_Name]
"""

helps['iot device children remove'] = """
    type: command
    short-summary: Remove comma-separated list of devices as children of specified device.
    examples:
    - name: Remove all mentioned devices as children of specified device.
      text: >
        az iot device children remove -d [Edge_Device_Id] --child-list [Comma_Separated_Non_Edge_Device_Id]
        -n [IoTHub_Name]
    - name: Remove all non-edge devices as children specified edge device.
      text: >
        az iot device children remove -d [Edge_Device_Id] --remove-all
"""

helps['iot edge'] = """
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

helps['iot edge set-modules'] = """
    type: command
    short-summary: Set edge modules on a single device.
    long-summary: |
                  The modules content is json and must include a root object containing the "modulesContent" property.

                  Alternatively "modulesContent" can be nested in a "content" property.
                  E.g. {"modulesContent":{...}} or {"content":{"modulesContent":{...}}}
    examples:
    - name: Test edge modules while in development by setting modules on a target device.
      text: >
        az iot edge set-modules --hub-name [IoTHub_Name] --device-id [Device_Id] --content ../modules_content.json
"""

helps['iot edge deployment'] = """
    type: group
    short-summary: Manage IoT Edge deployments at scale.
"""

helps['iot edge deployment create'] = """
    type: command
    short-summary: Create an IoT Edge deployment in the target IoT Hub.
    long-summary: |
                  The deployment content is json and must include a root object containing the "modulesContent" property.

                  Alternatively "modulesContent" can be nested in a "content" property.
                  E.g. {"modulesContent":{...}} or {"content":{"modulesContent":{...}}}
    examples:
    - name: Create a deployment with labels (bash syntax example) that applies for devices in 'building 9' and
            the environment is 'test'.
      text: >
        az iot edge deployment create -d [Deployment_Name] -n [IoTHub_Name] --content ../modules_content.json
        --labels '{"key0":"value0", "key1":"value1"}'
        --target-condition "tags.building=9 and tags.environment='test'" --priority 3
    - name: Create a deployment with labels (cmd syntax example) that applies for devices tagged with environment 'dev'.
      text: >
        az iot edge deployment create -d [Deployment_Name] -n [IoTHub_Name] --content ../modules_content.json
        --labels "{\\"key\\":\\"value\\"}"
        --target-condition "tags.environment='dev'"
"""

helps['iot edge deployment show'] = """
    type: command
    short-summary: Get the details of an IoT Edge deployment.
"""

helps['iot edge deployment list'] = """
    type: command
    short-summary: List IoT Edge deployments in an IoT Hub.
"""

helps['iot edge deployment update'] = """
    type: command
    short-summary: Update an IoT Edge deployment with the specified properties.
    long-summary: Use --set followed by property assignments for updating a deployment.
                  Leverage properties returned from 'az iot edge deployment show'.
    examples:
    - name: Alter the labels and target condition of an existing edge deployment
      text: >
        az iot edge deployment update -d [Deployment_Name] -n [IoTHub_Name]
        --set labels='{"purpose":"dev", "owners":"IoTEngineering"}' targetCondition='tags.building=9'
"""

helps['iot edge deployment delete'] = """
    type: command
    short-summary: Delete an IoT Edge deployment.
"""

helps['iot edge deployment show-metric'] = """
    type: command
    short-summary: Evaluate a target system metric defined in an IoT Edge deployment.
    examples:
    - name: Evaluate the 'appliedCount' system metric
      text: >
        az iot edge deployment show-metric -m appliedCount -d [Deployment_Name] -n [IoTHub_Name]
"""

helps['iot dps'] = """
    type: group
    short-summary: Manage entities in an Azure IoT Hub Device Provisioning Service.
                   Augmented with the IoT extension.
"""

helps['iot dps enrollment'] = """
    type: group
    short-summary: Manage enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment list'] = """
    type: command
    short-summary: List device enrollments in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment show'] = """
    type: command
    short-summary: Get device enrollment details in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment create'] = """
    type: command
    short-summary: Create a device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Create an enrollment '[Enrollment_ID]' with attestation type 'x509' in the Azure
            IoT provisioning service '[DPS_Name]' in the resource group '[Resource_Group_Name]'
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type x509
        --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment '[Enrollment_ID]' with attestation type 'x509' in the Azure
            IoT Device Provisioning Service '[DPS_Name]' in the resource group
            '[Resource_Group_Name]' with provisioning status 'disabled', target IoT Hub
            '[IoTHub_Host_Name]', device id '[Device_Id]' and initial twin
            properties '{"location":{"region":"US"}}'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type x509
        --certificate-path /certificates/Certificate.pem --provisioning-status disabled
        --iot-hub-host-name [IoTHub_Host_Name]
        --initial-twin-properties "{'location':{'region':'US'}}" --device-id [Device_Id]
    - name: Create an enrollment 'MyEnrollment' with attestation type 'tpm' in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type tpm
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
    - name: Create an enrollment 'MyEnrollment' with attestation type 'symmetrickey' in the Azure
            IoT Device Provisioning service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type symmetrickey
        --primary-key [Primary_Key] --secondary-key [Secondary_Key]
    - name: Create an enrollment 'MyEnrollment' with reprovision in the Azure IoT Device Provisioning
            service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type tpm
        --reprovision-policy [Reprovision_Type] --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
    - name: Create an enrollment 'MyEnrollment' with static allocation policy in the Azure
            IoT Device Provisioning service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type tpm --allocation-policy static
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89 --iot-hubs [iot_hub_host_name]
    - name: Create an enrollment 'MyEnrollment' with hashed allocation policy and multiple hubs in the Azure
            IoT Device Provisioning service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --attestation-type tpm --allocation-policy hashed
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89 --iot-hubs "[iot_hub_host_name1] [iot_hub_host_name2]"
"""

helps['iot dps enrollment update'] = """
    type: command
    short-summary: Update a device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment '[Enrollment_ID]' with a new x509 certificate in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrolment_ID] --certificate-path /certificates/NewCertificate.pem
        --etag AAAAAAAAAAA=
    - name: Update enrollment '[Enrollment_ID]' with a new endorsement key in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
        --etag AAAAAAAAAAA=
    - name: Update enrollment '[Enrollment_ID]' with a new primary key in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --primary-key [New_Primary_Key]
        --etag AAAAAAAAAAA=
    - name: Update enrollment '[Enrollment_ID]' with a new reprovision type in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --reprovision-policy [Reprovision_Type]
        --etag AAAAAAAAAAA=
    - name: Update enrollment '[Enrollment_ID]' with a new allocation policy in the Azure IoT
            Device Provisioning Service '[DPS_Name]' in the resource group '[Resource_Group_Name]'.
      text: >
        az iot dps enrollment update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --allocation-policy geolatency
        --etag AAAAAAAAAAA= --iot-hubs "[iot_hub_host_name1] [iot_hub_host_name2] [iot_hub_host_name3]"
"""

helps['iot dps enrollment delete'] = """
    type: command
    short-summary: Delete a device enrollment in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment-group'] = """
    type: group
    short-summary: Manage Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment-group list'] = """
    type: command
    short-summary: List enrollments groups in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment-group show'] = """
    type: command
    short-summary: Get the details of an enrollment group in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps enrollment-group create'] = """
    type: command
    short-summary: Create an enrollment group in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Create an enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service
            '[DPS_Name]' in the resource group '[Resource_Group_Name] using an intermediate certificate as primary certificate'.
      text: >
        az iot dps enrollment-group create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service
            '[DPS_Name]' in the resource group '[Resource_Group_Name] using a CA certificate [Certificate_Name]
            as secondary certificate'.
      text: >
        az iot dps enrollment-group create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --secondary-ca-name [Certificate_Name]
    - name: Create an enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service
            'MyDps' in the resource group '[Resource_Group_Name]' with provisioning status
            'enabled', target IoT Hub '[IoTHub_Host_Name]' and initial twin
            tags '{"location":{"region":"US"}} using an intermediate certificate as primary certificate'.
      text: >
        az iot dps enrollment-group create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --certificate-path /certificates/Certificate.pem
        --provisioning-status enabled --iot-hub-host-name [IoTHub_Host_Name]
        --initial-twin-tags "{'location':{'region':'US'}}"
    - name: Create an enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service
            '[DPS_Name]' in the resource group '[Resource_Group_Name] with attestation type 'symmetrickey'.
      text: >
        az iot dps enrollment-group create -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --primary-key [Primary_Key] --secondary-key [Secondary_Key]

"""

helps['iot dps enrollment-group update'] = """
    type: command
    short-summary: Update an enrollment group in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service '[DPS_Name]'
            in the resource group '[Resource_Group_Name]' with new initial twin tags.
      text: >
        az iot dps enrollment-group update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --initial-twin-tags "{'location':{'region':'US2'}}" --etag AAAAAAAAAAA=
    - name: Update enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service '[DPS_Name]'
            in the resource group '[Resource_Group_Name]' with new primary intermediate certificate
            and remove existing secondary intermediate certificate.
      text: >
        az iot dps enrollment-group update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --certificate-path /certificates/NewCertificate.pem
        --remove-secondary-certificate --etag AAAAAAAAAAA=
    - name: Update enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service '[DPS_Name]'
            in the resource group '[Resource_Group_Name]' with new secondary CA certificate
            '[Certificate_Name]' and remove existing primary CA certificate.
      text: >
        az iot dps enrollment-group update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --secondary-ca-name [Certificate_Name]
        --remove-certificate --etag AAAAAAAAAAA=
    - name: Update enrollment group '[Enrollment_ID]' in the Azure IoT provisioning service '[DPS_Name]'
            in the resource group '[Resource_Group_Name]' with new primary key.
      text: >
        az iot dps enrollment-group update -g [Resource_Group_Name] --dps-name [DPS_Name]
        --enrollment-id [Enrollment_ID] --primary-key [New_Primary_Key] --etag AAAAAAAAAAA=
"""

helps['iot dps enrollment-group delete'] = """
    type: command
    short-summary: Delete an enrollment group in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps registration'] = """
    type: group
    short-summary: Manage Azure IoT Hub Device Provisioning Service registrations.
"""

helps['iot dps registration list'] = """
    type: command
    short-summary: List device registration state in an Azure IoT Hub Device Provisioning
        Service enrollment group.
"""

helps['iot dps registration show'] = """
    type: command
    short-summary: Get the device registration state in an Azure IoT Hub Device Provisioning Service.
"""

helps['iot dps registration delete'] = """
    type: command
    short-summary: Delete a device registration in an Azure IoT Hub Device Provisioning Service.
"""
