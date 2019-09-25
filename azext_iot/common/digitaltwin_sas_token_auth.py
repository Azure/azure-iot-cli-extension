# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""
digitaltwin_sas_token_auth: Module containing DigitalTwin Model Shared Access Signature token class.

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


class DigitalTwinSasTokenAuthentication(Authentication):
    """
    Shared Access Signature authorization for DigitalTwin Repository.

    Args:
        uri (str): Uri of target resource.
        shared_access_policy_name (str): Name of shared access policy.
        shared_access_key (str): Shared access key.
        expiry (int): Expiry of the token to be generated. Input should
            be seconds since the epoch, in UTC. Default is an hour later from now.
    """
    def __init__(self, repositoryId, endpoint, shared_access_key_name, shared_access_key, expiry=None):
        self.repositoryId = repositoryId
        self.policy = shared_access_key_name
        self.key = shared_access_key
        self.endpoint = endpoint
        if expiry is None:
            self.expiry = time() + 3600  # Default expiry is an hour later
        else:
            self.expiry = expiry

    def generate_sas_token(self):
        """
        Create a shared access signiture token as a string literal.

        Returns:
            result (str): SAS token as string literal.
        """
        encoded_uri = quote_plus(self.endpoint)
        encoded_repo_id = quote_plus(self.repositoryId)
        ttl = int(self.expiry)
        sign_key = '%s\n%s\n%d' % (encoded_repo_id, encoded_uri, ttl)
        signature = b64encode(HMAC(b64decode(self.key), sign_key.encode('utf-8'), sha256).digest())
        result = {
            'sr': self.endpoint,
            'sig': signature,
            'se': str(ttl)
        }

        if self.policy:
            result['skn'] = self.policy
        result['rid'] = self.repositoryId

        return 'SharedAccessSignature ' + urlencode(result)
