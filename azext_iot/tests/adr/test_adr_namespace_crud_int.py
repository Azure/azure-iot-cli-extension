# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import shlex
from urllib.parse import quote

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._log import LogKind as L, _log, timed_step
from azext_iot.tests.adr.conftest import (
    TEST_API_VERSION, TEST_LOCATION, TEST_RG, TEST_SUBSCRIPTION, generate_adr_namespace_name,
)


class TestADRNamespaceCrud(ADRLiveScenarioTest):
    def test_namespace_crud_lifecycle(self):
        if not TEST_RG:
            pytest.skip("Set azext_iot_adr_resource_group or azext_iot_testrg to an existing disposable-test resource group.")
        _log(L.TEST, "test_namespace_crud_lifecycle")
        subscription_arg = f" --subscription {shlex.quote(TEST_SUBSCRIPTION)}" if TEST_SUBSCRIPTION else ""
        group_args = f"-g {shlex.quote(TEST_RG)}{subscription_arg}"
        with timed_step("Step 1 > Read-only preflight"):
            account = self.cmd(f"account show{subscription_arg}").get_output_in_json()
            cloud = self.cmd("cloud show").get_output_in_json()
            self.cmd(f"group show -n {shlex.quote(TEST_RG)}{subscription_arg}")
            arm = cloud["endpoints"]["resourceManager"].rstrip("/")
            url = (
                f"{arm}/subscriptions/{quote(account['id'], safe='')}/resourceGroups/{quote(TEST_RG, safe='')}"
                f"/providers/Microsoft.DeviceRegistry/namespaces?api-version={quote(TEST_API_VERSION, safe='')}"
            )
            self.cmd(f"rest --method get --url {shlex.quote(url)}")
            _log(L.RESULT, "Preflight passed; location=%s API=%s", TEST_LOCATION, TEST_API_VERSION)

        name = generate_adr_namespace_name()
        args = f"-n {name} {group_args}"
        deleted = False
        try:
            with timed_step("Step 2 > Create namespace"):
                self.cmd(f"iot adr ns create {args} --location {shlex.quote(TEST_LOCATION)} --no-wait")
                self.cmd(f"iot adr ns wait {args} --created")
                created = self.cmd(f"iot adr ns show {args}").get_output_in_json()
                assert created["name"] == name
                assert created["identity"]["type"] == "SystemAssigned"
                _log(L.OK, "Namespace created")

            with timed_step("Step 3 > List and missing-resource behavior"):
                namespaces = self.cmd(f"iot adr ns list {group_args}").get_output_in_json()
                assert name in [namespace["name"] for namespace in namespaces]
                self.cmd(f"iot adr ns list{subscription_arg}")
                self.cmd(f"iot adr ns show -n {name}-missing {group_args}", expect_failure=True)

            with timed_step("Step 4 > Update tags and messaging"):
                updated = self.cmd(f"iot adr ns update {args} --tags env=test purpose=ci").get_output_in_json()
                assert updated["tags"] == {"env": "test", "purpose": "ci"}
                updated = self.cmd(f"iot adr ns update {args} --tags owner=adr-tests").get_output_in_json()
                assert updated["tags"] == {"owner": "adr-tests"}
                updated = self.cmd(f"iot adr ns update {args} --messaging-endpoints '{{{{}}}}'").get_output_in_json()
                assert not updated["properties"].get("messaging", {}).get("endpoints")
                self.cmd(f"iot adr ns wait {args} --updated")

            with timed_step("Step 5 > Manage system-assigned identity"):
                self.cmd(f"iot adr ns identity remove {args}")
                self.cmd(f"iot adr ns identity wait {args} --updated")
                identity = self.cmd(f"iot adr ns identity show {args}").get_output_in_json()
                assert identity.get("type", "None") == "None"
                self.cmd(f"iot adr ns identity assign {args} --no-wait")
                self.cmd(f"iot adr ns identity wait {args} --updated")
                identity = self.cmd(f"iot adr ns identity show {args}").get_output_in_json()
                assert identity["type"] == "SystemAssigned"

            with timed_step("Step 6 > Delete namespace"):
                self.cmd(f"iot adr ns delete {args} --yes")
                self.cmd(f"iot adr ns wait {args} --deleted")
                deleted = True
                self.cmd(f"iot adr ns show {args}", expect_failure=True)
                _log(L.OK, "Namespace deleted")
        finally:
            if not deleted:
                with timed_step("Cleanup > Delete disposable namespace"):
                    try:
                        self.cmd(f"iot adr ns delete {args} --yes")
                    except Exception:
                        _log(L.WARN, "Namespace cleanup failed; remove '%s' from resource group '%s'.", name, TEST_RG)
