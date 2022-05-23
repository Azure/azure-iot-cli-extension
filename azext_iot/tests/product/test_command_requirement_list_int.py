# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from . import AICSLiveScenarioTest


class TestRequirementList(AICSLiveScenarioTest):
    def test_list_default(self):
        create_output = self.cmd(
            "iot product requirement list --base-url {BASE_URL}"
        ).get_output_in_json()
        expected = [
            {
                "badgeType": "IotDevice",
                "provisioningRequirement": {
                    "provisioningTypes": ["SymmetricKey", "TPM", "X509"]
                },
            }
        ]
        assert create_output == expected

    def test_list_device(self):
        create_output = self.cmd(
            "iot product requirement list --badge-type IotDevice --base-url {BASE_URL}"
        ).get_output_in_json()
        expected = [
            {
                "badgeType": "IotDevice",
                "provisioningRequirement": {
                    "provisioningTypes": ["SymmetricKey", "TPM", "X509"]
                },
            }
        ]
        assert create_output == expected

    def test_list_edge(self):
        create_output = self.cmd(
            "iot product requirement list --badge-type IotEdgeCompatible --base-url {BASE_URL}"
        ).get_output_in_json()
        expected = [
            {
                "badgeType": "IotEdgeCompatible",
                "provisioningRequirement": {"provisioningTypes": ["ConnectionString", "TPM"]},
            }
        ]
        assert create_output == expected

    def test_list_pnp(self):
        create_output = self.cmd(
            "iot product requirement list --badge-type Pnp --base-url {BASE_URL}"
        ).get_output_in_json()
        expected = [
            {
                "badgeType": "Pnp",
                "provisioningRequirement": {
                    "provisioningTypes": ["SymmetricKey", "TPM", "X509"]
                },
            }
        ]
        assert create_output == expected
