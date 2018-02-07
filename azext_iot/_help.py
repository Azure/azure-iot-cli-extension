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
                   Augmented with the IoT Extension.
"""

helps['iot hub'] = """
    type: group
    short-summary: Manage entities in an Azure IoT Hub.
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
        az iot hub device-identity create -n [IoTHub Name] -d [Device ID] -ee
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert valid for 10 days then use its thumbprint.
      text: >
        az iot hub device-identity create -n [IoTHub Name] -d [Device ID]
        -am x509_thumbprint --valid-days 10
    - name: Create an IoT device with self-signed certificate authorization,
            generate a cert of default expiration (365 days) and output to target directory.
      text: >
        az iot hub device-identity create -n [IoTHub Name] -d [Device ID] -am x509_thumbprint
        --output-dir /path/to/output
    - name: Create an IoT device with self-signed certificate authorization and
            explicitly provide primary and secondary thumbprints.
      text: >
        az iot hub device-identity create -n [IoTHub Name] -d [Device ID] -am x509_thumbprint
        -ptp [Thumbprint 1] -stp [Thumbprint 2]
    - name: Create an IoT device with root CA authorization with disabled status and reason
      text: >
        az iot hub device-identity create -n [IoTHub Name] -d [Device ID] -am x509_ca
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
        az iot hub device-identity update -d [Device ID] -n [IoTHub Name]
        --set capabilities.iotEdge=true
    - name: Disable device status
      text: >
        az iot hub device-identity update -d [Device ID] -n [IoTHub Name] --set status=disabled
    - name: In one command
      text: >
        az iot hub device-identity update -d [Device ID] -n [IoTHub Name]
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
        az iot hub device-twin update --device-id [Device ID] --hub-name [IoTHub Name]
        --set tags='{"location":{"region":"US"}}'
    - name: Remove the 'region' property from parent 'location' property
      text: >
        az iot hub device-twin update --device-id [Device ID] --hub-name [IoTHub Name]
        --set tags.location.region='null'
"""

helps['iot hub device-twin replace'] = """
    type: command
    short-summary: Replace device twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace device twin with file contents.
      text: >
        az iot hub device-twin replace -d [Device ID] -n [IoTHub Name] -j ../mydevicetwin.json
"""

helps['iot hub module-identity'] = """
    type: group
    short-summary: Manage IoT Edge modules.
"""

helps['iot hub module-identity show-connection-string'] = """
    type: command
    short-summary: Show a target IoT Edge module connection string.
"""

helps['iot hub module-identity create'] = """
    type: command
    short-summary: Create a module on a target IoT Edge device in an IoT Hub.
"""

helps['iot hub module-identity show'] = """
    type: command
    short-summary: Get the details of an IoT Edge module.
"""

helps['iot hub module-identity list'] = """
    type: command
    short-summary: List modules of an IoT Edge device.
"""

helps['iot hub module-identity update'] = """
    type: command
    short-summary: Update an IoT Hub Edge module.
    long-summary: Use --set followed by property assignments for updating a module.
                  Leverage properties returned from 'iot hub module-identity show'.
    examples:
    - name: Regenerate module symmetric authentication keys
      text: >
        az iot hub module-identity update -m [Module Name] -d [Device ID] -n [IoTHub Name]
        --set authentication.symmetricKey.primaryKey="[Key Value]"
        authentication.symmetricKey.secondaryKey="[key value]"
"""

helps['iot hub module-identity delete'] = """
    type: command
    short-summary: Delete a device in an IoT Hub.
"""

helps['iot hub module-twin'] = """
    type: group
    short-summary: Manage IoT Edge module twin configuration.
"""

helps['iot hub module-twin show'] = """
    type: command
    short-summary: Get a module twin definition.
"""

helps['iot hub module-twin update'] = """
    type: command
    short-summary: Update module twin definition.
    long-summary: Use --set followed by property assignments for updating a module.
                  Leverage properties returned from 'iot hub module-twin show'.
    examples:
    - name: Add desired properties to module twin.
      text: >
        az iot hub module-twin update -d [Device ID] -n [IoTHub Name] -m [Module Name] --set
        properties.desired='{"conditions":{"temperature":{"warning":70, "critical":100}}}'
    - name: Remove 'critical' property from parent 'temperature'
      text: >
        az iot hub module-twin update -d mydevice -n myhub -m mymod --set
        properties.desired.condition.temperature.critical='null'
"""

helps['iot hub module-twin replace'] = """
    type: command
    short-summary: Replace module twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace module twin with file contents.
      text: >
        az iot hub module-twin replace -d [Device ID] -n [IoTHub Name]
        -m [Module Name] -j ../mymodtwin.json
"""

helps['iot hub apply-configuration'] = """
    type: command
    short-summary: Apply deployment manifest to a single device.
    long-summary: Manifest content is json and must have root element of 'content' or 'moduleContent'
                  e.g. {"content":{...}} or {"moduleContent":{...}}
    examples:
    - name: Test configuration while in development.
      text: >
        az iot hub apply-configuration --hub-name [IoTHub Name] --device-id [Device ID]
        --content ../mycontent.json
"""

helps['iot hub generate-sas-token'] = """
    type: command
    short-summary: Generate a SAS token for a target hub or device.
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
        az iot hub query -n [IoTHub Name] -q "select * from devices"
    - name: Query all module twin data on target device.
      text: >
        az iot hub query -n [IoTHub Name] -q "select * from devices.modules where devices.deviceId = '[Device ID]'"
"""

helps['iot hub show-connection-string'] = """
    type: command
    short-summary: Show a target IoT Hub Connection String.
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

helps['iot device send-d2c-message'] = """
    type: command
    short-summary: Send an MQTT device-to-cloud message.
"""

helps['iot device simulate'] = """
    type: command
    short-summary: Simulate a device in an Azure IoT Hub.
"""

helps['iot device upload-file'] = """
    type: command
    short-summary: Upload a local file as a device to a pre-configured blob storage container.
"""

helps['iot edge'] = """
    type: group
    short-summary: Deploy and manage IoT solutions on the Edge.
"""

helps['iot edge deployment'] = """
    type: group
    short-summary: Configure IoT Edge deployments.
"""

helps['iot edge deployment create'] = """
    type: command
    short-summary: Create an IoT Edge deployment in the target IoT Hub.
    long-summary: Configuration json must have root of 'content' like {"content":{...}}.
    examples:
    - name: Create deployment with condition where a device is in 'building 9' and
            the environment is 'test'.
      text: >
        az iot edge deployment create -c [configuration] -n [IoTHub Name] --content ../mycontent.json
        -lab '{"key0":"value0", "key1":"value1"}'
        --target-condition "tags.building=9 and tags.environment='test'" --priority 3
"""

helps['iot edge deployment show'] = """
    type: command
    short-summary: Get the details of an IoT Edge configuration in an IoT Hub.
"""

helps['iot edge deployment list'] = """
    type: command
    short-summary: List IoT Edge configurations in an IoT Hub.
"""

helps['iot edge deployment update'] = """
    type: command
    short-summary: Update an IoT Edge deployment configuration with the specified properties.
    long-summary: Use --set followed by property assignments for updating a deployment configuration.
                  Leverage properties returned from 'az iot edge deployment show'.
    examples:
    - name: Alter the priority of a deployment configuration and update the targetCondition
      text: >
        az iot edge deployment update -c [configuration] -n [IoTHub Name] --set priority=10
        targetCondition="tags.building=43 and tags.environment='dev'"
"""

helps['iot edge deployment delete'] = """
    type: command
    short-summary: Delete an IoT Hub Edge deployment.
"""

helps['iot dps'] = """
    type: group
    short-summary: Manage entities in Azure IoT Hub Device Provisioning Service.
                   Augmented with the IoT Extension.
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
    - name: Create an enrollment '[Enrollment ID]' with attestation type 'x509' in the Azure
            IoT provisioning service '[DPS Name]' in the resource group '[Resource Group Name]'
      text: >
        az iot dps enrollment create -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --attestation-type x509
        --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment '[Enrollment ID]' with attestation type 'x509' in the Azure
            IoT Device Provisioning Service '[DPS Name]' in the resource group
            '[Resource Group Name]' with provisioning status 'disabled', target IoT Hub
            '[IoTHub Name].azure-devices.net', device id '[Device ID]' and initial twin
            properties '{"location":{"region":"US"}}'.
      text: >
        az iot dps enrollment create -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --attestation-type x509
        --certificate-path /certificates/Certificate.pem --provisioning-status disabled
        --iot-hub-host-name [IoTHub Name].azure-devices.net
        --initial-twin-properties "{'location':{'region':'US'}}" --device-id [Device ID]
    - name: Create an enrollment 'MyEnrollment' with attestation type 'tpm' in the Azure IoT
            Device Provisioning Service '[DPS Name]' in the resource group '[Resource Group Name]'.
      text: >
        az iot dps enrollment create -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --attestation-type tpm
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
"""

helps['iot dps enrollment update'] = """
    type: command
    short-summary: Update a device enrollment in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment '[Enrollment ID]' with a new x509 certificate in the Azure IoT
            Device Provisioning Service '[DPS Name]' in the resource group '[Resource Group Name]'.
      text: >
        az iot dps enrollment update -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrolment ID] --certificate-path /certificates/NewCertificate.pem
        --etag AAAAAAAAAAA=
    - name: Update enrollment '[Enrollment ID]' with a new endorsement key in the Azure IoT
            Device Provisioning Service '[DPS Name]' in the resource group '[Resource Group Name]'.
      text: >
        az iot dps enrollment update -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
        --etag AAAAAAAAAAA=
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
    - name: Create an enrollment group '[Enrollment ID]' in the Azure IoT provisioning service
            '[DPS Name]' in the resource group '[Resource Group Name]'.
      text: >
        az iot dps enrollment-group create -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment group '[Enrollment ID]' in the Azure IoT provisioning service
            'MyDps' in the resource group '[Resource Group Name]' with provisioning status
            'enabled', target IoT Hub '[IoTHub Name].azure-devices.net' and initial twin
            tags '{"location":{"region":"US"}}'.
      text: >
        az iot dps enrollment-group create -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --certificate-path /certificates/Certificate.pem
        --provisioning-status enabled --iot-hub-host-name [IoTHub Name].azure-devices.net
        --initial-twin-tags "{'location':{'region':'US'}}"
"""

helps['iot dps enrollment-group update'] = """
    type: command
    short-summary: Update an enrollment group in an Azure IoT Hub Device Provisioning Service.
    examples:
    - name: Update enrollment group '[Enrollment ID]' with a new certificate in the
            Azure IoT provisioning service '[DPS name]' in the resource group
            'MyResourceGroup' and update its initial twin tags.
      text: >
        az iot dps enrollment-group update -g [Resource Group Name] --dps-name [DPS Name]
        --enrollment-id [Enrollment ID] --certificate-path /certificates/NewCertificate.pem
        --initial-twin-tags "{'location':{'region':'US2'}}" --etag AAAAAAAAAAA=
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
