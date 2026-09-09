# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from base64 import b64encode
from hashlib import sha256
from http.client import HTTPException
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit
from urllib.request import urlopen

from azure.cli.core.azclierror import (
    AzureResponseError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)

from azext_iot._factory import (
    adr_service_factory,
    adr_software_update_data_service_factory,
)
from azext_iot.adr.common import SU_ENDPOINT_TYPE
from azext_iot.adr.providers import base as provider_base
from azext_iot.adr.providers.base import ADRProvider
from azext_iot.adr.providers.software_update_staging import SoftwareUpdateStager

_READ_CHUNK_SIZE = 4 * 1024 * 1024
_URL_READ_TIMEOUT_SECONDS = 60


class SoftwareUpdateDataProvider(ADRProvider):
    """Resolve and access the ADU v2 data plane linked to an ADR namespace."""

    def __init__(self, cmd):
        self.cmd = cmd
        self.registry_client = adr_service_factory(cmd.cli_ctx)
        self.client = None

    def _await_terminal(self, poller, **kwargs):
        return provider_base.wait_for_terminal_state(poller, **kwargs)

    def _resolve_endpoint(
        self, namespace_name: str, resource_group_name: str
    ) -> str:
        namespace = self.registry_client.namespaces.get(
            resource_group_name=resource_group_name,
            namespace_name=namespace_name,
        )
        properties = (namespace or {}).get("properties") or {}
        updating = properties.get("updating") or {}
        endpoints = updating.get("endpoints") or {}
        software_update_endpoints = [
            (name, endpoint or {})
            for name, endpoint in endpoints.items()
            if str((endpoint or {}).get("endpointType", "")).casefold()
            == SU_ENDPOINT_TYPE.casefold()
        ]
        if not software_update_endpoints:
            raise ResourceNotFoundError(
                f"Namespace '{namespace_name}' has no Software Updates link. "
                "Create one with 'az iot adr ns link su add'."
            )

        ready_endpoints = [
            (name, endpoint)
            for name, endpoint in software_update_endpoints
            if str(endpoint.get("linkingState", "")).casefold() == "succeeded"
            and str(endpoint.get("serviceAddress") or "").strip()
        ]
        if len(ready_endpoints) > 1:
            raise AzureResponseError(
                f"Namespace '{namespace_name}' has multiple ready Software Updates "
                "links; the data-plane endpoint is ambiguous."
            )
        if not ready_endpoints:
            failed = next(
                (
                    (name, endpoint)
                    for name, endpoint in software_update_endpoints
                    if str(endpoint.get("linkingState", "")).casefold()
                    == "failed"
                ),
                None,
            )
            if failed is not None:
                endpoint_name, endpoint = failed
                error = endpoint.get("linkingError") or {}
                detail = error.get("message") if isinstance(error, dict) else None
                message = (
                    f"Software Updates link '{endpoint_name}' is in a Failed state."
                )
                if detail:
                    message += f" {detail}"
                raise AzureResponseError(message)
            raise AzureResponseError(
                "No Software Updates link is ready. Wait until its linkingState "
                "is Succeeded and serviceAddress is populated."
            )

        endpoint = ready_endpoints[0][1]
        service_address = str(endpoint.get("serviceAddress") or "").strip()
        return self._normalize_endpoint(service_address)

    def _client_for_endpoint(self, endpoint: str):
        """Create a data client only after resolving the linked service host."""
        self.client = adr_software_update_data_service_factory(
            self.cmd.cli_ctx, endpoint=endpoint
        )
        return self.client

    @staticmethod
    def _normalize_endpoint(service_address: str) -> str:
        candidate = service_address.strip()
        parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
        if parsed.scheme and parsed.scheme.casefold() not in ("http", "https"):
            raise AzureResponseError(
                "The Software Updates link returned an unsupported serviceAddress scheme."
            )
        if (
            not parsed.netloc
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise AzureResponseError(
                "The Software Updates link returned an invalid serviceAddress."
            )
        return parsed.netloc


class SoftwareUpdateProvider(SoftwareUpdateDataProvider):
    """Manage Software Update content through the linked ADU v2 data plane."""

    @staticmethod
    def _parse_key_value_pairs(
        values: Optional[List[str]],
        argument_name: str,
        *,
        allowed_keys: Optional[Set[str]] = None,
    ) -> Dict[str, str]:
        result = {}
        for value in values or []:
            if "=" not in value:
                raise InvalidArgumentValueError(
                    f"{argument_name} values must use the key=value format."
                )
            key, item_value = value.split("=", 1)
            if not key or not item_value:
                raise InvalidArgumentValueError(
                    f"{argument_name} values must include a non-empty key and value."
                )
            if allowed_keys is not None and key not in allowed_keys:
                raise InvalidArgumentValueError(
                    f"{argument_name} contains unsupported property '{key}'."
                )
            result[key] = item_value
        return result

    @classmethod
    def _parse_files(
        cls, files: Optional[List[List[str]]]
    ) -> Optional[List[Dict[str, str]]]:
        if not files:
            return None
        result = []
        for file_values in files:
            item = cls._parse_key_value_pairs(
                file_values,
                "--file",
                allowed_keys={"filename", "url"},
            )
            if not {"filename", "url"} <= set(item):
                raise InvalidArgumentValueError(
                    "When using --file both filename and url are required."
                )
            result.append(item)
        return result

    @staticmethod
    def _calculate_url_metadata(url: str) -> Tuple[int, str]:
        digest = sha256()
        size = 0
        try:
            with urlopen(url, timeout=_URL_READ_TIMEOUT_SECONDS) as response:
                while True:
                    chunk = response.read(_READ_CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
        except (HTTPException, OSError, ValueError):
            raise AzureResponseError(
                "Unable to read the import manifest URL. Verify that it is "
                "accessible, or provide both --size and --hashes."
            ) from None
        return size, b64encode(digest.digest()).decode("utf8")

    def list_updates(
        self,
        namespace_name: str,
        resource_group_name: str,
        search: Optional[str] = None,
        filter: Optional[str] = None,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.list_updates(
            search=search,
            filter=filter,
        )

    def show_update(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
        update_name: str,
        update_version: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.get_update(
            provider=update_provider,
            name=update_name,
            version=update_version,
        )

    def delete_update(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
        update_name: str,
        update_version: str,
        **kwargs,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        poller = self._client_for_endpoint(endpoint).software_update.begin_delete_update(
            provider=update_provider,
            name=update_name,
            version=update_version,
        )
        return self._wait(
            poller,
            f"Deleting update '{update_provider}/{update_name}/{update_version}'...",
            **kwargs,
        )

    def import_update(
        self,
        namespace_name: str,
        resource_group_name: str,
        url: str,
        size: Optional[int] = None,
        hashes: Optional[List[str]] = None,
        friendly_name: Optional[str] = None,
        files: Optional[List[List[str]]] = None,
        enable_scan: Optional[bool] = None,
        **kwargs,
    ):
        calculated_size = None
        calculated_hash = None
        if size is None or not hashes:
            calculated_size, calculated_hash = self._calculate_url_metadata(url)

        manifest_hashes = self._parse_key_value_pairs(hashes, "--hashes")
        if not manifest_hashes:
            manifest_hashes = {"sha256": calculated_hash}
        if not manifest_hashes.get("sha256"):
            raise InvalidArgumentValueError(
                "--hashes must include a non-empty sha256 value."
            )

        manifest_size = size if size is not None else calculated_size
        if manifest_size is None or manifest_size < 1:
            raise InvalidArgumentValueError("--size must be greater than zero.")

        import_item = {
            "importManifest": {
                "url": url,
                "sizeInBytes": manifest_size,
                "hashes": manifest_hashes,
            }
        }
        import_files = self._parse_files(files)
        if import_files:
            import_item["files"] = import_files
        if friendly_name is not None:
            import_item["friendlyName"] = friendly_name

        return self._import_updates(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            import_items=[import_item],
            enable_scan=enable_scan,
            **kwargs,
        )

    def _import_updates(
        self,
        namespace_name: str,
        resource_group_name: str,
        import_items: List[Dict],
        enable_scan: Optional[bool] = None,
        endpoint: Optional[str] = None,
        **kwargs,
    ):
        request = {"importUpdateInput": import_items}
        if enable_scan is not None:
            request["enableScan"] = enable_scan

        endpoint = endpoint or self._resolve_endpoint(
            namespace_name, resource_group_name
        )
        poller = self._client_for_endpoint(endpoint).software_update.begin_import_update(
            import_update_request=request,
            logging_enable=False,
        )
        return self._wait(poller, "Importing software update...", **kwargs)

    def stage_update(
        self,
        namespace_name: str,
        resource_group_name: str,
        manifest_paths: List[str],
        storage_account: str,
        storage_container_name: str,
        storage_account_subscription: Optional[str] = None,
        storage_prefix: Optional[str] = None,
        friendly_name: Optional[str] = None,
        enable_scan: Optional[bool] = None,
        overwrite: bool = False,
        then_import: bool = False,
        sas_expiry_hours: int = 4,
        **kwargs,
    ):
        if kwargs.get("no_wait") and not then_import:
            raise InvalidArgumentValueError(
                "--no-wait can only be used together with --then-import."
            )
        if enable_scan is not None and not then_import:
            raise InvalidArgumentValueError(
                "--enable-scan can only be used together with --then-import."
            )

        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        stager = SoftwareUpdateStager(
            cmd=self.cmd,
            storage_account=storage_account,
            storage_account_subscription=storage_account_subscription,
        )
        summary, import_items = stager.stage(
            manifest_paths=manifest_paths,
            storage_container_name=storage_container_name,
            storage_prefix=storage_prefix,
            overwrite=overwrite,
            include_sas=then_import,
            sas_expiry_hours=sas_expiry_hours,
            friendly_name=friendly_name,
        )
        if not then_import:
            return summary

        return self._import_updates(
            namespace_name=namespace_name,
            resource_group_name=resource_group_name,
            import_items=import_items,
            enable_scan=enable_scan,
            endpoint=endpoint,
            **kwargs,
        )

    def list_update_files(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
        update_name: str,
        update_version: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.list_files(
            provider=update_provider,
            name=update_name,
            version=update_version,
        )

    def show_update_file(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
        update_name: str,
        update_version: str,
        update_file_id: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.get_file(
            provider=update_provider,
            name=update_name,
            version=update_version,
            file_id=update_file_id,
        )

    def list_operation_statuses(
        self, namespace_name: str, resource_group_name: str
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(
            endpoint
        ).software_update.list_operation_statuses()

    def show_operation_status(
        self,
        namespace_name: str,
        resource_group_name: str,
        operation_id: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(
            endpoint
        ).software_update.get_operation_status(operation_id=operation_id)

    def list_providers(self, namespace_name: str, resource_group_name: str):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.list_providers()

    def list_names(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.list_names(
            provider=update_provider
        )

    def list_versions(
        self,
        namespace_name: str,
        resource_group_name: str,
        update_provider: str,
        update_name: str,
        filter: Optional[str] = None,
    ):
        endpoint = self._resolve_endpoint(namespace_name, resource_group_name)
        return self._client_for_endpoint(endpoint).software_update.list_versions(
            provider=update_provider,
            name=update_name,
            filter=filter,
        )
