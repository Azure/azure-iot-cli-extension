# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from base64 import b64encode
from hashlib import sha256
from unittest.mock import MagicMock, patch

import pytest
from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.core.exceptions import ResourceExistsError

from azext_iot.adr.providers.software_update_staging import SoftwareUpdateStager


def _write_manifest(tmp_path, payload=b"payload", filename="payload.bin"):
    payload_path = tmp_path / filename
    payload_path.write_bytes(payload)
    manifest = {
        "updateId": {
            "provider": "Contoso",
            "name": "Thermostat",
            "version": "1.0",
        },
        "files": [
            {
                "filename": filename,
                "sizeInBytes": len(payload),
                "hashes": {
                    "sha256": b64encode(sha256(payload).digest()).decode("utf8")
                },
            }
        ],
        "manifestVersion": "5.0",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, manifest


@pytest.fixture()
def stager():
    with patch(
        "azext_iot.adr.providers.software_update_staging.get_subscription_id",
        return_value="subscription",
    ), patch(
        "azext_iot.adr.providers.software_update_staging.StorageAccountManager"
    ) as manager_type:
        blob_service = MagicMock()
        blob_service.credential.account_name = "storage"
        blob_service.credential.account_key = "key"
        manager_type.return_value.get_sas_blob_service_client.return_value = (
            blob_service
        )
        value = SoftwareUpdateStager(
            cmd=MagicMock(cli_ctx=MagicMock()),
            storage_account="storage",
        )
        yield value, blob_service, manager_type


def _configure_new_blobs(blob_service):
    container = blob_service.get_container_client.return_value
    blobs = {}

    def get_blob(blob_name):
        blob = blobs.setdefault(blob_name, MagicMock())
        blob.exists.return_value = False
        blob.url = f"https://storage.example/{blob_name}"
        return blob

    container.get_blob_client.side_effect = get_blob
    return blobs


def test_stage_uploads_manifest_and_payload_without_sas(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    blobs = _configure_new_blobs(blob_service)

    with patch(
        "azext_iot.adr.providers.software_update_staging.generate_blob_sas"
    ) as generate_sas:
        summary, import_items = value.stage(
            [str(manifest_path)],
            "updates",
        )

    assert import_items == []
    assert summary["readyToImport"] is True
    assert summary["storagePrefix"] == "deviceupdate"
    assert "nextStep" in summary
    assert len(blobs) == 2
    assert {
        artifact["status"]
        for artifact in summary["updates"][0]["artifacts"]
    } == {"uploaded"}
    for blob in blobs.values():
        blob.upload_blob.assert_called_once()
    generate_sas.assert_not_called()


def test_stage_generates_batch_import_item(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    _configure_new_blobs(blob_service)

    with patch(
        "azext_iot.adr.providers.software_update_staging.generate_blob_sas",
        return_value="sig=secret",
    ) as generate_sas:
        summary, import_items = value.stage(
            [str(manifest_path)],
            "updates",
            include_sas=True,
            friendly_name="Friendly",
            sas_expiry_hours=6,
        )

    assert "nextStep" not in summary
    assert "sasExpiresOn" in summary
    assert generate_sas.call_count == 2
    assert {
        call.kwargs["blob_name"] for call in generate_sas.call_args_list
    } == {
        "deviceupdate/Contoso/Thermostat/1.0/manifest.json",
        "deviceupdate/Contoso/Thermostat/1.0/payload.bin",
    }
    assert {
        call.kwargs["container_name"] for call in generate_sas.call_args_list
    } == {"updates"}
    assert import_items == [
        {
            "importManifest": {
                "url": (
                    "https://storage.example/deviceupdate/Contoso/"
                    "Thermostat/1.0/manifest.json?sig=secret"
                ),
                "sizeInBytes": manifest_path.stat().st_size,
                "hashes": {
                    "sha256": b64encode(
                        sha256(manifest_path.read_bytes()).digest()
                    ).decode("utf8")
                },
            },
            "files": [
                {
                    "filename": "payload.bin",
                    "url": (
                        "https://storage.example/deviceupdate/Contoso/"
                        "Thermostat/1.0/payload.bin?sig=secret"
                    ),
                }
            ],
            "friendlyName": "Friendly",
        }
    ]


def test_stage_reuses_matching_blobs(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    container = blob_service.get_container_client.return_value

    def get_blob(blob_name):
        blob = MagicMock()
        artifact_path = (
            manifest_path
            if blob_name.endswith("manifest.json")
            else tmp_path / "payload.bin"
        )
        content = artifact_path.read_bytes()
        blob.exists.return_value = True
        blob.get_blob_properties.return_value.metadata = {
            "adu_sha256": sha256(content).hexdigest()
        }
        blob.get_blob_properties.return_value.size = len(content)
        blob.url = f"https://storage.example/{blob_name}"
        return blob

    container.get_blob_client.side_effect = get_blob
    summary, _ = value.stage([str(manifest_path)], "updates")

    assert {
        artifact["status"]
        for artifact in summary["updates"][0]["artifacts"]
    } == {"reused"}


def test_stage_rejects_conflicting_blob_without_overwrite(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    blob = MagicMock()
    blob.exists.return_value = True
    blob.get_blob_properties.return_value.metadata = {"adu_sha256": "different"}
    blob.get_blob_properties.return_value.size = 1
    blob_service.get_container_client.return_value.get_blob_client.return_value = (
        blob
    )

    with pytest.raises(InvalidArgumentValueError, match="--overwrite"):
        value.stage([str(manifest_path)], "updates")


def test_stage_overwrites_conflicting_blobs_when_requested(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    blob = MagicMock()
    blob.exists.return_value = True
    blob.get_blob_properties.return_value.metadata = {"adu_sha256": "different"}
    blob.get_blob_properties.return_value.size = 1
    blob.url = "https://storage.example/blob"
    blob_service.get_container_client.return_value.get_blob_client.return_value = (
        blob
    )

    summary, _ = value.stage(
        [str(manifest_path)],
        "updates",
        overwrite=True,
    )

    assert {
        artifact["status"]
        for artifact in summary["updates"][0]["artifacts"]
    } == {"uploaded"}
    assert blob.upload_blob.call_count == 2
    assert all(
        call.kwargs["overwrite"] is True
        for call in blob.upload_blob.call_args_list
    )


def test_stage_rejects_manifest_hash_mismatch_before_upload(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["files"][0]["hashes"]["sha256"] = "incorrect"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="SHA-256"):
        value.stage([str(manifest_path)], "updates")

    blob_service.create_container.assert_not_called()


def test_stage_preflights_every_manifest_before_upload(stager, tmp_path):
    value, blob_service, _ = stager
    first_directory = tmp_path / "first"
    second_directory = tmp_path / "second"
    first_directory.mkdir()
    second_directory.mkdir()
    first_manifest, _ = _write_manifest(first_directory, payload=b"first")
    second_manifest, second = _write_manifest(second_directory, payload=b"second")
    second["files"][0]["hashes"]["sha256"] = "incorrect"
    second_manifest.write_text(json.dumps(second), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="SHA-256"):
        value.stage(
            [str(first_manifest), str(second_manifest)],
            "updates",
        )

    blob_service.create_container.assert_not_called()


def test_stage_rejects_artifact_path_traversal(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["files"][0]["filename"] = "../payload.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="beside the manifest"):
        value.stage([str(manifest_path)], "updates")

    blob_service.create_container.assert_not_called()


@pytest.mark.parametrize("expiry_hours", [0, 25])
def test_stage_rejects_sas_expiry_outside_bounds(
    stager, tmp_path, expiry_hours
):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)

    with pytest.raises(InvalidArgumentValueError, match="between 1 and 24"):
        value.stage(
            [str(manifest_path)],
            "updates",
            sas_expiry_hours=expiry_hours,
        )

    blob_service.create_container.assert_not_called()


def test_stage_accepts_storage_account_resource_id():
    resource_id = (
        "/subscriptions/storage-sub/resourceGroups/rg/providers/"
        "Microsoft.Storage/storageAccounts/storage"
    )
    cli_ctx = MagicMock()
    with patch(
        "azext_iot.adr.providers.software_update_staging.StorageAccountManager"
    ) as manager_type:
        SoftwareUpdateStager(
            cmd=MagicMock(cli_ctx=cli_ctx),
            storage_account=resource_id,
        )

    manager_type.assert_called_once_with(
        cli_ctx=cli_ctx,
        subscription_id="storage-sub",
    )


def test_stage_tolerates_existing_container(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    _configure_new_blobs(blob_service)
    blob_service.create_container.side_effect = ResourceExistsError("exists")

    summary, _ = value.stage([str(manifest_path)], "updates")

    assert summary["readyToImport"] is True
