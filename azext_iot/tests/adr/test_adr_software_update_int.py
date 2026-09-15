# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import os
from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from msrestazure.tools import parse_resource_id

from azext_iot.tests.adr import ADRLiveScenarioTest
from azext_iot.tests.adr.conftest import TEST_RG
from azext_iot.tests.generators import generate_generic_id


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


@pytest.mark.usefixtures("set_cwd")
class TestADRSoftwareUpdateStage(ADRLiveScenarioTest):
    def test_software_update_stage_upload_and_reuse(self):
        namespace_name = os.getenv("azext_iot_adr_su_namespace")
        storage_account = os.getenv("azext_iot_adr_su_storage_account")
        storage_subscription = os.getenv(
            "azext_iot_adr_su_storage_subscription"
        )
        if not namespace_name or not storage_account:
            pytest.skip(
                "Set azext_iot_adr_su_namespace and "
                "azext_iot_adr_su_storage_account to run the stage integration test."
            )

        parsed_storage = (
            parse_resource_id(storage_account)
            if storage_account.startswith("/")
            else {}
        )
        account_name = parsed_storage.get("name") or storage_account
        subscription = (
            parsed_storage.get("subscription") or storage_subscription
        )
        container = f"adr-stage-{generate_generic_id()[:12]}".lower()
        subscription_arg = (
            f" --storage-subscription {storage_subscription}"
            if storage_subscription and not parsed_storage
            else ""
        )

        with TemporaryDirectory() as directory:
            payload_path = Path(directory) / "payload.bin"
            payload = b"ADR stage integration payload"
            payload_path.write_bytes(payload)
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "updateId": {
                            "provider": "Contoso",
                            "name": f"stage-{generate_generic_id()[:8]}",
                            "version": "1.0",
                        },
                        "compatibility": [
                            {
                                "deviceManufacturer": "Contoso",
                                "deviceModel": "StageTest",
                            }
                        ],
                        "instructions": {"steps": []},
                        "files": [
                            {
                                "filename": payload_path.name,
                                "sizeInBytes": len(payload),
                                "hashes": {
                                    "sha256": b64encode(
                                        sha256(payload).digest()
                                    ).decode("utf8")
                                },
                            }
                        ],
                        "manifestVersion": "5.0",
                    }
                ),
                encoding="utf-8",
            )
            command = (
                "iot adr ns su software-update stage "
                f"--ns {namespace_name} -g {TEST_RG} "
                f"--manifest-path '{manifest_path}' "
                f"--storage-account '{storage_account}' "
                f"--storage-container {container}{subscription_arg}"
            )
            try:
                first = self.cmd(command).get_output_in_json()
                assert first["readyToImport"] is True
                assert "sasExpiresOn" not in first
                assert {
                    artifact["status"]
                    for artifact in first["updates"][0]["artifacts"]
                } == {"uploaded"}

                second = self.cmd(command).get_output_in_json()
                assert {
                    artifact["status"]
                    for artifact in second["updates"][0]["artifacts"]
                } == {"reused"}
            finally:
                cleanup = (
                    f"storage container delete --account-name {account_name} "
                    f"--name {container} --auth-mode key"
                )
                if subscription:
                    cleanup += f" --subscription {subscription}"
                self.cmd(cleanup)


@pytest.mark.usefixtures("set_cwd")
class TestADRSoftwareUpdateDiscovery(ADRLiveScenarioTest):
    """Validate catalog and no-wait follow-up surfaces against a linked service."""

    def test_catalog_and_operation_status_discovery(self):
        namespace_name = os.getenv("azext_iot_adr_su_namespace")
        if not namespace_name:
            pytest.skip(
                "Set azext_iot_adr_su_namespace to run Software Updates "
                "catalog/status integration coverage."
            )

        providers = self.cmd(
            "iot adr ns su software-update catalog provider list "
            f"--ns {namespace_name} -g {TEST_RG}"
        ).get_output_in_json()
        assert isinstance(providers, list)
        if providers:
            provider = providers[0]
            names = self.cmd(
                "iot adr ns su software-update catalog name list "
                f"--ns {namespace_name} -g {TEST_RG} "
                f"--update-provider '{provider}'"
            ).get_output_in_json()
            assert isinstance(names, list)
            if names:
                versions = self.cmd(
                    "iot adr ns su software-update catalog version list "
                    f"--ns {namespace_name} -g {TEST_RG} "
                    f"--update-provider '{provider}' "
                    f"--update-name '{names[0]}'"
                ).get_output_in_json()
                assert isinstance(versions, list)
                if versions:
                    self.cmd(
                        "iot adr ns su software-update wait "
                        f"--ns {namespace_name} -g {TEST_RG} "
                        f"--update-provider '{provider}' "
                        f"--update-name '{names[0]}' "
                        f"--update-version '{versions[0]}'"
                    )

        statuses = self.cmd(
            "iot adr ns su software-update operation-status list "
            f"--ns {namespace_name} -g {TEST_RG}"
        ).get_output_in_json()
        assert isinstance(statuses, list)
        if statuses:
            operation_id = statuses[0]["operationId"]
            shown = self.cmd(
                "iot adr ns su software-update operation-status show "
                f"--ns {namespace_name} -g {TEST_RG} "
                f"--operation-id '{operation_id}'"
            ).get_output_in_json()
            assert shown["operationId"] == operation_id
