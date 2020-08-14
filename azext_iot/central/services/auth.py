# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
import base64
import hmac
import hashlib


def generate_device_key(masterkey, device_id):
    """
    Generate device SAS key

    Args:
        masterkey: Primary group SAS token to generate device keys
        device_id: unique case-sensitive device id
    Returns:
        device key
    """
    secret = base64.b64decode(masterkey)
    device_key = base64.b64encode(
        hmac.new(
            secret, msg=device_id.encode("utf8"), digestmod=hashlib.sha256
        ).digest()
    )
    return device_key
