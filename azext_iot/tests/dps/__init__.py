# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.common.shared import AuthenticationTypeDataplane
from knack.log import get_logger


logger = get_logger(__name__)
# Each lifecycle keeps its sequence of auth phases, but policy-incompatible
# service credentials are now separate, visibly skipped pytest cases. This
# does NOT disable symmetric-key/X.509 device enrollment or registration.
_SERVICE_SAS_DISABLED = pytest.mark.skip(
    reason=(
        "DPS disableLocalAuth=true rejects service shared-access-policy SAS authentication "
        "(--auth-type key / --login connection string). The same lifecycle runs with "
        "Entra login; device symmetric-key and X.509 attestation remain supported."
    )
)
DPS_SERVICE_AUTH_PARAMS = [
    pytest.param((AuthenticationTypeDataplane.key.value,), id="key", marks=_SERVICE_SAS_DISABLED),
    pytest.param((AuthenticationTypeDataplane.login.value,), id="login"),
    pytest.param(("cstring",), id="cstring", marks=_SERVICE_SAS_DISABLED),
]

CERT_NAME = "aziotcli"
WEBHOOK_URL = "https://www.test.test"
API_VERSION = "2019-03-31"

PREFIX_DEVICE = "test-device-"
PREFIX_EDGE_DEVICE = "test-edge-device-"
PREFIX_INDIVIDUAL_ENROLLMENT = "test-enrollment-"
PREFIX_GROUP_ENROLLMENT = "test-groupenroll-"
MAX_HUB_RETRIES = 3

TEST_ENDORSEMENT_KEY = (
    "AToAAQALAAMAsgAgg3GXZ0SEs/gakMyNRqXXJP1S124GUgtk8qHaGzMUaaoABgCAAEMAEAgAAAAAAAEAibym9HQP9vxCGF5dVc1Q"
    "QsAGe021aUGJzNol1/gycBx3jFsTpwmWbISRwnFvflWd0w2Mc44FAAZNaJOAAxwZvG8GvyLlHh6fGKdh+mSBL4iLH2bZ4Ry22cB3"
    "CJVjXmdGoz9Y/j3/NwLndBxQC+baNvzvyVQZ4/A2YL7vzIIj2ik4y+ve9ir7U0GbNdnxskqK1KFIITVVtkTIYyyFTIR0BySjPrRI"
    "Dj7r7Mh5uF9HBppGKQCBoVSVV8dI91lNazmSdpGWyqCkO7iM4VvUMv2HT/ym53aYlUrau+Qq87Tu+uQipWYgRdF11KDfcpMHqqzB"
    "QQ1NpOJVhrsTrhyJzO7KNw=="
)
TEST_KEY_REGISTRATION_ID = "myarbitrarydeviceId"
GENERATED_KEY = "cT/EXZvsplPEpT//p98Pc6sKh8mY3kYgSxavHwMkl7w="
