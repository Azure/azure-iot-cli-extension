# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Registry Device lifecycle and backend-materialized child integration coverage."""

import json
import os

import pytest

from azext_iot.tests import CaptureOutputLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    wait_for_materialized_resources,
    wait_for_resource_succeeded,
)
from azext_iot.tests.adr._log import LogKind, _log
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id


def _registry_device_name() -> str:
    return f"registry{generate_generic_id()[:8]}"


RUN_CERTIFICATE_REVOCATION = (
    os.getenv("azext_iot_adr_revoke_certificates", "").lower()
    in {"1", "true", "yes"}
)
CA_AUTH_PROFILE_NAME = os.getenv("azext_iot_adr_ca_auth_profile_name")


def _create_registry_device(
    test,
    namespace_name: str,
    device_name: str,
    *,
    no_wait: bool,
) -> dict:
    external_device_id = f"external-{device_name}"
    test.cmd(
        f"iot adr ns create -n {namespace_name} -g {TEST_RG} "
        f"--location {TEST_LOCATION}"
    )
    create_command = (
        f"iot adr ns registry-device create -n {device_name} "
        f"--ns {namespace_name} -g {TEST_RG} "
        f"--enablement-state Enabled --external-device-id {external_device_id} "
        "--manufacturer Contoso --model Ignite --tags env=integration"
    )
    show_command = (
        f"iot adr ns registry-device show -n {device_name} "
        f"--ns {namespace_name} -g {TEST_RG}"
    )
    if no_wait:
        test.cmd(f"{create_command} --no-wait")
        test.cmd(
            "iot adr ns registry-device wait "
            f"--external-device-id {external_device_id} "
            f"--ns {namespace_name} -g {TEST_RG}"
        )
        return wait_for_resource_succeeded(test, show_command)
    return test.cmd(create_command).get_output_in_json()


def _cleanup_namespace(test, namespace_name: str) -> None:
    try:
        test.cmd(
            f"iot adr ns delete -n {namespace_name} -g {TEST_RG} --yes"
        )
    except Exception as error:  # noqa: BLE001 - cleanup is best-effort
        _log(LogKind.WARN, "Cleanup failed: %s", error)


@pytest.mark.usefixtures("set_cwd")
class TestADRRegistryDeviceLifecycle(CaptureOutputLiveScenarioTest):
    def test_registry_device_lifecycle(self):
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()

        try:
            created = _create_registry_device(
                self, namespace_name, device_name, no_wait=True
            )
            show_command = (
                f"iot adr ns registry-device show -n {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            )
            assert created["name"] == device_name
            assert created["properties"]["enablementState"] == "Enabled"
            external_device_id = f"external-{device_name}"
            assert created["properties"]["externalDeviceId"] == external_device_id

            shown = self.cmd(show_command).get_output_in_json()
            assert shown["name"] == device_name
            shown_by_external_id = self.cmd(
                "iot adr ns registry-device show "
                f"--external-device-id {external_device_id} "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert shown_by_external_id["name"] == device_name
            self.cmd(
                "iot adr ns registry-device show "
                f"-n {device_name} --external-device-id {external_device_id} "
                f"--ns {namespace_name} -g {TEST_RG}",
                expect_failure=True,
            )
            self.cmd(
                "iot adr ns registry-device show "
                "--external-device-id does-not-exist "
                f"--ns {namespace_name} -g {TEST_RG}",
                expect_failure=True,
            )

            listed = self.cmd(
                f"iot adr ns registry-device list --ns {namespace_name} "
                f"-g {TEST_RG}"
            ).get_output_in_json()
            assert device_name in [device["name"] for device in listed]

            updated = self.cmd(
                f"iot adr ns registry-device update -n {device_name} "
                f"--ns {namespace_name} -g {TEST_RG} "
                "--enablement-state Enabled --software-revision 2.0 "
                "--tags env=updated"
            ).get_output_in_json()
            assert updated["properties"]["enablementState"] == "Enabled"
            assert updated["properties"]["softwareRevision"] == "2.0"
            assert updated["tags"]["env"] == "updated"

            self.cmd(
                f"iot adr ns registry-device update -n {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}",
                expect_failure=True,
            )

            disabled = self.cmd(
                f"iot adr ns registry-device update -n {device_name} "
                f"--ns {namespace_name} -g {TEST_RG} "
                "--enablement-state Disabled"
            ).get_output_in_json()
            assert disabled["properties"]["enablementState"] == "Disabled"

            self.cmd(
                "iot adr ns registry-device auth list "
                f"--registry-device-name missing-device --ns {namespace_name} "
                f"-g {TEST_RG}",
                expect_failure=True,
            )

            self.cmd(
                f"iot adr ns registry-device delete -n {device_name} "
                f"--ns {namespace_name} -g {TEST_RG} --yes"
            )
            self.cmd(show_command, expect_failure=True)
        finally:
            _cleanup_namespace(self, namespace_name)

    def test_registry_device_authentication_profiles(self):
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()

        try:
            _create_registry_device(
                self, namespace_name, device_name, no_wait=False
            )

            profile_list_command = (
                "iot adr ns registry-device auth list "
                f"--registry-device-name {device_name} --ns {namespace_name} "
                f"-g {TEST_RG}"
            )
            try:
                profiles = wait_for_materialized_resources(
                    self,
                    profile_list_command,
                    description=(
                        f"authentication profiles for Registry Device "
                        f"'{device_name}'"
                    ),
                    timeout=60,
                )
            except AssertionError as error:
                pytest.skip(
                    "Backend did not materialize Registry Device "
                    f"Authentication Profiles within 60 seconds: {error}"
                )

            auth_profiles = {}
            configured_profile = os.getenv("azext_iot_adr_auth_profile_name")
            profile_names = [item["name"] for item in profiles]
            if configured_profile and configured_profile not in profile_names:
                profile_names.append(configured_profile)
            for profile_name in profile_names:
                self.cmd(
                    "iot adr ns registry-device auth wait "
                    f"-n {profile_name} --registry-device-name {device_name} "
                    f"--ns {namespace_name} -g {TEST_RG}"
                )
                profile = self.cmd(
                    "iot adr ns registry-device auth show "
                    f"-n {profile_name} --registry-device-name {device_name} "
                    f"--ns {namespace_name} -g {TEST_RG}"
                ).get_output_in_json()
                serialized_profile = json.dumps(profile).casefold()
                for secret_field in (
                    '"primarykey"',
                    '"secondarykey"',
                    '"privatekey"',
                ):
                    assert secret_field not in serialized_profile
                auth_profiles[profile_name] = (
                    (profile.get("properties") or {}).get("authenticationType")
                )

            symmetric_profile = next(
                (
                    name
                    for name, auth_type in auth_profiles.items()
                    if auth_type == "SymmetricKey"
                ),
                None,
            )
            if symmetric_profile:
                key_lengths = self.cmd(
                    "iot adr ns registry-device auth show-keys "
                    f"-n {symmetric_profile} "
                    f"--registry-device-name {device_name} "
                    f"--ns {namespace_name} -g {TEST_RG} "
                    '--query "{primary:length(symmetricKey.primaryKey),'
                    'secondary:length(symmetricKey.secondaryKey)}"'
                ).get_output_in_json()
                assert key_lengths["primary"] > 0
                assert key_lengths["secondary"] > 0
            else:
                self.cmd(
                    "iot adr ns registry-device auth show-keys "
                    f"-n {next(iter(auth_profiles))} "
                    f"--registry-device-name {device_name} "
                    f"--ns {namespace_name} -g {TEST_RG}",
                    expect_failure=True,
                )

            ineligible_profile = next(
                (
                    name
                    for name, auth_type in auth_profiles.items()
                    if auth_type != "CertificateAuthoritySignedX509Certificate"
                ),
                None,
            )
            if ineligible_profile:
                self.cmd(
                    "iot adr ns registry-device auth revoke-certs "
                    f"-n {ineligible_profile} "
                    f"--registry-device-name {device_name} "
                    f"--ns {namespace_name} -g {TEST_RG} --yes",
                    expect_failure=True,
                )

        finally:
            _cleanup_namespace(self, namespace_name)

    @pytest.mark.skipif(
        not RUN_CERTIFICATE_REVOCATION or not CA_AUTH_PROFILE_NAME,
        reason=(
            "Set azext_iot_adr_revoke_certificates=true and "
            "azext_iot_adr_ca_auth_profile_name to run destructive "
            "certificate revocation coverage."
        ),
    )
    def test_registry_device_certificate_revocation(self):
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()

        try:
            _create_registry_device(
                self, namespace_name, device_name, no_wait=False
            )
            profile = self.cmd(
                "iot adr ns registry-device auth show "
                f"-n {CA_AUTH_PROFILE_NAME} "
                f"--registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert profile["properties"]["authenticationType"] == (
                "CertificateAuthoritySignedX509Certificate"
            )
            self.cmd(
                "iot adr ns registry-device auth revoke-certs "
                f"-n {CA_AUTH_PROFILE_NAME} "
                f"--registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG} --yes"
            )
        finally:
            _cleanup_namespace(self, namespace_name)

    def _assert_read_only_child(
        self,
        list_command: str,
        show_command: str,
        fixture_environment: str,
    ) -> None:
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()

        try:
            _create_registry_device(
                self, namespace_name, device_name, no_wait=False
            )
            child_list_command = (
                f"{list_command} --registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            )
            try:
                resources = wait_for_materialized_resources(
                    self,
                    child_list_command,
                    description=f"resources for '{list_command}'",
                    timeout=60,
                )
            except AssertionError as error:
                pytest.skip(
                    f"Backend did not materialize resources for "
                    f"'{list_command}' within 60 seconds: {error}"
                )

            resource_name = os.getenv(fixture_environment) or resources[0]["name"]
            resource = self.cmd(
                f"{show_command} -n {resource_name} "
                f"--registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert resource["name"] == resource_name
        finally:
            _cleanup_namespace(self, namespace_name)

    def test_registry_device_attributes(self):
        self._assert_read_only_child(
            "iot adr ns registry-device attribute list",
            "iot adr ns registry-device attribute show",
            "azext_iot_adr_attribute_name",
        )

    def test_registry_device_user_attribute_lifecycle(self):
        """User-authored attributes are writable in 2026-11-02-preview."""
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()
        attribute_name = f"site{generate_generic_id()[:8]}"

        try:
            _create_registry_device(self, namespace_name, device_name, no_wait=False)

            scope = (
                f"--registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            )
            created = self.cmd(
                f"iot adr ns registry-device attribute create -n {attribute_name} {scope} "
                f"--schema https://contoso.com/schemas/site.json "
                f'--properties \'{{"site": "plant-3", "rack": 12}}\''
            ).get_output_in_json()
            assert created["name"] == attribute_name
            properties = created["properties"]
            assert properties["reportedBy"] == "User"
            assert properties["schema"] == "https://contoso.com/schemas/site.json"
            assert properties["site"] == "plant-3"

            shown = self.cmd(
                f"iot adr ns registry-device attribute show -n {attribute_name} {scope}"
            ).get_output_in_json()
            assert shown["name"] == attribute_name

            listed = self.cmd(
                f"iot adr ns registry-device attribute list {scope}"
            ).get_output_in_json()
            assert attribute_name in [item["name"] for item in listed]

            # create is a full replace: omitted properties are dropped.
            replaced = self.cmd(
                f"iot adr ns registry-device attribute create -n {attribute_name} {scope} "
                f'--properties \'{{"site": "plant-4"}}\''
            ).get_output_in_json()
            assert replaced["properties"]["site"] == "plant-4"
            assert "rack" not in replaced["properties"]

            self.cmd(
                f"iot adr ns registry-device attribute delete -n {attribute_name} {scope} -y"
            )
            self.cmd(
                f"iot adr ns registry-device attribute show -n {attribute_name} {scope}",
                expect_failure=True,
            )
        finally:
            _cleanup_namespace(self, namespace_name)

    def test_registry_device_software_update_alias(self):
        """`show -n software-update` resolves to the ADU-materialized 'update'."""
        namespace_name = generate_adr_namespace_name()
        device_name = _registry_device_name()

        try:
            _create_registry_device(self, namespace_name, device_name, no_wait=False)
            scope = (
                f"--registry-device-name {device_name} "
                f"--ns {namespace_name} -g {TEST_RG}"
            )
            list_command = f"iot adr ns registry-device attribute list {scope}"
            try:
                attributes = wait_for_materialized_resources(
                    self,
                    list_command,
                    description="registry device attributes",
                    timeout=60,
                )
            except AssertionError as error:
                pytest.skip(
                    f"Backend did not materialize attributes within 60 seconds: {error}"
                )

            names = [item["name"] for item in attributes]
            if "update" not in names:
                pytest.skip(
                    f"No ADU-reported 'update' attribute materialized; got {names}."
                )

            aliased = self.cmd(
                f"iot adr ns registry-device attribute show -n software-update {scope}"
            ).get_output_in_json()
            # The alias is input-only: the resource still reports its real name.
            assert aliased["name"] == "update"
            assert aliased["id"].endswith("/attributes/update")

            canonical = self.cmd(
                f"iot adr ns registry-device attribute show -n update {scope}"
            ).get_output_in_json()
            assert canonical["id"] == aliased["id"]

            # The alias is scoped to `show`; delete must not resolve it.
            self.cmd(
                f"iot adr ns registry-device attribute delete -n software-update "
                f"{scope} -y",
                expect_failure=True,
            )
        finally:
            _cleanup_namespace(self, namespace_name)

    def test_registry_device_attribute_negatives(self):
        namespace_name = generate_adr_namespace_name()

        # Client-side guard: fires before any service call.
        self.cmd(
            f"iot adr ns registry-device attribute create -n bad "
            f"--registry-device-name nonexistent --ns {namespace_name} -g {TEST_RG} "
            f"--reported-by Microsoft.DeviceUpdate",
            expect_failure=True,
        )
        self.cmd(
            f"iot adr ns registry-device attribute create -n bad "
            f"--registry-device-name nonexistent --ns {namespace_name} -g {TEST_RG} "
            f"--properties '{{\"reportedBy\":\"Microsoft.DeviceUpdate\"}}'",
            expect_failure=True,
        )
        self.cmd(
            f"iot adr ns registry-device attribute create -n bad "
            f"--registry-device-name nonexistent --ns {namespace_name} -g {TEST_RG} "
            f"--properties '[1, 2, 3]'",
            expect_failure=True,
        )

    def test_registry_device_capabilities(self):
        self._assert_read_only_child(
            "iot adr ns registry-device capability list",
            "iot adr ns registry-device capability show",
            "azext_iot_adr_capability_name",
        )
