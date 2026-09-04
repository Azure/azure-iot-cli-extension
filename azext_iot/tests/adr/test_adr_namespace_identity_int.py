# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Namespace identity integration coverage."""

import os

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._log import LogKind, _log
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id


UAMI_RESOURCE_ID = os.getenv("azext_iot_adr_uami_resource_id", "").strip()


def _create_namespace(test, namespace_name: str) -> None:
    test.cmd(
        f"iot adr ns create -n {namespace_name} -g {TEST_RG} "
        f"--location {TEST_LOCATION}"
    )


def _cleanup_namespace(test, namespace_name: str) -> None:
    try:
        test.cmd(
            f"iot adr ns delete -n {namespace_name} -g {TEST_RG} --yes"
        )
    except Exception as error:  # noqa: BLE001 - cleanup is best-effort
        _log(LogKind.WARN, "Cleanup failed: %s", error)


@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceIdentity(CaptureOutputLiveScenarioTest):
    def test_namespace_identity_assign_remove_show(self):
        namespace_name = generate_adr_namespace_name()
        missing_namespace = f"missing{generate_generic_id()[:8]}"

        try:
            _create_namespace(self, namespace_name)

            identity = self.cmd(
                f"iot adr ns identity show -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert "SystemAssigned" in identity["type"]

            removed = self.cmd(
                f"iot adr ns identity remove -n {namespace_name} "
                f"-g {TEST_RG} --system true"
            ).get_output_in_json()
            assert removed["type"] == "None"
            no_identity_upsert = self.cmd(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert no_identity_upsert["identity"]["type"] == "None"

            assigned = self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --system true"
            ).get_output_in_json()
            assert assigned["type"] == "SystemAssigned"
            user_only = self.cmd(
                f"iot adr ns identity remove -n {namespace_name} "
                f"-g {TEST_RG} --system true"
            ).get_output_in_json()
            assert user_only["type"] == "UserAssigned"
            user_only_upsert = self.cmd(
                f"iot adr ns create -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert user_only_upsert["identity"]["type"] == "UserAssigned"
            assert UAMI_RESOURCE_ID.casefold() in {
                resource_id.casefold()
                for resource_id in (
                    user_only_upsert["identity"].get(
                        "userAssignedIdentities"
                    ) or {}
                )
            }
            self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --system true"
            )

            self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --system true",
                expect_failure=True,
            )
            self.cmd(
                f"iot adr ns identity wait -n {namespace_name} "
                f"-g {TEST_RG} --updated"
            )

            shown = self.cmd(
                f"iot adr ns identity show -n {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert shown["type"] == "SystemAssigned"

            self.cmd(
                f"iot adr ns identity show -n {missing_namespace} -g {TEST_RG}",
                expect_failure=True,
            )
        finally:
            _cleanup_namespace(self, namespace_name)


@pytest.mark.skipif(
    not UAMI_RESOURCE_ID,
    reason=(
        "Set azext_iot_adr_uami_resource_id to run namespace UAMI "
        "preservation and removal coverage."
    ),
)
@pytest.mark.usefixtures("set_cwd")
class TestADRNamespaceUAMI(CaptureOutputLiveScenarioTest):
    def test_namespace_uami_idempotent_assign_and_partial_remove(self):
        namespace_name = generate_adr_namespace_name()

        try:
            _create_namespace(self, namespace_name)
            combined = self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --system true --user {UAMI_RESOURCE_ID}"
            ).get_output_in_json()
            assert "SystemAssigned" in combined["type"]
            assert "UserAssigned" in combined["type"]
            assert UAMI_RESOURCE_ID.casefold() in {
                resource_id.casefold()
                for resource_id in (
                    combined.get("userAssignedIdentities") or {}
                )
            }

            self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --user {UAMI_RESOURCE_ID}",
                expect_failure=True,
            )

            system_only = self.cmd(
                f"iot adr ns identity remove -n {namespace_name} "
                f"-g {TEST_RG} --user {UAMI_RESOURCE_ID}"
            ).get_output_in_json()
            assert system_only["type"] == "SystemAssigned"

            self.cmd(
                f"iot adr ns identity assign -n {namespace_name} "
                f"-g {TEST_RG} --user {UAMI_RESOURCE_ID}"
            )
            all_users_removed = self.cmd(
                f"iot adr ns identity remove -n {namespace_name} "
                f"-g {TEST_RG} --user"
            ).get_output_in_json()
            assert all_users_removed["type"] == "SystemAssigned"
            assert not all_users_removed.get("userAssignedIdentities")
        finally:
            _cleanup_namespace(self, namespace_name)
