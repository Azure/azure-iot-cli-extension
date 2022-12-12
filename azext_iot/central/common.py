# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types

"""

from enum import Enum

from azext_iot.central.models.enum import ApiVersion

EDGE_ONLY_FILTER = "type eq 'GatewayDevice' or type eq 'EdgeDevice'"

API_VERSION = ApiVersion.ga.value
API_VERSION_PREVIEW = ApiVersion.preview.value


class DestinationType(Enum):
    """
    Data Export destination type.
    """

    Webhook = "webhook@v1"
    BlobStorage = "blobstorage@v1"
    AzureDataExplorer = "dataexplorer@v1"
    ServiceBusQueue = "servicebusqueue@v1"
    ServiceBusTopic = "servicebustopic@v1"
    EventHub = "eventhubs@v1"


class ExportSource(Enum):
    """
    Data Export Source.
    """

    Telemetry = "telemetry"
    Properties = "properties"
    DeviceLifecycle = "deviceLifecycle"
    DeviceTemplateLifecycle = "deviceTemplateLifecycle"
    DeviceConnectivity = "deviceConnectivity"


class X509CertificateEntry(Enum):
    """
    X509 Attestation Certificate Entry Type
    """

    Primary = "primary"
    Secondary = "secondary"


class JobBatchType(Enum):
    """
    Job Batch Type
    """

    Number = "number"
    Percentage = "percentage"


class EnrollmentGroupProvisionStatus(Enum):
    """
    Enable or disable enrollment entry.

    """

    Disabled = "disabled"
    Enabled = "enabled"


class EnrollmentGroupAttestationType(Enum):
    """
    X509 or Symmetric
    """

    X509 = "x509"
    SymmetricKey = "symmetricKey"
