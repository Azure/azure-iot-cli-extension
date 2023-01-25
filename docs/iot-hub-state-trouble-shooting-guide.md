# IoT Hub State Troubleshooting Guide

This document provides additional help for the command group `az iot hub state` and answers to common questions.

## Definitions and Expected Behavior

The list below mapping hub aspects to hub properties. Any hub property that is not included in the list below may not be exported or imported correctly.

ARM:
 - Built-in event hub's retention time
 - Certificates
 - Cloud to device properties
 - Disable device SAS
 - Disable local auth
 - Enable file upload notifications
 - File upload storage endpoint
 - Identities
   + User-assigned identities
   + System assigned identities (whether it was on or off)
 - Network rule sets
 - Routing
   + Endpoints
   + Fallback route
   + Routes
 - Tags

Configurations:
 - ADM configurations
 - Edge deployments

Devices:
 - Device identities
 - Device twins
 - Device modules
   + Module identities
   + Module twins

### Data structure for Azure Resource Manager (ARM)

When the ARM hub aspect is specified, an ARM template with no parameters will be downloaded and stored under "arm". You can take the template from ARM, save it to another file and use that in an ARM deployment.

#### Connection Strings for Endpoints and File Upload

Connection strings for endpoints and file uploads will be retrieved during the export process.

#### Hub creation with Import and Migrate

If the hub specified for import or the destination hub in migrate does not exist and the ARM aspect is selected, the hub will be created. Below is a list of differences when the hub is created or if it is already created. The reasons for these differences is because the resource group cannot be retrieved from the ARM template and the other properties cannot be changed once the hub exists.

| Hub Property                      | If Destination Hub Exists                                                               | If Destination Hub Does not exist                                                     |
|-----------------------------------|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| Resource Group                    | The resource group for the hub will be retrieved and used if not specified.             | The resource group must be specified in the command, otherwise the command will fail. |
| Location                          | The location will be set to the current destination hub location.                       | The location from the template will be used.                                          |
| Sku                               | The sku will be set to the current destination hub sku.                                 | The sku from the template will be used.                                               |
| Built-in EventHub Partition Count | The partition count will be set to the current destination hub partition count.         | The partition count from the template will be used.                                   |
| Data Residency                    | The data residency flag will be set to the current destination hub data residency flag. | The data residency flag from the template will be used.                               |
| Features                          | The features will be set to the current destination hub features.                       | The features from the template will be used.                                          |

IMPORTANT: if only devices and/or configurations are specified, the destination hub must already be created. Otherwise the command will fail.

### Data structure for configurations

When the configuration hub aspect is specified, ADM configurations and edge deployments will be downloaded and stored under "configurations". The "configurations" section is broken up into "admConfigurations" and "edgeDeployments" and each sub section has a mapping of configuration id to configuration properties.

### Data structure for devices

When the device hub aspect is specified, all devices (including edge and non-edge) will be downloaded and stored under "devices". The section is a mapping of device id to a device object consisting of "identity", "twin", "modules", and "parent" if applicable. The "identity" section will hold the identity of the device and most information about the device. The "twin" section will only hold twin information that is only found in the device twin: tags and desired properties. The "parent" section only holds the device id of the parent device.

The "modules" subsection has a mapping of module id to module object consisting of "identity" and "twin". The "identity" section will hold the identity of the module. The "twin" section will only hold the twin information of the module.

Certain aspects, such as times (ex: lastUpdated, statusUpdateTime), etags (ex: deviceEtag), generation ids, will not be copied over since they cannot be set during device creation.

For devices that use symmetric key authentication, the same symmetric key will be copied over to the destination hub.

### Replace on Import and Migrate

When the replace flag is given for import or migrate, certain hub aspects will be removed before the rest of the hub state is uploaded.

| Aspect         | Deleted Property                                                                     | Clarification                                                    |
|----------------|--------------------------------------------------------------------------------------|------------------------------------------------------------------|
| ARM            | Certificates*                                                                        | If a certificate is present, it will need an etag to be updated. |
| Devices        | (Edge and Non-edge) Device Identities, Device Twins, Module Identities, Module Twins | All devices will be deleted.                                     |
| Configurations | ADM configurations and Edge Deployments                                              | All configurations will be deleted.                              |

Note: for ARM, properties that are not Certificates will be replaced, even if the replace flag is not present, as a result of the ARM template upload.

## Example Export File

For an example of an export file, see [here](samples/iot_hub_state_export.json). In this file, private and sensitive data has been wiped so this file will not work with `az iot hub state import` but the file should provide an example of the overall structure.

## Common Issues

If `az iot hub state migrate` fails, please use `az iot hub state export` with the origin hub followed by `az iot hub state import` with the destination hub. Using these two commands will result in the same functionality but will also create a file. This action will also help pinpoint issues - the information below will refer to export (which includes the export of hub aspects for the origin hub in migrate) and import (which includes the import of hub aspects for the destination hub in migrate).

If the ARM aspect fails, the entire command will fail. Otherwise, if a device or configuration fails to upload or download, the rest of the command will continue with warnings.

### Certificates on Import

If a certificate that is to be imported is already in the destination hub, you will need to delete the certificate before it can be replaced. This can be achieved by using the replace flag with the ARM aspect.

An etag is needed to update the certificate in the destination hub, but the ARM template for IoT Hub certificates does not accept etags. Thus, the only solution is to delete the current certificate and upload the imported certificate.

### System Identity Assignment on Import

If System Identity is not enabled during Import, it will be enabled during import and a principal id will be assigned. This will not copy over any assigned permissions to the hub.

If System Identity is already enabled, the principal id will not be regenerated and any current permissions should work.

#### Endpoints with System Identity Authentication on Import

Endpoints with System Identity authentication will be successfully copied over only if:

1. The destination hub already has system assigned identity enabled
2. The service the endpoint is connected to exists
3. The service the endpoint is connected to has the correct permissions to the destination hub's system identity.

If either of the above conditions are not met, the endpoint will not be copied and the command will fail.

To fix this, add the permissions needed for the system assigned identity and rerun the command. If this cannot be done because the hub does not exist yet (or system assigned permissions are not enabled):
 1. Make a copy of the state you want to import and remove the offending endpoint(s) in your copy
 2. Run `az iot hub state import` with the copied file
 3. Check that the hub has been created and system assigned identity is enabled
 4. Assign the correct permissions for the IoT Hub's system assigned identity to the correct endpoint scope(s)
 5. Run `az iot hub state import` with the original file (with the endpoint(s)) or create the endpoint manually

### Endpoints and Routes on Export

The export command will retrieve connection strings for endpoints that have key-based authentication. If the IoT hub has an endpoint that is connected to a deleted instance of a service, that endpoint and any routes using that endpoint will not be exported.

The export command will also check if the service the endpoint is connected to exists for endpoints with System Identity or User Identity authentication.

### Private Endpoints on Import

Private Endpoints are not supported currently. They will be ignored during import.

### Devices and Configurations

If you cannot export or import any device or configurations, please check access to your devices and configurations using `az iot hub device-identity list` and `az iot hub configuration list` respectively.

Private endpoints and restricted public network access would limit whether you can import or export devices and configurations. Please check these settings before proceeding.

### Limitations with different IoT Hub Skus

There are some limitations with different IoT Hub Skus which can cause failures, especially when downgrading Skus. Please refer to the documentation [here](https://learn.microsoft.com/en-us/azure/iot-hub/iot-hub-scaling).

## Further Reading

For a manual guide, please refer to the documention [here](https://learn.microsoft.com/en-us/azure/iot-hub/iot-hub-how-to-clone).
