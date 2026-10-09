# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Owned ADR Schema Registry, Schema, and Schema Version lifecycle."""

import json
import shlex

import pytest

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    CleanupLedger,
    is_retryable_resource_error,
    resource_is_absent,
    wait_for_condition,
    wait_for_resource_absent,
)
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    TEST_SUBSCRIPTION,
)
from azext_iot.tests.generators import generate_generic_id


def _storage_rbac_pending(error):
    related = (
        error,
        getattr(error, "exception", None),
        getattr(error, "__cause__", None),
        getattr(error, "__context__", None),
    )
    message = " ".join(str(item) for item in related if item).casefold()
    return "storagerbacpermissionmissing" in message


def _schema_version_pending(error):
    return _storage_rbac_pending(error) or is_retryable_resource_error(error)


def _create_schema_version_with_retry(
    test,
    command,
    expected_name,
    description,
):
    version = wait_for_condition(
        lambda: test.cmd(command).get_output_in_json(),
        lambda _: True,
        description=description,
        timeout=600,
        interval=30,
        is_retryable_error=_storage_rbac_pending,
    )
    assert version["name"] == expected_name
    return version


def _quote_scenario_argument(value):
    return shlex.quote(value).replace("{", "{{").replace("}", "}}")


def _cleanup_owned(
    test,
    show_command,
    delete_command,
    *,
    is_retryable_show_error=None,
):
    if is_retryable_show_error:
        absent = wait_for_condition(
            lambda: resource_is_absent(test, show_command),
            lambda _absent: True,
            description=f"cleanup readiness: {show_command}",
            timeout=600,
            interval=15,
            is_retryable_error=is_retryable_show_error,
        )
    else:
        absent = resource_is_absent(test, show_command)
    if absent:
        return
    test.cmd(delete_command)
    if is_retryable_show_error:
        wait_for_condition(
            lambda: resource_is_absent(test, show_command),
            lambda is_absent: is_absent,
            description=f"resource absence: {show_command}",
            timeout=600,
            interval=15,
            is_retryable_error=is_retryable_show_error,
        )
    else:
        wait_for_resource_absent(test, show_command)


def _cleanup_schema_version(test, show_command, delete_command):
    _cleanup_owned(
        test,
        show_command,
        delete_command,
        is_retryable_show_error=_schema_version_pending,
    )


class _SchemaScenario(ADRLiveScenarioTest):
    def cmd(self, command, checks=None, expect_failure=False):
        return super().cmd(
            f"{command} --subscription {shlex.quote(TEST_SUBSCRIPTION)}",
            checks=checks,
            expect_failure=expect_failure,
        )


@pytest.mark.usefixtures("set_cwd")
class TestADRSchemaLifecycle(_SchemaScenario):
    @pytest.mark.timeout(2400, func_only=False)
    def test_schema_registry_and_versions_lifecycle(self):
        suffix = generate_generic_id().lower()[:10]
        storage_name = f"adrschema{suffix}"
        registry_name = f"registry{suffix}"
        registry_namespace = f"models{suffix}"
        thing_schema = f"smartlamp{suffix}"
        message_schema = f"lamppower{suffix}"

        thing_v1_content = json.dumps(
            {
                "@context": "https://www.w3.org/2022/wot/td/v1.1",
                "@type": "tm:ThingModel",
                "title": "SmartLamp",
                "properties": {"on": {"type": "boolean"}},
            }
        )
        thing_v2_content = json.dumps(
            {
                "@context": "https://www.w3.org/2022/wot/td/v1.1",
                "@type": "tm:ThingModel",
                "title": "SmartLamp",
                "properties": {
                    "on": {"type": "boolean"},
                    "brightness": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                }
            }
        )
        message_content = json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"power": {"type": "number"}},
                "required": ["power"],
            }
        )

        storage_show = f"storage account show -n {storage_name} -g {TEST_RG}"
        storage_delete = f"storage account delete -n {storage_name} -g {TEST_RG} --yes"
        registry_args = f"-n {registry_name} -g {TEST_RG}"
        registry_show = f"iot adr schema registry show {registry_args}"
        registry_delete = f"iot adr schema registry delete {registry_args} --yes"
        thing_args = f"-n {thing_schema} --registry {registry_name} -g {TEST_RG}"
        thing_show = f"iot adr schema show {thing_args}"
        thing_delete = f"iot adr schema delete {thing_args} --yes"
        message_args = f"-n {message_schema} --registry {registry_name} -g {TEST_RG}"
        message_show = f"iot adr schema show {message_args}"
        message_delete = f"iot adr schema delete {message_args} --yes"

        def version_commands(schema_name, version):
            args = (
                f"--registry {registry_name} --schema {schema_name} "
                f"--version {version} -g {TEST_RG}"
            )
            return (
                f"iot adr schema version show {args}",
                f"iot adr schema version delete {args} --yes",
            )

        thing_v1_show, thing_v1_delete = version_commands(thing_schema, "1")
        thing_v2_show, thing_v2_delete = version_commands(thing_schema, "02")
        message_v1_show, message_v1_delete = version_commands(message_schema, "1")

        with CleanupLedger() as cleanup:
            assert resource_is_absent(self, storage_show)
            cleanup.register(
                "storage account",
                lambda: _cleanup_owned(self, storage_show, storage_delete),
            )
            storage = self.cmd(
                f"storage account create -n {storage_name} -g {TEST_RG} "
                f"--location {TEST_LOCATION} --sku Standard_LRS --kind StorageV2 "
                "--enable-hierarchical-namespace true --allow-shared-key-access false "
                "--public-network-access Enabled"
            ).get_output_in_json()
            assert storage["isHnsEnabled"] is True
            container = self.cmd(
                f"storage container-rm create --storage-account {storage_name} "
                f"--name schemas -g {TEST_RG} --public-access off"
            ).get_output_in_json()
            container_url = (
                f"{storage['primaryEndpoints']['blob'].rstrip('/')}/schemas"
            )

            assert resource_is_absent(self, registry_show)
            cleanup.register(
                "schema registry",
                lambda: _cleanup_owned(self, registry_show, registry_delete),
            )
            registry = self.cmd(
                f"iot adr schema registry create {registry_args} "
                f"--registry-namespace {registry_namespace} "
                "--storage-account-container-url "
                f"{shlex.quote(container_url)} --system-assigned-mi"
            ).get_output_in_json()
            assert registry["identity"]["type"] == "SystemAssigned"
            assert registry["identity"]["principalId"]
            assert registry["properties"]["namespace"] == registry_namespace
            assert (
                registry["properties"]["storageAccountContainerUrl"]
                == container_url
            )
            shown_registry = self.cmd(registry_show).get_output_in_json()
            assert shown_registry["id"].casefold() == registry["id"].casefold()
            listed_registries = self.cmd(
                f"iot adr schema registry list -g {TEST_RG}"
            ).get_output_in_json()
            assert registry["id"].casefold() in {
                item["id"].casefold() for item in listed_registries
            }
            updated_registry = self.cmd(
                f"iot adr schema registry update {registry_args} "
                "--description 'Semantic Model registry'"
            ).get_output_in_json()
            assert (
                updated_registry["properties"]["description"]
                == "Semantic Model registry"
            )

            self.cmd(
                "role assignment create "
                f"--assignee-object-id {registry['identity']['principalId']} "
                "--assignee-principal-type ServicePrincipal "
                "--role 'Storage Blob Data Contributor' "
                f"--scope {shlex.quote(container['id'])}"
            )

            assert resource_is_absent(self, thing_show)
            cleanup.register(
                "Thing Model schema",
                lambda: _cleanup_owned(self, thing_show, thing_delete),
            )
            assert resource_is_absent(self, thing_v1_show)
            cleanup.register(
                "Thing Model version 1",
                lambda: _cleanup_schema_version(
                    self, thing_v1_show, thing_v1_delete
                ),
            )
            thing = self.cmd(
                f"iot adr schema create {thing_args} --schema-type ThingModel "
                "--format JsonLD/1.1"
            ).get_output_in_json()
            assert thing["properties"]["schemaType"] == "ThingModel"
            assert thing["properties"]["format"] == "JsonLD/1.1"
            _create_schema_version_with_retry(
                self,
                "iot adr schema version create "
                f"--registry {registry_name} --schema {thing_schema} --version 1 "
                f"--schema-content {_quote_scenario_argument(thing_v1_content)} "
                f"-g {TEST_RG}",
                expected_name="1",
                description="Thing Model version 1 creation",
            )
            shown_thing = self.cmd(thing_show).get_output_in_json()
            assert shown_thing["id"].casefold() == thing["id"].casefold()
            thing_v1 = wait_for_condition(
                lambda: self.cmd(thing_v1_show).get_output_in_json(),
                lambda version: version.get("name") == "1",
                description="Thing Model version 1 storage readability",
                timeout=600,
                interval=15,
                is_retryable_error=_schema_version_pending,
            )
            assert thing_v1["name"] == "1"
            assert (
                thing_v1["properties"]["schemaContent"]
                == thing_v1_content
            )

            assert resource_is_absent(self, thing_v2_show)
            cleanup.register(
                "Thing Model version 02",
                lambda: _cleanup_schema_version(
                    self, thing_v2_show, thing_v2_delete
                ),
            )
            _create_schema_version_with_retry(
                self,
                "iot adr schema version create "
                f"--registry {registry_name} --schema {thing_schema} --version 02 "
                f"--schema-content {_quote_scenario_argument(thing_v2_content)} "
                f"-g {TEST_RG}",
                expected_name="02",
                description="Thing Model version 02 creation",
            )
            thing_v2 = wait_for_condition(
                lambda: self.cmd(thing_v2_show).get_output_in_json(),
                lambda version: version.get("name") == "02",
                description="Thing Model version 02 storage readability",
                timeout=600,
                interval=15,
                is_retryable_error=_schema_version_pending,
            )
            assert thing_v2["name"] == "02"

            versions = self.cmd(
                f"iot adr schema version list --registry {registry_name} "
                f"--schema {thing_schema} -g {TEST_RG}"
            ).get_output_in_json()
            assert {version["name"] for version in versions} == {"1", "02"}

            assert resource_is_absent(self, message_show)
            cleanup.register(
                "Message Schema",
                lambda: _cleanup_owned(self, message_show, message_delete),
            )
            assert resource_is_absent(self, message_v1_show)
            cleanup.register(
                "Message Schema version 1",
                lambda: _cleanup_schema_version(
                    self, message_v1_show, message_v1_delete
                ),
            )
            message = self.cmd(
                f"iot adr schema create {message_args} --schema-type MessageSchema "
                "--format JsonSchema/draft-07"
            ).get_output_in_json()
            assert message["properties"]["schemaType"] == "MessageSchema"
            assert message["properties"]["format"] == "JsonSchema/draft-07"
            _create_schema_version_with_retry(
                self,
                "iot adr schema version create "
                f"--registry {registry_name} --schema {message_schema} --version 1 "
                f"--schema-content {_quote_scenario_argument(message_content)} "
                f"-g {TEST_RG}",
                expected_name="1",
                description="Message Schema version 1 creation",
            )
            message_v1 = wait_for_condition(
                lambda: self.cmd(message_v1_show).get_output_in_json(),
                lambda version: version.get("name") == "1",
                description="Message Schema version 1 storage readability",
                timeout=600,
                interval=15,
                is_retryable_error=_schema_version_pending,
            )
            assert message_v1["id"].endswith("/schemaVersions/1")

            schemas = self.cmd(
                f"iot adr schema list --registry {registry_name} -g {TEST_RG}"
            ).get_output_in_json()
            assert {schema["name"] for schema in schemas} == {
                thing_schema,
                message_schema,
            }

            _cleanup_schema_version(self, message_v1_show, message_v1_delete)
            cleanup.dismiss("Message Schema version 1")
            _cleanup_owned(self, message_show, message_delete)
            cleanup.dismiss("Message Schema")
            _cleanup_schema_version(self, thing_v2_show, thing_v2_delete)
            cleanup.dismiss("Thing Model version 02")
            _cleanup_schema_version(self, thing_v1_show, thing_v1_delete)
            cleanup.dismiss("Thing Model version 1")
            _cleanup_owned(self, thing_show, thing_delete)
            cleanup.dismiss("Thing Model schema")
            _cleanup_owned(self, registry_show, registry_delete)
            cleanup.dismiss("schema registry")
            _cleanup_owned(self, storage_show, storage_delete)
            cleanup.dismiss("storage account")
