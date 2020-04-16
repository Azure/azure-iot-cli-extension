# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Nothing in this file should be used outside of service/central

from azext_iot import constants
from azext_iot.common import auth


def get_headers(token, cmd, has_json_payload=False):
    if not token:
        aad_token = auth.get_aad_token(cmd, resource="https://apps.azureiotcentral.com")
        token = "Bearer {}".format(aad_token["accessToken"])

    if has_json_payload:
        return {
            "Authorization": token,
            "User-Agent": constants.USER_AGENT,
            "Content-Type": "application/json",
        }

    return {"Authorization": token, "User-Agent": constants.USER_AGENT}
