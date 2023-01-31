# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.tests.iothub import DATAPLANE_AUTH_TYPES


class TestIoTHubUtilities(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubUtilities, self).__init__(test_case)

    def test_iothub_generate_sas_token(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom duration
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -n {self.entity_name} --du 1000",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            if auth_phase != "cstring":
                # Custom policy
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --pn service",
                        auth_type=auth_phase,
                    ),
                    checks=[self.exists("sas")],
                )

            # Error - non-existent custom policy
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token --pn somepolicy -n {self.entity_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                expect_failure=True,
            )

        # Error - Unable to change key type when using cstring
        self.cmd(
            f"iot hub generate-sas-token --login {self.connection_string} --kt secondary",
            expect_failure=True,
        )

        # Offline SAS token generation
        self.cmd(
            f"iot hub generate-sas-token --connection-string {self.connection_string}",
            checks=[self.exists("sas")],
        )

        self.cmd(
            f"iot hub generate-sas-token --connection-string {self.connection_string} --du 1000",
            checks=[self.exists("sas")],
        )

    def test_iothub_connection_string_show(self):
        conn_str_pattern = r"^HostName={0}.azure-devices.net;SharedAccessKeyName=iothubowner;SharedAccessKey=".format(
            self.entity_name
        )
        conn_str_eventhub_pattern = (
            r"^Endpoint=sb://(.+?)servicebus.windows.net/;SharedAccessKeyName="
            r"iothubowner;SharedAccessKey=(.+?);EntityPath="
        )

        default_policy = "iothubowner"
        nonexistent_policy = "badpolicy"

        hubs_in_sub = self.cmd("iot hub connection-string show").get_output_in_json()

        hubs_in_rg = self.cmd(f"iot hub connection-string show -g {self.entity_rg}").get_output_in_json()
        assert len(hubs_in_sub) >= len(hubs_in_rg)

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name}",
            checks=[self.check_pattern("connectionString", conn_str_pattern)],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} --pn {default_policy}",
            checks=[self.check_pattern("connectionString", conn_str_pattern)],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} -g {self.entity_rg} --pn {nonexistent_policy}",
            expect_failure=True,
        )

        self.cmd(
            f"iot hub connection-string show --pn {nonexistent_policy}",
            checks=[self.check("length(@)", 0)],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} --eh",
            checks=[self.check_pattern("connectionString", conn_str_eventhub_pattern)],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} -g {self.entity_rg}",
            checks=[
                self.check("length(@)", 1),
                self.check_pattern("connectionString", conn_str_pattern),
            ],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} -g {self.entity_rg} --all",
            checks=[
                self.greater_than("length(connectionString[*])", 0),
                self.check_pattern("connectionString[0]", conn_str_pattern),
            ],
        )

        self.cmd(
            f"iot hub connection-string show -n {self.entity_name} -g {self.entity_rg} --all --eh",
            checks=[
                self.greater_than("length(connectionString[*])", 0),
                self.check_pattern(
                    "connectionString[0]", conn_str_eventhub_pattern
                ),
            ],
        )

    def test_iothub_init(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            devices = self.cmd(
                self.set_cmd_auth_type(
                    f'iot hub query --hub-name {self.entity_name} -q "select * from devices"',
                    auth_type=auth_phase,
                )
            ).get_output_in_json()
            assert len(devices) >= 0

        # Test mode 2 handler
        self.cmd(
            'iot hub query -q "select * from devices"',
            expect_failure=True,
        )

        # Error - invalid cstring
        self.cmd(
            'iot hub query -q "select * from devices" -l "Hostname=badlogin;key=1235"',
            expect_failure=True,
        )
