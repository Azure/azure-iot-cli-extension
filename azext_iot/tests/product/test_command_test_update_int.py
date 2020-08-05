# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from . import AICSLiveScenarioTest
from azext_iot.product.shared import AttestationType


class TestTestUpdateInt(AICSLiveScenarioTest):
    def __init__(self, test_case):
        self.test_id = "524ac74f-752b-4748-9667-45cd09e8a098"
        super(TestTestUpdateInt, self).__init__(test_case)

    def test_update_symmetric_key(self):
        # call the GET /deviceTest/{test_id}
        output = self.cmd(
            "iot product test update -t {} --at symmetricKey --base-url {}".format(
                self.test_id, self.kwargs["BASE_URL"]
            )
        ).get_output_in_json()

        assert output["id"] == self.test_id
        assert (
            output["provisioningConfiguration"]["type"]
            == AttestationType.symmetricKey.value
        )
        assert output["provisioningConfiguration"]["symmetricKeyEnrollmentInformation"]
