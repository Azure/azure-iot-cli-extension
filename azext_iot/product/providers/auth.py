# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from msrest.authentication import Authentication


class AICSAuthentication(Authentication):
    def __init__(self, cmd, base_url):
        self.cmd = cmd
        self.base_url = base_url

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

        session = session or super(AICSAuthentication, self).signed_session()
        session.headers["Authorization"] = self.generate_token()
        return session

    def generate_token(self):
        from azure.cli.core._profile import Profile

        profile = Profile(cli_ctx=self.cmd.cli_ctx)
        creds, subscription, tenant = profile.get_raw_token()
        parsed_token = {
            "tokenType": creds[0],
            "accessToken": creds[1],
            "expiresOn": creds[2].get("expiresOn", "N/A"),
            "tenant": tenant,
            "subscription": subscription,
        }
        return "{} {}".format(parsed_token["tokenType"], parsed_token["accessToken"])
