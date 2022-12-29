# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
import pytest
import azext_iot.iothub.commands_state as subject
from azure.cli.core.azclierror import (
    FileOperationError,
    BadRequestError,
    MutuallyExclusiveArgumentError
)
import azext_iot.iothub.providers.state_constants as constants

from azext_iot.tests.conftest import generate_cs

hub_name = "hubname"
hub_rg = "hubrg"
resource_not_found_error = "Resource not found."


class TestHubStateExport:
    def test_present_file_no_replace(self, fixture_cmd, fixture_ghcs, mocker):
        patched_prompt_y_n = mocker.patch("azext_iot.iothub.providers.state.prompt_y_n")
        patched_prompt_y_n.return_value = False

        # make a temporary file
        fake_file = "fake_file.json"
        with open(fake_file, "w") as f:
            f.write("Hello World")

        with pytest.raises(FileOperationError) as error:
            subject.state_export(
                cmd=fixture_cmd,
                state_file=fake_file,
                hub_name="someHub",
                resource_group_name="somerg"
            )
        assert constants.FILE_NOT_EMPTY_ERROR == str(error.value)

        if os.path.isfile(fake_file):
            os.remove(fake_file)

    def test_hub_login_with_arm_aspects(self, fixture_cmd):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_export(
                cmd=fixture_cmd,
                state_file="./file.json",
                login=generate_cs()
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)


class TestHubStateImport:
    def test_missing_file(self, fixture_cmd):
        file_name = "./file.json"
        with pytest.raises(FileOperationError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file="./file.json",
                hub_name="someHub",
                resource_group_name="somerg"
            )
        assert constants.FILE_NOT_FOUND_ERROR.format(file_name) == str(error.value)

    def test_hub_login_with_arm_aspects(self, fixture_cmd):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file="./file.json",
                login=generate_cs()
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)

    def test_missing_arm_file(self, fixture_cmd):
        hub_name = "someHub"
        # make a temporary file
        fake_file = "fake_file.json"
        with open(fake_file, "w") as f:
            f.write("{}")

        with pytest.raises(BadRequestError) as error:
            subject.state_import(
                cmd=fixture_cmd,
                state_file=fake_file,
                hub_name=hub_name,
                resource_group_name="somerg"
            )
        assert constants.HUB_NOT_CREATED_MSG.format(hub_name) == str(error.value)

        if os.path.isfile(fake_file):
            os.remove(fake_file)


class TestHubStateMigrate:
    def test_hub_login_with_arm_aspects(self, fixture_cmd, fixture_ghcs):
        with pytest.raises(MutuallyExclusiveArgumentError) as error:
            subject.state_migrate(
                cmd=fixture_cmd,
                login=generate_cs(),
                orig_hub_login=generate_cs()
            )
        assert constants.LOGIN_WITH_ARM_ERROR == str(error.value)
