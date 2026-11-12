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


def get_adr_arm_endpoint(cli_ctx=None):
    """Keep public/canary routing explicit; IoT clients can select their active sovereign cloud."""
    default = PUBLIC_ARM_ENDPOINT
    allowed = {CANARY_ARM_ENDPOINT, PUBLIC_ARM_ENDPOINT}
    if cli_ctx is not None:
        resource_manager = cli_ctx.cloud.endpoints.resource_manager
        if isinstance(resource_manager, str) and resource_manager.rstrip("/").lower() in {
            "https://management.usgovcloudapi.net", "https://management.chinacloudapi.cn",
        }:
            default = resource_manager.rstrip("/").lower()
            allowed = {default}
    endpoint = os.getenv("AZURE_IOT_ADR_ARM_ENDPOINT", default).rstrip("/").lower()
    if endpoint not in allowed:
        raise InvalidArgumentValueError(
            f"AZURE_IOT_ADR_ARM_ENDPOINT must be {' or '.join(sorted(allowed))}."
        )
    return endpoint
