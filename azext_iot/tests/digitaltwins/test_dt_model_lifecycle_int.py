# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import json
import os
from time import sleep
from knack.log import get_logger
from azext_iot.common.utility import (
    scantree,
    process_json_arg,
)
from . import DTLiveScenarioTest
from . import generate_resource_id

logger = get_logger(__name__)


@pytest.mark.usefixtures("set_cwd")
class TestDTModelLifecycle(DTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestDTModelLifecycle, self).__init__(test_case)

    def test_dt_models(self):
        self.wait_for_capacity()

        instance_name = generate_resource_id()
        models_directory = "./models"
        inline_model = "./models/Floor.json"
        room_dtmi = "dtmi:com:example:Room;1"
        floor_dtmi = "dtmi:com:example:Floor;1"
        ontology_directories = [
            "./references/opendigitaltwins-building/Ontology",
            "./references/opendigitaltwins-smartcities/Ontology",
            "./references/opendigitaltwins-energygrid/Ontology"
        ]

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

        create_models_output = self.cmd(
            "dt model create -n {} --from-directory '{}'".format(
                instance_name, models_directory
            )
        ).get_output_in_json()

        assert_create_models_attributes(
            create_models_output, directory_path=models_directory
        )

        list_models_output = self.cmd(
            "dt model list -n {}".format(instance_name)
        ).get_output_in_json()
        assert len(list_models_output) == len(create_models_output)
        for model in list_models_output:
            assert model["id"]

        list_models_output = self.cmd(
            "dt model list -n {} -g {} --definition".format(instance_name, self.rg)
        ).get_output_in_json()
        assert len(list_models_output) == len(create_models_output)
        for model in list_models_output:
            assert model["id"]
            assert model["model"]

        model_dependencies_output = self.cmd(
            "dt model list -n {} -g {} --dependencies-for '{}'".format(
                instance_name,
                self.rg,
                room_dtmi,
            )
        ).get_output_in_json()
        assert len(model_dependencies_output) == 2

        # Multiple dependencies-for should return union of all dependencies
        model_multi_dependencies_output = self.cmd(
            "dt model list -n {} -g {} --dependencies-for '{}'".format(
                instance_name,
                self.rg,
                "' '".join([room_dtmi, floor_dtmi]),
            )
        ).get_output_in_json()
        assert len(model_multi_dependencies_output) == 3

        for model in create_models_output:
            model_show_output = self.cmd(
                "dt model show -n {} --dtmi '{}'".format(instance_name, model["id"])
            ).get_output_in_json()
            assert model_show_output["id"] == model["id"]

            model_show_def_output = self.cmd(
                "dt model show -n {} -g {} --dtmi '{}' --definition".format(
                    instance_name, self.rg, model["id"]
                )
            ).get_output_in_json()

            assert model_show_def_output["id"] == model["id"]
            assert model_show_def_output["model"]
            assert model_show_def_output["model"]["@id"] == model["id"]

        model_json = process_json_arg(inline_model, "models")
        model_id = model_json["@id"]
        inc_model_id = _increment_model_id(model_id)
        model_json["@id"] = inc_model_id
        self.kwargs["modelJson"] = json.dumps(model_json)
        create_models_inline_output = self.cmd(
            "dt model create -n {} --models '{}'".format(instance_name, "{modelJson}")
        ).get_output_in_json()
        assert create_models_inline_output[0]["id"] == inc_model_id

        self.cmd(
            "dt model delete -n {} --dtmi '{}'".format(instance_name, inc_model_id)
        )
        self.cmd(
            "dt model create -n {} --models '{}'".format(instance_name, "{modelJson}")
        )

        update_model_output = self.cmd(
            "dt model update -n {} --dtmi '{}' --decommission".format(
                instance_name, inc_model_id
            )
        ).get_output_in_json()
        assert update_model_output["id"] == inc_model_id
        assert update_model_output["decommissioned"] is True

        list_models_output = self.cmd(
            "dt model list -n {}".format(instance_name)
        ).get_output_in_json()

        # Delete all
        self.cmd(
            "dt model delete-all -n {} --yes".format(instance_name)
        )

        assert (
            len(
                self.cmd(
                    "dt model list -n {}".format(instance_name)
                ).get_output_in_json()
            )
            == 0
        )

        for ontology_directory in ontology_directories:
            # Run the following part of test only if model files exist in the ontology directory
            if os.path.isdir(ontology_directory) and len(os.listdir(ontology_directory)) > 0:
                # Create Ontology with number of models exceeding API limit
                create_ontology_output = self.cmd(
                    "dt model create -n {} --from-directory '{}'".format(
                        instance_name, ontology_directory
                    )
                ).get_output_in_json()

                assert_create_models_attributes(
                    create_ontology_output, directory_path=ontology_directory
                )


def assert_create_models_attributes(result, directory_path=None, models=None):
    if not any([directory_path, models]):
        raise ValueError("Provide directory_path or models.")

    local_test_models = []
    if directory_path:
        local_test_models = _get_models_from_directory(directory_path)

    assert len(result) == len(local_test_models)

    for m in result:
        local_model = [model for model in local_test_models if model["id"] == m["id"]]
        assert len(local_model) == 1
        assert m["id"] == local_model[0]["id"]


def _get_models_from_directory(from_directory):
    payload = []
    for entry in scantree(from_directory):
        if not entry.name.endswith(".json"):
            logger.debug(
                "Skipping {} - model file must end with .json".format(entry.path)
            )
            continue
        entry_json = process_json_arg(content=entry.path, argument_name=entry.name)
        payload.append(entry_json)

    return _get_models_metadata(payload)


def _get_models_metadata(models):
    models_metadata = []
    for model in models:
        metadata = {
            "id": model["@id"],
            "decommissioned": False,
            "displayName": model.get("displayName", ""),
            "resolveSource": "$devloper",  # Currently no other resolveSource
            "serviceOrigin": "ADT",  # Currently no other serviceOrigin
        }
        models_metadata.append(metadata)

    return models_metadata


def _increment_model_id(model_id):
    # This block is to increment model version for
    # executing model create of a different style
    model_ver = int(model_id.split(";")[-1])
    model_ver = model_ver + 1
    model_id_chars = list(model_id)
    model_id_chars[-1] = str(model_ver)
    inc_model_id = "".join(model_id_chars)
    return inc_model_id
