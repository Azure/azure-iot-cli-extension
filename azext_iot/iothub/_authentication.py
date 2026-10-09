# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Azure Core authentication for Hub HTTP clients; MQTT/AMQP remain separate."""

from urllib.parse import urlsplit

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.core.pipeline.policies import SansIOHTTPPolicy


class HubAuthenticationPolicy(SansIOHTTPPolicy):
    """Refresh CLI OAuth/SAS for every request, never for another origin."""

    def __init__(self, authentication, endpoint):
        self.authentication = authentication
        self.endpoint = endpoint

    def on_request(self, request):
        origin = urlsplit(self.endpoint)
        target = urlsplit(request.http_request.url)
        if (
            origin.scheme != "https" or target.scheme != "https"
            or not origin.hostname or not target.hostname
            or target.username or target.password or origin.username or origin.password
            or (target.hostname, target.port or 443) != (origin.hostname, origin.port or 443)
        ):
            raise ServiceRequestError("Refusing to send Hub credentials to an insecure or different origin.")
        if isinstance(self.authentication, AzureKeyCredential):
            authorization = self.authentication.key
        elif callable(self.authentication):
            authorization = self.authentication()
        else:
            with self.authentication.signed_session() as session:
                authorization = session.headers["Authorization"]
        if (
            not isinstance(authorization, str) or not authorization.startswith(("Bearer ", "SharedAccessSignature "))
            or authorization.startswith("Bearer SharedAccessSignature ")
        ):
            raise ClientAuthenticationError("Hub authentication must supply a complete Bearer or SharedAccessSignature value.")
        request.http_request.headers["Authorization"] = authorization
