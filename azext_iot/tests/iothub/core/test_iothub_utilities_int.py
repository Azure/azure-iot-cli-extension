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
                    f"iot hub generate-sas-token -n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom duration
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -n {self.host_name} --du 1000",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            if auth_phase != "cstring":
                # Custom policy
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub generate-sas-token -n {self.host_name} -g {self.entity_rg} --pn service",
                        auth_type=auth_phase,
                    ),
                    checks=[self.exists("sas")],
                )

            # Error - non-existent custom policy
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token --pn somepolicy -n {self.host_name} -g {self.entity_rg}",
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

    def test_iothub_generate_sas_token_hostname_type(self):
        """Bug-bash #9: --hostname-type permutations for hub-level SAS.

        Verifies the `sr=` audience in the generated SAS token matches the requested hostname type.
        """
        from urllib.parse import unquote

        def extract_sr(sas_payload):
            sas = sas_payload["sas"].replace("SharedAccessSignature ", "")
            for part in sas.split("&"):
                if part.startswith("sr="):
                    return unquote(part[3:])
            raise AssertionError(f"sas token had no sr= component: {sas}")

        hub = self.cmd(
            f"iot hub show -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()
        props = hub["properties"]
        classic_hn = props["hostName"]
        device_hn = props.get("deviceHostName")
        service_hn = props.get("serviceHostName")
        is_gwv2 = bool(device_hn and service_hn)

        # auto: defaults to service hostname on GWv2, classic on V1
        token = self.cmd(
            f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg}",
            checks=[self.exists("sas")],
        ).get_output_in_json()
        expected_auto = service_hn if is_gwv2 else classic_hn
        assert extract_sr(token) == expected_auto, \
            f"auto: expected sr={expected_auto}, got {extract_sr(token)}"

        # classic
        token = self.cmd(
            f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --hostname-type classic",
            checks=[self.exists("sas")],
        ).get_output_in_json()
        assert extract_sr(token) == classic_hn

        if is_gwv2:
            # service (only valid on GWv2)
            token = self.cmd(
                f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --hostname-type service",
                checks=[self.exists("sas")],
            ).get_output_in_json()
            assert extract_sr(token) == service_hn

            # device (valid for hub-level SAS too — produces device-endpoint audience)
            token = self.cmd(
                f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --hostname-type device",
                checks=[self.exists("sas")],
            ).get_output_in_json()
            assert extract_sr(token) == device_hn
        else:
            # service / device must error on classic hubs
            self.cmd(
                f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --hostname-type service",
                expect_failure=True,
            )
            self.cmd(
                f"iot hub generate-sas-token -n {self.entity_name} -g {self.entity_rg} --hostname-type device",
                expect_failure=True,
            )

    def test_iothub_connection_string_show(self):
        conn_str_pattern = r"^HostName={0}(\.\w+)?\.azure-devices\.net;SharedAccessKeyName=iothubowner;SharedAccessKey=".format(
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
            self.cmd(
                self.set_cmd_auth_type(
                    f'iot hub query --hub-name {self.host_name} -q "select * from devices"',
                    auth_type=auth_phase,
                ),
                checks=[self.check("length([*])", 0)],
            )

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
