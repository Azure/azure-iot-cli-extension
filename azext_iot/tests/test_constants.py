# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum


class ResourceTypes(Enum):
    """
    Resource types to use with az resource
    """
    central = "Microsoft.IoTCentral/IoTApps"
    hub = "Microsoft.Devices/IotHubs"
    dps = "Microsoft.Devices/provisioningServices"


class FileNames:
    central_device_template_file = "central/json/device_template.json"
    central_edge_template_file = "central/json/device_template_edge.json"
    central_deeply_nested_device_template_file = (
        "central/json/deeply_nested_template.json"
    )
    central_device_file = "central/json/device.json"
    central_edge_devices_file = "central/json/edge_devices.json"
    central_edge_children_file = "central/json/edge_children.json"
    central_device_group_file = "central/json/device_group.json"
    central_organization_file = "central/json/organization.json"
    central_role_file = "central/json/role.json"
    central_user_file = "central/json/users.json"
    central_job_file = "central/json/job.json"
    central_scheduled_job_file = "central/json/scheduled_job.json"
    central_enrollment_group_file = "central/json/enrollment_group.json"
    central_enrollment_group_x509_file = "central/json/enrollment_group_x509.json"
    central_fileupload_file = "central/json/fileupload.json"
    central_device_twin_file = "central/json/device_twin.json"
    central_edge_modules_file = "central/json/edge_modules.json"
    central_device_component_file = "central/json/device_components.json"
    central_device_properties_file = "central/json/device_properties.json"
    central_property_validation_template_file = (
        "central/json/property_validation_template.json"
    )
    central_query_response_file = "central/json/query_response.json"
    central_destination_file = "central/json/destination.json"
    central_export_file = "central/json/export.json"


class CertificatesMessage:
    invalidBase64 = "The certificate content is not a valid base64 string value"
    unmatchedSegment = ("The certificate does not contain matched BEGIN and END segments, please either have both '-----BEGIN "
                        "CERTIFICATE-----' and '-----END CERTIFICATE-----', or consider deleting them.")
