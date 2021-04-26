# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from . import AICSLiveScenarioTest
from azext_iot.product.shared import BadgeType


class TestTestShowInt(AICSLiveScenarioTest):
    def __init__(self, test_case):
        self.test_id = "524ac74f-752b-4748-9667-45cd09e8a098"
        super(TestTestShowInt, self).__init__(test_case)

    def test_case_list_test(self):
        # call the GET /deviceTest/{test_id}
        output = self.cmd(
            "iot product test case list -t {}  --base-url {}".format(
                self.test_id, self.kwargs["BASE_URL"]
            )
        ).get_output_in_json()

        assert (
            output["certificationBadgeTestCases"][0]["type"].lower()
            == BadgeType.Pnp.value.lower()
        )
