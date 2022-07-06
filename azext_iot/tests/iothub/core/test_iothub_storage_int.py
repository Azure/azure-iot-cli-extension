# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
from time import sleep
from knack.util import CLIError
from pathlib import Path
from knack.log import get_logger

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.settings import UserTypes
from azext_iot.common.utility import ensure_iothub_sdk_min_version, ensure_azure_namespace_path

from azext_iot.tests.generators import generate_generic_id
# TODO: assert DEVICE_DEVICESCOPE_PREFIX format in parent device twin.
from azext_iot.constants import IOTHUB_TRACK_2_SDK_MIN_VERSION
from azure.cli.core._profile import Profile
from azure.cli.core.mock import DummyCli


logger = get_logger(__name__)
STORAGE_ROLE = "Storage Blob Data Contributor"
CWD = os.path.dirname(os.path.abspath(__file__))
user_managed_identity_name = generate_generic_id()
SETUP_MAX_ATTEMPTS = 3
JOB_POLL_MAX_ATTEMPTS = 5
SETUP_SLEEP_INTERVAL = 10
IDENTITY_SLEEP_INTERVAL = 75


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
        from datetime import datetime, timedelta
        ensure_azure_namespace_path()
        from azure.storage.blob import ResourceTypes, AccountSasPermissions, generate_account_sas, BlobServiceClient

        blob_service_client = BlobServiceClient.from_connection_string(conn_str=self.storage_cstring)

        sas_token = generate_account_sas(
            blob_service_client.account_name,
            account_key=blob_service_client.credential.account_key,
            resource_types=ResourceTypes(object=True),
            permission=AccountSasPermissions(
                read=True, add=True, create=True, delete=True, filter=True, list=True, update=True, write=True
            ),
            expiry=datetime.utcnow() + timedelta(hours=1)
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

        role_assignments = self.get_role_assignments(self.live_storage_id, STORAGE_ROLE)
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
                role_assignments = self.get_role_assignments(self.live_storage_id, STORAGE_ROLE)
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
                    'iot hub device-identity export -n {} --bcu "{}"'.format(
                        self.entity_name, self.live_storage_uri
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", True),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --ik true'.format(
                        self.entity_name, self.live_storage_uri, "key"
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
                    'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {}'.format(
                        self.entity_name, self.live_storage_uri, self.live_storage_uri, "key"
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("inputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", "keyBased"),
                        self.exists("jobId"),
                    ],
                )
                setup_completed = True
            except Exception as x:
                attempts += 1
                if attempts >= SETUP_MAX_ATTEMPTS:
                    raise x

    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
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
                    'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {} --ik true'.format(
                        self.entity_name, self.live_storage_uri, "identity", "[system]"
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", False),
                        self.check("storageAuthenticationType", "identityBased"),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {} --identity {}'.format(
                        self.entity_name, self.live_storage_uri, self.live_storage_uri, "identity", "[system]"
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("inputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", "identityBased"),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {}'.format(
                        self.entity_name, self.live_storage_uri, "identity", "fake_managed_identity"
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

    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
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
                    'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {} --ik true'.format(
                        self.entity_name, self.live_storage_uri, "identity", identity_id
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "export"),
                        self.check("excludeKeysInExport", False),
                        self.check("storageAuthenticationType", "identityBased"),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                job_id = self.cmd(
                    'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {} --identity {}'.format(
                        self.entity_name, self.live_storage_uri, self.live_storage_uri, "identity", identity_id
                    ),
                    checks=[
                        self.check("outputBlobContainerUri", self.live_storage_uri),
                        self.check("inputBlobContainerUri", self.live_storage_uri),
                        self.check("failureReason", None),
                        self.check("type", "import"),
                        self.check("storageAuthenticationType", "identityBased"),
                        self.exists("jobId"),
                    ],
                ).get_output_in_json()["jobId"]

                # give time to finish job
                self.wait_till_job_completion(job_id)

                self.cmd(
                    'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {}'.format(
                        self.entity_name, self.live_storage_uri, "identity", "fake_managed_identity"
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
            self.cmd(
                'role assignment delete --assignee "{}" --role "{}" --scope "{}"'.format(
                    identity_principal, STORAGE_ROLE, self.live_storage_id
                )
            )
            self.cmd(
                "iot hub identity remove -n {} --user".format(
                    self.entity_name
                )
            )

        self.tearDown()

    def wait_till_job_completion(self, job_id):
        tries = 0
        status = self.cmd(
            f"iot hub job show -n {self.entity_name} -g {self.entity_rg} --job-id {job_id}"
        ).get_output_in_json()["status"]

        while status not in ["failed", "completed"] and tries < JOB_POLL_MAX_ATTEMPTS:
            status = self.cmd(
                f"iot hub job show -n {self.entity_name} -g {self.entity_rg} --job-id {job_id}"
            ).get_output_in_json()["status"]
            sleep(SETUP_SLEEP_INTERVAL)
            tries += 1

        if status == "failed":
            status = self.cmd(
                f"iot hub job show -n {self.entity_name} -g {self.entity_rg} --job-id {job_id}"
            ).get_output_in_json()
            logger.error(status)
        assert status == "completed"

    def check_for_running_import_export(self):
        job_list = []
        for job_type in ["import", "export"]:
            job_list.extend(self.cmd(
                f"iot hub job list -n {self.entity_name} -g {self.entity_rg} --job-type {job_type} --job-status running"
            ).get_output_in_json())
        if len(job_list) > 0:
            for job in job_list:
                self.wait_till_job_completion(job["jobId"])
