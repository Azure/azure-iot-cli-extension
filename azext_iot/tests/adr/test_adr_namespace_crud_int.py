# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""ADR namespace CRUD integration coverage."""

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import CleanupLedger
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceCrud(CaptureOutputLiveScenarioTest):
    def test_namespace_crud_lifecycle(self):
        namespace_name = generate_adr_namespace_name()

        with CleanupLedger() as cleanup:
            self.cmd(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG} "
                f"--location {TEST_LOCATION} --no-wait"
            )
            cleanup.register(
                "namespace",
                lambda: self.cmd(
                    f"iot adr ns delete -n {namespace_name} "
                    f"-g {TEST_RG} --yes"
                ),
            )
            self.cmd(
                f"iot adr ns wait -n {namespace_name} -g {TEST_RG}"
            )
            created = self.cmd(
                f"iot adr ns show -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert created["name"] == namespace_name
            assert created["location"] == TEST_LOCATION
            assert created["properties"]["provisioningState"] == "Succeeded"
            created_observability = created["properties"].get("observability")
            assert (created_observability or {}).get("enabled", False) is False

            replaced = self.cmd(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG} "
                f"--location {TEST_LOCATION} --tags phase=replaced"
            ).get_output_in_json()
            assert (
                replaced["properties"].get("observability")
                == created_observability
            )

            self.cmd(
                f"iot adr ns wait -n {namespace_name} -g {TEST_RG} "
                "--custom \"name=='condition-that-never-matches'\" "
                "--interval 1 --timeout 1",
                expect_failure=True,
            )

            shown = self.cmd(
                f"iot adr ns show -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert shown["name"] == namespace_name

            listed = self.cmd(
                f"iot adr ns list -g {TEST_RG}"
            ).get_output_in_json()
            assert namespace_name in [namespace["name"] for namespace in listed]

            updated = self.cmd(
                f"iot adr ns update -n {namespace_name} -g {TEST_RG} "
                "--tags env=test purpose=ci"
            ).get_output_in_json()
            assert updated["tags"] == {"env": "test", "purpose": "ci"}

            replaced_tags = self.cmd(
                f"iot adr ns update -n {namespace_name} -g {TEST_RG} "
                "--tags owner=adr-tests"
            ).get_output_in_json()
            assert replaced_tags["tags"] == {"owner": "adr-tests"}

            self.cmd(
                f"iot adr ns update -n {namespace_name} -g {TEST_RG}",
                expect_failure=True,
            )

            self.cmd(
                f"iot adr ns delete -n {namespace_name} -g {TEST_RG} "
                "--yes --no-wait"
            )
            self.cmd(
                f"iot adr ns wait -n {namespace_name} -g {TEST_RG} --deleted"
            )
            cleanup.dismiss("namespace")
            self.cmd(
                f"iot adr ns show -n {namespace_name} -g {TEST_RG}",
                expect_failure=True,
            )
