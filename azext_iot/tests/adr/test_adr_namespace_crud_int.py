# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""ADR namespace CRUD integration coverage."""

import shlex

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import CleanupLedger
from azext_iot.tests.adr._log import LogKind as L, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    TEST_SUBSCRIPTION,
    generate_adr_namespace_name,
)


@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceCrud(ADRLiveScenarioTest):
    def test_namespace_crud_lifecycle(self):
        _log(L.TEST, "test_namespace_crud_lifecycle")
        namespace_name = generate_adr_namespace_name()
        subscription_arg = (
            f" --subscription {shlex.quote(TEST_SUBSCRIPTION)}"
            if TEST_SUBSCRIPTION
            else ""
        )
        group_args = f"-g {shlex.quote(TEST_RG)}{subscription_arg}"
        resource_args = f"-n {shlex.quote(namespace_name)} {group_args}"

        with CleanupLedger() as cleanup:
            with timed_step("Step 1 > Create namespace"):
                self.cmd(
                    f"iot adr ns create {resource_args} "
                    f"--location {shlex.quote(TEST_LOCATION)} --no-wait"
                )
                self.cmd(f"iot adr ns wait {resource_args}")
                created = self.cmd(
                    f"iot adr ns show {resource_args}"
                ).get_output_in_json()
                assert created["name"] == namespace_name
                assert created["location"] == TEST_LOCATION
                assert (
                    created["properties"]["provisioningState"]
                    == "Succeeded"
                )
                created_observability = created["properties"].get(
                    "observability"
                )
                assert (
                    created_observability or {}
                ).get("enabled", False) is False
                _log(L.OK, "Namespace created")

            cleanup.register(
                "namespace",
                lambda: self.cmd(
                    f"iot adr ns delete {resource_args} --yes"
                ),
            )

            with timed_step("Step 2 > Upsert and read namespace"):
                replaced = self.cmd(
                    f"iot adr ns create {resource_args} "
                    f"--location {shlex.quote(TEST_LOCATION)} "
                    "--tags phase=replaced"
                ).get_output_in_json()
                assert (
                    replaced["properties"].get("observability")
                    == created_observability
                )

                self.cmd(
                    f"iot adr ns wait {resource_args} "
                    "--custom \"name=='condition-that-never-matches'\" "
                    "--interval 1 --timeout 1",
                    expect_failure=True,
                )

                shown = self.cmd(
                    f"iot adr ns show {resource_args}"
                ).get_output_in_json()
                assert shown["name"] == namespace_name

            with timed_step("Step 3 > Update namespace tags"):
                updated = self.cmd(
                    f"iot adr ns update {resource_args} "
                    "--tags env=test purpose=ci"
                ).get_output_in_json()
                assert updated["tags"] == {
                    "env": "test",
                    "purpose": "ci",
                }

                replaced_tags = self.cmd(
                    f"iot adr ns update {resource_args} "
                    "--tags owner=adr-tests"
                ).get_output_in_json()
                assert replaced_tags["tags"] == {"owner": "adr-tests"}

                self.cmd(
                    f"iot adr ns update {resource_args}",
                    expect_failure=True,
                )

            with timed_step("Step 4 > Delete namespace"):
                self.cmd(
                    f"iot adr ns delete {resource_args} --yes --no-wait"
                )
                self.cmd(f"iot adr ns wait {resource_args} --deleted")
                cleanup.dismiss("namespace")
                self.cmd(
                    f"iot adr ns show {resource_args}",
                    expect_failure=True,
                )
                _log(L.OK, "Namespace deleted")

    def test_namespace_list_by_resource_group(self):
        self._assert_namespace_list(by_resource_group=True)

    def test_namespace_list_by_subscription(self):
        self._assert_namespace_list(by_resource_group=False)

    def _assert_namespace_list(self, *, by_resource_group: bool):
        namespace_name = generate_adr_namespace_name()
        subscription_arg = (
            f" --subscription {shlex.quote(TEST_SUBSCRIPTION)}"
            if TEST_SUBSCRIPTION
            else ""
        )
        group_args = f"-g {shlex.quote(TEST_RG)}{subscription_arg}"
        resource_args = f"-n {shlex.quote(namespace_name)} {group_args}"

        with CleanupLedger() as cleanup:
            self.cmd(
                f"iot adr ns create {resource_args} "
                f"--location {shlex.quote(TEST_LOCATION)}"
            )
            cleanup.register(
                "namespace",
                lambda: self.cmd(f"iot adr ns delete {resource_args} --yes"),
            )
            list_args = group_args if by_resource_group else subscription_arg
            listed = self.cmd(
                f"iot adr ns list {list_args}"
            ).get_output_in_json()
            assert namespace_name in [namespace["name"] for namespace in listed]
