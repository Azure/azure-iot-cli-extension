# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests.iothub import IoTLiveScenarioTest


class TestIotHubCertificateRoot(IoTLiveScenarioTest):
    def __init__(self, test_case):
        self.original_enableRootCertificateV2 = False
        super(TestIotHubCertificateRoot, self).__init__(test_case, add_data_contributor=False)

    def tearDown(self):
        # Revert transition
        version = 'v2' if self.original_enableRootCertificateV2 else 'v1'
        self.cmd(
            f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav {version} --yes"
        )

        super(TestIotHubCertificateRoot, self).tearDown()

    def test_certificate_root(self):
        authority = self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        self.original_enableRootCertificateV2 = authority["enableRootCertificateV2"]

        if authority["enableRootCertificateV2"] is False:

            self.cmd(
                f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
                checks=[
                    self.check("enableRootCertificateV2", False),
                ],
            )

            # Transition to Digicert (initial transition)
            self.cmd(
                f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav v2 --yes",
                checks=[
                    self.check("enableRootCertificateV2", True),
                ],
            )

        self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", True),
            ],
        )

        # Revert transition
        self.cmd(
            f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav v1 --yes",
            checks=[
                self.check("enableRootCertificateV2", False),
            ],
        )

        self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", False),
            ],
        )

        # Transition to Digicert (second transition)
        self.cmd(
            f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav v2 --yes",
            checks=[
                self.check("enableRootCertificateV2", True),
            ],
        )

        self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", True),
            ],
        )
