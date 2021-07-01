# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests import IoTLiveScenarioTest
from azext_iot.tests.settings import DynamoSettings, ENV_SET_TEST_IOTHUB_BASIC
from azext_iot.tests.generators import generate_generic_id
from azext_iot.tests.iothub import (
    DATAPLANE_AUTH_TYPES,
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)

settings = DynamoSettings(req_env_set=ENV_SET_TEST_IOTHUB_BASIC)

LIVE_HUB = settings.env.azext_iot_testhub
LIVE_RG = settings.env.azext_iot_testrg


class TestIoTHubDevices(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubDevices, self).__init__(test_case, LIVE_HUB, LIVE_RG)

    def test_iothub_device_identity(self):
        to_remove_device_ids = []
        for auth_phase in DATAPLANE_AUTH_TYPES:
            for device_type in DEVICE_TYPES:
                device_count = 4
                device_ids = self.generate_device_names(
                    device_count, edge=device_type == "edge"
                )
                edge_enabled = "--edge-enabled" if device_type == "edge" else ""

                # Symmetric key device checks
                d0_device_checks = [
                    self.check("deviceId", device_ids[0]),
                    self.check("status", "enabled"),
                    self.check("statusReason", None),
                    self.check("connectionState", "Disconnected"),
                    self.check("capabilities.iotEdge", device_type == "edge"),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                ]

                # Symmetric key device creation
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} {edge_enabled}",
                        auth_type=auth_phase,
                    ),
                    checks=d0_device_checks,
                )
                to_remove_device_ids.append(device_ids[0])

                # x509 thumbprint device checks
                d1_device_checks = [
                    self.check("deviceId", device_ids[1]),
                    self.check("status", "enabled"),
                    self.check("statusReason", None),
                    self.check("capabilities.iotEdge", device_type == "edge"),
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
                ]

                # Create x509 thumbprint device
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create --device-id {device_ids[1]} "
                        f"--hub-name {LIVE_HUB} --resource-group {LIVE_RG} --auth-method x509_thumbprint "
                        f"--primary-thumbprint {PRIMARY_THUMBPRINT} --secondary-thumbprint {SECONDARY_THUMBPRINT} "
                        f"{edge_enabled}",
                        auth_type=auth_phase,
                    ),
                    checks=d1_device_checks,
                )
                to_remove_device_ids.append(device_ids[1])

                # Create x509 thumbprint device using generated cert for primary thumbprint
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create --device-id {device_ids[2]} --hub-name {LIVE_HUB} "
                        f"--resource-group {LIVE_RG} --auth-method x509_thumbprint --valid-days 1 {edge_enabled}",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[2]),
                        self.check("status", "enabled"),
                        self.check("statusReason", None),
                        self.check("capabilities.iotEdge", device_type == "edge"),
                        self.check("connectionState", "Disconnected"),
                        self.check("authentication.symmetricKey.primaryKey", None),
                        self.check("authentication.symmetricKey.secondaryKey", None),
                        self.exists("authentication.x509Thumbprint.primaryThumbprint"),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint",
                            None,
                        ),
                    ],
                )
                to_remove_device_ids.append(device_ids[2])

                # Create x509 CA device, disabled status with reason, auth with connection string
                status_reason = "Test Status Reason"
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity create --device-id {device_ids[3]} --hub-name {LIVE_HUB} "
                        f"--resource-group {LIVE_RG} --auth-method x509_ca --status disabled "
                        f"--status-reason '{status_reason}' {edge_enabled}",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[3]),
                        self.check("status", "disabled"),
                        self.check("statusReason", status_reason),
                        self.check("capabilities.iotEdge", device_type == "edge"),
                        self.check("connectionState", "Disconnected"),
                        self.check("authentication.symmetricKey.primaryKey", None),
                        self.check("authentication.symmetricKey.secondaryKey", None),
                        self.check(
                            "authentication.x509Thumbprint.primaryThumbprint",
                            None,
                        ),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint",
                            None,
                        ),
                    ],
                )

                # Delete device identity
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity delete -d {device_ids[3]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=self.is_empty(),
                )

                # Validate deletion worked
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity show -d {device_ids[3]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    expect_failure=True,
                )

                # Show symmetric key device identity
                d0_show = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity show -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=d0_device_checks,
                ).get_output_in_json()

                # Reset device symmetric key using device-identity generic update
                d0_updated = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity update -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} "
                        '--set authentication.symmetricKey.primaryKey="" '
                        'authentication.symmetricKey.secondaryKey=""',
                        auth_type=auth_phase,
                    )
                ).get_output_in_json()
                assert (
                    d0_updated["authentication"]["symmetricKey"]["primaryKey"]
                    != d0_show["authentication"]["symmetricKey"]["primaryKey"]
                )
                assert (
                    d0_updated["authentication"]["symmetricKey"]["secondaryKey"]
                    != d0_show["authentication"]["symmetricKey"]["secondaryKey"]
                )

                # Update device identity with higher level update parms
                random_status_reason = generate_generic_id()
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity update -d {device_ids[1]} --ee false "
                        f"--ptp {SECONDARY_THUMBPRINT} --stp {PRIMARY_THUMBPRINT} "
                        f"--status-reason '{random_status_reason}' --status disabled "
                        f"-n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=[
                        self.check("deviceId", device_ids[1]),
                        self.check("status", "disabled"),
                        self.check("capabilities.iotEdge", False),
                        self.check("statusReason", random_status_reason),
                        self.check(
                            "authentication.x509Thumbprint.primaryThumbprint",
                            SECONDARY_THUMBPRINT,
                        ),
                        self.check(
                            "authentication.x509Thumbprint.secondaryThumbprint",
                            PRIMARY_THUMBPRINT,
                        ),
                    ],
                )

                query_checks = [self.check("length([*])", len(to_remove_device_ids))]
                for d in to_remove_device_ids:
                    query_checks.append(self.exists(f"[?deviceId=='{d}']"))

                # By default query has no return cap
                self.cmd(
                    self.set_cmd_auth_type(
                        f'iot hub query --hub-name {LIVE_HUB} -g {LIVE_RG} -q "select * from devices"',
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                )

                # -1 Top is equivalent to unlimited
                self.cmd(
                    self.set_cmd_auth_type(
                        f'iot hub query --top -1 --hub-name {LIVE_HUB} -g {LIVE_RG} -q "select * from devices"',
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                )

                # Explicit top to constrain records and use connection string
                self.cmd(
                    self.set_cmd_auth_type(
                        f'iot hub query --top 1 --hub-name {LIVE_HUB} -g {LIVE_RG} -q "select * from devices"',
                        auth_type=auth_phase,
                    ),
                    checks=[self.check("length([*])", 1)],
                )
                # List devices
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity list -n {LIVE_HUB} -g {LIVE_RG}",
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                )

                # List devices filtering for edge devices
                edge_filtered_list = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub device-identity list -n {LIVE_HUB} -g {LIVE_RG} --ee",
                        auth_type=auth_phase,
                    )
                ).get_output_in_json()
                assert all(
                    (d["capabilities"]["iotEdge"] is True for d in edge_filtered_list)
                )

    def test_iothub_device_renew_key(self):
        device_count = 2
        device_ids = self.generate_device_names(device_count)

        original_device = self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        ).get_output_in_json()

        self.cmd(
            f"iot hub device-identity create -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG} "
            f"--am x509_thumbprint --ptp {PRIMARY_THUMBPRINT} --stp {SECONDARY_THUMBPRINT}"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            renew_primary_key_device = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity renew-key -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} --kt primary",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()
            assert (
                renew_primary_key_device["authentication"]["symmetricKey"]["primaryKey"]
                != original_device["authentication"]["symmetricKey"]["primaryKey"]
            )
            assert (
                renew_primary_key_device["authentication"]["symmetricKey"][
                    "secondaryKey"
                ]
                == original_device["authentication"]["symmetricKey"]["secondaryKey"]
            )

        swap_keys_device = self.cmd(
            self.set_cmd_auth_type(
                f"iot hub device-identity renew-key -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG} --kt swap",
                auth_type=auth_phase,
            )
        ).get_output_in_json()
        assert (
            renew_primary_key_device["authentication"]["symmetricKey"]["primaryKey"]
            == swap_keys_device["authentication"]["symmetricKey"]["secondaryKey"]
        )
        assert (
            renew_primary_key_device["authentication"]["symmetricKey"]["secondaryKey"]
            == swap_keys_device["authentication"]["symmetricKey"]["primaryKey"]
        )

        self.cmd(
            self.set_cmd_auth_type(
                f"iot hub device-identity renew-key -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG} --kt secondary",
                auth_type=auth_phase,
            ),
            expect_failure=True,
        )

    def test_iothub_device_connection_string_show(self):
        device_count = 2
        device_ids = self.generate_device_names(device_count)

        symmetric_key_device = self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        ).get_output_in_json()

        self.cmd(
            f"iot hub device-identity create -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG} --am x509_ca"
        )

        sym_cstring_pattern = f"HostName={LIVE_HUB}.azure-devices.net;DeviceId={device_ids[0]};SharedAccessKey=#"
        cer_cstring_pattern = (
            f"HostName={LIVE_HUB}.azure-devices.net;DeviceId={device_ids[1]};x509=true"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            primary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity connection-string show -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            target_key = symmetric_key_device["authentication"]["symmetricKey"][
                "primaryKey"
            ]
            target_sym_cstring = sym_cstring_pattern.replace("#", target_key)

            assert target_sym_cstring == primary_key_cstring["connectionString"]

            secondary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity connection-string show -d {device_ids[0]} "
                    f"-n {LIVE_HUB} -g {LIVE_RG} --kt secondary",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            target_key = symmetric_key_device["authentication"]["symmetricKey"][
                "secondaryKey"
            ]
            target_sym_cstring = sym_cstring_pattern.replace("#", target_key)

            assert target_sym_cstring == secondary_key_cstring["connectionString"]

            x509_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub device-identity connection-string show -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            assert cer_cstring_pattern == x509_cstring["connectionString"]

    # TODO: Improve validation of tests via micro device client or other means.
    def test_iothub_device_generate_sas_token(self):
        device_count = 2
        device_ids = self.generate_device_names(device_count)

        # Create SAS-auth device
        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}"
        )

        # Create non SAS-auth device
        self.cmd(
            f"iot hub device-identity create -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG} --auth-method X509_ca"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -d {device_ids[0]} -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom duration
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -d {device_ids[0]} --du 1000 -n {LIVE_HUB} -g {LIVE_RG}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom key type
            self.cmd(
                self.set_cmd_auth_type(
                    f'iot hub generate-sas-token -d {device_ids[0]} --kt "secondary" -n {LIVE_HUB} -g {LIVE_RG}',
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Error - generate sas token against non SAS device
            self.cmd(
                f"iot hub generate-sas-token -d {device_ids[1]} -n {LIVE_HUB} -g {LIVE_RG}",
                expect_failure=True,
            )

        # Mixed case connection string
        cstring = self.connection_string
        mixed_case_cstring = cstring.replace("HostName", "hostname", 1)
        self.cmd(
            f"iot hub generate-sas-token -d {device_ids[0]} --login {mixed_case_cstring}",
            checks=[self.exists("sas")],
        )
