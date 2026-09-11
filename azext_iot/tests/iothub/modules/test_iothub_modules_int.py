# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azext_iot.tests.iothub import IoTLiveScenarioTest
from azext_iot.common.utility import generate_key
from azext_iot.tests.helpers import wait_for_assertion
from azext_iot.tests.iothub import (
    DATAPLANE_AUTH_TYPES,
    PRIMARY_THUMBPRINT,
    SECONDARY_THUMBPRINT,
    DEVICE_TYPES,
)


class TestIoTHubModules(IoTLiveScenarioTest):
    def __init__(self, test_case):
        super(TestIoTHubModules, self).__init__(test_case)

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
                        f"iot hub device-identity create "
                        f"-d {device_ids[0]} -n {self.host_name} -g {self.entity_rg} {edge_enabled}",
                        auth_type=auth_phase,
                    ),
                )

                m0_d0_checks = [
                    self.check("deviceId", device_ids[0]),
                    self.check("moduleId", module_ids[0]),
                    self.exists("authentication.symmetricKey.primaryKey"),
                    self.exists("authentication.symmetricKey.secondaryKey"),
                ]

                # Module identity creation with custom symmetric keys
                custom_primary_key = generate_key()
                custom_secondary_key = generate_key()
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create --module-id {module_ids[0]} --device-id {device_ids[0]} "
                        f"--hub-name {self.host_name} --resource-group {self.entity_rg} --primary-key {custom_primary_key} "
                        f"--secondary-key {custom_secondary_key}",
                        auth_type=auth_phase,
                    ),
                    checks=m0_d0_checks + [
                        self.check(
                            "authentication.symmetricKey.primaryKey",
                            custom_primary_key
                        ),
                        self.check(
                            "authentication.symmetricKey.secondaryKey",
                            custom_secondary_key,
                        ),
                    ],
                )

                # Delete module identity with custom symmetric keys.
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity delete -m {module_ids[0]} -d {device_ids[0]} "
                        f"-n {self.host_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=self.is_empty(),
                )

                # Create module identity with generated symmetric keys
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create --module-id {module_ids[0]} --device-id {device_ids[0]} "
                        f"--hub-name {self.host_name} --resource-group {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=m0_d0_checks,
                )

                # Create module identity with x509 thumbprint
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity create -m {module_ids[1]} -d {device_ids[0]} "
                        f"-n {self.host_name} -g {self.entity_rg} --auth-method x509_thumbprint "
                        f"--primary-thumbprint {PRIMARY_THUMBPRINT} --secondary-thumbprint {SECONDARY_THUMBPRINT}",
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
                        f"-n {self.host_name} -g {self.entity_rg} --am x509_thumbprint --valid-days 1",
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
                        f"-n {self.host_name} -g {self.entity_rg} --am x509_ca",
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
                        f"iot hub module-identity show "
                        f"-m {module_ids[0]} -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=m0_d0_checks,
                ).get_output_in_json()

                # Reset module symmetric key using module-identity generic update
                m0_d0_updated = self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity update -m {module_ids[0]} -d {device_ids[0]} "
                        f'-n {self.host_name} -g {self.entity_rg} --set authentication.symmetricKey.primaryKey="" '
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

                module_query_result = wait_for_assertion(
                    lambda: self.cmd(
                        self.set_cmd_auth_type(
                            f"iot hub query -n {self.host_name} -g {self.entity_rg} "
                            f"-q \"select * from devices.modules where devices.deviceId='{device_ids[0]}'\"",
                            auth_type=auth_phase,
                        ),
                        checks=query_checks,
                    )
                ).get_output_in_json()

                target_module_count = (
                    2 + module_count if device_type == "edge" else module_count
                )
                assert len(module_query_result) == target_module_count

                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity list -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=query_checks,
                )

                # Delete module identity.
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity delete "
                        f"-m {module_ids[2]} -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    checks=self.is_empty(),
                )

                # Validate deletion worked.
                self.cmd(
                    self.set_cmd_auth_type(
                        f"iot hub module-identity show "
                        f"-m {module_ids[2]} -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg}",
                        auth_type=auth_phase,
                    ),
                    expect_failure=True,
                )

    def test_iothub_module_renew_key(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)
        module_count = 2
        module_ids = self.generate_module_names(module_count)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        symmetric_key_module = self.cmd(
            f"iot hub module-identity create "
            f"-m {module_ids[0]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        self.cmd(
            f"iot hub module-identity create "
            f"-m {module_ids[1]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} --am x509_ca"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            swap_keys_module = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity renew-key "
                    f"-m {module_ids[0]} -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg} --kt swap",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()
            assert (
                symmetric_key_module["authentication"]["symmetricKey"]["primaryKey"]
                == swap_keys_module["authentication"]["symmetricKey"]["secondaryKey"]
            )
            assert (
                symmetric_key_module["authentication"]["symmetricKey"]["secondaryKey"]
                == swap_keys_module["authentication"]["symmetricKey"]["primaryKey"]
            )

            renew_module = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity renew-key -m {module_ids[0]} "
                    f"-d {device_ids[0]} -n {self.host_name} -g {self.entity_rg} --kt both",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()
            assert (
                renew_module["authentication"]["symmetricKey"]["primaryKey"]
                != swap_keys_module["authentication"]["symmetricKey"]["primaryKey"]
            )
            assert (
                renew_module["authentication"]["symmetricKey"]["secondaryKey"]
                != swap_keys_module["authentication"]["symmetricKey"]["secondaryKey"]
            )
            symmetric_key_module = renew_module

        # avoid having this affect swap results
        for auth_phase in DATAPLANE_AUTH_TYPES:
            renew_result = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity renew-key -m * "
                    f"-d {device_ids[0]} -n {self.host_name} -g {self.entity_rg} --kt secondary",
                    auth_type=auth_phase,
                ),
            ).get_output_in_json()
            assert renew_result.get("policyKey") == "secondaryKey"
            # only one sas module, one result
            device_result = renew_result["rotatedKeys"][0]
            assert device_result["id"] == device_ids[0]
            assert device_result["moduleId"] == module_ids[0]
            assert not device_result["primaryKey"]
            assert device_result["secondaryKey"]

    def test_iothub_module_connection_string_show(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)
        module_count = 2
        module_ids = self.generate_device_names(module_count)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        symmetric_key_module = self.cmd(
            f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        ).get_output_in_json()

        self.cmd(
            f"iot hub module-identity create "
            f"-m {module_ids[1]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} --am x509_ca"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            primary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[0]} -d {device_ids[0]} "
                    f"-n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            cs = primary_key_cstring["connectionString"]
            target_key = symmetric_key_module["authentication"]["symmetricKey"]["primaryKey"]
            assert f"DeviceId={device_ids[0]}" in cs
            assert f"ModuleId={module_ids[0]}" in cs
            assert f"SharedAccessKey={target_key}" in cs
            assert cs.startswith(f"HostName={self.entity_name}")

            secondary_key_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[0]} -d {device_ids[0]} "
                    f"-n {self.host_name} -g {self.entity_rg} --kt secondary",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            cs = secondary_key_cstring["connectionString"]
            target_key = symmetric_key_module["authentication"]["symmetricKey"]["secondaryKey"]
            assert f"DeviceId={device_ids[0]}" in cs
            assert f"ModuleId={module_ids[0]}" in cs
            assert f"SharedAccessKey={target_key}" in cs
            assert cs.startswith(f"HostName={self.entity_name}")

            x509_cstring = self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub module-identity connection-string show -m {module_ids[1]} -d {device_ids[0]} "
                    f"-n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                )
            ).get_output_in_json()

            cs = x509_cstring["connectionString"]
            assert f"DeviceId={device_ids[0]}" in cs
            assert f"ModuleId={module_ids[1]}" in cs
            assert "x509=true" in cs
            assert cs.startswith(f"HostName={self.entity_name}")

    def test_iothub_module_generate_sas_token(self):
        device_count = 1
        device_ids = self.generate_device_names(device_count)

        module_count = 2
        module_ids = self.generate_device_names(module_count)

        self.cmd(
            f"iot hub device-identity create -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        )

        self.cmd(
            f"iot hub module-identity create -m {module_ids[0]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}"
        )

        self.cmd(
            f"iot hub module-identity create -m {module_ids[1]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg} "
            "--auth-method x509_ca"
        )

        for auth_phase in DATAPLANE_AUTH_TYPES:
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} -n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom duration
            self.cmd(
                self.set_cmd_auth_type(
                    f"iot hub generate-sas-token "
                    f"-m {module_ids[0]} -d {device_ids[0]} --du 1000 -n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Custom key type
            self.cmd(
                self.set_cmd_auth_type(
                    f'iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} --kt "secondary" '
                    f"-n {self.host_name} -g {self.entity_rg}",
                    auth_type=auth_phase,
                ),
                checks=[self.exists("sas")],
            )

            # Error - generate sas token against non SAS module
            self.cmd(
                f"iot hub generate-sas-token -m {module_ids[1]} -d {device_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                expect_failure=True,
            )

            # Error - generate sas token against module with no device
            self.cmd(
                f"iot hub generate-sas-token -m {module_ids[0]} -n {self.entity_name} -g {self.entity_rg}",
                expect_failure=True,
            )

        # Mixed case connection string
        cstring = self.connection_string
        mixed_case_cstring = cstring.replace("HostName", "hostname", 1)
        self.cmd(
            f"iot hub generate-sas-token -m {module_ids[0]} -d {device_ids[0]} --login {mixed_case_cstring}",
            checks=[self.exists("sas")],
        )

    def test_iothub_module_hostname_type_permutations(self):
        """--hostname-type permutations for module-scope CS-show and SAS.

        - `--hostname-type service` is rejected on CS-show
        - `--hostname-type service` is accepted on SAS (caller opts in; audience targets service endpoint).
        - On GWv2 hubs, auto (default) resolves to the device endpoint for both CS-show and SAS.
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
        is_gwv2 = bool(device_hn)

        device_id = self.generate_device_names(1)[0]
        module_id = self.generate_device_names(1)[0]
        self.cmd(
            f"iot hub device-identity create -d {device_id} -n {self.entity_name} -g {self.entity_rg}"
        )
        self.cmd(
            f"iot hub module-identity create -m {module_id} -d {device_id} -n {self.entity_name} -g {self.entity_rg}"
        )

        # module-identity connection-string show

        self.cmd(
            f"iot hub module-identity connection-string show -m {module_id} -d {device_id} "
            f"-n {self.host_name} -g {self.entity_rg} --hostname-type service",
            expect_failure=True,
        )

        # classic
        cs_classic = self.cmd(
            f"iot hub module-identity connection-string show -m {module_id} -d {device_id} "
            f"-n {self.host_name} -g {self.entity_rg} --hostname-type classic",
        ).get_output_in_json()["connectionString"]
        assert f"HostName={classic_hn}" in cs_classic

        if is_gwv2:
            cs_device = self.cmd(
                f"iot hub module-identity connection-string show -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg} --hostname-type device",
            ).get_output_in_json()["connectionString"]
            assert f"HostName={device_hn}" in cs_device

            cs_auto = self.cmd(
                f"iot hub module-identity connection-string show -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg}",
            ).get_output_in_json()["connectionString"]
            assert f"HostName={device_hn}" in cs_auto

        # generate-sas-token (module scope)
        token = self.cmd(
            f"iot hub generate-sas-token -m {module_id} -d {device_id} "
            f"-n {self.host_name} -g {self.entity_rg} --hostname-type classic",
            checks=[self.exists("sas")],
        ).get_output_in_json()
        assert extract_sr(token) == f"{classic_hn}/devices/{device_id}/modules/{module_id}"

        if is_gwv2:
            token = self.cmd(
                f"iot hub generate-sas-token -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg} --hostname-type device",
                checks=[self.exists("sas")],
            ).get_output_in_json()
            assert extract_sr(token) == f"{device_hn}/devices/{device_id}/modules/{module_id}"

            # service is selectable for module scope
            token = self.cmd(
                f"iot hub generate-sas-token -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg} --hostname-type service",
                checks=[self.exists("sas")],
            ).get_output_in_json()
            assert extract_sr(token) == f"{service_hn}/devices/{device_id}/modules/{module_id}"

            token = self.cmd(
                f"iot hub generate-sas-token -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg}",
                checks=[self.exists("sas")],
            ).get_output_in_json()
            assert extract_sr(token) == f"{device_hn}/devices/{device_id}/modules/{module_id}"
        else:
            self.cmd(
                f"iot hub generate-sas-token -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg} --hostname-type device",
                expect_failure=True,
            )
            self.cmd(
                f"iot hub generate-sas-token -m {module_id} -d {device_id} "
                f"-n {self.host_name} -g {self.entity_rg} --hostname-type service",
                expect_failure=True,
            )
