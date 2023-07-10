# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from typing import List, Optional

from knack.log import get_logger
from azext_iot.digitaltwins.providers.deletion_job import DEFAULT_DELETE_JOB_ID_PREFIX

from azext_iot.tests.helpers import assign_role_assignment
from . import DTLiveScenarioTest
from . import generate_resource_id
from time import sleep

logger = get_logger(__name__)
MAX_TRIES = 5
POLL_SLEEP_INTERVAL = 30


class TestDTDeleteJobs(DTLiveScenarioTest):
    def __init__(self, test_case):
        self.storage_cstring = None
        super(TestDTDeleteJobs, self).__init__(test_case)

    def test_dt_job_delete_all(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        models_directory = "./models"
        floor_dtmi = "dtmi:com:example:Floor;1"
        floor_twin_id = "myfloor"
        room_dtmi = "dtmi:com:example:Room;1"
        room_twin_id = "myroom"

        create_output = self.cmd(
            "dt create -n {} -g {} -l {}".format(instance_name, self.rg, self.region)
        ).get_output_in_json()
        self.track_instance(create_output)

        assign_role_assignment(
            role=self.role_map["owner"],
            scope=create_output["id"],
            assignee=self.current_user,
            wait=60)

        # Setup Models, Twins, Relationships
        self.cmd(
            "dt model create -n {} --from-directory '{}'".format(
                instance_name, models_directory
            )
        )

        self.kwargs["tempAndThermostatComponentJson"] = json.dumps(
            {
                "Temperature": 10.2,
                "Thermostat": {
                    "$metadata": {},
                    "setPointTemp": 23.12,
                },
            }
        )

        self.cmd(
            "dt twin create -n {} --dtmi {} --twin-id {}".format(
                instance_name, floor_dtmi, floor_twin_id
            )
        ).get_output_in_json()

        self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{tempAndThermostatComponentJson}",
            )
        ).get_output_in_json()

        sleep(5)  # Wait for API to catch up
        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins'".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 2

        relationship_id = "myedge"
        relationship = "contains"
        self.kwargs["relationshipJson"] = json.dumps(
            {"ownershipUser": "me", "ownershipDepartment": "mydepartment"}
        )

        self.cmd(
            "dt twin relationship create -n {} -g {} --relationship-id {} --relationship {} --twin-id {} "
            "--target-twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                relationship_id,
                relationship,
                floor_twin_id,
                room_twin_id,
                "{relationshipJson}",
            )
        ).get_output_in_json()

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                instance_name,
                floor_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        # Job part
        valid_delete_job_id = "{}_valid_delete_job".format(instance_name)
        create_valid_delete_job_output = self.cmd(
            "dt job deletion create -n '{}' -g '{}' -j '{}'".format(
                instance_name, self.rg, valid_delete_job_id
            )
        ).get_output_in_json()

        assert_delete_job_creation(
            create_valid_delete_job_output, valid_delete_job_id
        )

        error = poll_job_status(
            cmd=self.cmd,
            rg=self.rg,
            instance_name=instance_name,
            job_id=valid_delete_job_id,
            expected_statuses=["succeeded"]
        )
        assert error is None

        model_query_result = self.cmd(
            "dt model list -n {} -g {}".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(model_query_result) == 0

        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins' --cost".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 0

        create_generated_delete_job_output = self.cmd(
            "dt job deletion create -n '{}' -g '{}'".format(
                instance_name, self.rg
            )
        ).get_output_in_json()

        assert_delete_job_creation(
            create_generated_delete_job_output
        )

        error = poll_job_status(
            cmd=self.cmd,
            rg=self.rg,
            instance_name=instance_name,
            job_id=create_generated_delete_job_output["id"],
            expected_statuses=["succeeded"]
        )
        assert error is None

        list_job_output = self.cmd(
            "dt job deletion list -n '{}' -g '{}'".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(list_job_output) == 2


def poll_job_status(cmd, rg: str, instance_name: str, job_id: str, expected_statuses: List[str]) -> Optional[dict]:
    """
    Helper function to poll job deletion status until finalized. Returns the error.

    Note that the first status in expected_statuses should be the expected final status. This method will check for running
    and not started statuses without needing to be specified in expected_statuses.
    """
    num_tries = 0
    final_status = expected_statuses[0]
    expected_statuses.extend(["running", "notstarted"])
    while num_tries < MAX_TRIES:
        num_tries += 1
        deletion_job_output = cmd(
            "dt job deletion show -n '{}' -g '{}' -j '{}'".format(instance_name, rg, job_id)
        ).get_output_in_json()
        assert deletion_job_output["status"] in expected_statuses
        if deletion_job_output["status"] == final_status:
            return deletion_job_output["error"]
        sleep(POLL_SLEEP_INTERVAL)


def assert_delete_job_creation(
    create_delete_job_output: dict,
    expected_job_id: str = None
):
    assert create_delete_job_output
    assert create_delete_job_output["createdDateTime"]
    assert create_delete_job_output["purgeDateTime"]
    assert create_delete_job_output["finishedDateTime"] is None
    assert create_delete_job_output["error"] is None
    assert create_delete_job_output["status"] == "notstarted"
    assert create_delete_job_output["id"]
    # We know the expected job id only when it is passed in as a param, else it is system generated
    if expected_job_id:
        assert create_delete_job_output["id"] == expected_job_id
    else:
        assert create_delete_job_output["id"].startswith(DEFAULT_DELETE_JOB_ID_PREFIX)
