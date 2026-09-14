# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest

from azext_iot.common.shared import AuthenticationTypeDataplane
from knack.log import get_logger


logger = get_logger(__name__)
# Service-policy SAS requires its own explicitly local-auth-enabled fixture phase.
# Device symmetric-key/X.509 attestation is independent and remains in regular coverage.
DPS_SERVICE_AUTH_PARAMS = [
    pytest.param((AuthenticationTypeDataplane.key.value,), id="key", marks=pytest.mark.dps_service_sas),
    pytest.param((AuthenticationTypeDataplane.login.value,), id="login"),
    pytest.param(("cstring",), id="cstring", marks=pytest.mark.dps_service_sas),
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
