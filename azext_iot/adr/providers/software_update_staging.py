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
from typing import Dict, List, Optional, Tuple

from azure.cli.core.azclierror import InvalidArgumentValueError
from azure.cli.core.commands.client_factory import get_subscription_id
from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import (
    BlobSasPermissions,
    generate_blob_sas,
)
from msrestazure.tools import parse_resource_id

from azext_iot.deviceupdate.providers.storage import StorageAccountManager

_DEFAULT_PREFIX = "deviceupdate"
_MINIMUM_SAS_EXPIRY_HOURS = 1
_MAXIMUM_SAS_EXPIRY_HOURS = 24


class SoftwareUpdateStager:
    """Validate and upload local Software Update import artifacts."""

    def __init__(
        self,
        cmd,
        storage_account: str,
        storage_account_subscription: Optional[str] = None,
    ):
        account_name, subscription_id = self._resolve_storage_account(
            cmd,
            storage_account,
            storage_account_subscription,
        )
        self.account_name = account_name
        self.storage_manager = StorageAccountManager(
            cli_ctx=cmd.cli_ctx,
            subscription_id=subscription_id,
        )
        self.blob_service_client = (
            self.storage_manager.get_sas_blob_service_client(
                account_name=self.account_name
            )
        )

    @staticmethod
    def _resolve_storage_account(
        cmd,
        storage_account: str,
        storage_account_subscription: Optional[str],
    ) -> Tuple[str, str]:
        if not storage_account or not storage_account.strip():
            raise InvalidArgumentValueError("--storage-account cannot be empty.")

        value = storage_account.strip()
        if value.startswith("/"):
            parsed = parse_resource_id(value)
            if (
                str(parsed.get("namespace", "")).casefold()
                != "microsoft.storage"
                or str(parsed.get("type", "")).casefold() != "storageaccounts"
                or not parsed.get("name")
                or not parsed.get("subscription")
            ):
                raise InvalidArgumentValueError(
                    "--storage-account must be a storage account name or ARM resource ID."
                )
            subscription_id = parsed["subscription"]
            if (
                storage_account_subscription
                and storage_account_subscription.casefold()
                != subscription_id.casefold()
            ):
                raise InvalidArgumentValueError(
                    "--storage-subscription does not match the storage account ARM ID."
                )
            return parsed["name"], subscription_id

        subscription_id = storage_account_subscription or get_subscription_id(
            cmd.cli_ctx
        )
        return value, subscription_id

    @staticmethod
    def _read_manifest(manifest_path: str) -> Dict:
        path = Path(manifest_path).expanduser()
        if not path.is_file():
            raise InvalidArgumentValueError(
                f"Import manifest does not exist or is not a file: {manifest_path}"
            )
        try:
            raw = path.read_bytes()
            manifest = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidArgumentValueError(
                f"Unable to read a valid JSON import manifest: {manifest_path}"
            ) from error
        if not isinstance(manifest, dict):
            raise InvalidArgumentValueError(
                f"Import manifest must contain a JSON object: {manifest_path}"
            )
        return {
            "path": path.resolve(),
            "content": raw,
            "manifest": manifest,
        }

    @staticmethod
    def _calculate_content_metadata(content: bytes) -> Dict[str, object]:
        digest = sha256(content)
        return {
            "size": len(content),
            "sha256": b64encode(digest.digest()).decode("utf8"),
            "sha256_hex": digest.hexdigest(),
        }

    @classmethod
    def _read_artifact(
        cls,
        manifest_directory: Path,
        definition: Dict,
        manifest_path: Path,
    ) -> Dict:
        if not isinstance(definition, dict):
            raise InvalidArgumentValueError(
                f"Manifest file entries must be JSON objects: {manifest_path}"
            )
        filename = definition.get("filename")
        if (
            not isinstance(filename, str)
            or not filename
            or filename in {".", ".."}
            or "/" in filename
            or "\\" in filename
        ):
            raise InvalidArgumentValueError(
                f"Manifest file names must reference files beside the manifest: {filename!r}"
            )
        path = (manifest_directory / filename).resolve()
        if path.parent != manifest_directory or not path.is_file():
            raise InvalidArgumentValueError(
                f"Manifest artifact does not exist beside the manifest: {filename}"
            )
        try:
            content = path.read_bytes()
        except OSError as error:
            raise InvalidArgumentValueError(
                f"Unable to read manifest artifact: {filename}"
            ) from error

        metadata = cls._calculate_content_metadata(content)
        declared_size = definition.get("sizeInBytes")
        declared_hashes = definition.get("hashes")
        declared_sha256 = (
            declared_hashes.get("sha256")
            if isinstance(declared_hashes, dict)
            else None
        )
        if not isinstance(declared_size, int) or declared_size < 0:
            raise InvalidArgumentValueError(
                f"Manifest artifact '{filename}' must define sizeInBytes."
            )
        if not declared_sha256:
            raise InvalidArgumentValueError(
                f"Manifest artifact '{filename}' must define hashes.sha256."
            )
        if declared_size != metadata["size"]:
            raise InvalidArgumentValueError(
                f"Manifest artifact '{filename}' size does not match sizeInBytes."
            )
        if declared_sha256 != metadata["sha256"]:
            raise InvalidArgumentValueError(
                f"Manifest artifact '{filename}' SHA-256 hash does not match the manifest."
            )
        return {
            "filename": filename,
            "path": path,
            "content": content,
            **metadata,
        }

    @classmethod
    def _prepare_manifest(cls, manifest_path: str, prefix: str) -> Dict:
        manifest_record = cls._read_manifest(manifest_path)
        manifest = manifest_record["manifest"]
        update_id = manifest.get("updateId")
        required_update_id = ("provider", "name", "version")
        if not isinstance(update_id, dict) or any(
            not isinstance(update_id.get(key), str) or not update_id[key].strip()
            for key in required_update_id
        ):
            raise InvalidArgumentValueError(
                f"Import manifest must define updateId provider, name, and version: {manifest_path}"
            )

        root = "/".join(
            [
                prefix,
                update_id["provider"].strip(),
                update_id["name"].strip(),
                update_id["version"].strip(),
            ]
        )
        manifest_metadata = cls._calculate_content_metadata(
            manifest_record["content"]
        )
        manifest_artifact = {
            "filename": manifest_record["path"].name,
            "path": manifest_record["path"],
            "content": manifest_record["content"],
            "blob_name": f"{root}/{manifest_record['path'].name}",
            **manifest_metadata,
        }

        artifacts = {}
        files = manifest.get("files") or []
        if not isinstance(files, list):
            raise InvalidArgumentValueError(
                f"Import manifest files must be a JSON array: {manifest_path}"
            )
        for definition in files:
            candidates = [definition]
            if isinstance(definition, dict):
                related_files = definition.get("relatedFiles") or []
                if not isinstance(related_files, list):
                    raise InvalidArgumentValueError(
                        f"relatedFiles must be a JSON array: {manifest_path}"
                    )
                candidates.extend(related_files)
            for candidate in candidates:
                artifact = cls._read_artifact(
                    manifest_record["path"].parent,
                    candidate,
                    manifest_record["path"],
                )
                existing = artifacts.get(artifact["filename"])
                if existing and existing["sha256"] != artifact["sha256"]:
                    raise InvalidArgumentValueError(
                        f"Manifest contains conflicting definitions for '{artifact['filename']}'."
                    )
                artifact["blob_name"] = f"{root}/{artifact['filename']}"
                artifacts[artifact["filename"]] = artifact

        return {
            "update_id": {
                key: update_id[key].strip() for key in required_update_id
            },
            "manifest": manifest_artifact,
            "artifacts": list(artifacts.values()),
        }

    @staticmethod
    def _upload_artifact(
        container_client, artifact: Dict, overwrite: bool
    ) -> str:
        blob_client = container_client.get_blob_client(artifact["blob_name"])
        if blob_client.exists():
            properties = blob_client.get_blob_properties()
            metadata = properties.metadata or {}
            if (
                metadata.get("adu_sha256") == artifact["sha256_hex"]
                and properties.size == artifact["size"]
            ):
                artifact["url"] = blob_client.url
                return "reused"
            if not overwrite:
                raise InvalidArgumentValueError(
                    f"Blob '{artifact['blob_name']}' already exists with different content. "
                    "Use --overwrite to replace it."
                )

        blob_client.upload_blob(
            artifact["content"],
            overwrite=overwrite,
            metadata={
                "adu_sha256": artifact["sha256_hex"],
                "adu_size": str(artifact["size"]),
            },
        )
        artifact["url"] = blob_client.url
        return "uploaded"

    def stage(
        self,
        manifest_paths: List[str],
        storage_container_name: str,
        storage_prefix: Optional[str] = None,
        overwrite: bool = False,
        include_sas: bool = False,
        sas_expiry_hours: int = 4,
        friendly_name: Optional[str] = None,
    ) -> Tuple[Dict, List[Dict]]:
        if not manifest_paths:
            raise InvalidArgumentValueError(
                "At least one --manifest-path is required."
            )
        if not storage_container_name or not storage_container_name.strip():
            raise InvalidArgumentValueError("--storage-container cannot be empty.")
        if not (
            _MINIMUM_SAS_EXPIRY_HOURS
            <= sas_expiry_hours
            <= _MAXIMUM_SAS_EXPIRY_HOURS
        ):
            raise InvalidArgumentValueError(
                "--sas-expiry-hours must be between 1 and 24."
            )

        prefix = (storage_prefix or _DEFAULT_PREFIX).strip().strip("/")
        if not prefix:
            raise InvalidArgumentValueError("--storage-prefix cannot be empty.")
        prepared = [
            self._prepare_manifest(manifest_path, prefix)
            for manifest_path in manifest_paths
        ]

        container_name = storage_container_name.strip()
        try:
            self.blob_service_client.create_container(container_name)
        except ResourceExistsError:
            pass
        container_client = self.blob_service_client.get_container_client(
            container_name
        )

        summary_updates = []
        for update in prepared:
            staged_artifacts = []
            all_artifacts = [update["manifest"], *update["artifacts"]]
            for artifact in all_artifacts:
                state = self._upload_artifact(
                    container_client, artifact, overwrite
                )
                staged_artifacts.append(
                    {
                        "filename": artifact["filename"],
                        "blobName": artifact["blob_name"],
                        "sizeInBytes": artifact["size"],
                        "status": state,
                    }
                )
            summary_updates.append(
                {
                    "updateId": update["update_id"],
                    "artifacts": staged_artifacts,
                }
            )

        import_items = []
        expires_on = None
        if include_sas:
            expires_on = datetime.now(timezone.utc) + timedelta(
                hours=sas_expiry_hours
            )
            credential = self.blob_service_client.credential

            def build_sas_url(artifact):
                sas_token = generate_blob_sas(
                    account_name=credential.account_name,
                    container_name=container_name,
                    blob_name=artifact["blob_name"],
                    account_key=credential.account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=expires_on,
                ).lstrip("?")
                return f"{artifact['url']}?{sas_token}"

            for index, update in enumerate(prepared):
                manifest_artifact = update["manifest"]
                item = {
                    "importManifest": {
                        "url": build_sas_url(manifest_artifact),
                        "sizeInBytes": manifest_artifact["size"],
                        "hashes": {"sha256": manifest_artifact["sha256"]},
                    }
                }
                import_files = [
                    {
                        "filename": artifact["filename"],
                        "url": build_sas_url(artifact),
                    }
                    for artifact in update["artifacts"]
                ]
                if import_files:
                    item["files"] = import_files
                if index == 0 and friendly_name is not None:
                    item["friendlyName"] = friendly_name
                import_items.append(item)

        summary = {
            "storageAccount": self.account_name,
            "storageContainer": container_name,
            "storagePrefix": prefix,
            "updates": summary_updates,
            "readyToImport": True,
        }
        if expires_on is not None:
            summary["sasExpiresOn"] = expires_on.isoformat()
        else:
            summary["nextStep"] = (
                "Run the same stage command with --then-import to generate "
                "fresh SAS URLs and import the staged updates."
            )
        return summary, import_items
