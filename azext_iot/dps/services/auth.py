# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Private distribution for preview customers
# Governed by license terms at https://aka.ms/iothub-certmgmt-privprev-license
# --------------------------------------------------------------------------------------------

import time
import base64
import hmac
import hashlib
import urllib


def get_dps_sas_auth_header(
    scope_id, device_id, key,
):
    sr = "{}%2Fregistrations%2F{}".format(scope_id, device_id)
    expires = int(time.time() + 21600)
    registration_id = f"{sr}\n{str(expires)}"
    secret = base64.b64decode(key)
    signature = base64.b64encode(
        hmac.new(
            secret, msg=registration_id.encode("utf8"), digestmod=hashlib.sha256
        ).digest()
    )
    quote_signature = urllib.parse.quote(signature, "~()*!.'")
    token = f"SharedAccessSignature sr={sr}&sig={quote_signature}&se={str(expires)}&skn=registration"
    return token
