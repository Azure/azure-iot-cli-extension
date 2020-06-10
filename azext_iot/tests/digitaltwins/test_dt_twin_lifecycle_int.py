# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
from time import sleep
from knack.log import get_logger
from ..settings import DynamoSettings
from . import DTLiveScenarioTest
from . import (
    generate_resource_id,
    generate_group_id,
)

logger = get_logger(__name__)

twin_tests_env_vars = [
    "azext_dt_rbac_assignee_owner",
]

settings = DynamoSettings([], twin_tests_env_vars)
run_tests = False

if all([settings.env.azext_dt_rbac_assignee_owner]):
    run_tests = True


@pytest.mark.skipif(not run_tests, reason="azext_dt_rbac_assignee_owner is required.")
@pytest.mark.usefixtures("set_cwd")
class TestDTTwinLifecycle(DTLiveScenarioTest):
    def __init__(self, test_case):
        self.group_names = [generate_group_id()]
        self.instance_names = [generate_resource_id(), generate_resource_id()]
        self.rbac_assignee_owner = settings.env.azext_dt_rbac_assignee_owner
        self.dt_location = "westus2"
        self.instance_name = generate_resource_id()
        self.floor_dtmi = "dtmi:example:Floor;1"
        self.floor_twin_id = "myfloor"
        self.room_dtmi = "dtmi:example:Room;1"
        self.room_twin_id = "myroom"
        self.thermostat_dtmi = "dtmi:com:example:Thermostat;1"
        self.thermostat_component_id = "Thermostat"

        super(TestDTTwinLifecycle, self).__init__(test_case, self.group_names)

    def test_dt_twin(self):
        models_directory = "./models"

        self.cmd(
            "dt create -n {} -g {} -l {}".format(
                self.instance_name, self.group_names[0], self.dt_location
            )
        )

        self.cmd(
            "dt role-assignment create -n {} -g {} --assignee {} --role '{}'".format(
                self.instance_name, self.group_names[0], self.rbac_assignee_owner, self.role_map["owner"]
            )
        )
        # Wait for RBAC to catch-up
        sleep(10)

        self.cmd(
            "dt model create -n {} --from-directory '{}'".format(
                self.instance_name, models_directory
            )
        )

        twin_query_result = self.cmd(
            "dt twin query -n {} -q 'select * from digitaltwins'".format(
                self.instance_name
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 0

        self.kwargs["tempAndThermostatComponentJson"] = json.dumps(
            {
                "Temperature": 10.2,
                "Thermostat": {
                    "$metadata": {},
                    "setPointTemp": 23.12,
                },
            }
        )

        floor_twin = self.cmd(
            "dt twin create -n {} --dtmi {} --twin-id {}".format(
                self.instance_name, self.floor_dtmi, self.floor_twin_id
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=floor_twin,
            expected_twin_id=self.floor_twin_id,
            expected_dtmi=self.floor_dtmi,
        )

        room_twin = self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                self.instance_name,
                self.group_names[0],
                self.room_dtmi,
                self.room_twin_id,
                "{tempAndThermostatComponentJson}",
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=room_twin,
            expected_twin_id=self.room_twin_id,
            expected_dtmi=self.room_dtmi,
            properties=self.kwargs["tempAndThermostatComponentJson"],
            component_name=self.thermostat_component_id,
        )

        # Component

        thermostat_component = self.cmd(
            "dt twin component show -n {} -g {} --twin-id {} --component {}".format(
                self.instance_name,
                self.group_names[0],
                self.room_twin_id,
                self.thermostat_component_id,
            )
        ).get_output_in_json()

        self.kwargs["thermostatJsonPatch"] = json.dumps(
            [{"op": "replace", "path": "/setPointTemp", "value": 50.5}]
        )

        # Currently component update does not return value
        self.cmd(
            "dt twin component update -n {} -g {} --twin-id {} --component {} --json-patch '{}'".format(
                self.instance_name,
                self.group_names[0],
                self.room_twin_id,
                self.thermostat_component_id,
                "{thermostatJsonPatch}",
            )
        )

        thermostat_component = self.cmd(
            "dt twin component show -n {} -g {} --twin-id {} --component {}".format(
                self.instance_name,
                self.group_names[0],
                self.room_twin_id,
                self.thermostat_component_id,
            )
        ).get_output_in_json()

        assert (
            thermostat_component["setPointTemp"]
            == json.loads(self.kwargs["thermostatJsonPatch"])[0]["value"]
        )

        twins_id_list = [
            (self.floor_twin_id, self.floor_dtmi),
            (self.room_twin_id, self.room_dtmi),
        ]

        for twin_tuple in twins_id_list:
            twin = self.cmd(
                "dt twin show -n {} --twin-id {} {}".format(
                    self.instance_name,
                    twin_tuple[0],
                    "-g {}".format(self.group_names[0])
                    if twins_id_list[-1] == twin_tuple
                    else "",
                )
            ).get_output_in_json()
            assert_twin_attributes(
                twin=twin, expected_twin_id=twin_tuple[0], expected_dtmi=twin_tuple[1]
            )

        self.kwargs["temperatureJsonPatch"] = json.dumps(
            {"op": "replace", "path": "/Temperature", "value": 20.2}
        )

        update_twin_result = self.cmd(
            "dt twin update -n {} --twin-id {} --json-patch '{}'".format(
                self.instance_name, self.room_twin_id, "{temperatureJsonPatch}",
            )
        ).get_output_in_json()

        assert (
            update_twin_result["Temperature"]
            == json.loads(self.kwargs["temperatureJsonPatch"])["value"]
        )

        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins'".format(
                self.instance_name, self.group_names[0]
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 2

        relationship_id = "myedge"
        relationship = "contains"
        self.kwargs["relationshipJson"] = json.dumps(
            {"ownershipUser": "me", "ownershipDepartment": "mydepartment"}
        )
        self.kwargs["relationshipJsonPatch"] = json.dumps(
            {"op": "replace", "path": "/ownershipUser", "value": "meme"}
        )

        twin_relationship_create_result = self.cmd(
            "dt twin relationship create -n {} -g {} --relationship-id {} --relationship {} --twin-id {} "
            "--target-twin-id {} --properties '{}'".format(
                self.instance_name,
                self.group_names[0],
                relationship_id,
                relationship,
                self.floor_twin_id,
                self.room_twin_id,
                "{relationshipJson}",
            )
        ).get_output_in_json()

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_create_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=self.floor_twin_id,
            target_id=self.room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        twin_relationship_show_result = self.cmd(
            "dt twin relationship show -n {} -g {} --twin-id {} --relationship-id {}".format(
                self.instance_name,
                self.group_names[0],
                self.floor_twin_id,
                relationship_id,
            )
        ).get_output_in_json()

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_show_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=self.floor_twin_id,
            target_id=self.room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        twin_edge_update_result = self.cmd(
            "dt twin relationship update -n {} -g {} --relationship-id {} --twin-id {} "
            "--json-patch '{}'".format(
                self.instance_name,
                self.group_names[0],
                relationship_id,
                self.floor_twin_id,
                "{relationshipJsonPatch}",
            )
        ).get_output_in_json()

        assert (
            twin_edge_update_result["ownershipUser"]
            == json.loads(self.kwargs["relationshipJsonPatch"])["value"]
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                self.instance_name, self.floor_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} -g {} --twin-id {} --relationship {}".format(
                self.instance_name,
                self.group_names[0],
                self.floor_twin_id,
                relationship,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                self.instance_name, self.room_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 0

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {} --incoming".format(
                self.instance_name, self.room_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {} --kind {} --incoming".format(
                self.instance_name, self.room_twin_id, relationship
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        # No output from API for delete edge
        self.cmd(
            "dt twin relationship delete -n {} --twin-id {} -r {}".format(
                self.instance_name, self.floor_twin_id, relationship_id,
            )
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} -g {} --twin-id {} --kind {}".format(
                self.instance_name,
                self.group_names[0],
                self.floor_twin_id,
                relationship,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 0

        # Twin + Component Telemetry. Neither returns data. Only 204 status code.

        self.kwargs["telemetryJson"] = json.dumps({"data": generate_resource_id()})

        self.cmd(
            "dt twin telemetry send -n {} -g {} --twin-id {} --telemetry '{}'".format(
                self.instance_name,
                self.group_names[0],
                self.room_twin_id,
                "{telemetryJson}",
            )
        )

        self.cmd(
            "dt twin telemetry send -n {} -g {} --twin-id {} --component {} --telemetry '{}'".format(
                self.instance_name,
                self.group_names[0],
                self.room_twin_id,
                self.thermostat_component_id,
                "{telemetryJson}",
            )
        )

        for twin_tuple in twins_id_list:
            # No output from API for delete twin
            self.cmd(
                "dt twin delete -n {} --twin-id {} {}".format(
                    self.instance_name,
                    twin_tuple[0],
                    "-g {}".format(self.group_names[0])
                    if twins_id_list[-1] == twin_tuple
                    else "",
                )
            )
        sleep(4)  # Wait for API to catch up
        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins' --cost".format(
                self.instance_name, self.group_names[0]
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 0
        assert twin_query_result["cost"]


# TODO: Refactor - limited interface
def assert_twin_attributes(
    twin, expected_twin_id, expected_dtmi, properties=None, component_name=None
):
    assert twin["$dtId"] == expected_twin_id
    assert twin["$etag"]

    metadata = twin["$metadata"]
    metadata["$model"] == expected_dtmi

    if properties:
        properties = json.loads(properties)

        for key in properties:
            if key != component_name:
                assert metadata[key]["desiredValue"] == properties[key]

        if component_name:
            component_metadata = twin[component_name]["$metadata"]
            component_props = properties[component_name]

            for key in component_props:
                if key != "$metadata":
                    assert (
                        component_metadata[key]["desiredValue"] == component_props[key]
                    )


def assert_twin_relationship_attributes(
    twin_relationship_obj,
    expected_relationship,
    relationship_id,
    source_id,
    target_id,
    properties=None,
):
    assert twin_relationship_obj["$relationshipId"] == relationship_id
    assert twin_relationship_obj["$relationshipName"] == expected_relationship
    assert twin_relationship_obj["$sourceId"] == source_id
    assert twin_relationship_obj["$targetId"] == target_id

    if properties:
        properties = json.loads(properties)
        for key in properties:
            assert twin_relationship_obj[key] == properties[key]
