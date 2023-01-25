# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

OVERWRITE_FILE_MSG = "File {0} is not empty. Overwrite file? "
FILE_NOT_EMPTY_ERROR = "Command aborted. Include the --replace flag to overwrite file."
FILE_NOT_FOUND_ERROR = 'File {0} does not exist.'
LOGIN_WITH_ARM_ERROR = "Hub aspect 'arm' is not supported with connection string via --login."
TARGET_HUB_NOT_FOUND_MSG = "Destination IoT Hub {0} was not found and cannot be created with current hub aspects."
MISSING_RG_ON_CREATE_ERROR = "Please provide the resource group for the hub that will be created."
SAVE_STATE_MSG = "Saved state of IoT Hub '{0}' to {1}"
UPLOAD_STATE_MSG = "Uploaded state from '{0}' to IoT Hub '{1}'"
MIGRATE_STATE_MSG = "Migrated state from IoT Hub '{0}' to IoT Hub '{1}'"
FAILED_ARM_MSG = "Arm deployment for IoT Hub {0} failed."
FAILED_ARM_IDENTITY_ENDPOINT_MSG = "Cannot create IoT Hub {0} because the endpoints {1} have Identity Based authentication."
HUB_NOT_CREATED_MSG = "IoT Hub {0} was not created because the arm template was missing in the state file."
DELETE_CERT_DESC = "Deleting certificates from destination hub"
SAVE_CONFIGURATIONS_DESC = "Saving ADM configurations and Edge Deployments"
SAVE_CONFIGURATIONS_RETRIEVE_FAIL_MSG = "Failed to retrieve configurations. Skipping configuration retrieval."
SAVE_DEVICE_DESC = "Saving devices and modules"
SAVE_DEVICES_RETRIEVE_FAIL_MSG = "Failed to retrieve devices. Skipping devices retrieval."
SAVE_SPECIFIC_DEVICE_RETRIEVE_FAIL_MSG = "Failed to retrieve device {0}. Skipping this device."
SAVE_SPECIFIC_DEVICE_MODULES_RETRIEVE_FAIL_MSG = "Failed to retrieve modules for device {0}. Skipping modules for this device."
SAVE_SPECIFIC_DEVICE_SPECIFIC_MODULE_RETRIEVE_FAIL_MSG = "Failed to retrieve module {0} for module {1} for device {2}. \
Skipping this module for this device."
SAVE_UAI_RETRIEVE_FAIL_MSG = "Failed to retrieve information for User Assigned Identity {0}. Skipping this identity."
SAVE_ENDPOINT_RETRIEVE_FAIL_MSG = "Failed to retrieve permissions for {0} endpoint {1}. Skipping this endpoint."
SAVE_ENDPOINT_UAI_RETRIEVE_FAIL_MSG = "Skipping {0} endpoint {1} because it relies on missing user assigned identity {2}."
SAVE_ENDPOINT_INFO_RETRIEVE_FAIL_MSG = "Failed to retrieve information for {0} endpoint {1}. Skipping this endpoint."
SAVE_ROUTE_FAIL_MSG = "Skipping route {0} because it relies on endpoint {1}."
SAVE_FILE_UPLOAD_UAI_RETRIEVE_FAIL_MSG = "Skipping the file upload because it relies on user assigned identity {0}."
SAVE_FILE_UPLOAD_RETRIEVE_FAIL_MSG = "Failed to retrieve permissions for file upload. Skipping the file upload."
SAVE_ARM_DESC = "Saved ARM template."
PRIVATE_ENDPOINT_WARNING_MSG = "Private endpoints for IoT Hub will be ignored for state import."
CREATE_IOT_HUB_MSG = "Created IoT Hub {0}."
UPDATED_IOT_HUB_MSG = "Updated IoT Hub {0}."
UPLOAD_CONFIGURATIONS_DESC = "Uploading ADM configurations and Edge Deployments"
UPLOAD_ADM_CONFIG_ERROR_MSG = "Failed to upload ADM configuration {0}. Error Message: {1}"
UPLOAD_EDGE_DEPLOYMENT_ERROR_MSG = "Failed to upload Edge Deployment {0}. Error Message: {1}"
UPLOAD_DEVICE_MSG = "Uploading devices and modules"
UPLOAD_DEVICE_IDENTITY_MSG = "Failed to upload device identity for {0}. Proceeding to next device. Error Message: {1}"
UPLOAD_DEVICE_TWIN_MSG = "Failed to upload device twin for {0}. Proceeding to next device. Error Message: {1}"
UPLOAD_DEVICE_MODULE_IDENTITY_MSG = "Failed to upload module identity for {0} for the device {1}. Proceeding to next module. \
Error Message: {2}"
UPLOAD_DEVICE_MODULE_TWIN_MSG = "Failed to upload module twin for {0} for the device {1}. Proceeding to next module. Error \
Message: {2}"
UPLOAD_EDGE_MODULE_MSG = "Failed to upload edge modules for the device {0}. Proceeding to next device. Error Message: {1}"
UPLOAD_DEVICE_RELATIONSHIP_MSG = "Failed to set parent-child relationship for the parent device {0} to the child device {1}. \
Error Message: {2}"
MISSING_HUB_ASPECTS_MSG = " Some hub aspects ({0}) were not uploaded because the necessary aspects were not found in the file."
BAD_DEVICE_AUTHORIZATION_MSG = "Authorization type for module '{0}' in device '{1}' not recognized."
BAD_DEVICE_MODULE_AUTHORIZATION_MSG = "Authorization type for module '{0}' in device '{1}' not recognized."
SKIP_CONFIGURATION_DELETE_MSG = "Failed to retrieve configurations. Skipping configuration deletion."
DELETE_CONFIGURATION_DESC = "Deleting configurations from destination hub"
DELETE_CONFIGURATION_FAILURE_MSG = "Configuration '{0}' not found during hub clean-up."
DELETE_DEVICES_DESC = "Deleting device identities from destination hub"
DELETE_DEVICES_FAILURE_MSG = "Device identity '{0}' not found during hub clean-up."
