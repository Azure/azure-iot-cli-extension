# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import os

from io import open
from os.path import exists
from . import PNPLiveScenarioTest
from azext_iot.common.utility import read_file_content
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.pnp.common import RoleIdentifier
from knack.util import CLIError

_capability_model_payload = "test_pnp_create_payload_model.json"
_pnp_dns_suffix = "azureiotrepository-test.com"


@pytest.mark.usefixtures("set_cwd")
class TestPnPModelLifecycle(PNPLiveScenarioTest):
    def __init__(self, _):
        super(TestPnPModelLifecycle, self).__init__(_)
        account_settings = EmbeddedCLI().invoke("account show").as_json()["user"]

        repo_id = (
            EmbeddedCLI()
            .invoke("iot pnp repo list --pnp-dns-suffix {}".format(_pnp_dns_suffix))
            .as_json()[0]["tenantId"]
        )

        self.kwargs.update(
            {
                "model": "test_model_definition.json",
                "user_id": account_settings["name"],
                "user_type": account_settings["type"],
                "repo_id": repo_id,
                "pnp_dns_suffix": _pnp_dns_suffix,
            }
        )

    def setUp(self):
        if self._testMethodName == "test_model_lifecycle":

            roles = self.cmd(
                "iot pnp role-assignment list --resource-id {repo_id} --resource-type Tenant --subject-id {user_id} "
                "--pnp-dns-suffix {pnp_dns_suffix}"
            )
            # check for TenantAdministrator
            try:
                roles = roles.get_output_in_json()
                role_assignments = list(
                    map(lambda role: role["subject"]["role"], roles)
                )
                if RoleIdentifier.tenantAdmin.value not in role_assignments:
                    self.skipTest("Need TenantAdmin role to perform tests")
            except CLIError as e:
                self.skipTest(e)

            # Assign roles for model test

            self.cmd(
                "iot pnp role-assignment create --resource-id {repo_id} --resource-type Tenant --subject-id {user_id} "
                "--subject-type {user_type} --role ModelsCreator --pnp-dns-suffix {pnp_dns_suffix}"
            )

            self.cmd(
                "iot pnp role-assignment create --resource-id {repo_id} --resource-type Tenant --subject-id {user_id} "
                "--subject-type {user_type} --role ModelsPublisher --pnp-dns-suffix {pnp_dns_suffix}"
            )

            # Generate model ID

            model = str(read_file_content(_capability_model_payload))
            _model_id = self._generate_model_id(json.loads(model)["@id"])
            self.kwargs.update({"model_id": _model_id})
            model_newContent = model.replace(
                json.loads(model)["@id"], self.kwargs["model_id"]
            )
            model_newContent = model_newContent.replace("\n", "")

            fo = open(self.kwargs["model"], "w+", encoding="utf-8")
            fo.write(model_newContent)
            fo.close()

    def tearDown(self):
        if exists(self.kwargs["model"]):
            os.remove(self.kwargs["model"])

        if self._testMethodName == "test_model_lifecycle":

            # RBAC for model integration tests (create, show, publish models in tenant)

            self.cmd(
                "iot pnp role-assignment delete --resource-id {repo_id} --resource-type Tenant --subject-id {user_id} "
                "--role ModelsCreator --pnp-dns-suffix {pnp_dns_suffix}"
            )

            self.cmd(
                "iot pnp role-assignment delete --resource-id {repo_id} --resource-type Tenant --subject-id {user_id} "
                "--role ModelsPublisher --pnp-dns-suffix {pnp_dns_suffix}"
            )

    def _generate_model_id(self, model_id):
        from datetime import datetime

        now = datetime.now()
        date_str = now.strftime("test%m%d%H")
        time_str = now.strftime("%M").strip("0")
        return "{}:{};{}".format(model_id, date_str, time_str)

    def test_model_lifecycle(self):

        # Error: Invalid model definition file
        self.cmd(
            "iot pnp model create --model '' --pnp-dns-suffix {pnp_dns_suffix}",
            expect_failure=True,
        )

        # Error: wrong path of model definition
        self.cmd(
            "iot pnp model create --model model.json --pnp-dns-suffix {pnp_dns_suffix}",
            expect_failure=True,
        )

        # Success: Create new model
        created = self.cmd(
            "iot pnp model create --model {model} --pnp-dns-suffix {pnp_dns_suffix}"
        ).get_output_in_json()

        assert created["@id"] == self.kwargs["model_id"]

        # Checking the model list
        self.cmd(
            "iot pnp model list --pnp-dns-suffix {pnp_dns_suffix}",
            checks=[
                self.greater_than("length([*])", 0),
                self.exists("[?modelId==`{}`]".format(self.kwargs["model_id"])),
            ],
        )

        # Get model
        model = self.cmd(
            "iot pnp model show -m {model_id} --pnp-dns-suffix {pnp_dns_suffix}"
        ).get_output_in_json()
        assert json.dumps(model)
        assert model["@id"] == self.kwargs["model_id"]

        # Publish model
        published = self.cmd(
            "iot pnp model publish -m {model_id} --pnp-dns-suffix {pnp_dns_suffix} --yes"
        ).get_output_in_json()
        assert json.dumps(published)
        assert published["@id"] == self.kwargs["model_id"]

        # Checking the model list for published model
        self.cmd(
            "iot pnp model list -q {model_id} --state Listed --pnp-dns-suffix {pnp_dns_suffix}",
            checks=[
                self.greater_than("length([*])", 0),
                self.exists("[?modelId==`{}`]".format(self.kwargs["model_id"])),
            ],
        )


class TestPNPRepo(PNPLiveScenarioTest):
    def __init__(self, test_case):
        account = EmbeddedCLI().invoke("account show").as_json()
        self.user_id = account["user"]["name"]
        self.user_type = account["user"]["type"]
        super(TestPNPRepo, self).__init__(test_case)

    def setUp(self):
        if self._testMethodName == "test_repo_rbac":
            # check for TenantAdministrator
            try:
                repo_id = (
                    EmbeddedCLI()
                    .invoke(
                        "iot pnp repo list --pnp-dns-suffix {}".format(_pnp_dns_suffix)
                    )
                    .as_json()[0]["tenantId"]
                )
                roles = self.cmd(
                    "iot pnp role-assignment list --resource-id {0} --resource-type Tenant --subject-id {1} "
                    "--pnp-dns-suffix {2}".format(
                        repo_id, self.user_id, _pnp_dns_suffix
                    )
                )
                roles = roles.get_output_in_json()
                role_assignments = list(
                    map(lambda role: role["subject"]["role"], roles)
                )
                if RoleIdentifier.tenantAdmin.value not in role_assignments:
                    self.skipTest("Need TenantAdmin role to perform test")
            except CLIError as e:
                self.skipTest(e)

    @pytest.mark.skipif(True, reason="Create not functional at the moment")
    def test_repo_create(self):

        # create repo

        repo = self.cmd(
            "iot pnp repo create --pnp-dns-suffix {pnp_dns_suffix}"
        ).get_output_in_json()

        repo_id = repo["tenantId"]

        # list repos

        repos = self.cmd(
            "az iot pnp repo list --pnp-dns-suffix {pnp_dns_suffix}"
        ).get_output_in_json()

        assert len(repos) == 1
        assert repos[0]["tenantId"] == repo_id

        # get role assignments for repo, should only be one (tenant admin)

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant --pnp-dns-suffix {1}".format(
                repo_id, _pnp_dns_suffix
            )
        ).get_output_in_json()

        assert len(role_assignments) == 1
        assert role_assignments[0]["subjectMetadata"]["subjectId"] == self.user_id
        assert (
            role_assignments[0]["subject"]["role"] == RoleIdentifier.tenantAdmin.value
        )

    def test_repo_rbac(self):

        # get repo

        repos = self.cmd(
            "az iot pnp repo list --pnp-dns-suffix {}".format(_pnp_dns_suffix)
        ).get_output_in_json()

        repo_id = repos[0]["tenantId"]

        # add role assignment for repo (tenant)
        new_role = RoleIdentifier.modelsCreator.value
        self.cmd(
            "az iot pnp role-assignment create --resource-id {0} --resource-type Tenant "
            "--subject-id {1} --subject-type {2} --role {3} --pnp-dns-suffix {4}".format(
                repo_id, self.user_id, self.user_type, new_role, _pnp_dns_suffix
            )
        )

        # get newest role assignments for user

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant --subject-id {1} "
            "--pnp-dns-suffix {2}".format(repo_id, self.user_id, _pnp_dns_suffix)
        ).get_output_in_json()

        # ensure our new role exists

        assert (
            len(
                [
                    role
                    for role in role_assignments
                    if role["subjectMetadata"]["subjectId"] == self.user_id
                    and role["subject"]["role"] == new_role
                ]
            )
            == 1
        )

        # delete role assignment

        self.cmd(
            "az iot pnp role-assignment delete --resource-id {0} --resource-type Tenant --role {1} --subject {2} "
            "--pnp-dns-suffix {3}".format(
                repo_id, new_role, self.user_id, _pnp_dns_suffix
            )
        )

        # get assignments again

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant --subject-id {1} "
            "--pnp-dns-suffix {2}".format(repo_id, self.user_id, _pnp_dns_suffix)
        ).get_output_in_json()

        # ensure our new role does not exist
        assert (
            len(
                [
                    role
                    for role in role_assignments
                    if role["subjectMetadata"]["subjectId"] == self.user_id
                    and role["subject"]["role"] == new_role
                ]
            )
            == 0
        )
