# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from base64 import b64encode
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from azext_iot.adr.rbac import LinkRbacManager
from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr._helpers import (
    ADRFullInfraHelper,
    CleanupLedger,
    ROLE_PROPAGATION_DELAY,
    SU_LIFECYCLE_TIMEOUT,
    SU_PROVISIONING_MAX_POLLS,
    SU_PROVISIONING_POLL_INTERVAL,
    wait_for_condition,
)
from azext_iot.tests.adr._log import timed_step
from azext_iot.tests.adr.conftest import (
    TEST_LOCATION,
    TEST_RG,
    TEST_SUBSCRIPTION,
    generate_adr_namespace_name,
)
from azext_iot.tests.generators import generate_generic_id

_REPORT_POLL_ATTEMPTS = 12
_REPORT_POLL_INTERVAL_SECONDS = 10
_ACCESS_POLL_ATTEMPTS = 30


@pytest.mark.usefixtures("set_cwd")
class TestADRSoftwareUpdateLocalCommands(ADRLiveScenarioTest):
    def test_software_update_local_commands(self):
        with TemporaryDirectory() as directory:
            payload_path = Path(directory) / "install.sh"
            payload_path.write_bytes(b"#!/bin/sh\necho updated\n")

            hashes = self.cmd(
                "iot adr ns su software-update calculate-hash "
                f"--file-path {payload_path}"
            ).get_output_in_json()
            assert hashes[0]["bytes"] == payload_path.stat().st_size
            assert hashes[0]["hashAlgorithm"] == "sha256"

            manifest = self.cmd(
                "iot adr ns su software-update init v5 "
                "--update-provider Contoso --update-name integration "
                "--update-version 1.0 --compat manufacturer=Contoso model=T1000 "
                "--step handler=microsoft/script:1 "
                f"--file path={payload_path}"
            ).get_output_in_json()
            assert manifest["manifestVersion"] == "5.0"
            assert manifest["updateId"] == {
                "provider": "Contoso",
                "name": "integration",
                "version": "1.0",
            }
            assert manifest["files"][0]["filename"] == payload_path.name


def _write_update(directory, name):
    """Write an importable single-step update and return its manifest path and update ID."""
    payload = json.dumps({"name": name, "version": "1.0", "packages": [{"name": "libcurl4-doc"}]}).encode("utf8")
    payload_path = Path(directory) / f"{name}-apt-manifest.json"
    payload_path.write_bytes(payload)
    update_id = {"provider": "Contoso", "name": name, "version": "1.0"}
    manifest_path = Path(directory) / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "updateId": update_id,
            "compatibility": [{"deviceManufacturer": "Contoso", "deviceModel": "StageTest"}],
            "instructions": {
                "steps": [{
                    "handler": "microsoft/apt:1",
                    "files": [payload_path.name],
                    "handlerProperties": {"installedCriteria": "1.0"},
                }]
            },
            "files": [{
                "filename": payload_path.name,
                "sizeInBytes": len(payload),
                "hashes": {"sha256": b64encode(sha256(payload).digest()).decode("utf8")},
            }],
            "manifestVersion": "5.0",
            "createdDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }),
        encoding="utf-8",
    )
    return manifest_path, update_id


def _access_pending(error):
    message = str(error).lower()
    return any(token in message for token in ("403", "forbidden", "unauthorized", "not authorized"))


def _report_pending(error):
    message = str(error).lower().replace(" ", "")
    return any(token in message for token in ("404", "notfound", "reportnotready", "inprogress"))


@pytest.mark.usefixtures("set_cwd")
class TestADRSoftwareUpdateLinked(ADRFullInfraHelper, ADRLiveScenarioTest):
    """Stage, import, catalog, operation status and reports on an owned SU-linked namespace."""

    def _delete_owned_resource(self, kind, name, resource_group, *, no_wait=False):
        super()._delete_owned_resource(kind, name, resource_group, no_wait=kind == "su" or no_wait)

    @pytest.mark.timeout(SU_LIFECYCLE_TIMEOUT * 2)
    def test_linked_namespace_software_update_and_reports(self):
        namespace_name = generate_adr_namespace_name()
        su_name = f"testsu{generate_generic_id()[:8]}"
        storage_account = f"adrsu{generate_generic_id()[:16]}"
        storage_created = False
        try:
            with timed_step("Setup 1/3 ❯ Namespace, Update Instance and storage account"):
                namespace = self.create_owned_resource(
                    f"iot adr ns create -n {namespace_name} -g {TEST_RG} --location {TEST_LOCATION}",
                    kind="namespace", name=namespace_name, resource_group=TEST_RG,
                ).get_output_in_json()
                self.create_owned_resource(
                    f"iot adr ns su instance create -n {su_name} -g {TEST_RG} "
                    f"--location {TEST_LOCATION} --system-assigned-mi --no-wait",
                    kind="su", name=su_name, resource_group=TEST_RG,
                )
                storage_created = True
                self.cmd(
                    f"storage account create -n {storage_account} -g {TEST_RG} --location {TEST_LOCATION}"
                )

            with timed_step("Setup 2/3 ❯ Grant roles while the Update Instance provisions"):
                su_id = wait_for_condition(
                    lambda: self.cmd(f"iot adr ns su instance show -n {su_name} -g {TEST_RG}").get_output_in_json(),
                    lambda resource: bool(resource.get("id")),
                    description="owned SU materialization",
                    timeout=120,
                )["id"]
                caller_id = LinkRbacManager(self.cli_ctx)._current_assignee_object_id(  # pylint: disable=protected-access
                    TEST_SUBSCRIPTION
                )
                grants = [
                    (namespace["identity"]["principalId"], "Contributor", "ServicePrincipal"),
                    (namespace["identity"]["principalId"], "Device Update Administrator", "ServicePrincipal"),
                    (caller_id, "Device Update Administrator", None),
                ]
                for principal, role, principal_type in grants:
                    assert self.assign_role(principal, role, su_id, assignee_type=principal_type), (
                        f"The SU fixture requires {role} on the owned Update Instance."
                    )
                wait_for_condition(
                    lambda: self.cmd(f"iot adr ns su instance show -n {su_name} -g {TEST_RG}").get_output_in_json(),
                    lambda resource: resource["properties"]["provisioningState"] == "Succeeded",
                    is_terminal_failure=lambda resource: resource["properties"].get("provisioningState")
                    in {"Failed", "Canceled", "Cancelled"},
                    description="owned SU provisioning Succeeded",
                    timeout=None,
                    max_attempts=SU_PROVISIONING_MAX_POLLS,
                    interval=SU_PROVISIONING_POLL_INTERVAL,
                    describe=lambda resource: f"provisioningState={resource['properties'].get('provisioningState')}",
                )

            with timed_step("Setup 3/3 ❯ link su add (system-assigned identity)"):
                self.cmd(
                    f"iot adr ns link su add --ns {namespace_name} -g {TEST_RG} -n su "
                    f"--su-id {su_id} --system-assigned-mi --timeout 1200"
                )
                wait_for_condition(
                    lambda: self.cmd(
                        f"iot adr ns su software-update catalog provider list --ns {namespace_name} -g {TEST_RG}"
                    ).get_output_in_json(),
                    lambda providers: isinstance(providers, list),
                    description="caller SU data-plane access",
                    timeout=None,
                    max_attempts=_ACCESS_POLL_ATTEMPTS,
                    interval=ROLE_PROPAGATION_DELAY,
                    is_retryable_error=_access_pending,
                )

            with TemporaryDirectory() as directory:
                update_name = f"stage{generate_generic_id()[:8]}"
                manifest_path, update_id = _write_update(directory, update_name)
                stage = (
                    f"iot adr ns su software-update stage --ns {namespace_name} -g {TEST_RG} "
                    f"--manifest-path '{manifest_path}' --storage-account {storage_account} "
                    f"--storage-container {update_name}"
                )
                with timed_step("Stage ❯ Upload, then reuse"):
                    first = self.cmd(stage).get_output_in_json()
                    assert first["readyToImport"] is True
                    assert "sasExpiresOn" not in first
                    assert {a["status"] for a in first["updates"][0]["artifacts"]} == {"uploaded"}
                    second = self.cmd(stage).get_output_in_json()
                    assert {a["status"] for a in second["updates"][0]["artifacts"]} == {"reused"}

                with timed_step("Import ❯ stage --then-import --no-wait, then wait --created"):
                    self.cmd(f"{stage} --then-import --no-wait")
                    version_args = (
                        f"--update-provider {update_id['provider']} --update-name {update_name} "
                        f"--update-version {update_id['version']}"
                    )
                    self.cmd(
                        f"iot adr ns su software-update wait --ns {namespace_name} -g {TEST_RG} "
                        f"{version_args} --created --timeout 1200"
                    )
                    shown = self.cmd(
                        f"iot adr ns su software-update show --ns {namespace_name} -g {TEST_RG} {version_args}"
                    ).get_output_in_json()
                    assert shown["updateId"] == update_id

            with timed_step("Discovery ❯ Catalog and operation status"):
                catalog = f"iot adr ns su software-update catalog {{}} list --ns {namespace_name} -g {TEST_RG}"
                assert update_id["provider"] in self.cmd(catalog.format("provider")).get_output_in_json()
                names = self.cmd(
                    catalog.format("name") + f" --update-provider {update_id['provider']}"
                ).get_output_in_json()
                assert update_name in names
                versions = self.cmd(
                    catalog.format("version")
                    + f" --update-provider {update_id['provider']} --update-name {update_name}"
                ).get_output_in_json()
                assert update_id["version"] in versions

                statuses = self.cmd(
                    f"iot adr ns su software-update operation-status list --ns {namespace_name} -g {TEST_RG}"
                ).get_output_in_json()
                assert statuses, "The import must report an operation status."
                operation_id = statuses[0]["operationId"]
                status = self.cmd(
                    f"iot adr ns su software-update operation-status show --ns {namespace_name} -g {TEST_RG} "
                    f"--operation-id {operation_id}"
                ).get_output_in_json()
                assert status["operationId"] == operation_id

            with timed_step("Reports ❯ Namespace and group reports"):
                self._assert_reports(namespace_name)
        finally:
            with CleanupLedger() as cleanup:
                if storage_created:
                    cleanup.register(
                        "storage account",
                        lambda: self.cmd(f"storage account delete -n {storage_account} -g {TEST_RG} --yes"),
                    )
                cleanup.register("owned ADR resources", self.cleanup_full_infra)

    def _assert_reports(self, namespace_name):
        group_name = f"testgrp{generate_generic_id()[:8]}"
        report = f"iot adr ns report {{}} --ns {namespace_name} -g {TEST_RG} --report-type {{}}"
        with CleanupLedger() as cleanup:
            group_uuid = self.cmd(
                f"iot adr ns group create -n {group_name} --ns {namespace_name} -g {TEST_RG} --query-string \"*\""
            ).get_output_in_json()["properties"]["uuid"]
            cleanup.register(
                "group",
                lambda: self.cmd(f"iot adr ns group delete -n {group_name} --ns {namespace_name} -g {TEST_RG} --yes"),
            )
            for report_type, group in (
                ("NamespaceUpdateComplianceReport", None),
                ("GroupBestUpdatesComplianceReport", group_name),
                ("GroupInstallableUpdatesReport", group_name),
            ):
                group_arg = f" --group-name {group}" if group else ""
                generated = self.cmd(report.format("generate", report_type) + group_arg).get_output_in_json()
                assert generated["reportType"] == report_type
                latest = wait_for_condition(
                    lambda: self.cmd(report.format("latest", report_type) + group_arg).get_output_in_json(),
                    lambda _: True,
                    description=f"{report_type} publication",
                    timeout=None,
                    interval=_REPORT_POLL_INTERVAL_SECONDS,
                    max_attempts=_REPORT_POLL_ATTEMPTS,
                    describe=lambda value: f"reportType={(value or {}).get('reportType')!r}",
                    is_retryable_error=_report_pending,
                )
                assert latest["reportType"] == report_type
                if group:
                    assert generated["reportTarget"] == group_uuid
                    assert latest["reportTarget"] == group_uuid

            self.cmd(
                report.format("generate", "NamespaceUpdateComplianceReport") + f" --group-name {group_name}",
                expect_failure=True,
            )
            self.cmd(report.format("generate", "GroupBestUpdatesComplianceReport"), expect_failure=True)
