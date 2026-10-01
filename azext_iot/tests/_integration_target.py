# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Stdlib-only ARM target validation shared by controllers and evidence gates."""

import re

SUBSCRIPTION = "a386d5ea-ea90-441a-8263-d816368c84a1"
RESOURCE_GROUP = "cli-int-test-rg"
ENDPOINT_ENV = "azext_iot_test_arm_endpoint"
PUBLIC_ARM = "https://management.azure.com"
CANARY_ARM = "https://centraluseuap.management.azure.com"


def target(region="centraluseuap", endpoint=None):
    if not isinstance(region, str) or not re.fullmatch(r"[a-z0-9]{1,64}", region):
        raise ValueError("Integration region must be an Azure region identifier.")
    if endpoint in (None, ""):
        endpoint = CANARY_ARM if region == "centraluseuap" else PUBLIC_ARM
    if endpoint not in (PUBLIC_ARM, CANARY_ARM):
        raise ValueError("Integration region/ARM endpoint pair is not authorized.")
    if endpoint == CANARY_ARM and region != "centraluseuap":
        raise ValueError("Canary ARM requires region centraluseuap.")
    return {"region": region, "endpoint": endpoint}


def public_scope(subscription, group, region, endpoint=None):
    if target(region, endpoint)["endpoint"] == PUBLIC_ARM and (subscription, group) != (SUBSCRIPTION, RESOURCE_GROUP):
        raise ValueError("Public ARM integrations require the authorized subscription and resource group.")


def matches(receipt, expected):
    # Existing canary receipts predate target metadata; public receipts must attest it.
    return receipt.get("target") == expected or (
        "target" not in receipt and expected == target()
    )
