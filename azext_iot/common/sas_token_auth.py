# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
sas_token_auth: Module containing Shared Access Signature token class.

"""

from base64 import b64encode, b64decode
from hashlib import sha256
from hmac import HMAC
from time import time
try:
    from urllib import (urlencode, quote_plus)
except ImportError:
    from urllib.parse import (urlencode, quote_plus)
from msrest.authentication import Authentication


class SasTokenAuthentication(Authentication):
    """
    Shared Access Signature authorization for Azure IoT Hub.

    Args:
        uri (str): Uri of target resource.
        shared_access_policy_name (str): Name of shared access policy.
        shared_access_key (str): Shared access key.
        expiry (int): Future expiry (in seconds) of the token to be generated.
    """
    def __init__(self, uri, shared_access_policy_name, shared_access_key, expiry=3600):
        self.uri = uri
        self.policy = shared_access_policy_name
        self.key = shared_access_key
        self.expiry = int(expiry)

    def signed_session(self, session=None):
        """
        Create requests session with SAS auth headers.

        If a session object is provided, configure it directly. Otherwise,
        create a new session and return it.

        Returns:
            session (): requests.Session.
        """

        return self.refresh_session(session)

    def refresh_session(self, session=None):
        """
        Refresh requests session with SAS auth headers.

        If a session object is provided, configure it directly. Otherwise,
        create a new session and return it.

        Returns:
            session (): requests.Session.
        """

        session = session or super(SasTokenAuthentication, self).signed_session()
        session.headers['Authorization'] = self.generate_sas_token()
        return session

    def generate_sas_token(self, absolute=False):
        """
        Create a shared access signature token as a string literal.

        Args:
            absolute (bool): In general the sas token ttl is generated relative to 'now' (UTC) + expiry.
                Set to true to generate a sas token with no relative start.

        Returns:
            result (str): SAS token as string literal.
        """
        encoded_uri = quote_plus(self.uri)
        ttl = int(self.expiry) if absolute else int(time() + self.expiry)
        sign_key = '%s\n%d' % (encoded_uri, ttl)
        signature = b64encode(HMAC(b64decode(self.key), sign_key.encode('utf-8'), sha256).digest())

        result = {
            'sr': self.uri,
            'sig': signature,
            'se': str(ttl)
        }

        if self.policy:
            result['skn'] = self.policy

        return 'SharedAccessSignature ' + urlencode(result)


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
