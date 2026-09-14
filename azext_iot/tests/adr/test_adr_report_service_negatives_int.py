# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.core.exceptions import HttpResponseError

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import ADRFullInfraHelper
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRReportServiceNegatives(
    ADRFullInfraHelper, ADRLiveScenarioTest
):
    def test_report_service_negatives(self):
        namespace_name = generate_adr_namespace_name()
        rg = TEST_RG

        try:
            self.cmd(
                f"iot adr ns create -n {namespace_name} -g {rg} "
                f"--location {TEST_LOCATION}"
            )

            with pytest.raises(HttpResponseError) as report_failure:
                self.cmd(
                    f"iot adr ns report latest --ns {namespace_name} -g {rg} "
                    "--report-type NamespaceUpdateComplianceReport"
                )
            assert report_failure.value.status_code == 404
        finally:
            self.cleanup_namespace(namespace_name, rg)
