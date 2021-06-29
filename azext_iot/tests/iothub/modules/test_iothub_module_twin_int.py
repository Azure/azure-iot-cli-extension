# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from pathlib import Path
from uuid import uuid4

from azext_iot.common.utility import read_file_content
from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_BASIC)

LIVE_HUB = "test-hub-" + str(uuid4())
LIVE_RG = settings.env.azext_iot_testrg
CWD = os.path.dirname(os.path.abspath(__file__))


class TestIoTHubModuleTwin(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubModuleTwin, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    def test_iothub_module_twin(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            device_count = 1
            device_ids = self.generate_device_names(device_count)
            module_count = 1
            module_ids = self.generate_device_names(module_count)

            patch_desired = {
                generate_generic_id(): generate_generic_id(),
                generate_generic_id(): generate_generic_id(),
            }
            patch_tags = {
                generate_generic_id(): generate_generic_id(),
                generate_generic_id(): generate_generic_id(),
            }

            self.kwargs["patch_desired"] = json.dumps(patch_desired)
            self.kwargs["patch_tags"] = json.dumps(patch_tags)

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            )

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            )

            # Initial twin state
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin show -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("moduleId", module_ids[0]),
                    self.check("deviceId", device_ids[0]),
                    self.exists("properties.desired"),
                    self.exists("properties.reported"),
                ],
            ).get_output_in_json()

            assert d0_twin["properties"]["desired"]["$version"] == 1
            assert d0_twin["properties"]["reported"]["$version"] == 1

            # Patch based twin update of desired props
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--desired '{patch_desired}'",  # Not f-string due to CLI TestFramework self.kwargs application :(
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            assert d0_twin["properties"]["desired"]["$version"] == 2

            for key in patch_desired:
                assert d0_twin["properties"]["desired"][key] == patch_desired[key]

            # Patch based twin update of tag props
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--tags '{patch_tags}'",  # Not f-string due to CLI TestFramework self.kwargs application :(
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            for key in patch_tags:
                assert d0_twin["tags"][key] == patch_tags[key]

            for key in patch_desired:
                assert d0_twin["properties"]["desired"][key] == patch_desired[key]

            assert d0_twin["properties"]["desired"]["$version"] == 2

            # Patch based twin update of tag and desired props
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--tags '{patch_tags}' --desired '{patch_desired}'",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            for key in patch_tags:
                assert d0_twin["tags"][key] == patch_tags[key]

            for key in patch_desired:
                assert d0_twin["properties"]["desired"][key] == patch_desired[key]

            assert d0_twin["properties"]["desired"]["$version"] == 3

            # Prepare removal of all twin tag properties
            for key in patch_tags:
                patch_tags[key] = None
            self.kwargs["patch_tags"] = json.dumps(patch_tags)

            # Remove all twin tag properties
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--tags '{patch_tags}'",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()
            assert d0_twin["tags"] is None

            # Prepare removal of single desired twin property
            target_key = list(patch_desired.keys())[0]
            patch_desired[target_key] = None
            self.kwargs["patch_desired"] = json.dumps(patch_desired)

            # Remove single desired property
            d0_twin = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--desired '{patch_desired}'",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            assert d0_twin["properties"]["desired"].get(target_key) is None
            assert d0_twin["properties"]["desired"]["$version"] == 4

            # Validation error --desired is not an object
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin update -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "--desired 'badinput'",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

    def test_iothub_module_twin_replace(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            device_count = 1
            device_ids = self.generate_device_names(device_count)
            module_count = 1
            module_ids = self.generate_device_names(module_count)

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            )

            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            )

            replace_twin_content_path = os.path.join(
                Path(CWD).parent, "test_generic_replace.json"
            )
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin replace -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} -j "
                    f"'{replace_twin_content_path}'",
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("moduleId", module_ids[0]),
                    self.check("deviceId", device_ids[0]),
                    self.check("properties.desired.awesome", 9001),
                    self.check("properties.desired.temperature.min", 10),
                    self.check("properties.desired.temperature.max", 100),
                    self.check("tags.location.region", "US"),
                ],
            )

            # Inline json
            replace_twin_content_path = os.path.join(
                Path(CWD).parent, "test_generic_replace.json"
            )
            self.kwargs["inline_replace_content"] = read_file_content(
                replace_twin_content_path
            )
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-twin replace -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                    "-j '{inline_replace_content}'",
                    auth_type=auth_phase,
                ),
                checks=[
                    self.check("moduleId", module_ids[0]),
                    self.check("deviceId", device_ids[0]),
                    self.check("properties.desired.awesome", 9001),
                    self.check("properties.desired.temperature.min", 10),
                    self.check("properties.desired.temperature.max", 100),
                    self.check("tags.location.region", "US"),
                ],
            )
