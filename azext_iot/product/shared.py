# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from enum import Enum


class TaskType(Enum):
    QueueTestRun = "QueueTestRun"
    GenerateTestCases = "GenerateTestCases"


class BadgeType(Enum):
    IotDevice = "IotDevice"
    Pnp = "Pnp"
    IotEdgeCompatible = "IotEdgeCompatible"


class AttestationType(Enum):
    symmetricKey = "SymmetricKey"
    tpm = "TPM"
    x509 = "X509"
    connectionString = "ConnectionString"


class DeviceType(Enum):
    FinishedProduct = "FinishedProduct"
    DevKit = "DevKit"


class DeviceTestTaskStatus(Enum):
    queued = "Queued"
    started = "Started"
    running = "Running"
    completed = "Completed"
    failed = "Failed"
    cancelled = "Cancelled"


class ValidationType(Enum):
    test = "Test"
    certification = "Certification"


BASE_URL = "https://prod.certsvc.trafficmanager.net"
