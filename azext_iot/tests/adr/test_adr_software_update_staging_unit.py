# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
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


_STORAGE_ACCOUNT_ID = (
    "/subscriptions/storage-sub/resourceGroups/rg/providers/"
    "Microsoft.Storage/storageAccounts/storage"
)


@pytest.mark.parametrize("account,subscription,message", [
    (None, None, "--storage-account cannot be empty"),
    ("", None, "--storage-account cannot be empty"),
    (" \t ", None, "--storage-account cannot be empty"),
    (_STORAGE_ACCOUNT_ID.replace("Microsoft.Storage", "Microsoft.Devices"), None, "name or ARM resource ID"),
    (_STORAGE_ACCOUNT_ID.replace("storageAccounts", "containers"), None, "name or ARM resource ID"),
    (_STORAGE_ACCOUNT_ID.rsplit("/", 1)[0], None, "name or ARM resource ID"),
    ("/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/storage", None, "name or ARM resource ID"),
    (_STORAGE_ACCOUNT_ID, "different-sub", "--storage-subscription does not match"),
])
def test_stage_rejects_invalid_storage_target_before_client_creation(account, subscription, message):
    with patch(
        "azext_iot.adr.providers.software_update_staging.StorageAccountManager"
    ) as manager_type, patch(
        "azext_iot.adr.providers.software_update_staging.get_subscription_id"
    ) as get_subscription:
        with pytest.raises(InvalidArgumentValueError, match=message):
            SoftwareUpdateStager(
                cmd=MagicMock(), storage_account=account, storage_account_subscription=subscription,
            )

    manager_type.assert_not_called()
    get_subscription.assert_not_called()


@pytest.mark.parametrize("account,subscription", [
    (" storage ", "storage-sub"),
    (" " + _STORAGE_ACCOUNT_ID + " ", "STORAGE-SUB"),
])
def test_stage_explicit_storage_subscription_does_not_use_default_profile(account, subscription):
    cli_ctx = MagicMock()
    with patch(
        "azext_iot.adr.providers.software_update_staging.StorageAccountManager"
    ) as manager_type, patch(
        "azext_iot.adr.providers.software_update_staging.get_subscription_id"
    ) as get_subscription:
        value = SoftwareUpdateStager(
            cmd=MagicMock(cli_ctx=cli_ctx), storage_account=account, storage_account_subscription=subscription,
        )

    assert value.account_name == "storage"
    manager_type.assert_called_once_with(cli_ctx=cli_ctx, subscription_id="storage-sub")
    manager_type.return_value.get_sas_blob_service_client.assert_called_once_with(account_name="storage")
    get_subscription.assert_not_called()


@pytest.mark.parametrize("arguments,message", [
    ({"manifest_paths": []}, "At least one --manifest-path"),
    ({"manifest_paths": None}, "At least one --manifest-path"),
    ({"storage_container_name": None}, "--storage-container cannot be empty"),
    ({"storage_container_name": ""}, "--storage-container cannot be empty"),
    ({"storage_container_name": " \t "}, "--storage-container cannot be empty"),
    ({"storage_prefix": "/"}, "--storage-prefix cannot be empty"),
    ({"storage_prefix": " /// "}, "--storage-prefix cannot be empty"),
    ({"storage_prefix": " \t "}, "--storage-prefix cannot be empty"),
])
def test_stage_rejects_empty_inputs_without_storage_calls(stager, tmp_path, arguments, message):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    options = {"manifest_paths": [str(manifest_path)], "storage_container_name": "updates"}
    options.update(arguments)

    with pytest.raises(InvalidArgumentValueError, match=message):
        value.stage(**options)

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("is_directory", [False, True], ids=["missing", "directory"])
def test_stage_rejects_manifest_that_is_not_a_file(stager, tmp_path, is_directory):
    value, blob_service, _ = stager
    manifest_path = tmp_path / "manifest.json"
    if is_directory:
        manifest_path.mkdir()

    with pytest.raises(InvalidArgumentValueError, match="does not exist or is not a file") as error:
        value.stage([str(manifest_path)], "updates")

    assert str(manifest_path) in str(error.value)
    assert blob_service.mock_calls == []


@pytest.mark.parametrize("content,cause", [
    (b'{"updateId":', json.JSONDecodeError),
    (b"\xff", UnicodeDecodeError),
])
def test_stage_rejects_unreadable_json_manifest(stager, tmp_path, content, cause):
    value, blob_service, _ = stager
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(content)

    with pytest.raises(InvalidArgumentValueError, match="Unable to read a valid JSON import manifest") as error:
        value.stage([str(manifest_path)], "updates")

    assert isinstance(error.value.__cause__, cause)
    assert str(manifest_path) in str(error.value)
    assert blob_service.mock_calls == []


@pytest.mark.parametrize("manifest", [[], None, "manifest", 1])
def test_stage_requires_manifest_json_object(stager, tmp_path, manifest):
    value, blob_service, _ = stager
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="must contain a JSON object"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("filename,message", [
    ("manifest.json", "Unable to read a valid JSON import manifest"),
    ("payload.bin", "Unable to read manifest artifact"),
])
def test_stage_wraps_filesystem_read_errors_before_upload(stager, tmp_path, filename, message):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    unreadable = tmp_path / filename
    read_bytes = Path.read_bytes
    failure = PermissionError("Synthetic access denied")
    failed_reads = []

    def read_file(path):
        if path == unreadable:
            failed_reads.append(path)
            raise failure
        return read_bytes(path)

    with patch.object(Path, "read_bytes", read_file):
        with pytest.raises(InvalidArgumentValueError, match=message) as error:
            value.stage([str(manifest_path)], "updates")

    assert error.value.__cause__ is failure
    assert filename in str(error.value)
    assert failed_reads == [unreadable]
    assert blob_service.mock_calls == []


@pytest.mark.parametrize("update_id", [
    None, [], {}, {"provider": "Contoso", "name": "Thermostat"},
    {"provider": " ", "name": "Thermostat", "version": "1.0"},
    {"provider": "Contoso", "name": 1, "version": "1.0"},
    {"provider": "Contoso", "name": "Thermostat", "version": ""},
])
def test_stage_requires_complete_nonempty_update_id(stager, tmp_path, update_id):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["updateId"] = update_id
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="must define updateId provider, name, and version"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("field", ["files", "relatedFiles"])
@pytest.mark.parametrize("definitions", [{"filename": "payload.bin"}, "payload.bin", 1])
def test_stage_requires_file_definition_arrays(stager, tmp_path, field, definitions):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    owner = manifest if field == "files" else manifest["files"][0]
    owner[field] = definitions
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match=f"{field} must be a JSON array"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("definition", [None, [], "payload.bin", 1])
def test_stage_requires_file_definition_objects(stager, tmp_path, definition):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["files"] = [definition]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match="Manifest file entries must be JSON objects"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("is_directory", [False, True], ids=["missing", "directory"])
def test_stage_requires_payload_file_beside_manifest(stager, tmp_path, is_directory):
    value, blob_service, _ = stager
    manifest_path, _ = _write_manifest(tmp_path)
    artifact_path = tmp_path / "payload.bin"
    artifact_path.unlink()
    if is_directory:
        artifact_path.mkdir()

    with pytest.raises(InvalidArgumentValueError, match="Manifest artifact does not exist beside the manifest: payload.bin"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("size,message", [
    (None, "must define sizeInBytes"),
    (-1, "must define sizeInBytes"),
    ("7", "must define sizeInBytes"),
    (7.5, "must define sizeInBytes"),
    (0, "size does not match sizeInBytes"),
    (8, "size does not match sizeInBytes"),
])
def test_stage_requires_valid_matching_artifact_size(stager, tmp_path, size, message):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["files"][0]["sizeInBytes"] = size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match=message):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


@pytest.mark.parametrize("hashes", [None, {}, {"sha256": ""}, {"sha512": "other"}, "sha256"])
def test_stage_requires_sha256_artifact_hash(stager, tmp_path, hashes):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    manifest["files"][0]["hashes"] = hashes
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InvalidArgumentValueError, match=r"must define hashes\.sha256"):
        value.stage([str(manifest_path)], "updates")

    assert blob_service.mock_calls == []


def test_stage_rejects_conflicting_duplicate_when_local_content_changes(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path, payload=b"first")
    replacement = b"second"
    manifest["files"].append({
        "filename": "payload.bin", "sizeInBytes": len(replacement),
        "hashes": {"sha256": b64encode(sha256(replacement).digest()).decode("utf8")},
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    artifact_path = tmp_path / "payload.bin"
    read_bytes = Path.read_bytes
    payload_reads = []

    def read_and_replace(path):
        content = read_bytes(path)
        if path == artifact_path:
            payload_reads.append(content)
            if len(payload_reads) == 1:
                path.write_bytes(replacement)
        return content

    with patch.object(Path, "read_bytes", read_and_replace):
        with pytest.raises(InvalidArgumentValueError, match="conflicting definitions for 'payload.bin'"):
            value.stage([str(manifest_path)], "updates")

    assert payload_reads == [b"first", replacement]
    assert artifact_path.read_bytes() == replacement
    assert blob_service.mock_calls == []


def test_stage_deduplicates_identical_related_payload(stager, tmp_path):
    value, blob_service, _ = stager
    manifest_path, manifest = _write_manifest(tmp_path)
    definition = manifest["files"][0]
    definition["relatedFiles"] = [dict(definition)]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    blobs = _configure_new_blobs(blob_service)

    summary, import_items = value.stage([str(manifest_path)], "updates")

    assert import_items == []
    assert [artifact["filename"] for artifact in summary["updates"][0]["artifacts"]] == ["manifest.json", "payload.bin"]
    assert len(blobs) == 2
    for blob in blobs.values():
        blob.upload_blob.assert_called_once()


@pytest.mark.parametrize("friendly_name,expiry_hours", [(None, 1), ("Batch", 24)])
def test_stage_manifest_only_batch_sas_and_friendly_name(stager, tmp_path, friendly_name, expiry_hours):
    value, blob_service, _ = stager
    paths = []
    for index in range(2):
        directory = tmp_path / str(index)
        directory.mkdir()
        manifest_path, manifest = _write_manifest(directory)
        manifest["updateId"]["version"] = f" {index}.0 "
        manifest.pop("files")
        if index == 1:
            manifest["files"] = []
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        paths.append(manifest_path)
    blobs = _configure_new_blobs(blob_service)
    before = datetime.now(timezone.utc)

    with patch(
        "azext_iot.adr.providers.software_update_staging.generate_blob_sas", return_value="?sig=synthetic",
    ) as generate_sas:
        summary, import_items = value.stage(
            [str(path) for path in paths], " updates ", storage_prefix=" /custom/ ",
            include_sas=True, friendly_name=friendly_name, sas_expiry_hours=expiry_hours,
        )

    assert summary["readyToImport"] is True
    assert summary["storagePrefix"] == "custom" and summary["storageContainer"] == "updates"
    assert "nextStep" not in summary
    expires = datetime.fromisoformat(summary["sasExpiresOn"])
    assert before + timedelta(hours=expiry_hours) <= expires <= datetime.now(timezone.utc) + timedelta(hours=expiry_hours)
    assert len(import_items) == 2
    assert generate_sas.call_count == 2
    assert len(blobs) == 2
    blob_service.create_container.assert_called_once_with("updates")
    for index, (item, path) in enumerate(zip(import_items, paths)):
        content = path.read_bytes()
        blob_name = f"custom/Contoso/Thermostat/{index}.0/manifest.json"
        expected = {
            "importManifest": {
                "url": f"https://storage.example/{blob_name}?sig=synthetic",
                "sizeInBytes": len(content),
                "hashes": {"sha256": b64encode(sha256(content).digest()).decode("utf8")},
            },
        }
        if index == 0 and friendly_name is not None:
            expected["friendlyName"] = friendly_name
        assert item == expected
        blobs[blob_name].upload_blob.assert_called_once_with(
            content, overwrite=False,
            metadata={"adu_sha256": sha256(content).hexdigest(), "adu_size": str(len(content))},
        )
        call = generate_sas.call_args_list[index]
        assert call.kwargs["blob_name"] == blob_name
        assert call.kwargs["account_name"] == "storage" and call.kwargs["container_name"] == "updates"
        assert call.kwargs["account_key"] == "key"
        assert str(call.kwargs["permission"]) == "r"
        assert call.kwargs["expiry"] == expires
