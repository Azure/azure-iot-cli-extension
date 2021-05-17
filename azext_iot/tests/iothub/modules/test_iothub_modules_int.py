# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.tests.iothub import (
    DATAPLANE_AUTH_TYPES,
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_BASIC)

LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg


class TestIoTHubModules(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubModules, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    def test_iothub_module_identity(self):
        for auth_phase in DATAPLANE_AUTH_TYPES:
            for device_type in DEVICE_TYPES:
                device_count = 1
                module_count = 4
                device_ids = self.generate_device_names(
                    device_count, edge=device_type == "edge"
                )
                module_ids = self.generate_module_names(module_count)
                edge_enabled = "--edge-enabled" if device_type == "edge" else ""

                # Symmetric key device creation
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} {edge_enabled}",
                        auth_type=auth_phase,
                    ),
                )

                m0_d0_checks = [
                    self.check("deviceId", device_ids[0]),
                    self.check("moduleId", module_ids[0]),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                ]

                # Create module identity with symmetric keys
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create --module-id {module_ids[0]} --device-id {device_ids[0]} "
                        f"--hub-name {LIVE_HUB} --resource-group {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=m0_d0_checks,
                )

                # Create module identity with x509 thumbprint
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create -m {module_ids[1]} -d {device_ids[0]} "
                        f"-n {LIVE_HUB} -g {LIVE_RG} --auth-method x509_thumbprint --primary-thumbprint {PRIMARY_THUMBPRINT} "
                        f"--secondary-thumbprint {SECONDARY_THUMBPRINT}",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[0]),
                        self.check("moduleId", module_ids[1]),
                        self.check("connectionState", "Disconnected"),
                        self.check("authentication.symmetricKey.primaryKey", None),
                        self.check("authentication.symmetricKey.secondaryKey", None),
                        self.check(
                            "authentication.x509Thumbprint.primaryThumbprint",
                            PRIMARY_THUMBPRINT,
                        ),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint",
                            SECONDARY_THUMBPRINT,
                        ),
                    ],
                )

                # Create module identity with generated x509 thumbprint
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create -m {module_ids[2]} -d {device_ids[0]} "
                        f"-n {LIVE_HUB} -g {LIVE_RG} --am x509_thumbprint --valid-days 1",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[0]),
                        self.check("moduleId", module_ids[2]),
                        self.check("connectionState", "Disconnected"),
                        self.check("authentication.symmetricKey.primaryKey", None),
                        self.check("authentication.symmetricKey.secondaryKey", None),
                        self.exists("authentication.x509Thumbprint.primaryThumbprint"),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint", None
                        ),
                    ],
                )

                # Create module identity with x509 ca
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create -m {module_ids[3]} -d {device_ids[0]} "
                        f"-n {LIVE_HUB} -g {LIVE_RG} --am x509_ca",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[0]),
                        self.check("moduleId", module_ids[3]),
                        self.check("connectionState", "Disconnected"),
                        self.check("authentication.symmetricKey.primaryKey", None),
                        self.check("authentication.symmetricKey.secondaryKey", None),
                        self.check(
                            "authentication.x509Thumbprint.primaryThumbprint", None
                        ),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint", None
                        ),
                    ],
                )

                # Show symmetric key module identity
                m0_d0_show = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity show -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=m0_d0_checks,
                ).get_output_in_json()

                # Reset module symmetric key using module-identity generic update
                m0_d0_updated = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity update -m {module_ids[0]} -d {device_ids[0]} "
                        f'-n {LIVE_HUB} -g {LIVE_RG} --set authentication.symmetricKey.primaryKey="" '
                        'authentication.symmetricKey.secondaryKey=""',
                        auth_type=auth_phase,
                    )
                ).get_output_in_json()
                assert (
                    m0_d0_updated["authentication"]["symmetricKey"]["primaryKey"]
                    != m0_d0_show["authentication"]["symmetricKey"]["primaryKey"]
                )
                assert (
                    m0_d0_updated["authentication"]["symmetricKey"]["secondaryKey"]
                    != m0_d0_show["authentication"]["symmetricKey"]["secondaryKey"]
                )

                query_checks = []
                for m in module_ids:
                    query_checks.append(self.exists(f"[?moduleId=='{m}']"))
                if device_type == "edge":
                    query_checks.append(self.exists("[?moduleId=='$edgeAgent']"))
                    query_checks.append(self.exists("[?moduleId=='$edgeHub']"))

                # Query device modules. Edge devices include the $edgeAgent and $edgeHub system modules.
                module_query_result = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub query -n {LIVE_HUB} -g {LIVE_RG} "
                        f"-q \"select * from devices.modules where devices.deviceId='{device_ids[0]}'\"",
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                ).get_output_in_json()

                target_module_count = (
                    2 + module_count if device_type == "edge" else module_count
                )
                assert len(module_query_result) == target_module_count

                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity list -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                )

                # Delete module identity.
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity delete -m {module_ids[2]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=self.is_empty(),
                )

                # Validate deletion worked.
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity show -m {module_ids[2]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    expect_failure=True,
                )

    def test_iothub_module_connection_string_show(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)
        module_count = 2
        module_ids = self.generate_device_names(module_count)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        ).get_output_in_json()

        symmetric_key_module = self.cmd(
            f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        ).get_output_in_json()

        self.cmd(
            f"iot hub module-identity create -m {module_ids[1]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} --am x509_ca"
        )

        sym_cstring_pattern = (
            f"HostName={LIVE_HUB}.azure-devices.net;DeviceId={device_ids[0]};"
            f"ModuleId={module_ids[0]};SharedAccessKey=#"
        )
        cer_cstring_pattern = f"HostName={LIVE_HUB}.azure-devices.net;DeviceId={device_ids[0]};ModuleId={module_ids[1]};x509=true"

        for auth_phase in DATAPLANE_AUTH_TYPES:
            primary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[0]} -d {device_ids[0]} "
                    f"-n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            target_key = symmetric_key_module["authentication"]["symmetricKey"][
                "primaryKey"
            ]
            target_sym_cstring = sym_cstring_pattern.replace("#", target_key)

            assert target_sym_cstring == primary_key_cstring["connectionString"]

            secondary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[0]} -d {device_ids[0]} "
                    f"-n {LIVE_HUB} -g {LIVE_RG} --kt secondary",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            target_key = symmetric_key_module["authentication"]["symmetricKey"][
                "secondaryKey"
            ]
            target_sym_cstring = sym_cstring_pattern.replace("#", target_key)

            assert target_sym_cstring == secondary_key_cstring["connectionString"]

            x509_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[1]} -d {device_ids[0]} "
                    f"-n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            assert cer_cstring_pattern == x509_cstring["connectionString"]

    def test_iothub_module_generate_sas_token(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        module_count = 2
        module_ids = self.generate_device_names(module_count)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        )

        self.cmd(
            f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        )

        self.cmd(
            f"iot hub module-identity create -m {module_ids[1]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
            "--auth-method x509_ca"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom duration
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} --du 1000 -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom key type
            self.cmd(
                self.set_cmd_auth_type(
                    f'iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} --kt "secondary" '
                    f"-n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Error - generate sas token against non SAS module
            self.cmd(
                f"iot hub generate-sas-token -m {module_ids[1]} -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                expect_failure=True,
            )

            # Error - generate sas token against module with no device
            self.cmd(
                f"iot hub generate-sas-token -m {module_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                expect_failure=True,
            )

        # Mixed case connection string
        cstring = self.connection_string
        mixed_case_cstring = cstring.replace("HostName", "hostname", 1)
        self.cmd(
            f"iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} --login {mixed_case_cstring}",
            checks=[self.exists("sas")],
        )
