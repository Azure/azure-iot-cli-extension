# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
# Nothing in this file should be used outside of service/central

from azext_iot.service import auth


def get_token(token, cmd):
    if not token:
        token = auth.get_aad_token(cmd, resource="https://apps.azureiotcentral.com")
        return "Bearer {}".format(token["accessToken"])

    return token
