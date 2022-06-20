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
    central_fileupload_file = "central/json/fileupload.json"
    central_device_twin_file = "central/json/device_twin.json"
    central_device_attestation_file = "central/json/device_attestation.json"
    central_edge_modules_file = "central/json/edge_modules.json"
    central_device_component_file = "central/json/device_components.json"
    central_device_properties_file = "central/json/device_properties.json"
    central_property_validation_template_file = (
        "central/json/property_validation_template.json"
    )
    central_query_response_file = "central/json/query_response.json"
    central_destination_file = "central/json/destination.json"
    central_export_file = "central/json/export.json"
