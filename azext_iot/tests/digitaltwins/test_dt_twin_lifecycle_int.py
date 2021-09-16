# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
from time import sleep
from knack.log import get_logger
from . import DTLiveScenarioTest
from . import (
    generate_resource_id,
)

logger = get_logger(__name__)


@pytest.mark.usefixtures("set_cwd")
class TestDTTwinLifecycle(DTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDTTwinLifecycle, self).__init__(test_case)

    def test_dt_twin(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        models_directory = "./models"
        floor_dtmi = "dtmi:com:example:Floor;1"
        floor_twin_id = "myfloor"
        room_dtmi = "dtmi:com:example:Room;1"
        room_twin_id = "myroom"
        thermostat_component_id = "Thermostat"
        etag = 'AAAA=='

        create_output = self.cmd(
            "dt create -n {} -g {} -l {}".format(instance_name, self.rg, self.region)
        ).get_output_in_json()
        self.track_instance(create_output)

        self.cmd(
            "dt role-assignment create -n {} -g {} --assignee {} --role '{}'".format(
                instance_name, self.rg, self.current_user, self.role_map["owner"]
            )
        )
        # Wait for RBAC to catch-up
        sleep(60)

        self.cmd(
            "dt model create -n {} --from-directory '{}'".format(
                instance_name, models_directory
            )
        )

        twin_query_result = self.cmd(
            "dt twin query -n {} -q 'select * from digitaltwins'".format(instance_name)
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

        self.kwargs["emptyThermostatComponentJson"] = json.dumps(
            {"Thermostat": {"$metadata": {}}}
        )

        floor_twin = self.cmd(
            "dt twin create -n {} --dtmi {} --twin-id {}".format(
                instance_name, floor_dtmi, floor_twin_id
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=floor_twin,
            expected_twin_id=floor_twin_id,
            expected_dtmi=floor_dtmi,
        )

        # twin create with component - example of bare minimum --properties

        # create twin will fail without --properties
        self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {}".format(
                instance_name, self.rg, room_dtmi, room_twin_id
            ),
            expect_failure=True,
        )

        # minimum component object with empty $metadata object
        min_room_twin = self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{emptyThermostatComponentJson}",
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=min_room_twin,
            expected_twin_id=room_twin_id,
            expected_dtmi=room_dtmi,
            properties=self.kwargs["emptyThermostatComponentJson"],
            component_name=thermostat_component_id,
        )

        replaced_room_twin = self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{tempAndThermostatComponentJson}",
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=replaced_room_twin,
            expected_twin_id=room_twin_id,
            expected_dtmi=room_dtmi,
            properties=self.kwargs["tempAndThermostatComponentJson"],
            component_name=thermostat_component_id,
        )

        # new twin cannot be created with same twin_id if if-none-match provided
        self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --if-none-match --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{emptyThermostatComponentJson}",
            ),
            expect_failure=True
        )

        # delete command should fail if etag is different
        self.cmd(
            "dt twin delete -n {} -g {} --twin-id {} --etag '{}'".format(
                instance_name,
                self.rg,
                room_twin_id,
                etag
            ),
            expect_failure=True
        )

        self.cmd(
            "dt twin delete -n {} -g {} --twin-id {}".format(
                instance_name,
                self.rg,
                room_twin_id,
            )
        )

        room_twin = self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{tempAndThermostatComponentJson}",
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=room_twin,
            expected_twin_id=room_twin_id,
            expected_dtmi=room_dtmi,
            properties=self.kwargs["tempAndThermostatComponentJson"],
            component_name=thermostat_component_id,
        )

        # Component

        thermostat_component = self.cmd(
            "dt twin component show -n {} -g {} --twin-id {} --component {}".format(
                instance_name,
                self.rg,
                room_twin_id,
                thermostat_component_id,
            )
        ).get_output_in_json()

        self.kwargs["thermostatJsonPatch"] = json.dumps(
            [{"op": "replace", "path": "/setPointTemp", "value": 50.5}]
        )

        # Currently component update does not return value
        self.cmd(
            "dt twin component update -n {} -g {} --twin-id {} --component {} --json-patch '{}'".format(
                instance_name,
                self.rg,
                room_twin_id,
                thermostat_component_id,
                "{thermostatJsonPatch}",
            )
        )

        thermostat_component = self.cmd(
            "dt twin component show -n {} -g {} --twin-id {} --component {}".format(
                instance_name,
                self.rg,
                room_twin_id,
                thermostat_component_id,
            )
        ).get_output_in_json()

        assert (
            thermostat_component["setPointTemp"]
            == json.loads(self.kwargs["thermostatJsonPatch"])[0]["value"]
        )

        twins_id_list = [
            (floor_twin_id, floor_dtmi),
            (room_twin_id, room_dtmi),
        ]

        for twin_tuple in twins_id_list:
            twin = self.cmd(
                "dt twin show -n {} --twin-id {} {}".format(
                    instance_name,
                    twin_tuple[0],
                    "-g {}".format(self.rg) if twins_id_list[-1] == twin_tuple else "",
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
                instance_name,
                room_twin_id,
                "{temperatureJsonPatch}",
            )
        ).get_output_in_json()

        assert (
            update_twin_result["Temperature"]
            == json.loads(self.kwargs["temperatureJsonPatch"])["value"]
        )

        self.cmd(
            "dt twin update -n {} --twin-id {} --json-patch '{}' --etag '{}'".format(
                instance_name,
                room_twin_id,
                "{temperatureJsonPatch}",
                etag
            ),
            expect_failure=True
        )

        update_twin_result = self.cmd(
            "dt twin update -n {} --twin-id {} --json-patch '{}' --etag '{}'".format(
                instance_name,
                room_twin_id,
                "{temperatureJsonPatch}",
                update_twin_result["$etag"]
            )
        ).get_output_in_json()

        assert (
            update_twin_result["Temperature"]
            == json.loads(self.kwargs["temperatureJsonPatch"])["value"]
        )

        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins'".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 2

        # Relationship Tests
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
            "--target-twin-id {}".format(
                instance_name,
                self.rg,
                relationship_id,
                relationship,
                floor_twin_id,
                room_twin_id,
            )
        ).get_output_in_json()

        twin_relationship_create_result = self.cmd(
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

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_create_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=floor_twin_id,
            target_id=room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        # new twin cannot be created with same twin_id if if-none-match provided
        twin_relationship_create_result = self.cmd(
            "dt twin relationship create -n {} -g {} --relationship-id {} --relationship {} --twin-id {} "
            "--target-twin-id {} --if-none-match --properties '{}'".format(
                instance_name,
                self.rg,
                relationship_id,
                relationship,
                floor_twin_id,
                room_twin_id,
                "{relationshipJson}",
            ),
            expect_failure=True
        )

        twin_relationship_show_result = self.cmd(
            "dt twin relationship show -n {} -g {} --twin-id {} --relationship-id {}".format(
                instance_name,
                self.rg,
                floor_twin_id,
                relationship_id,
            )
        ).get_output_in_json()

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_show_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=floor_twin_id,
            target_id=room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        twin_edge_update_result = self.cmd(
            "dt twin relationship update -n {} -g {} --relationship-id {} --twin-id {} "
            "--json-patch '{}'".format(
                instance_name,
                self.rg,
                relationship_id,
                floor_twin_id,
                "{relationshipJsonPatch}",
            )
        ).get_output_in_json()

        assert (
            twin_edge_update_result["ownershipUser"]
            == json.loads(self.kwargs["relationshipJsonPatch"])["value"]
        )

        # Fail to update if the etag if different
        self.cmd(
            "dt twin relationship update -n {} -g {} --relationship-id {} --twin-id {} "
            "--json-patch '{}' --etag '{}'".format(
                instance_name,
                self.rg,
                relationship_id,
                floor_twin_id,
                "{relationshipJsonPatch}",
                etag
            ),
            expect_failure=True
        )

        twin_edge_update_result = self.cmd(
            "dt twin relationship update -n {} -g {} --relationship-id {} --twin-id {} "
            "--json-patch '{}' --etag '{}'".format(
                instance_name,
                self.rg,
                relationship_id,
                floor_twin_id,
                "{relationshipJsonPatch}",
                twin_edge_update_result["$etag"]
            )
        ).get_output_in_json()

        assert (
            twin_edge_update_result["ownershipUser"]
            == json.loads(self.kwargs["relationshipJsonPatch"])["value"]
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                instance_name,
                floor_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} -g {} --twin-id {} --relationship {}".format(
                instance_name,
                self.rg,
                floor_twin_id,
                relationship,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                instance_name,
                room_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 0

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {} --incoming".format(
                instance_name,
                room_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {} --kind {} --incoming".format(
                instance_name, room_twin_id, relationship
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        self.cmd(
            "dt twin relationship delete -n {} --twin-id {} -r {} --etag '{}'".format(
                instance_name,
                floor_twin_id,
                relationship_id,
                etag
            ),
            expect_failure=True
        )

        # No output from API for delete edge
        self.cmd(
            "dt twin relationship delete -n {} --twin-id {} -r {}".format(
                instance_name,
                floor_twin_id,
                relationship_id,
            )
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} -g {} --twin-id {} --kind {}".format(
                instance_name,
                self.rg,
                floor_twin_id,
                relationship,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 0

        # Twin + Component Telemetry. Neither returns data. Only 204 status code.

        self.kwargs["telemetryJson"] = json.dumps({"data": generate_resource_id()})

        self.cmd(
            "dt twin telemetry send -n {} -g {} --twin-id {} --telemetry '{}'".format(
                instance_name,
                self.rg,
                room_twin_id,
                "{telemetryJson}",
            )
        )

        self.cmd(
            "dt twin telemetry send -n {} -g {} --twin-id {} --component {} --telemetry '{}'".format(
                instance_name,
                self.rg,
                room_twin_id,
                thermostat_component_id,
                "{telemetryJson}",
            )
        )

        self.cmd(
            "dt twin delete-all -n {} --yes".format(
                instance_name,
            )
        )
        sleep(5)  # Wait for API to catch up

        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins' --cost".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 0
        assert twin_query_result["cost"]

        self.cmd(
            "dt reset -n {} --yes".format(
                instance_name,
            )
        )

        model_query_result = self.cmd(
            "dt model list -n {} -g {}".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(model_query_result) == 0

    def test_dt_twin_bulk_delete(self):
        self.wait_for_capacity()
        instance_name = generate_resource_id()
        models_directory = "./models"
        floor_dtmi = "dtmi:com:example:Floor;1"
        floor_twin_id = "myfloor"
        room_dtmi = "dtmi:com:example:Room;1"
        room_twin_id = "myroom"
        thermostat_component_id = "Thermostat"

        create_output = self.cmd(
            "dt create -n {} -g {} -l {}".format(instance_name, self.rg, self.region)
        ).get_output_in_json()
        self.track_instance(create_output)

        self.cmd(
            "dt role-assignment create -n {} -g {} --assignee {} --role '{}'".format(
                instance_name, self.rg, self.current_user, self.role_map["owner"]
            )
        )
        # Wait for RBAC to catch-up
        sleep(60)

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

        floor_twin = self.cmd(
            "dt twin create -n {} --dtmi {} --twin-id {}".format(
                instance_name, floor_dtmi, floor_twin_id
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=floor_twin,
            expected_twin_id=floor_twin_id,
            expected_dtmi=floor_dtmi,
        )

        room_twin = self.cmd(
            "dt twin create -n {} -g {} --dtmi {} --twin-id {} --properties '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
                room_twin_id,
                "{tempAndThermostatComponentJson}",
            )
        ).get_output_in_json()

        assert_twin_attributes(
            twin=room_twin,
            expected_twin_id=room_twin_id,
            expected_dtmi=room_dtmi,
            properties=self.kwargs["tempAndThermostatComponentJson"],
            component_name=thermostat_component_id,
        )

        sleep(5)  # Wait for API to catch up
        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins'".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 2

        # Relationship Tests
        relationship_id = "myedge"
        relationship = "contains"
        self.kwargs["relationshipJson"] = json.dumps(
            {"ownershipUser": "me", "ownershipDepartment": "mydepartment"}
        )

        twin_relationship_create_result = self.cmd(
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

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_create_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=floor_twin_id,
            target_id=room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                instance_name,
                floor_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 1

        # Delete all relationships
        self.cmd(
            "dt twin relationship delete-all -n {} --twin-id {} --yes".format(
                instance_name,
                floor_twin_id,
            )
        )

        twin_relationship_list_result = self.cmd(
            "dt twin relationship list -n {} --twin-id {}".format(
                instance_name,
                floor_twin_id,
            )
        ).get_output_in_json()
        assert len(twin_relationship_list_result) == 0

        # Recreate relationship for delete all twins
        twin_relationship_create_result = self.cmd(
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

        assert_twin_relationship_attributes(
            twin_relationship_obj=twin_relationship_create_result,
            expected_relationship=relationship,
            relationship_id=relationship_id,
            source_id=floor_twin_id,
            target_id=room_twin_id,
            properties=self.kwargs["relationshipJson"],
        )

        self.cmd(
            "dt twin delete-all -n {} --yes".format(
                instance_name,
            )
        )
        sleep(5)  # Wait for API to catch up

        twin_query_result = self.cmd(
            "dt twin query -n {} -g {} -q 'select * from digitaltwins' --cost".format(
                instance_name, self.rg
            )
        ).get_output_in_json()
        assert len(twin_query_result["result"]) == 0
        assert twin_query_result["cost"]

        model_query_result = self.cmd(
            "dt model list -n {} -g {}".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(model_query_result) > 0

        self.cmd(
            "dt twin create -n {} --dtmi {} --twin-id {}".format(
                instance_name, floor_dtmi, floor_twin_id
            )
        )

        self.cmd(
            "dt reset -n {} --yes".format(
                instance_name,
            )
        )

        # Wait for API to catch up
        sleep(10)

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
        assert properties

        for key in properties:
            if key != component_name:
                assert properties[key] == twin[key]


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
