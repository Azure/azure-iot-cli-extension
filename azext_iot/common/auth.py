# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.cli.core._profile import Profile
import base64
import hmac
import hashlib


def get_aad_token(cmd, resource=None):
    """
    get AAD token to access to a specified resource
    :param resource: Azure resource endpoints. Default to Azure Resource Manager
    Use 'az cloud show' command for other Azure resources
    """
    resource = resource or cmd.cli_ctx.cloud.endpoints.active_directory_resource_id
    profile = Profile(cli_ctx=cmd.cli_ctx)
    creds, subscription, tenant = profile.get_raw_token(
        subscription=None, resource=resource
    )
    return {
        "tokenType": creds[0],
        "accessToken": creds[1],
        "expiresOn": creds[2].get("expiresOn", "N/A"),
        "subscription": subscription,
        "tenant": tenant,
    }


def generate_device_key(primarykey, device_id):
    """
    Generate device SAS key
    Args:
        primarykey: Primary group SAS token to generate device keys
        device_id: unique case-sensitive device id
    Returns:
        device key
    """
    secret = base64.b64decode(primarykey)
    device_key = base64.b64encode(
        hmac.new(
            secret, msg=device_id.encode("utf8"), digestmod=hashlib.sha256
        ).digest()
    )
    return device_key
