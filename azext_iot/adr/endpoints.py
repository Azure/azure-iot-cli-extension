# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Explicit ARM routing for ADR and its linked management-plane dependencies."""

import os

from azure.cli.core.azclierror import InvalidArgumentValueError

from azext_iot._factory import _ADR_CANARY_ARM_ENDPOINT as CANARY_ARM_ENDPOINT

PUBLIC_ARM_ENDPOINT = "https://management.azure.com"


def get_adr_arm_endpoint():
    """Keep canary by default; never infer an ARM host from a resource location."""
    endpoint = os.getenv("AZURE_IOT_ADR_ARM_ENDPOINT", CANARY_ARM_ENDPOINT).rstrip("/").lower()
    if endpoint not in {CANARY_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT}:
        raise InvalidArgumentValueError(
            "AZURE_IOT_ADR_ARM_ENDPOINT must be https://management.azure.com "
            "or https://centraluseuap.management.azure.com."
        )
    return endpoint
