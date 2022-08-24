# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES


class TestIotHubCertificateRoot(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIotHubCertificateRoot, self).__init__(test_case)

    def test_certificate_root(self):
        self.cmd(
                f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", False),
            ],
        )

        # Transition to Digicert
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
