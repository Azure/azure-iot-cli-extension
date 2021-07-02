# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
from time import sleep

from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.common.utility import ensure_iothub_sdk_min_version

from azext_iot.tests.generators import generate_generic_id
# TODO: assert DEVICE_DEVICESCOPE_PREFIX format in parent device twin.
from azext_iot.constants import IOTHUB_TRACK_2_SDK_MIN_VERSION

opt_env_set = ["azext_iot_teststorageuri", "azext_iot_identity_teststorageid"]

settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_BASIC, opt_env_set=opt_env_set
)

LIVE_HUB = "test-hub-" + generate_generic_id()
LIVE_RG = settings.env.azext_iot_testrg

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE_URI = settings.env.azext_iot_teststorageuri

# Set this environment variable to enable identity-based integration tests
# You will need permissions to add and remove role assignments for this storage account
LIVE_STORAGE_RESOURCE_ID = settings.env.azext_iot_identity_teststorageid

CWD = os.path.dirname(os.path.abspath(__file__))

user_managed_identity_name = generate_generic_id()


class TestIoTStorage(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTStorage, self).__init__(test_case, LIVE_HUB, LIVE_RG)
        self.managed_identity = None

    def get_managed_identity(self):
        # Check if there is a managed identity already
        if self.managed_identity:
            return self.managed_identity

        # Create managed identity
        result = self.cmd(
            "identity create -n {} -g {}".format(
                user_managed_identity_name, LIVE_RG
            )).get_output_in_json()

        # ensure resource is created before hub immediately tries to assign it
        sleep(10)

        self.managed_identity = result
        return self.managed_identity

    def tearDown(self):
        if self.managed_identity:
            self.cmd('identity delete -n {} -g {}'.format(
                user_managed_identity_name, LIVE_RG
            ))
        return super().tearDown()

    @pytest.mark.skipif(
        not LIVE_STORAGE_URI, reason="empty azext_iot_teststorageuri env var"
    )
    def test_storage(self):
        device_count = 1

        content_path = os.path.join(CWD, "test_generic_replace.json")
        device_ids = self.generate_device_names(device_count)

        self.cmd(
            "iot hub device-identity create -d {} -n {} -g {} --ee".format(
                device_ids[0], LIVE_HUB, LIVE_RG
            ),
            checks=[self.check("deviceId", device_ids[0])],
        )

        self.cmd(
            'iot device upload-file -d {} -n {} --fp "{}" --ct {}'.format(
                device_ids[0], LIVE_HUB, content_path, "application/json"
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

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}"'.format(
                LIVE_HUB, LIVE_STORAGE_URI
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.check("excludeKeysInExport", True),
                self.exists("jobId"),
            ],
        )

        # give time to finish job
        sleep(30)

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --ik true'.format(
                LIVE_HUB, LIVE_STORAGE_URI, "key"
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.check("excludeKeysInExport", False),
                self.exists("jobId"),
            ],
        )

        # give time to finish job
        sleep(30)

        self.cmd(
            'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {}'.format(
                LIVE_HUB, LIVE_STORAGE_URI, LIVE_STORAGE_URI, "key"
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("inputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "import"),
                self.check("storageAuthenticationType", "keyBased"),
                self.exists("jobId"),
            ],
        )

    @pytest.mark.skipif(
        not all([LIVE_STORAGE_RESOURCE_ID, LIVE_STORAGE_URI]),
        reason="azext_iot_identity_teststorageid and azext_iot_teststorageuri env vars not set",
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_system_identity_storage(self):
        identity_type_enable = "SystemAssigned"
        storage_role = "Storage Blob Data Contributor"

        # check hub identity
        identity_enabled = False

        hub_identity = self.cmd(
            "iot hub identity show -n {}".format(LIVE_HUB)
        ).get_output_in_json()

        if identity_type_enable not in hub_identity.get("type", None):
            # enable hub identity and get ID
            hub_identity = self.cmd(
                "iot hub identity assign -n {} --system".format(
                    LIVE_HUB,
                )
            ).get_output_in_json()

            identity_enabled = True

        # principal id for system assigned user identity
        hub_id = hub_identity.get("principalId", None)
        assert hub_id

        # setup RBAC for storage account
        storage_account_roles = self.cmd(
            'role assignment list --scope "{}" --role "{}" --query "[].principalId"'.format(
                LIVE_STORAGE_RESOURCE_ID, storage_role
            )
        ).get_output_in_json()

        if hub_id not in storage_account_roles:
            self.cmd(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    hub_id, storage_role, LIVE_STORAGE_RESOURCE_ID
                )
            )
            # give time to finish job
            sleep(60)

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {} --ik true'.format(
                LIVE_HUB, LIVE_STORAGE_URI, "identity", "[system]"
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.check("excludeKeysInExport", False),
                self.check("storageAuthenticationType", "identityBased"),
                self.exists("jobId"),
            ],
        )

        self.cmd(
            'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {} --identity {}'.format(
                LIVE_HUB, LIVE_STORAGE_URI, LIVE_STORAGE_URI, "identity", "[system]"
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("inputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "import"),
                self.check("storageAuthenticationType", "identityBased"),
                self.exists("jobId"),
            ],
        )

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {}'.format(
                LIVE_HUB, LIVE_STORAGE_URI, "identity", "fake_managed_identity"
            ),
            expect_failure=True
        )

        # if we enabled identity for this hub, undo identity and RBAC
        if identity_enabled:
            # delete role assignment first, disabling identity removes the assignee ID from AAD
            self.cmd(
                'role assignment delete --assignee "{}" --role "{}" --scope "{}"'.format(
                    hub_id, storage_role, LIVE_STORAGE_RESOURCE_ID
                )
            )
            self.cmd(
                "iot hub identity remove -n {} --system".format(
                    LIVE_HUB
                )
            )

    @pytest.mark.skipif(
        not all([LIVE_STORAGE_RESOURCE_ID, LIVE_STORAGE_URI]),
        reason="azext_iot_identity_teststorageid and azext_iot_teststorageuri env vars not set",
    )
    @pytest.mark.skipif(
        not ensure_iothub_sdk_min_version(IOTHUB_TRACK_2_SDK_MIN_VERSION),
        reason="Skipping track 2 tests because SDK is track 1")
    def test_user_identity_storage(self):
        # User Assigned Managed Identity
        storage_role = "Storage Blob Data Contributor"
        user_identity = self.get_managed_identity()
        identity_id = user_identity["id"]
        # check hub identity
        identity_enabled = False
        hub_identity = self.cmd(
            "iot hub identity show -n {}".format(LIVE_HUB)
        ).get_output_in_json()

        if hub_identity.get("userAssignedIdentities", None) != user_identity["principalId"]:
            # enable hub identity and get ID
            hub_identity = self.cmd(
                "iot hub identity assign -n {} --user {}".format(
                    LIVE_HUB, identity_id
                )
            ).get_output_in_json()

            identity_enabled = True

        identity_principal = hub_identity["userAssignedIdentities"][identity_id]["principalId"]
        assert identity_principal == user_identity["principalId"]

        # setup RBAC for storage account
        storage_account_roles = self.cmd(
            'role assignment list --scope "{}" --role "{}" --query "[].principalId"'.format(
                LIVE_STORAGE_RESOURCE_ID, storage_role
            )
        ).get_output_in_json()

        if identity_principal not in storage_account_roles:
            self.cmd(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    identity_principal, storage_role, LIVE_STORAGE_RESOURCE_ID
                )
            )
            # give time to finish job
            sleep(60)

        # identity-based device-identity export
        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {} --ik true'.format(
                LIVE_HUB, LIVE_STORAGE_URI, "identity", identity_id
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.check("excludeKeysInExport", False),
                self.check("storageAuthenticationType", "identityBased"),
                self.exists("jobId"),
            ],
        )

        # give time to finish job
        sleep(30)

        self.cmd(
            'iot hub device-identity import -n {} --ibcu "{}" --obcu "{}" --auth-type {} --identity {}'.format(
                LIVE_HUB, LIVE_STORAGE_URI, LIVE_STORAGE_URI, "identity", identity_id
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("inputBlobContainerUri", LIVE_STORAGE_URI),
                self.check("failureReason", None),
                self.check("type", "import"),
                self.check("storageAuthenticationType", "identityBased"),
                self.exists("jobId"),
            ],
        )

        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {} --identity {}'.format(
                LIVE_HUB, LIVE_STORAGE_URI, "identity", "fake_managed_identity"
            ),
            expect_failure=True
        )

        # if we enabled identity for this hub, undo identity and RBAC
        if identity_enabled:
            # delete role assignment first, disabling identity removes the assignee ID from AAD
            self.cmd(
                'role assignment delete --assignee "{}" --role "{}" --scope "{}"'.format(
                    identity_principal, storage_role, LIVE_STORAGE_RESOURCE_ID
                )
            )
            self.cmd(
                "iot hub identity remove -n {} --user".format(
                    LIVE_HUB
                )
            )

        self.tearDown()
