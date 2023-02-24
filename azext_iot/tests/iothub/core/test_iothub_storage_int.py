# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from time import sleep
from knack.util import CLIError
from pathlib import Path
from knack.log import get_logger
import pytest
from azext_iot.tests.helpers import delete_role_assignment, get_role_assignments

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.settings import UserTypes
from azext_iot.common.utility import generate_storage_account_sas_token

from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.shared import AuthenticationType
# TODO: assert DEVICE_DEVICESCOPE_PREFIX format in parent device twin.
from azure.cli.core._profile import Profile
from azure.cli.core.mock import DummyCli


logger = get_logger(__name__)
STORAGE_ROLE = "Storage Blob Data Contributor"
CWD = os.path.dirname(os.path.abspath(__file__))
user_managed_identity_name = generate_generic_id()
SETUP_MAX_ATTEMPTS = 3
JOB_POLL_MAX_ATTEMPTS = 3
SETUP_SLEEP_INTERVAL = 10
IDENTITY_SLEEP_INTERVAL = 60


class TestIoTStorage(IoTLiveScenarioTest):
    def __init__(self, test_case):
        self.storage_cstring = None
        super(TestIoTStorage, self).__init__(test_case)
        self.managed_identity = None

        self.profile = Profile(cli_ctx=DummyCli())
        subscription = self.profile.get_subscription()
        self.user = subscription["user"]

        self.live_storage_uri = self.get_container_sas_url()

        storage_account = self.cmd(
            "storage account show --name {}".format(self.storage_account_name)
        ).get_output_in_json()

        self.live_storage_id = storage_account["id"]

    def get_container_sas_url(self):
        sas_token = generate_storage_account_sas_token(
            self.storage_cstring, read=True, write=True, create=True, add=True, delete=True
        )
        container_sas_url = (
            "https://" + self.storage_account_name + ".blob.core.windows.net" + "/" + self.storage_container + "?" + sas_token
        )
        return container_sas_url

    def get_managed_identity(self):
        # Check if there is a managed identity already
        if self.managed_identity:
            return self.managed_identity

        # Create managed identity
        result = self.cmd(
            "identity create -n {} -g {}".format(
                user_managed_identity_name, self.entity_rg
            )).get_output_in_json()

        # ensure resource is created before hub immediately tries to assign it
        sleep(10)

        self.managed_identity = result
        return self.managed_identity

    def assign_storage_role_if_needed(self, assignee):

        role_assignments = get_role_assignments(
            scope=self.live_storage_id,
            role=STORAGE_ROLE)
        role_assignment_principal_ids = [assignment["principalId"] for assignment in role_assignments]

        if assignee not in role_assignment_principal_ids:
            if self.user["type"] == UserTypes.user.value:
                self.cmd(
                    'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                        assignee, STORAGE_ROLE, self.live_storage_id
                    )
                )
            elif self.user["type"] == UserTypes.servicePrincipal.value:
                self.cmd(
                    'role assignment create --assignee-object-id {} --role "{}" --scope "{}" --assignee-principal-type {}'.format(
                        assignee, STORAGE_ROLE, self.live_storage_id, "ServicePrincipal"
                    )
                )
            else:
                userType = self.user["type"]
                raise CLIError(f"User type {userType} not supported. Can't run test(s).")

            # ensure role assignment is complete
            while assignee not in role_assignment_principal_ids:
                role_assignments = get_role_assignments(
                    scope=self.live_storage_id,
                    role=STORAGE_ROLE)
                role_assignment_principal_ids = [assignment["principalId"] for assignment in role_assignments]
                sleep(10)

            sleep(IDENTITY_SLEEP_INTERVAL)

    def tearDown(self):
        if self.managed_identity:
            self.cmd('identity delete -n {} -g {}'.format(
                user_managed_identity_name, self.entity_rg
            ))
        return super().tearDown()

    def test_storage(self):
        device_count = 1

        content_path = os.path.join(Path(CWD).parent, "test_generic_replace.json")
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                device_ids[0], self.entity_name, self.entity_rg
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        self.cmd(
            'iot device upload-file -d {} -n {} --fp "{}" --ct {}'.format(
                device_ids[0], self.entity_name, content_path, "application/json"
            ),
            checks=self.is_empty(),
        )

        # With connection string
        self.cmd(
            'iot device upload-file -d {} --login {} --fp "{}" --ct {}'.format(
                device_ids[0], self.connection_string, content_path, "application/json"
            ),
            checks=self.is_empty(),
        )

        attempts = 0
        setup_completed = False
        while not setup_completed:
            try:
                self.check_for_running_import_export()

                job_id = self.cmd(
                    'iot hub device-identity export -n {} --bc "{}" --sa "{}"'.format(
                        self.entity_name, self.storage_container, self.storage_account_name
                    ),
                    checks=[
                        self.exists("outputBlobContainerUri"),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", True),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --ik true'.format(
                        self.entity_name, self.live_storage_uri
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", False),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                self.cmd(
                    'iot hub device-identity import -n {} --ibc "{}" --isa "{}" --obc "{}" --osa "{}"'.format(
                        self.entity_name, self.storage_container, self.storage_account_name,
                        self.storage_container, self.storage_account_name
                    ),
                    checks=[
                        self.exists("outputBlobContainerUri"),
                        self.exists("inputBlobContainerUri"),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", AuthenticationType.keyBased.name),
                        self.exists("jobId"),
                    ],
                )
                setup_completed = True
            except Exception as x:
                attempts += 1
                if attempts >= SETUP_MAX_ATTEMPTS:
                    raise x

    def test_system_identity_storage(self):
        identity_type_enable = "SystemAssigned"

        # check hub identity
        identity_enabled = False

        hub_identity = self.cmd(
            "iot hub identity show -n {}".format(self.entity_name)
        ).get_output_in_json()

        if identity_type_enable not in hub_identity.get("type", None):
            # enable hub identity and get ID
            hub_identity = self.cmd(
                "iot hub identity assign -n {} --system".format(
                    self.entity_name,
                )
            ).get_output_in_json()

            identity_enabled = True

        # principal id for system assigned user identity
        hub_id = hub_identity.get("principalId", None)
        assert hub_id

        attempts = 0
        setup_completed = False
        while not setup_completed:
            try:
                self.assign_storage_role_if_needed(hub_id)
                self.check_for_running_import_export()

                job_id = self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --identity {} --ik true'.format(
                        self.entity_name, self.live_storage_uri, "[system]"
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", False),
                        self.check("storageAuthenticationType", AuthenticationType.identityBased.name),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --identity {}'.format(
                        self.entity_name, self.live_storage_uri, self.live_storage_uri, "[system]"
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("inputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", AuthenticationType.identityBased.name),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --identity {}'.format(
                        self.entity_name, self.live_storage_uri, "fake_managed_identity"
                    ),
                    expect_failure=True
                )

                setup_completed = True
            except Exception as x:
                attempts += 1
                if attempts >= SETUP_MAX_ATTEMPTS:
                    raise x

        # if we enabled identity for this hub, undo identity and RBAC
        if identity_enabled:
            # delete role assignment first, disabling identity removes the assignee ID from AAD
            self.cmd(
                'role assignment delete --assignee "{}" --role "{}" --scope "{}"'.format(
                    hub_id, STORAGE_ROLE, self.live_storage_id
                )
            )
            self.cmd(
                "iot hub identity remove -n {} --system".format(
                    self.entity_name
                )
            )

    def test_user_identity_storage(self):
        # User Assigned Managed Identity
        user_identity = self.get_managed_identity()
        identity_id = user_identity["id"]
        # check hub identity
        identity_enabled = False
        hub_identity = self.cmd(
            "iot hub identity show -n {}".format(self.entity_name)
        ).get_output_in_json()

        if hub_identity.get("userAssignedIdentities", None) != user_identity["principalId"]:
            # enable hub identity and get ID
            hub_identity = self.cmd(
                "iot hub identity assign -n {} --user {}".format(
                    self.entity_name, identity_id
                )
            ).get_output_in_json()

            identity_enabled = True

        identity_principal = hub_identity["userAssignedIdentities"][identity_id]["principalId"]
        assert identity_principal == user_identity["principalId"]

        attempts = 0
        user_identity_setup_completed = False
        while not user_identity_setup_completed:
            try:
                self.assign_storage_role_if_needed(identity_principal)
                self.check_for_running_import_export()

                # identity-based device-identity export
                job_id = self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --identity {} --ik true'.format(
                        self.entity_name, self.live_storage_uri, identity_id
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", False),
                        self.check("storageAuthenticationType", AuthenticationType.identityBased.name),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --identity {}'.format(
                        self.entity_name, self.live_storage_uri, self.live_storage_uri, identity_id
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("inputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", AuthenticationType.identityBased.name),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --identity {}'.format(
                        self.entity_name, self.live_storage_uri, "fake_managed_identity"
                    ),
                    expect_failure=True
                )
                user_identity_setup_completed = True
            except Exception as x:
                attempts += 1
                if attempts >= SETUP_MAX_ATTEMPTS:
                    raise x

        # if we enabled identity for this hub, undo identity and RBAC
        if identity_enabled:
            # delete role assignment first, disabling identity removes the assignee ID from AAD
            delete_role_assignment(
                scope=self.live_storage_id,
                assignee=identity_principal,
                role=STORAGE_ROLE
            )
            self.cmd(
                "iot hub identity remove -n {} --user".format(
                    self.entity_name
                )
            )

        self.tearDown()

    def wait_till_job_completion(self, job_id):
        tries = 0

        while tries < JOB_POLL_MAX_ATTEMPTS:
            job_state = self.cmd(
                f"iot hub job show -n {self.entity_name} -g {self.entity_rg} --job-id {job_id}"
            ).get_output_in_json()
            if job_state["status"] in ["failed", "completed"]:
                break
            sleep(SETUP_SLEEP_INTERVAL)
            tries += 1

        if job_state["status"] == "failed":
            logger.error(job_state)
        if job_state["status"] != "completed":
            raise Exception(f"Job was not completed - status is {job_state['status']}.")

    def check_for_running_import_export(self):
        job_list = []
        for job_type in ["import", "export"]:
            job_list.extend(self.cmd(
                f"iot hub job list -n {self.entity_name} -g {self.entity_rg} --job-type {job_type} --job-status running"
            ).get_output_in_json())
        for job in job_list:
            self.wait_till_job_completion(job["jobId"])
