# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.common.shared import AuthenticationTypeDataplane
from knack.log import get_logger


logger = get_logger(__name__)
DATAPLANE_AUTH_TYPES = [
    AuthenticationTypeDataplane.key.value,
    AuthenticationTypeDataplane.login.value,
    "cstring",
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


def clean_dps_dataplane(cli, dps_cstring):
    # Individual Enrollments
    enrollment_list = cli.invoke(
        f"iot dps enrollment list --login {dps_cstring}"
    ).as_json()
    for enrollment in enrollment_list:
        cli.invoke(
            f"iot dps enrollment delete --login {dps_cstring} --eid {enrollment['registrationId']}"
        )

    # Enrollment Groups
    enrollment_list = cli.invoke(
        f"iot dps enrollment-group list --login {dps_cstring}"
    ).as_json()
    for enrollment in enrollment_list:
        cli.invoke(
            f"iot dps enrollment-group delete --login {dps_cstring} --eid {enrollment['enrollmentGroupId']}"
        )
