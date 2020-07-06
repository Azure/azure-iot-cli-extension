# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
import random
import json
import os

from io import open
from os.path import exists
from azure.cli.testsdk import LiveScenarioTest
from azext_iot.common.utility import read_file_content

_interface_payload = "test_pnp_create_payload_interface.json"
_capability_model_payload = "test_pnp_create_payload_model.json"


@pytest.mark.usefixtures("set_cwd")
class TestPnPModel(LiveScenarioTest):

    rand_val = random.randint(1, 15)

    def __init__(self, _):
        super(TestPnPModel, self).__init__(_)
        self.kwargs.update(
            {"model": "test_model_definition.json",}
        )

    def setUp(self):
        if self._testMethodName == "test_model_life_cycle":
            model = str(read_file_content(_capability_model_payload))
            _model_id = "{}{}".format(json.loads(model)["@id"], TestPnPModel.rand_val)
            self.kwargs.update({"model_id": _model_id})
            model_newContent = model.replace(
                json.loads(model)["@id"], self.kwargs["model_id"]
            )
            model_newContent = model_newContent.replace("\n", "")

            fo = open(self.kwargs["model"], "w+", encoding="utf-8")
            fo.write(model_newContent)
            fo.close()

    def tearDown(self):
        if exists(self.kwargs["model"]):
            os.remove(self.kwargs["model"])

    def test_model_life_cycle(self):

        # Error: missing model-id
        self.cmd(
            "iot pnp model create -m '' --model {model}", expect_failure=True,
        )

        # # Error: Invalid model definition file
        self.cmd(
            "iot pnp model create -m {model_id} --model ''", expect_failure=True,
        )

        # Error: wrong path of model definition
        self.cmd(
            "iot pnp model create -m {model_id} --model model.json", expect_failure=True,
        )

        # Success: Create new model
        created = self.cmd(
            "iot pnp model create -m {model_id} --model {model}",
        ).get_output_in_json()

        assert created["@id"] == self.kwargs["model_id"]

        # Checking the model list
        self.cmd(
            "iot pnp model list",
            checks=[
                self.greater_than("length([*])", 0),
                self.exists("[?modelId==`{}`]".format(self.kwargs["model_id"])),
            ],
        )

        # Get model
        model = self.cmd("iot pnp model show -m {model_id}").get_output_in_json()
        assert json.dumps(model)
        assert model["@id"] == self.kwargs["model_id"]

        # Publish model
        self.cmd("iot pnp model publish -m {model_id}")
