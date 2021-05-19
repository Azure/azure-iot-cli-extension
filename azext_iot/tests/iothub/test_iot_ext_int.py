# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest

from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC

# TODO: assert DEVICE_DEVICESCOPE_PREFIX format in parent device twin.
# from azext_iot.constants import DEVICE_DEVICESCOPE_PREFIX

opt_env_set = ["azext_iot_teststorageuri", "azext_iot_identity_teststorageid"]

settings = DynamoSettings(
    req_env_set=ENV_SET_TEST_IOTHUB_BASIC, opt_env_set=opt_env_set
)

LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg

# Set this environment variable to your empty blob container sas uri to test device export and enable file upload test.
# For file upload, you will need to have configured your IoT Hub before running.
LIVE_STORAGE = settings.env.azext_iot_teststorageuri

# Set this environment variable to enable identity-based integration tests
# You will need permissions to add and remove role assignments for this storage account
LIVE_STORAGE_ID = settings.env.azext_iot_identity_teststorageid

CWD = os.path.dirname(os.path.abspath(__file__))


class TestIoTStorage(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTStorage, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    @pytest.mark.skipif(
        not LIVE_STORAGE, reason="empty azext_iot_teststorageuri env var"
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
                LIVE_HUB, LIVE_STORAGE
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.exists("jobId"),
            ],
        )

    @pytest.mark.skipif(
        not all([LIVE_STORAGE_ID, LIVE_STORAGE]),
        reason="azext_iot_identity_teststorageid and azext_iot_teststorageuri env vars not set",
    )
    def test_identity_storage(self):
        identity_type_enable = "SystemAssigned"
        identity_type_disable = "None"
        storage_role = "Storage Blob Data Contributor"

        # check hub identity
        identity_enabled = False

        hub_identity = self.cmd(
            "iot hub show -n {}".format(LIVE_HUB)
        ).get_output_in_json()["identity"]

        if hub_identity.get("type", None) != identity_type_enable:
            # enable hub identity and get ID
            hub_identity = self.cmd(
                'iot hub update -n {} --set identity.type="{}"'.format(
                    LIVE_HUB, identity_type_enable
                )
            ).get_output_in_json()["identity"]

            identity_enabled = True

        hub_id = hub_identity.get("principalId", None)
        assert hub_id

        # setup RBAC for storage account
        storage_account_roles = self.cmd(
            'role assignment list --scope "{}" --role "{}" --query "[].principalId"'.format(
                LIVE_STORAGE_ID, storage_role
            )
        ).get_output_in_json()

        if hub_id not in storage_account_roles:
            self.cmd(
                'role assignment create --assignee "{}" --role "{}" --scope "{}"'.format(
                    hub_id, storage_role, LIVE_STORAGE_ID
                )
            )
            # give RBAC time to catch up
            from time import sleep
            sleep(30)

        # identity-based device-identity export
        self.cmd(
            'iot hub device-identity export -n {} --bcu "{}" --auth-type {}'.format(
                LIVE_HUB, LIVE_STORAGE, "identity"
            ),
            checks=[
                self.check("outputBlobContainerUri", LIVE_STORAGE),
                self.check("failureReason", None),
                self.check("type", "export"),
                self.exists("jobId"),
            ],
        )

        # if we enabled identity for this hub, undo identity and RBAC
        if identity_enabled:
            # delete role assignment first, disabling identity removes the assignee ID from AAD
            self.cmd(
                'role assignment delete --assignee "{}" --role "{}" --scope "{}"'.format(
                    hub_id, storage_role, LIVE_STORAGE_ID
                )
            )
            self.cmd(
                "iot hub update -n {} --set 'identity.type=\"{}\"'".format(
                    LIVE_HUB, identity_type_disable
                )
            )
