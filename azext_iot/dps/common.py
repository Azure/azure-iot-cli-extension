# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
shared: Define shared data types(enums) and constant strings.
"""


# Parameter Arg Groups
DPS_IDENTIFIER = "DPS Identifier"
SYM_KEY_AUTH = "Symmetric Key Authentication"
CERT_AUTH = "x509 Authentication"
TRUST_BUNDLE = "Trust Bundle"

# Error messages from Device SDK
DISABLED_REGISTRATION_ERROR = "Query Status Operation encountered an invalid registration status 'disabled' with a "\
    "status code of 200"
FAILED_REGISTRATION_ERROR = "Query Status operation returned a failed registration status with a status code of '200'"
UNAUTHORIZED_ERROR = "register request returned a service error status code 401"

# Error messages for Client
COMPUTE_KEY_ERROR = "Enrollment group id via --group-id is required if --compute-key is used."
CERTIFICATE_FILE_ERROR = "Both certificate and key files are required for registration with x509."
CERTIFICATE_RETRIEVAL_ERROR = "Please provide the certificate and key files via --certificate-file and --key-file."
TPM_SUPPORT_ERROR = "Device registration with TPM attestation is not supported yet."
