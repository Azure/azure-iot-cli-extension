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

class Certificates:
    # BEGIN CERTIFICATE + base64 content + END CERTIFICATE
    certificate_scenario_one = """-----BEGIN CERTIFICATE-----
        MIIC0DCCAbgCAQAwSDELMAkGA1UEBhMCVVMxEzARBgNVBAgMCldhc2hpbmd0b24x
        EDAOBgNVBAcMB1JlZG1vbmQxEjAQBgNVBAoMCW1pY3Jvc29mdDCCASIwDQYJKoZI
        hvcNAQEBBQADggEPADCCAQoCggEBAKHoysrr3iHghDKT/RKsQnl6zUpLGn0k/iIB
        lTvuYn8RpnMINgXU5bZrPp2oNvCX+CByQyd71e6MVqIgOVDI4fNgAAqLLbAAVxEw
        ZNK6wI3GiAe4S/Dr1LF5pStvjlgiPCmKVCf/tSipVKF/sEYHvZ5NtJqvA3h3dRnj
        inMyuQCxpx5ivTdOQiTi0zDko2Lmuds3w9etzqa5qshPNGmdNjCxFb9AdlROnXLs
        q/F3rjZZCI8TQZWLZwBhGZQ5ZiH0u/uJfoShsDhaSuE8wOMdXoNQYlXe0O/WjbYC
        GBelD8cT3cDILWCDSjZ3mfBG/Btca4N+mgWIkf3wB1M4CHOqiC0CAwEAAaBDMEEG
        CSqGSIb3DQEJDjE0MDIwDgYDVR0PAQH/BAQDAgWgMCAGA1UdJQEB/wQWMBQGCCsG
        AQUFBwMBBggrBgEFBQcDAjANBgkqhkiG9w0BAQsFAAOCAQEAlPoY4Sz+DV1d5+Kc
        VoFyTnsZn8RkJR0OcSM+nERf5KnesQC8zSdJFHWPaeffaxRKQO1RXVbLOv65N1aC
        iBapDyEi/vsuDERKgUzRs6LF0iezASrs5HL3o4pS3zMH7O5NqkYk7RIZOGPdfj6I
        vT5t+zUTsxQFJ9JnwuYQWwcJVbXPEsE0aH6EBHIgm/LZjF0YTXkic3Xkwev8r6bZ
        NhDUw0ak/DVp3AK3jQL6Px0J6SVH7+kP+megyH2ryIsWtE6Z3bNmlwN1rM7Hdm1G
        fTx3QY/W8XM5eAmyY9lj5LWrpIWJxz3gu3QrYUOfKt0w0WCLd1xNxPlobow2euhR
        mk0t+w==
        -----END CERTIFICATE-----"""
    # base64 content only
    certificate_scenario_two = """MIIC0DCCAbgCAQAwSDELMAkGA1UEBhMCVVMxEzARBgNVBAgMCldhc2hpbmd0b24x
        EDAOBgNVBAcMB1JlZG1vbmQxEjAQBgNVBAoMCW1pY3Jvc29mdDCCASIwDQYJKoZI
        hvcNAQEBBQADggEPADCCAQoCggEBAKHoysrr3iHghDKT/RKsQnl6zUpLGn0k/iIB
        lTvuYn8RpnMINgXU5bZrPp2oNvCX+CByQyd71e6MVqIgOVDI4fNgAAqLLbAAVxEw
        ZNK6wI3GiAe4S/Dr1LF5pStvjlgiPCmKVCf/tSipVKF/sEYHvZ5NtJqvA3h3dRnj
        inMyuQCxpx5ivTdOQiTi0zDko2Lmuds3w9etzqa5qshPNGmdNjCxFb9AdlROnXLs
        q/F3rjZZCI8TQZWLZwBhGZQ5ZiH0u/uJfoShsDhaSuE8wOMdXoNQYlXe0O/WjbYC
        GBelD8cT3cDILWCDSjZ3mfBG/Btca4N+mgWIkf3wB1M4CHOqiC0CAwEAAaBDMEEG
        CSqGSIb3DQEJDjE0MDIwDgYDVR0PAQH/BAQDAgWgMCAGA1UdJQEB/wQWMBQGCCsG
        AQUFBwMBBggrBgEFBQcDAjANBgkqhkiG9w0BAQsFAAOCAQEAlPoY4Sz+DV1d5+Kc
        VoFyTnsZn8RkJR0OcSM+nERf5KnesQC8zSdJFHWPaeffaxRKQO1RXVbLOv65N1aC
        iBapDyEi/vsuDERKgUzRs6LF0iezASrs5HL3o4pS3zMH7O5NqkYk7RIZOGPdfj6I
        vT5t+zUTsxQFJ9JnwuYQWwcJVbXPEsE0aH6EBHIgm/LZjF0YTXkic3Xkwev8r6bZ
        NhDUw0ak/DVp3AK3jQL6Px0J6SVH7+kP+megyH2ryIsWtE6Z3bNmlwN1rM7Hdm1G
        fTx3QY/W8XM5eAmyY9lj5LWrpIWJxz3gu3QrYUOfKt0w0WCLd1xNxPlobow2euhR
        mk0t+w=="""
    # non base64 content only
    certificate_scenario_three = "this is not base64 content"
    # EncodeBase64(BEGIN CERTIFICATE + base64 content + END CERTIFICATE)
    certificate_scenario_four = """LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tDQpNSUlEQWpDQ0Flc
        WdBd0lCQWdJVVBHZ04yVUl6bTNndDBUdlM2d29rcVhKTVZnWXdEUVlKS29aSWh2Y05BUUVMDQpCUUF3T3pF
        NU1EY0dBMVVFQXd3d2RHVnpkQzFrWlhacFkyVXROSFJsYzJrMmJXcGhZbUo1YVhWallXeDBaVE5zDQpjRGR
        qYVdkb2RYZ3pOR3B0YVhWdU1CNFhEVEl5TVRJd016QXhORGswTUZvWERUSXlNVEl3TkRBeE5EazBNRm93DQ
        pPekU1TURjR0ExVUVBd3d3ZEdWemRDMWtaWFpwWTJVdE5IUmxjMmsyYldwaFltSjVhWFZqWVd4MFpUTnNjR
        GRqDQphV2RvZFhnek5HcHRhWFZ1TUlJQklqQU5CZ2txaGtpRzl3MEJBUUVGQUFPQ0FROEFNSUlCQ2dLQ0FR
        RUFxbG9WDQpPY3lEUDVuWCtqalNudmgvYnR4UDJSODBKa1FHZGNFRFZhRWl6Wm9xVVdjMGROY3dZdWREaFh
        NWEZLV2ZBVzF1DQpaZVZ5Vm91UFhHY2syWE95VFBOZ3V1R2FHYmswOTYyb2xBREFQQzNoOEZCazA5SzJRc1
        cwM1BPV3QrMWwvem5RDQpRbE5BeG16ck01bThJbWtScERkaGlvVDJQSVErNzJkWHkyZjdwQ3RMK2RQaG5UM
        jB5ZGxQMjZvakw3UHpYWHd0DQoyb0lEN25sclpkQnZWaFBudTErZ0JpS2pBWndTSHUyRS9TQUFQSzJ6cTBt
        dkVHaHZOOWJNMjBEMDFteWo2TXFWDQpCQWxqWEU4aE5RQy8rSTVpVkkvamp5YlcxWThnMXN2VW91TFU2RG5
        zY21XcGgrOXZoRHVjUnFwS1JzUHR0OG5UDQpuTTVCcU1iZHMvbmFtZllOWndJREFRQUJNQTBHQ1NxR1NJYj
        NEUUVCQ3dVQUE0SUJBUUJ2VktCcmRNUUE0UkVmDQp5MVRqYVRWcDNkZUE4bktodXZhSE5VUmM5T2Q1VkZuU
        G9TN2dFR1B3OGZ6aFc3d3ZJTlhKTDVnU1lQd09VbUh1DQo0eHlFQ2FEU0ZaaDZmdysrS3cxMmRxYmQrRG5q
        cC9hMEhOUjBhZFVvcS9USDhDQTV2ZDgyeE4vczRZYlBjTElNDQpEZGxTdi9ZZU44MElOU3hEK21IbnZpaFh
        kR0RiS0d1M0RvZjdLUkNna0QySTFHNFdBUlNyajJ6WU5VcTUxYzdlDQpuR1pDdjZxUFJMb1VSdys2QjdtdH
        NwU282M0g4WVFabEpRRlF0SUJpdG9lTVlBY1lFZnRMTTJtbHYvY050QTFODQpsWHgyaHByMSt1Rm94dVIwZ
        DAyTERlaHpaeXNIUW9oSWt2bzE0WGhIbzFWV2hVeGc3Ry9TRkNsT1RrUjZjaVJCDQp4dERSdGl6Tw0KLS0t
        LS1FTkQgQ0VSVElGSUNBVEUtLS0tLQ=="""
    # BEGIN CERTIFICATE + base64 content
    certificate_scenario_five = """-----BEGIN CERTIFICATE-----
        MIIC0DCCAbgCAQAwSDELMAkGA1UEBhMCVVMxEzARBgNVBAgMCldhc2hpbmd0b24x
        EDAOBgNVBAcMB1JlZG1vbmQxEjAQBgNVBAoMCW1pY3Jvc29mdDCCASIwDQYJKoZI
        hvcNAQEBBQADggEPADCCAQoCggEBAKHoysrr3iHghDKT/RKsQnl6zUpLGn0k/iIB
        lTvuYn8RpnMINgXU5bZrPp2oNvCX+CByQyd71e6MVqIgOVDI4fNgAAqLLbAAVxEw
        ZNK6wI3GiAe4S/Dr1LF5pStvjlgiPCmKVCf/tSipVKF/sEYHvZ5NtJqvA3h3dRnj
        inMyuQCxpx5ivTdOQiTi0zDko2Lmuds3w9etzqa5qshPNGmdNjCxFb9AdlROnXLs
        q/F3rjZZCI8TQZWLZwBhGZQ5ZiH0u/uJfoShsDhaSuE8wOMdXoNQYlXe0O/WjbYC
        GBelD8cT3cDILWCDSjZ3mfBG/Btca4N+mgWIkf3wB1M4CHOqiC0CAwEAAaBDMEEG
        CSqGSIb3DQEJDjE0MDIwDgYDVR0PAQH/BAQDAgWgMCAGA1UdJQEB/wQWMBQGCCsG
        AQUFBwMBBggrBgEFBQcDAjANBgkqhkiG9w0BAQsFAAOCAQEAlPoY4Sz+DV1d5+Kc
        VoFyTnsZn8RkJR0OcSM+nERf5KnesQC8zSdJFHWPaeffaxRKQO1RXVbLOv65N1aC
        iBapDyEi/vsuDERKgUzRs6LF0iezASrs5HL3o4pS3zMH7O5NqkYk7RIZOGPdfj6I
        vT5t+zUTsxQFJ9JnwuYQWwcJVbXPEsE0aH6EBHIgm/LZjF0YTXkic3Xkwev8r6bZ
        NhDUw0ak/DVp3AK3jQL6Px0J6SVH7+kP+megyH2ryIsWtE6Z3bNmlwN1rM7Hdm1G
        fTx3QY/W8XM5eAmyY9lj5LWrpIWJxz3gu3QrYUOfKt0w0WCLd1xNxPlobow2euhR
        mk0t+w=="""
