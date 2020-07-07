# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.log import get_logger
from azext_iot.pnp.common import RoleIdentifier
from . import PNPLiveScenarioTest

logger = get_logger(__name__)


class TestPNPRepo(PNPLiveScenarioTest):
    def __init__(self, test_case):

        from azext_iot.common.embedded_cli import EmbeddedCLI

        account = EmbeddedCLI().invoke("account show").as_json()
        self.user_id = account["user"]["name"]
        self.user_type = account["user"]["type"]
        super(TestPNPRepo, self).__init__(test_case)

    @pytest.mark.skipif(True, reason="Create not functional at the moment")
    def test_repo_create(self):

        # create repo

        repo = self.cmd("iot pnp repo create").get_output_in_json()

        repo_id = repo["tenantId"]

        # list repos

        repos = self.cmd("az iot pnp repo list").get_output_in_json()

        assert len(repos) == 1
        assert repos[0]["tenantId"] == repo_id

        # get role assignments for repo, should only be one (tenant admin)

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant".format(
                repo_id
            )
        ).get_output_in_json()

        assert len(role_assignments) == 1
        assert role_assignments[0]["subjectMetadata"]["subjectId"] == self.user_id
        assert (
            role_assignments[0]["subject"]["role"] == RoleIdentifier.tenantAdmin.value
        )

    def test_repo_rbac(self):

        # get repo

        repos = self.cmd("az iot pnp repo list").get_output_in_json()

        repo_id = repos[0]["tenantId"]

        # add role assignment for repo (tenant)
        new_role = RoleIdentifier.modelsCreator.value
        self.cmd(
            "az iot pnp role-assignment create --resource-id {0} --resource-type Tenant "
            "--subject-id {1} --subject-type {2} --role {3}".format(
                repo_id, self.user_id, self.user_type, new_role
            )
        )

        # get newest role assignments for user

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant --subject-id {1}".format(
                repo_id, self.user_id
            )
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
            "az iot pnp role-assignment delete --resource-id {0} --resource-type Tenant --role {1} --subject {2}".format(
                repo_id, new_role, self.user_id
            )
        )

        # get assignments again

        role_assignments = self.cmd(
            "az iot pnp role-assignment list --resource-id {0} --resource-type Tenant --subject-id {1}".format(
                repo_id, self.user_id
            )
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
