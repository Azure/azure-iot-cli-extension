# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from knack.util import CLIError

from . import DTLiveScenarioTest, generate_resource_id


class TestDTWait(DTLiveScenarioTest):
    def test_dt_wait_timeout(self):
        self.wait_for_capacity()
        name = generate_resource_id()
        instance = self.cmd(f"dt create -n {name} -g {self.rg} -l {self.region}").get_output_in_json()
        self.track_instance(instance)
        command = f"dt wait -n {name} -g {self.rg} --timeout 1 --interval 1"

        for condition in ("--deleted", "--custom 'name == `\"never-matches\"`'"):
            with pytest.raises(CLIError, match="Wait operation timed-out after 1 seconds"):
                self.cmd(f"{command} {condition}")

        self.cmd(f"{command} --exists")
        self.cmd(f"{command} --created")
