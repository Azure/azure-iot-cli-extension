# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import json
import pytest
from contextlib import ExitStack
from datetime import datetime, timezone
from uuid import uuid4
from azure.cli.core.azclierror import CLIInternalError
from time import sleep
from knack.util import CLIError
from pathlib import Path

from azext_iot.tests.iothub import IoTLiveScenarioTest, MAX_RBAC_ASSIGNMENT_TRIES
from azext_iot.tests.iothub._integration_helpers import LOCAL_AUTH_DEVICE_HTTP_REASON
from azext_iot.tests.iothub.conftest import _delete_fixture_resource
from azext_iot.tests.settings import UserTypes, HUB_TEST_LOCATION
from azext_iot.common.utility import generate_storage_account_sas_token

from azext_iot.tests.generators import generate_generic_id
from azext_iot.common.shared import AuthenticationType
# TODO: assert DEVICE_DEVICESCOPE_PREFIX format in parent device twin.
from azure.cli.core._profile import Profile
from azure.cli.core.mock import DummyCli


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
            "identity create -n {} -g {} --location {}".format(
                user_managed_identity_name, self.entity_rg, HUB_TEST_LOCATION
            )).get_output_in_json()
        self.managed_identity = result

        # ensure resource is created before hub immediately tries to assign it
        sleep(10)

        return self.managed_identity

    def _storage_event(self, event, principal_id=None, assignment_id=None, attempt=None, job_id=None, job_status=None):
        # Successful CLI captures hide timing; retain only safe fields for failure diagnosis.
        print(json.dumps({
            "storageEvent": event, "time": datetime.now(timezone.utc).isoformat(),
            "hub": self.entity_name, "storageScope": self.live_storage_id,
            "principalId": principal_id, "assignmentId": assignment_id, "attempt": attempt,
            "jobId": job_id, "jobStatus": job_status,
        }, sort_keys=True), flush=True)

    def _storage_role_assignments(self):
        assignments = self.cmd(
            f'role assignment list --scope "{self.live_storage_id}" --role "{STORAGE_ROLE}" '
            "--fill-role-definition-name false"
        ).get_output_in_json()
        if not isinstance(assignments, list) or any(
            not isinstance(assignment, dict) or not isinstance(assignment.get("principalId"), str)
            or not assignment["principalId"]
            for assignment in assignments
        ):
            raise CLIInternalError("Storage role-assignment listing did not contain a valid principal list.")
        return assignments

    def assign_storage_role_if_needed(self, assignee, cleanup):
        def assigned():
            return any(
                assignment["principalId"].casefold() == assignee.casefold()
                for assignment in self._storage_role_assignments()
            )

        if assigned():
            self._storage_event("role.reused", principal_id=assignee)
            return
        if self.user["type"] == UserTypes.user.value:
            assignee_args = f'--assignee "{assignee}"'
        elif self.user["type"] == UserTypes.servicePrincipal.value:
            assignee_args = f'--assignee-object-id "{assignee}" --assignee-principal-type ServicePrincipal'
        else:
            raise CLIError(f"User type {self.user['type']} not supported. Can't run test(s).")

        assignment_name = str(uuid4())
        assignment_id = f"{self.live_storage_id}/providers/Microsoft.Authorization/roleAssignments/{assignment_name}"
        # A unique requested ID also permits exact cleanup after an uncertain create result.
        cleanup.callback(
            _delete_fixture_resource, f'role assignment delete --ids "{assignment_id}"', assignment_id,
        )
        self._storage_event("role.create.start", principal_id=assignee, assignment_id=assignment_id)
        self.cmd(
            f'role assignment create {assignee_args} --role "{STORAGE_ROLE}" --scope "{self.live_storage_id}" '
            f"--name {assignment_name}"
        )
        self._storage_event("role.create.complete", principal_id=assignee, assignment_id=assignment_id)
        for attempt in range(1, MAX_RBAC_ASSIGNMENT_TRIES + 1):
            visible = assigned()
            self._storage_event(
                "role.visible" if visible else "role.pending",
                principal_id=assignee, assignment_id=assignment_id, attempt=attempt,
            )
            sleep(SETUP_SLEEP_INTERVAL)
            if visible:
                sleep(IDENTITY_SLEEP_INTERVAL)
                self._storage_event("role.settle.complete", principal_id=assignee, assignment_id=assignment_id)
                return
        raise CLIInternalError(
            f"Storage role for principal '{assignee}' was not visible after {MAX_RBAC_ASSIGNMENT_TRIES} reads."
        )

    def tearDown(self):
        with ExitStack() as cleanup:
            cleanup.callback(super().tearDown)
            if self.managed_identity:
                cleanup.callback(
                    _delete_fixture_resource,
                    f"identity delete -n {user_managed_identity_name} -g {self.entity_rg}",
                    self.managed_identity["id"],
                )

    @pytest.mark.skip(reason=LOCAL_AUTH_DEVICE_HTTP_REASON)
    def test_device_upload_file(self):
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

    def test_storage(self):
        # Import/export authenticate as the service with Entra; storage SAS is
        # a separate storage credential and does not enable Hub local auth.
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
        with ExitStack() as cleanup:
            hub_identity = self.cmd(
                f"iot hub identity show -n {self.entity_name}"
            ).get_output_in_json()
            if "SystemAssigned" not in (hub_identity.get("type") or ""):
                hub_identity = self.cmd(
                    f"iot hub identity assign -n {self.entity_name} --system"
                ).get_output_in_json()
                cleanup.callback(self.cmd, f"iot hub identity remove -n {self.entity_name} --system")
            hub_id = hub_identity.get("principalId")
            assert hub_id
            self._storage_event("sami.attached", principal_id=hub_id)
            self.assign_storage_role_if_needed(hub_id, cleanup)
            self._exercise_identity_storage("[system]", hub_id)

    def test_user_identity_storage(self):
        user_identity = self.get_managed_identity()
        identity_id = user_identity["id"]
        with ExitStack() as cleanup:
            hub_identity = self.cmd(
                f"iot hub identity show -n {self.entity_name}"
            ).get_output_in_json()
            attached = hub_identity.get("userAssignedIdentities") or {}
            if identity_id.rstrip("/").casefold() not in {key.rstrip("/").casefold() for key in attached}:
                hub_identity = self.cmd(
                    f"iot hub identity assign -n {self.entity_name} --user {identity_id}"
                ).get_output_in_json()
                cleanup.callback(self.cmd, f"iot hub identity remove -n {self.entity_name} --user {identity_id}")
            attached = {
                key.rstrip("/").casefold(): value for key, value in hub_identity["userAssignedIdentities"].items()
            }
            identity_principal = attached[identity_id.rstrip("/").casefold()]["principalId"]
            assert identity_principal == user_identity["principalId"]
            self._storage_event("uami.attached", principal_id=identity_principal)
            self.assign_storage_role_if_needed(identity_principal, cleanup)
            self._exercise_identity_storage(identity_id, identity_principal)

    def _exercise_identity_storage(self, identity, principal_id):
        self.check_for_running_import_export()
        kind = "sami" if identity == "[system]" else "uami"
        self._storage_event(f"{kind}.export.start", principal_id=principal_id)
        job_id = self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --identity {} --ik true'.format(
                self.entity_name, self.live_storage_uri, identity
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
        self._storage_event(f"{kind}.export.submitted", principal_id=principal_id, job_id=job_id)
        self.wait_till_job_completion(job_id)
        self._storage_event(f"{kind}.import.start", principal_id=principal_id)
        job_id = self.cmd(
            'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --identity {}'.format(
                self.entity_name, self.live_storage_uri, self.live_storage_uri, identity
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
        self._storage_event(f"{kind}.import.submitted", principal_id=principal_id, job_id=job_id)
        self.wait_till_job_completion(job_id)
        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --identity {}'.format(
                self.entity_name, self.live_storage_uri, "fake_managed_identity"
            ),
            expect_failure=True
        )

    def wait_till_job_completion(self, job_id):
        tries = 0

        while tries < JOB_POLL_MAX_ATTEMPTS:
            job_state = self.cmd(
                f"iot hub job show -n {self.entity_name} -g {self.entity_rg} --job-id {job_id}"
            ).get_output_in_json()
            self._storage_event("job.status", job_id=job_id, job_status=job_state["status"])
            if job_state["status"] in ["failed", "completed"]:
                break
            sleep(SETUP_SLEEP_INTERVAL)
            tries += 1

        if job_state["status"] != "completed":
            raise CLIInternalError(f"Job was not completed - status is {job_state['status']}.")

    def check_for_running_import_export(self):
        job_list = []
        for job_type in ["import", "export"]:
            job_list.extend(self.cmd(
                f"iot hub job list -n {self.entity_name} -g {self.entity_rg} --job-type {job_type} --job-status running"
            ).get_output_in_json())
        for job in job_list:
            self.wait_till_job_completion(job["jobId"])
