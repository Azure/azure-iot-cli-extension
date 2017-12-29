# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.help_files import helps


helps['iot'] = """
    type: group
    short-summary: Manage Internet of Things (IoT) assets.
                   Augmented with the IoT Extension.
"""

helps['iot hub'] = """
    type: group
    short-summary: Manage entities in your Azure IoT Hub.
"""

helps['iot hub device-identity'] = """
    type: group
    short-summary: Manage IoT devices.
"""

helps['iot hub device-identity create'] = """
    type: command
    short-summary: Create a device in an IoT Hub.
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
    long-summary: Use --set followed by property assignments for updating your device.
                  Leverage parameters returned from 'iot hub device-identity show'.
    examples:
    - name: Turn on edge capabilities for device
      text: >
        az iot hub device-identity update -d mydevice -n myhub --set capabilities.iotEdge=true
    - name: Disable device status
      text: >
        az iot hub device-identity update -d mydevice -n myhub --set status=disabled
    - name: In one command
      text: >
        az iot hub device-identity update -d mydevice -n myhub --set status=disabled capabilities.iotEdge=true
"""

helps['iot hub device-identity delete'] = """
    type: command
    short-summary: Delete a device in an IoT Hub.
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
    long-summary: Use --set followed by property assignments for updating your device twin.
                  Leverage properties returned from 'iot hub device-twin show'.
    examples:
    - name: Add nested tags to device twin
      text: >
        az iot hub device-twin update --device-id mydevice --hub-name myhub --set tags='{"location":{"region":"US"}}'
"""

helps['iot hub device-twin replace'] = """
    type: command
    short-summary: Replace device twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace device twin with file contents
      text: >
        az iot hub device-twin replace -d mydevice -n myhub -j ../mydevicetwin.json
"""

helps['iot hub module-identity'] = """
    type: group
    short-summary: Manage IoT Edge modules.
"""

helps['iot hub module-identity show-connection-string'] = """
    type: command
    short-summary: Show a target IoT Hub Edge module connection string.
"""

helps['iot hub module-identity create'] = """
    type: command
    short-summary: Create a module on target device in an IoT hub.
"""

helps['iot hub module-identity show'] = """
    type: command
    short-summary: Get the details of an IoT Hub module.
"""

helps['iot hub module-identity list'] = """
    type: command
    short-summary: List modules of an IoT Hub Edge device.
"""

helps['iot hub module-identity update'] = """
    type: command
    short-summary: Update an IoT Hub Edge module.
    long-summary: Use --set followed by property assignments for updating your module.
                  Leverage properties returned from 'iot hub module-identity show'.
    examples:
    - name: Regenerate module symmetric authentication keys
      text: >
        az iot hub module-identity update -m mymod -d mydevice -n myhub --set authentication.symmetricKey.primaryKey=""
        authentication.symmetricKey.secondaryKey=""
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
    long-summary: Use --set followed by property assignments for updating your module.
                  Leverage properties returned from 'iot hub module-twin show'.
    examples:
    - name: Add desired properties to module twin
      text: >
        az iot hub module-twin update -d mydevice -n myhub -m mymod --set
        properties.desired='{"conditions":{"temperature":{"warning":70, "critical":100}}}'
"""

helps['iot hub module-twin replace'] = """
    type: command
    short-summary: Replace module twin definition with target json.
    long-summary: Input json directly or use a file path.
    examples:
    - name: Replace module twin with file contents
      text: >
        az iot hub module-twin replace -d mydevice -n myhub -m mymod -j ../mymodtwin.json
"""

helps['iot hub apply-configuration'] = """
    type: command
    short-summary: Apply deployment manifest to a single device.
    long-summary: Manifest content is json and must have root element of 'content' or 'moduleContent'
                  e.g. {"content":{...}} or {"moduleContent":{...}}
    examples:
    - name: Test configuration while in development
      text: >
        az iot hub apply-configuration --hub-name myhub --device-id mydevice --content ../mycontent.json
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
    - name: Query all device twin data on hub
      text: >
        az iot hub query -n myhub -q "select * from devices"
    - name: Query all module twin data on target device
      text: >
        az iot hub query -n myhub -q "select * from devices.modules where devices.deviceId = 'mydevice'"
"""

helps['iot hub show-connection-string'] = """
    type: command
    short-summary: Show a target IoT Hub's connection string.
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
    short-summary: Simulate a device on your Azure IoT Hub.
"""

helps['iot device upload-file'] = """
    type: command
    short-summary: Upload a local file as a device to a pre-configured blob storage container.
"""

helps['iot edge'] = """
    type: group
    short-summary: Deploy and manage your IoT solutions on the Edge.
"""

helps['iot edge deployment'] = """
    type: group
    short-summary: Configure your IoT Edge deployments.
"""

helps['iot edge deployment create'] = """
    type: command
    short-summary: Create an edge deployment in the target IoT Hub.
    long-summary: Configuration json must have root of 'content' like {"content":{...}}.
    examples:
    - name: Create deployment with condition that device is in building 9 and environment is test.
      text: >
        az iot edge deployment create -c myconfig -n myhub --content ../mycontent.json -lab '{"key0":"value0", "key1":"value1"}'
        --target-condition "tags.building=9 and tags.environment='test'" --priority 3
"""

helps['iot edge deployment show'] = """
    type: command
    short-summary: Get the details of an edge configuration in an IoT hub.
"""

helps['iot edge deployment list'] = """
    type: command
    short-summary: List edge configurations in an IoT hub.
"""

helps['iot edge deployment update'] = """
    type: command
    short-summary: Update an IoT Edge deployment configuration with the specified properties.
    long-summary: Use --set followed by property assignments for updating your deployment configuration.
                  Leverage properties returned from 'az iot edge deployment show'.
    examples:
    - name: Alter the priority of a deployment configuration and update the targetCondition
      text: >
        az iot edge deployment update -c myconfig -n myhub --set priority=10
        targetCondition="tags.building=43 and tags.environment='dev'"
"""

helps['iot edge deployment delete'] = """
    type: command
    short-summary: Delete an IoT Hub Edge deployment.
"""

helps['iot dps'] = """
    type: group
    short-summary: Manage Azure IoT provisioning services.
                   Augmented with the IoT Extension.
"""

helps['iot dps enrollment'] = """
    type: group
    short-summary: Manage Azure Provisioning Service Enrollments
"""

helps['iot dps enrollment list'] = """
    type: command
    short-summary: List device enrollments in an Azure provisioning service 
"""

helps['iot dps enrollment show'] = """
    type: command
    short-summary: Get the details of an Azure Provisioning Service device enrollment
"""

helps['iot dps enrollment create'] = """
    type: command
    short-summary: Create an Azure Provisioning Service device enrollment
    examples:
    - name: Create an enrollment 'MyEnrollment' with attestation type 'x509' in the Azure IoT provisioning service 'MyDps'
            in the resource group 'MyResourceGroup'
      text: >
        az iot dps enrollment create -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment --attestation-type x509
        --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment 'MyEnrollment' with attestation type 'x509' in the Azure IoT provisioning service 'MyDps'
            in the resource group 'MyResourceGroup' with provisioning status 'disabled', target IoT Hub 'MyHub.azure-devices.net', 
            device id 'MyDevice' and initial twin properties '{"location":{"region":"US"}}'
      text: >
        az iot dps enrollment create -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment --attestation-type x509
        --certificate-path /certificates/Certificate.pem --provisioning-status disabled --iot-hub-host-name MyHub.azure-devices.net
        --initial-twin-properties {\\"location\\":{\\"region\\":\\"US\\"}} --device-id MyDevice
    - name: Create an enrollment 'MyEnrollment' with attestation type 'tpm' in the Azure IoT provisioning service 'MyDps'
            in the resource group 'MyResourceGroup' 
      text: >
        az iot dps enrollment create -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment --attestation-type tpm
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89
"""

helps['iot dps enrollment update'] = """
    type: command
    short-summary: Update an Azure Provisioning Service device enrollment
    examples:
    - name: Update enrollment 'MyEnrollment' with a new x509 certificate in the Azure IoT provisioning service 'MyDps'
            in the resource group 'MyResourceGroup' 
      text: >
        az iot dps enrollment update -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment
        --certificate-path /certificates/NewCertificate.pem --etag AAAAAAAAAAA=
    - name: Update enrollment 'MyEnrollment' with a new endorsement key in the Azure IoT provisioning service 'MyDps'
            in the resource group 'MyResourceGroup'
      text: >
        az iot dps enrollment update -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment
        --endorsement-key 14963E8F3BA5B3984110B3C1CA8E8B89 --etag AAAAAAAAAAA=
"""

helps['iot dps enrollment delete'] = """
    type: command
    short-summary: Delete an Azure Provisioning Service device enrollment
"""

helps['iot dps enrollment-group'] = """
    type: group
    short-summary: Manage Azure Provisioning Service Enrollments Group
"""

helps['iot dps enrollment-group list'] = """
    type: command
    short-summary: List device enrollments in an Azure provisioning service group
"""

helps['iot dps enrollment-group show'] = """
    type: command
    short-summary: Get the details of an Azure Provisioning Service device enrollment group
"""

helps['iot dps enrollment-group create'] = """
    type: command
    short-summary: Create an Azure Provisioning Service device enrollment group
    examples:
    - name: Create an enrollment group 'MyEnrollment' in the Azure IoT provisioning service 'MyDps' in the resource group
            'MyResourceGroup'
      text: >
        az iot dps enrollment-group create -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment
        --certificate-path /certificates/Certificate.pem
    - name: Create an enrollment group 'MyEnrollment' in the Azure IoT provisioning service 'MyDps' in the resource group
            'MyResourceGroup' with provisioning status 'enabled', target IoT Hub 'MyHub.azure-devices.net' 
            and initial twin tags '{"location":{"region":"US"}}'
      text: >
        az iot dps enrollment-group create -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment 
        --certificate-path /certificates/Certificate.pem --provisioning-status enabled --iot-hub-host-name MyHub.azure-devices.net
        --initial-twin-tags {\\"location\\":{\\"region\\":\\"US\\"}}
"""

helps['iot dps enrollment-group update'] = """
    type: command
    short-summary: Update an Azure Provisioning Service device enrollment group
    examples:
    - name: Update enrollment group 'MyEnrollment' in the Azure IoT provisioning service 'MyDps' in the resource group
            'MyResourceGroup'
      text: >
        az iot dps enrollment-group update -g MyResourceGroup --dps-name MyDps --enrollment-id MyEnrollment
        --certificate-path /certificates/NewCertificate.pem --etag AAAAAAAAAAA=
"""

helps['iot dps enrollment-group delete'] = """
    type: command
    short-summary: Delete an Azure Provisioning Service device enrollment group
"""
