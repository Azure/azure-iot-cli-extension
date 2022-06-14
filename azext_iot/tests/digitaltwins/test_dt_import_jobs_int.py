# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from . import DTLiveScenarioTest
from . import generate_resource_id
from time import sleep

logger = get_logger(__name__)


class TestDTImportJobs(DTLiveScenarioTest):
    def __init__(self, test_case):
        self.storage_cstring = None
        super(TestDTImportJobs, self).__init__(test_case)

    def test_dt_importjobs(self):
        self.wait_for_capacity()

        storage_account_id = self.cmd(
            "storage account show -n '{}' -g '{}'".format(self.storage_account_name, self.rg)
        ).get_output_in_json()["id"]
        instance_name = generate_resource_id()
        # @avagraw - New APIs are only supported in East US in private preview.
        dt_region = "eastus"
        create_output = self.cmd(
            "dt create -n {} -g {} -l {} --assign-identity --scopes {} --role 'Storage Blob Data Contributor'".format(
                instance_name,
                self.rg,
                dt_region,
                storage_account_id
            )
        ).get_output_in_json()
        self.track_instance(create_output)

        self.cmd(
            "dt role-assignment create -n {} -g {} --assignee {} --role '{}'".format(
                instance_name, self.rg, self.current_user, self.role_map["owner"]
            )
        )
        # Wait for RBAC to catch-up
        sleep(60)

        # Upload import data files to storage account
        valid_import_data_file = "./import_data/bulk-models-twins-relationships-valid.ndjson"
        self.cmd(
            "storage blob upload --connection-string '{}' --container-name '{}' --file '{}' --overwrite".format(
                self.storage_cstring, self.storage_container, valid_import_data_file
            )
        )
        invalid_import_data_file = "./import_data/bulk-models-twins-relationships-invalid.ndjson"
        self.cmd(
            "storage blob upload --connection-string '{}' --container-name '{}' --file '{}' --overwrite".format(
                self.storage_cstring, self.storage_container, invalid_import_data_file
            )
        )

        # Create import job for valid import data
        valid_import_job_output_filename = "{}_valid_import_job_output.txt".format(instance_name)
        create_valid_import_job_output = self.cmd(
            "dt job import create -n '{}' -g '{}' --df '{}' --ibc '{}' --isa '{}' --of '{}'".format(
                instance_name, self.rg, valid_import_data_file.rsplit('/', maxsplit=1)[-1],
                self.storage_container, self.storage_account_name, valid_import_job_output_filename
            )
        ).get_output_in_json()

        assert_import_job_creation(create_valid_import_job_output)
        valid_import_job_id = create_valid_import_job_output["id"]

        # Show import job
        show_import_job_output = self.cmd(
            "dt job import show -n '{}' -g '{}' -j '{}'".format(instance_name, self.rg, valid_import_job_id)
        ).get_output_in_json()
        assert(show_import_job_output["id"] == valid_import_job_id)

        # Create import job for invalid import data
        invalid_import_job_output_filename = "{}_invalid_import_job_output.txt".format(instance_name)
        create_invalid_import_job_output = self.cmd(
            "dt job import create -n '{}' -g '{}' --df '{}' --ibc '{}' --isa '{}' --of '{}'".format(
                instance_name, self.rg, invalid_import_data_file.rsplit('/', maxsplit=1)[-1],
                self.storage_container, self.storage_account_name, invalid_import_job_output_filename
            )
        ).get_output_in_json()

        assert_import_job_creation(create_invalid_import_job_output)
        invalid_import_job_id = create_invalid_import_job_output["id"]

        # List import jobs
        list_import_jobs_output = self.cmd(
            "dt job import list -n '{}' -g '{}'".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(list_import_jobs_output) == 2
        import_job_ids = [valid_import_job_id, invalid_import_job_id]
        assert list_import_jobs_output[0]["id"] in import_job_ids
        assert list_import_jobs_output[1]["id"] in import_job_ids

        # Poll to ensure desired status of import jobs
        num_tries = 0
        max_tries = 5
        while num_tries < max_tries:
            num_tries += 1
            show_valid_import_job_output = self.cmd(
                "dt job import show -n '{}' -g '{}' -j '{}'".format(instance_name, self.rg, valid_import_job_id)
            ).get_output_in_json()
            assert(show_valid_import_job_output["status"] != "failed")
            show_invalid_import_job_output = self.cmd(
                "dt job import show -n '{}' -g '{}' -j '{}'".format(instance_name, self.rg, invalid_import_job_id)
            ).get_output_in_json()
            assert(show_invalid_import_job_output["status"] != "succeeded")
            if show_valid_import_job_output["status"] == "succeeded" and show_invalid_import_job_output["status"] == "failed":
                assert(show_invalid_import_job_output["error"]["error"]["code"] == "DTDLParsingError")
                assert(show_valid_import_job_output["error"] is None)
                break
            sleep(30)

        list_models_output = self.cmd(
            "dt model list -n {} -g {} --definition".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(list_models_output) == 10
        for model in list_models_output:
            assert model["id"]
            assert model["model"]

        twin_query_result = self.cmd(
            "dt twin query -n {} -q 'select * from digitaltwins'".format(instance_name)
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 10

        twin_ids = [twin["$dtId"] for twin in twin_query_result["result"]]
        relationship = "has"
        for twin_id in twin_ids:
            twin_relationship_list_result = self.cmd(
                "dt twin relationship list -n {} -g {} --twin-id {} --relationship {}".format(
                    instance_name, self.rg, twin_id, relationship
                )
            ).get_output_in_json()
            assert len(twin_relationship_list_result) == 1

        # Delete import jobs
        self.cmd(
            "dt job import delete -n '{}' -g '{}' -j '{}' -y".format(instance_name, self.rg, valid_import_job_id)
        )
        self.cmd(
            "dt job import delete -n '{}' -g '{}' -j '{}' -y".format(instance_name, self.rg, invalid_import_job_id)
        )

        # Delete output files from storage container
        if self.cmd(
            "storage blob exists --connection-string '{}' -c '{}' -n '{}'".format(
                self.storage_cstring, self.storage_container, valid_import_job_output_filename
            )
        ).get_output_in_json()["exists"]:
            self.cmd(
                "storage blob delete --connection-string '{}' -c '{}' -n '{}'".format(
                    self.storage_cstring, self.storage_container, valid_import_job_output_filename
                )
            )

        if self.cmd(
            "storage blob exists --connection-string '{}' -c '{}' -n '{}'".format(
                self.storage_cstring, self.storage_container, invalid_import_job_output_filename
            )
        ).get_output_in_json()["exists"]:
            self.cmd(
                "storage blob delete --connection-string '{}' -c '{}' -n '{}'".format(
                    self.storage_cstring, self.storage_container, invalid_import_job_output_filename
                )
            )


def assert_import_job_creation(create_import_job_output):
    assert(create_import_job_output is not None)
    assert(create_import_job_output["error"] is None)
    assert(create_import_job_output["status"] == "notstarted")
