# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Stdlib-only ARM target validation shared by controllers and evidence gates."""

import os
import re
from urllib.parse import urlsplit

SUBSCRIPTION = "a386d5ea-ea90-441a-8263-d816368c84a1"
RESOURCE_GROUP = "cli-int-test-rg"
ENDPOINT_ENV = "azext_iot_test_arm_endpoint"
PUBLIC_ARM = "https://management.azure.com"
CANARY_ARM = "https://centraluseuap.management.azure.com"
GOVERNMENT_ARM = "https://management.usgovcloudapi.net"
CHINA_ARM = "https://management.chinacloudapi.cn"
CLOUDS = {
    PUBLIC_ARM: {
        "name": "AzureCloud", "audience": "https://management.azure.com/",
        "storage": "core.windows.net", "servicebus": "servicebus.windows.net", "cosmos": "documents.azure.com",
    },
    GOVERNMENT_ARM: {
        "name": "AzureUSGovernment", "audience": "https://management.core.usgovcloudapi.net/",
        "storage": "core.usgovcloudapi.net", "servicebus": "servicebus.usgovcloudapi.net",
        "cosmos": "documents.azure.us",
    },
    CHINA_ARM: {
        "name": "AzureChinaCloud", "audience": "https://management.core.chinacloudapi.cn/",
        "storage": "core.chinacloudapi.cn", "servicebus": "servicebus.chinacloudapi.cn",
        "cosmos": "documents.azure.cn",
    },
}


def cloud(endpoint):
    if endpoint == CANARY_ARM:
        endpoint = PUBLIC_ARM
    if endpoint not in CLOUDS:
        raise ValueError("Integration ARM endpoint is not authorized.")
    return CLOUDS[endpoint]


def scope(endpoint):
    if cloud(endpoint)["name"] == "AzureCloud":
        return {"subscription": SUBSCRIPTION, "resource_group": RESOURCE_GROUP}
    subscription = os.getenv("azext_iot_test_subscription", "")
    group = os.getenv("azext_iot_testrg", "")
    if (not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", subscription)
            or not re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", group) or group.endswith(".")):
        raise ValueError("Sovereign integrations require an explicit subscription UUID and resource group.")
    return {"subscription": subscription, "resource_group": group}


def arm_hosts(endpoint):
    if cloud(endpoint)["name"] == "AzureCloud":
        return {urlsplit(PUBLIC_ARM).hostname, urlsplit(CANARY_ARM).hostname}
    return {urlsplit(endpoint).hostname}


def check_cloud(cli_ctx, endpoint):
    expected = PUBLIC_ARM if endpoint == CANARY_ARM else endpoint
    if cli_ctx.cloud.endpoints.resource_manager.rstrip("/").lower() != expected:
        raise ValueError("The active Azure CLI cloud does not match the scheduled integration target.")


def target(region="centraluseuap", endpoint=None):
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9]{1,64}", region):
        raise ValueError("Integration region must be an Azure region identifier.")
    if endpoint in (None, ""):
        endpoint = (GOVERNMENT_ARM if region.startswith("usgov") else CHINA_ARM if region.startswith("china")
                    else CANARY_ARM if region == "centraluseuap" else PUBLIC_ARM)
    cloud(endpoint)
    if (region.startswith("usgov") != (endpoint == GOVERNMENT_ARM)
            or region.startswith("china") != (endpoint == CHINA_ARM)):
        raise ValueError("Integration region and ARM endpoint must belong to the same cloud.")
    if endpoint == CANARY_ARM and region != "centraluseuap":
        raise ValueError("Canary ARM requires region centraluseuap.")
    return {"region": region, "endpoint": endpoint}


def public_scope(subscription, group, region, endpoint=None):
    endpoint = target(region, endpoint)["endpoint"]
    if endpoint != CANARY_ARM and {"subscription": subscription, "resource_group": group} != scope(endpoint):
        label = "Public" if endpoint == PUBLIC_ARM else "Sovereign"
        raise ValueError(f"{label} ARM integrations require the authorized subscription and resource group.")


def matches(receipt, expected):
    # Existing canary receipts predate target metadata; public receipts must attest it.
    return receipt.get("target") == expected or (
        "target" not in receipt and expected == target()
    )
