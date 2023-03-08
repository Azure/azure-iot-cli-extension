# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from typing import List, Optional

from knack.log import get_logger

from azext_iot.tests.helpers import assign_role_assignment
from . import DTLiveScenarioTest
from . import generate_resource_id
from time import sleep
from pathlib import Path
from azext_iot.digitaltwins.providers.import_job import DEFAULT_IMPORT_JOB_ID_PREFIX

logger = get_logger(__name__)
CWD = os.path.dirname(os.path.abspath(__file__))
MAX_TRIES = 5
RBAC_SLEEP_INTERVAL = 60
POLL_SLEEP_INTERVAL = 30
EXPECTED_MODEL_IDS = [
    "dtmi:com:microsoft:azure:iot:model0;1", "dtmi:com:microsoft:azure:iot:model1;1", "dtmi:com:microsoft:azure:iot:model2;1",
    "dtmi:com:microsoft:azure:iot:model3;1", "dtmi:com:microsoft:azure:iot:model4;1", "dtmi:com:microsoft:azure:iot:model5;1",
    "dtmi:com:microsoft:azure:iot:model6;1", "dtmi:com:microsoft:azure:iot:model7;1", "dtmi:com:microsoft:azure:iot:model8;1",
    "dtmi:com:microsoft:azure:iot:model9;1"
]
EXPECTED_TWIN_IDS = [
    "twin0", "twin1", "twin2", "twin3", "twin4", "twin5", "twin6", "twin7", "twin8", "twin9"
]


class TestDTImportJobs(DTLiveScenarioTest):
    def __init__(self, test_case):
        self.storage_cstring = None
        super(TestDTImportJobs, self).__init__(test_case)

    def _upload_import_data_file(self, import_data_filename):
        import_data_file = os.path.join(Path(CWD), "import_data", import_data_filename)
        # Delete already exisiting import data file
        if self.cmd(
            "storage blob exists --connection-string '{}' -c '{}' -n '{}'".format(
                self.storage_cstring, self.storage_container, import_data_filename
            )
        ).get_output_in_json()["exists"]:
            self.cmd(
                "storage blob delete --connection-string '{}' -c '{}' -n '{}'".format(
                    self.storage_cstring, self.storage_container, import_data_filename
                )
            )
        # Upload import data files to storage account
        self.cmd(
            "storage blob upload --connection-string '{}' --container-name '{}' --file '{}'".format(
                self.storage_cstring, self.storage_container, import_data_file
            )
        )

    def _cleanup_import_job(self, instance_name, import_job_id, import_job_output_file):
        # Delete import jobs
        self.cmd(
            "dt job import delete -n '{}' -g '{}' -j '{}' -y".format(instance_name, self.rg, import_job_id)
        )

        # Delete output files from storage container
        if self.cmd(
            "storage blob exists --connection-string '{}' -c '{}' -n '{}'".format(
                self.storage_cstring, self.storage_container, import_job_output_file
            )
        ).get_output_in_json()["exists"]:
            self.cmd(
                "storage blob delete --connection-string '{}' -c '{}' -n '{}'".format(
                    self.storage_cstring, self.storage_container, import_job_output_file
                )
            )

    def test_dt_import_jobs(self):
        self.wait_for_capacity()

        storage_account_id = self.cmd(
            "storage account show -n '{}' -g '{}'".format(self.storage_account_name, self.rg)
        ).get_output_in_json()["id"]
        instance_name = generate_resource_id()
        create_output = self.cmd(
            "dt create -n {} -g {} -l {} --mi-system-assigned --scopes {} --role 'Storage Blob Data Contributor'".format(
                instance_name,
                self.rg,
                self.region,
                storage_account_id
            )
        ).get_output_in_json()
        self.track_instance(create_output)

        assign_role_assignment(
            role=self.role_map["owner"],
            scope=create_output["id"],
            assignee=self.current_user,
            wait=RBAC_SLEEP_INTERVAL)

        # Upload Import Data Files
        valid_import_data_filename = "bulk-models-twins-relationships-valid.ndjson"
        self._upload_import_data_file(valid_import_data_filename)
        invalid_import_data_filename = "bulk-models-twins-relationships-invalid.ndjson"
        self._upload_import_data_file(invalid_import_data_filename)

        # Create import job for valid import data
        valid_import_job_id = "{}_valid_import_job".format(instance_name)
        create_valid_import_job_output = self.cmd(
            "dt job import create -n '{}' -g '{}' -j '{}' --df '{}' --ibc '{}' --isa '{}'".format(
                instance_name, self.rg, valid_import_job_id,
                valid_import_data_filename, self.storage_container, self.storage_account_name
            )
        ).get_output_in_json()

        expected_import_job_output_filename = "{}_output.txt".format(valid_import_job_id)
        assert_import_job_creation(
            create_valid_import_job_output, valid_import_data_filename, expected_import_job_output_filename, valid_import_job_id
        )
        valid_import_job_output_filename = create_valid_import_job_output["outputBlobUri"].split("/")[-1]

        # Run through import job lifecycle
        # Cancel import job (there could be a race condition)
        self.cmd(
            "dt job import cancel -n '{}' -g '{}' -j '{}' -y".format(instance_name, self.rg, valid_import_job_id)
        )

        # Poll to make sure job is cancelled
        error = poll_job_status(
            cmd=self.cmd,
            rg=self.rg,
            instance_name=instance_name,
            job_id=valid_import_job_id,
            expected_statuses=["cancelled", "cancelling"]
        )
        assert error is None

        # Delete import job
        self.cmd(
            "dt job import delete -n '{}' -g '{}' -j '{}' -y".format(instance_name, self.rg, valid_import_job_id)
        )

        # Recreate import job
        self.cmd(
            "dt job import create -n '{}' -g '{}' -j '{}' --df '{}' --ibc '{}' --isa '{}'".format(
                instance_name, self.rg, valid_import_job_id,
                valid_import_data_filename, self.storage_container, self.storage_account_name
            )
        ).get_output_in_json()

        # Show import job
        show_import_job_output = self.cmd(
            "dt job import show -n '{}' -g '{}' -j '{}'".format(instance_name, self.rg, valid_import_job_id)
        ).get_output_in_json()
        assert show_import_job_output["id"] == valid_import_job_id

        # Poll to ensure desired status of valid import job before starting new one
        error = poll_job_status(
            cmd=self.cmd,
            rg=self.rg,
            instance_name=instance_name,
            job_id=valid_import_job_id,
            expected_statuses=["succeeded"]
        )
        assert error is None

        # Create import job for invalid import data
        invalid_import_job_output_filename = "{}_invalid_import_job_output.txt".format(instance_name)
        create_invalid_import_job_output = self.cmd(
            "dt job import create -n '{}' -g '{}' --df '{}' --ibc '{}' --isa '{}' --of '{}'".format(
                instance_name, self.rg, invalid_import_data_filename,
                self.storage_container, self.storage_account_name, invalid_import_job_output_filename
            )
        ).get_output_in_json()

        assert_import_job_creation(
            create_invalid_import_job_output, invalid_import_data_filename, invalid_import_job_output_filename
        )
        invalid_import_job_id = create_invalid_import_job_output["id"]

        # List import jobs
        list_import_jobs_output = self.cmd(
            "dt job import list -n '{}' -g '{}'".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(list_import_jobs_output) == 2
        import_job_ids = [valid_import_job_id, invalid_import_job_id]
        assert list_import_jobs_output[0]["id"] in import_job_ids
        assert list_import_jobs_output[1]["id"] in import_job_ids

        # Poll to ensure desired status of invalid import job
        error = poll_job_status(
            cmd=self.cmd,
            rg=self.rg,
            instance_name=instance_name,
            job_id=invalid_import_job_id,
            expected_statuses=["failed"]
        )
        assert error["code"] == "DTDLParsingError"

        list_models_output = self.cmd(
            "dt model list -n {} -g {} --definition".format(instance_name, self.rg)
        ).get_output_in_json()
        model_ids = []
        for model in list_models_output:
            assert model["id"]
            assert model["model"]
            model_ids.append(model["id"])
        assert len(model_ids) == len(EXPECTED_MODEL_IDS)
        assert set(model_ids) == set(EXPECTED_MODEL_IDS)

        twin_query_result = self.cmd(
            "dt twin query -n {} -q 'select * from digitaltwins'".format(instance_name)
        ).get_output_in_json()
        twin_ids = []
        relationship = "has"
        for twin in twin_query_result["result"]:
            assert twin["$dtId"]
            assert twin["$metadata"]
            twin_ids.append(twin["$dtId"])
        assert len(twin_ids) == len(EXPECTED_TWIN_IDS)
        assert set(twin_ids) == set(EXPECTED_TWIN_IDS)
        for twin_id in twin_ids:
            twin_relationship_list_result = self.cmd(
                "dt twin relationship list -n {} -g {} --twin-id {} --relationship {}".format(
                    instance_name, self.rg, twin_id, relationship
                )
            ).get_output_in_json()
            assert len(twin_relationship_list_result) == 1

        # Delete import jobs and their output files
        self._cleanup_import_job(instance_name, valid_import_job_id, valid_import_job_output_filename)
        self._cleanup_import_job(instance_name, invalid_import_job_id, invalid_import_job_output_filename)
        list_import_jobs_output = self.cmd(
            "dt job import list -n '{}' -g '{}'".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(list_import_jobs_output) == 0


def poll_job_status(cmd, rg: str, instance_name: str, job_id: str, expected_statuses: List[str]) -> Optional[dict]:
    """
    Helper function to poll job import status until finalized. Returns the error.

    Note that the first status in expected_statuses should be the expected final status. This method will check for running
    and not started statuses without needing to be specified in expected_statuses.
    """
    num_tries = 0
    final_status = expected_statuses[0]
    expected_statuses.extend(["running", "notstarted"])
    while num_tries < MAX_TRIES:
        num_tries += 1
        import_job_output = cmd(
            "dt job import show -n '{}' -g '{}' -j '{}'".format(instance_name, rg, job_id)
        ).get_output_in_json()
        assert import_job_output["status"] in expected_statuses
        if import_job_output["status"] == final_status:
            return import_job_output["error"]
        sleep(POLL_SLEEP_INTERVAL)


def assert_import_job_creation(
    create_import_job_output: dict, expected_input_blob_name: str, expected_output_blob_name: str, expected_job_id: str = None
):
    assert create_import_job_output
    assert create_import_job_output["createdDateTime"]
    assert create_import_job_output["lastActionDateTime"]
    assert create_import_job_output["purgeDateTime"]
    assert create_import_job_output["finishedDateTime"] is None
    assert create_import_job_output["error"] is None
    assert create_import_job_output["status"] == "notstarted"
    assert create_import_job_output["inputBlobUri"]
    assert create_import_job_output["inputBlobUri"].split("/")[-1] == expected_input_blob_name
    assert create_import_job_output["outputBlobUri"]
    assert create_import_job_output["outputBlobUri"].split("/")[-1] == expected_output_blob_name
    assert create_import_job_output["id"]
    # We know the expected job id only when it is passed in as a param, else it is system generated
    if expected_job_id:
        assert create_import_job_output["id"] == expected_job_id
    else:
        assert create_import_job_output["id"].startswith(DEFAULT_IMPORT_JOB_ID_PREFIX)
