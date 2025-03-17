# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------


from typing import Optional


class Track1Credential:

    def __init__(self, credential, resource):
        """Track 1 credential that can be fed into Track 1 SDK clients. Exposes signed_session protocol.
        Note: Cross-tenant authentication is not supported.

        :param credential: Track 2 credential that exposes get_token protocol
        :param resource: AAD resource
        """
        self._credential = credential
        self._resource = resource

    def signed_session(self, session=None):
        import requests
        from azure.cli.core.auth.util import resource_to_scopes
        session = session or requests.Session()
        token = self._credential.get_token(*resource_to_scopes(self._resource))
        header = "{} {}".format('Bearer', token.token)
        session.headers['Authorization'] = header
        return session


def create_track1_credential(cli_ctx, resource: Optional[str] = None) -> Track1Credential:
    """Simple create a credential supported by Track 1 SDKS.
    """
    if not resource:
        resource = "https://management.core.windows.net/"
    from azure.cli.core._profile import Profile
    track2_credential = Profile(cli_ctx).get_login_credentials()[0]
    return Track1Credential(track2_credential, resource)
