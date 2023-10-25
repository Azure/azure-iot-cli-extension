# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests.iothub import IoTLiveScenarioTest


class TestIotHubCertificateRoot(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIotHubCertificateRoot, self).__init__(test_case, add_data_contributor=False)

    def test_certificate_root(self):
        initial_state = self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
        ).get_output_in_json()["enableRootCertificateV2"]

        # transition 1
        self.cmd(
            f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav "
            f"{'v1' if initial_state else 'v2'} --yes",
            checks=[
                self.check("enableRootCertificateV2", not initial_state),
            ],
        )

        self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", not initial_state),
            ],
        )

        # transition 2
        self.cmd(
            f"iot hub certificate root-authority set -n {self.entity_name} -g {self.entity_rg} --cav "
            f"{'v2' if initial_state else 'v1'} --yes",
            checks=[
                self.check("enableRootCertificateV2", initial_state),
            ],
        )

        self.cmd(
            f"iot hub certificate root-authority show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("enableRootCertificateV2", initial_state),
            ],
        )
