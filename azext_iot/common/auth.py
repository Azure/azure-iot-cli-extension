# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from typing import Optional
from azure.cli.core._profile import Profile
from msrest.authentication import Authentication


def get_aad_token(cli_ctx, resource: Optional[str] = None):
    """
    get AAD token to access to a specified resource
    :param resource: Azure resource endpoints. Default to Azure Resource Manager
    Use 'az cloud show' command for other Azure resources
    """
    resource = resource or cli_ctx.cloud.endpoints.active_directory_resource_id
    profile = Profile(cli_ctx=cli_ctx)
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


class IoTOAuth(Authentication):
    """
    Azure AD OAuth for Azure IoT Hub and DPS.

    """

    def __init__(self, cli_ctx, resource_id: Optional[str] = None):
        self.resource_id = resource_id
        self.cli_ctx = cli_ctx

    def signed_session(self, session=None):
        """
        Create requests session with SAS auth headers.

        If a session object is provided, configure it directly. Otherwise,
        create a new session and return it.

        Returns:
            session (): requests.Session.
        """

        return self.refresh_session(session)

    def refresh_session(
        self, session=None,
    ):
        """
        Refresh requests session with SAS auth headers.

        If a session object is provided, configure it directly. Otherwise,
        create a new session and return it.

        Returns:
            session (): requests.Session.
        """

        session = session or super(IoTOAuth, self).signed_session()
        parsed_token = get_aad_token(
            cli_ctx=self.cli_ctx, resource=self.resource_id
        )
        session.headers["Authorization"] = "{} {}".format(
            parsed_token["tokenType"], parsed_token["accessToken"]
        )
        return session
