# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from urllib.parse import urlsplit

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ServiceRequestError
from azure.core.pipeline.policies import SansIOHTTPPolicy


class DpsAuthenticationPolicy(SansIOHTTPPolicy):
    """Renew CLI SAS/AAD authentication on every request, only for its origin."""

    def __init__(self, authentication, endpoint):
        self.authentication = authentication
        self.endpoint = endpoint

    def on_request(self, request):
        origin = urlsplit(self.endpoint)
        target = urlsplit(request.http_request.url)
        if (
            target.scheme != "https" or target.username or target.password
            or (target.hostname, target.port) != (origin.hostname, origin.port)
        ):
            raise ServiceRequestError("Refusing to send DPS credentials to a different origin.")
        if isinstance(self.authentication, AzureKeyCredential):
            authorization = self.authentication.key
        elif callable(self.authentication):
            authorization = self.authentication()
        else:
            with self.authentication.signed_session() as session:
                authorization = session.headers["Authorization"]
        request.http_request.headers["Authorization"] = authorization
