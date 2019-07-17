# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
basic_sas_token_auth: Module containing Basic Shared Access Signature token class.

"""
from msrest.authentication import Authentication


class BasicSasTokenAuthentication(Authentication):
    """
    Basic Shared Access Signature authorization for Azure IoT Hub.

    Args:
        sas_token (str): sas token to use in authentication.
    """
    def __init__(self, sas_token):
        self.sas_token = sas_token

    def signed_session(self):
        """
        Create requests session with SAS auth headers.

        Returns:
            session (): requests.Session.
        """
        session = super(BasicSasTokenAuthentication, self).signed_session()
        session.headers['Authorization'] = self.sas_token
        return session

    def set_sas_token(self, new_token):
        self.sas_token = new_token
