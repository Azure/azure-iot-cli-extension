# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from knack.log import get_logger
from azext_iot.common.utility import handle_service_exception
from azext_iot.deviceupdate.providers.base import (
    DeviceUpdateDataModels,
    DeviceUpdateDataManager,
    AzureError,
    ARMPolling,
)
from azext_iot.deviceupdate.common import ADUValidHashAlgorithmType
from typing import Optional, List, Union, Dict

logger = get_logger(__name__)


def list_updates(
    cmd,
    name,
    instance_name,
    search: Optional[str] = None,
    filter: Optional[str] = None,
    by_provider: Optional[bool] = None,
    update_name: Optional[str] = None,
    update_provider: Optional[str] = None,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    try:
        if by_provider:
            if any([search, filter, update_name, update_provider]):
                logger.warning(
                    "--search, --filter, --update-name and --update-provider are not applicable when using --by-provider."
                )
            return data_manager.data_client.device_update.list_providers()
        if update_provider:
            if update_name:
                if search:
                    logger.warning("--search is not applicable when listing update versions by provider and name.")
                return data_manager.data_client.device_update.list_versions(
                    provider=update_provider, name=update_name, filter=filter
                )
            if any([search, filter, update_name]):
                logger.warning("--search, --filter and --update-name are not applicable when listing update names by provider.")
            return data_manager.data_client.device_update.list_names(provider=update_provider)
        if update_name:
            logger.warning("Use --update-name with --update-provider to list updates by version.")
        return data_manager.data_client.device_update.list_updates(search=search, filter=filter)
    except AzureError as e:
        handle_service_exception(e)


def list_update_files(
    cmd,
    name,
    instance_name,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.list_files(
            provider=update_provider, name=update_name, version=update_version
        )
    except AzureError as e:
        handle_service_exception(e)


def show_update(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.get_update(
            provider=update_provider, name=update_name, version=update_version
        )
    except AzureError as e:
        handle_service_exception(e)


def show_update_file(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    update_file_id: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    try:
        return data_manager.data_client.device_update.get_file(
            name=update_name, provider=update_provider, version=update_version, file_id=update_file_id
        )
    except AzureError as e:
        handle_service_exception(e)


def import_update(
    cmd,
    name: str,
    instance_name: str,
    url: str,
    size: Optional[int] = None,
    hashes: Optional[List[str]] = None,
    friendly_name: Optional[str] = None,
    file: Optional[List[List[str]]] = None,
    resource_group_name: Optional[str] = None,
):
    from azext_iot.deviceupdate.providers.base import MicroObjectCache

    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )
    client_calculated_meta = None
    if not size or not hashes:
        client_calculated_meta = data_manager.calculate_manifest_metadata(url)

    hashes = data_manager.assemble_nargs_to_dict(hash_list=hashes) or {"sha256": client_calculated_meta.hash}
    size = size or client_calculated_meta.bytes

    manifest_metadata = DeviceUpdateDataModels.ImportManifestMetadata(url=url, size_in_bytes=size, hashes=hashes)
    import_update_item = DeviceUpdateDataModels.ImportUpdateInputItem(
        import_manifest=manifest_metadata,
        friendly_name=friendly_name,
        files=data_manager.assemble_files(file_list_col=file),
    )
    cache = MicroObjectCache(cmd, DeviceUpdateDataModels)
    cache_resource_name = f"{name}_{instance_name}_importUpdate"
    cache_resource_type = "DeviceUpdate"
    cache_serialization_model = "[ImportUpdateInputItem]"
    defer = cmd.cli_ctx.data.get("_cache", False)
    cached_imports: Union[List[DeviceUpdateDataModels.ImportUpdateInputItem], None] = cache.get(
        resource_name=cache_resource_name,
        resource_group=data_manager.container.resource_group,
        resource_type=cache_resource_type,
        serialization_model=cache_serialization_model,
    )
    update_to_import = cached_imports if cached_imports else []
    update_to_import.append(import_update_item)

    if defer:
        cache.set(
            resource_name=cache_resource_name,
            resource_group=data_manager.container.resource_group,
            resource_type=cache_resource_type,
            payload=update_to_import,
            serialization_model=cache_serialization_model,
        )
        return
    else:
        import_poller = data_manager.data_client.device_update.begin_import_update(update_to_import=update_to_import)

        def import_handler(lro: ARMPolling):
            if lro.status() == "Succeeded":
                cache.remove(
                    resource_name=cache_resource_name,
                    resource_group=data_manager.container.resource_group,
                    resource_type=cache_resource_type,
                )
            elif lro.status() == "Failed":
                try:
                    logger.warning(
                        "Cached contents (if any) from usage of --defer were not removed. "
                        "Use 'az cache' command group to manage."
                    )
                    logger.error(lro._pipeline_response.http_response.text())
                except Exception:
                    pass

        import_poller.add_done_callback(import_handler)
        # @digimaun - TODO: Investigate better LRO error handling.
        return import_poller


def delete_update(
    cmd,
    name: str,
    instance_name: str,
    update_name: str,
    update_provider: str,
    update_version: str,
    resource_group_name: Optional[str] = None,
):
    data_manager = DeviceUpdateDataManager(
        cmd=cmd, account_name=name, instance_name=instance_name, resource_group=resource_group_name
    )

    # @digimaun - TODO: Investigate better LRO error handling.
    return data_manager.data_client.device_update.begin_delete_update(
        name=update_name, provider=update_provider, version=update_version
    )


def manifest_init_v5(
    cmd,
    update_name: str,
    update_provider: str,
    update_version: str,
    compatibility: List[List[str]],
    steps: List[List[str]],
    files: List[List[str]] = None,
    related_files: List[List[str]] = None,
    description: str = None,
    deployable: bool = None,
    no_validation: Optional[bool] = None,
):
    import json
    from datetime import datetime
    from pathlib import PurePath
    from azure.cli.core.azclierror import ArgumentUsageError

    def _sanitize_safe_params(safe_params: list, keep: list) -> list:
        """
        Intended to filter un-related params,
        leaving only related params with inherent positional indexing
        to be used by the _associate_related function.
        """
        result: List[str] = []
        if not safe_params:
            return result
        for param in safe_params:
            if param in keep:
                result.append(param)
        return result

    def _associate_related(sanitized_params: list, key: str) -> dict:
        """
        Intended to associate related param indexes. For example
        associate --file with the nearest --step or associate --related-file
        with the nearest --file.
        """
        result: Dict[int, list] = {}
        if not sanitized_params:
            return result
        params_len = len(sanitized_params)
        key_index = 0
        related_key_index = 0
        for i in range(params_len):
            if sanitized_params[i] == key:
                result[key_index] = []
                for j in range(i + 1, params_len):
                    if sanitized_params[j] == key:
                        break
                    result[key_index].append(related_key_index)
                    related_key_index = related_key_index + 1
                key_index = key_index + 1
        return result

    payload = {}
    payload["manifestVersion"] = "5.0"
    payload["createdDateTime"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["updateId"] = {}
    payload["updateId"]["name"] = update_name
    payload["updateId"]["provider"] = update_provider
    payload["updateId"]["version"] = update_version
    if deployable is False:
        payload["isDeployable"] = False
    if description:
        payload["description"] = description
    processed_compatibility = []
    for compat in compatibility:
        if not compat or not compat[0]:
            continue
        processed_compatibility.append(DeviceUpdateDataManager.assemble_nargs_to_dict(compat))
    payload["compatibility"] = processed_compatibility

    safe_params = cmd.cli_ctx.data.get("safe_params", [])
    processed_steps = []
    for s in range(len(steps)):
        if not steps[s] or not steps[s][0]:
            continue

        step_file_params = _sanitize_safe_params(safe_params, ["--step", "--file"])
        related_step_file_map = _associate_related(step_file_params, "--step")

        assembled_step = DeviceUpdateDataManager.assemble_nargs_to_dict(steps[s])
        step = {}
        if all(k in assembled_step for k in ("updateId.provider", "updateId.name", "updateId.version")):
            # reference step
            step = {
                "type": "reference",
                "updateId": {
                    "provider": assembled_step["updateId.provider"],
                    "name": assembled_step["updateId.name"],
                    "version": assembled_step["updateId.version"],
                },
            }
        elif "handler" in assembled_step:
            # inline step
            step = {
                "type": "inline",
                "handler": assembled_step["handler"],
            }
            step["files"] = [f.strip() for f in assembled_step["files"].split(",")] if "files" in assembled_step else []
            if not step["files"]:
                derived_step_files = []
                for f in related_step_file_map[s]:
                    step_file = files[f]
                    if not step_file or not step_file[0]:
                        continue
                    assembled_step_file = DeviceUpdateDataManager.assemble_nargs_to_dict(step_file)
                    if "path" in assembled_step_file:
                        derived_step_files.append(PurePath(assembled_step_file["path"]).name)
                step["files"] = derived_step_files

            if "properties" in assembled_step:
                step["handlerProperties"] = json.loads(assembled_step["properties"])

        if not step:
            raise ArgumentUsageError(
                "Usage of --step requires at least an entry of handler=<value> for an inline step or "
                "all of updateId.provider=<value>, updateId.name=<value>, updateId.version=<value> for a reference step."
            )

        step_desc = assembled_step.get("description") or assembled_step.get("desc")
        if step_desc:
            step["description"] = step_desc
        processed_steps.append(step)

    payload["instructions"] = {}
    payload["instructions"]["steps"] = processed_steps

    if files:
        file_params = _sanitize_safe_params(safe_params, ["--file", "--related-file"])
        related_file_map = _associate_related(file_params, "--file")

        processed_files = []
        for f in range(len(files)):
            if not files[f] or not files[f][0]:
                continue
            processed_file = {}
            assembled_file = DeviceUpdateDataManager.assemble_nargs_to_dict(files[f])
            if "path" not in assembled_file:
                raise ArgumentUsageError("When using --file path is required.")
            assembled_file_metadata = DeviceUpdateDataManager.calculate_file_metadata(assembled_file["path"])
            processed_file["hashes"] = {"sha256": assembled_file_metadata.hash}
            processed_file["filename"] = assembled_file_metadata.name
            processed_file["sizeInBytes"] = assembled_file_metadata.bytes

            if "properties" in assembled_file:
                processed_file["properties"] = json.loads(assembled_file["properties"])

            if "downloadHandler" in assembled_file:
                processed_file["downloadHandler"] = {"id": assembled_file["downloadHandler"]}

            processed_related_files = []
            for r in related_file_map[f]:
                related_file = related_files[r]
                if not related_file or not related_file[0]:
                    continue
                processed_related_file = {}
                assembled_related_file = DeviceUpdateDataManager.assemble_nargs_to_dict(related_file)
                if "path" not in assembled_related_file:
                    raise ArgumentUsageError("When using --related-file path is required.")
                related_file_metadata = DeviceUpdateDataManager.calculate_file_metadata(assembled_related_file["path"])
                processed_related_file["hashes"] = {"sha256": related_file_metadata.hash}
                processed_related_file["filename"] = related_file_metadata.name
                processed_related_file["sizeInBytes"] = related_file_metadata.bytes

                if "properties" in assembled_related_file:
                    processed_related_file["properties"] = json.loads(assembled_related_file["properties"])

                if processed_related_file:
                    processed_related_files.append(processed_related_file)

            if processed_related_files:
                processed_file["relatedFiles"] = processed_related_files

            if processed_file:
                processed_files.append(processed_file)

        payload["files"] = processed_files

    if not no_validation:
        import jsonschema
        from azure.cli.core.azclierror import ValidationError
        from azext_iot.deviceupdate.schemas import DEVICE_UPDATE_MANIFEST_V5, DEVICE_UPDATE_MANIFEST_V5_DEFS
        validator = jsonschema.Draft7Validator(DEVICE_UPDATE_MANIFEST_V5)
        validator.resolver.store[DEVICE_UPDATE_MANIFEST_V5_DEFS["$id"]] = DEVICE_UPDATE_MANIFEST_V5_DEFS

        try:
            validator.validate(payload)
        except jsonschema.ValidationError as ve:
            raise ValidationError(ve)

    return payload


def calculate_hash(
    file_paths: List[List[str]],
    hash_algo: str = ADUValidHashAlgorithmType.SHA256.value,
):
    result = []
    for path in file_paths:
        file_metadata = DeviceUpdateDataManager.calculate_file_metadata(path[0])
        result.append(
            {
                "bytes": file_metadata.bytes,
                "hash": file_metadata.hash,
                "hashAlgorithm": hash_algo,
                "uri": file_metadata.path.as_uri(),
            }
        )
    return result


def stage_update(
    cmd,
    name: str,
    instance_name: str,
    update_manifest_paths: List[str],
    storage_account_name: str,
    storage_container_name: str,
    friendly_name: str = None,
    then_import: Optional[bool] = None,
    resource_group_name: Optional[str] = None,
    overwrite: bool = False,
):
    from azext_iot.common.embedded_cli import EmbeddedCLI
    from datetime import datetime, timedelta
    from azext_iot.common.utility import process_json_arg
    from pathlib import PurePath
    from azure.identity import AzureCliCredential
    from azure.mgmt.storage import StorageManagementClient
    from azure.storage.blob import ResourceTypes, AccountSasPermissions, generate_account_sas, BlobServiceClient
    from azure.cli.core.azclierror import ResourceNotFoundError
    from azure.core.exceptions import ResourceExistsError
    from msrestazure.tools import parse_resource_id

    cli = EmbeddedCLI()
    az_account_info = cli.invoke("account show").as_json()
    azcli_credential = AzureCliCredential()

    target_subscription = cmd.cli_ctx.data.get("subscription_id") or az_account_info.get("id")
    storage_mgmt_client = StorageManagementClient(credential=azcli_credential, subscription_id=target_subscription)
    list_iterator = storage_mgmt_client.storage_accounts.list()
    target_account = None
    for acc in list_iterator:
        if acc.name == storage_account_name:
            target_account = acc
    if not target_account:
        raise ResourceNotFoundError(
            f"Unable to find storage account: {storage_account_name} in subscription: {target_subscription}.")

    storage_rg = parse_resource_id(target_account.id)["resource_group"]
    storage_keys = storage_mgmt_client.storage_accounts.list_keys(
        resource_group_name=storage_rg, account_name=target_account.name)
    blob_service_client = BlobServiceClient(
        account_url=target_account.primary_endpoints.blob, credential=storage_keys.keys[0].value)
    try:
        blob_service_client.create_container(name=storage_container_name)
    except ResourceExistsError:
        pass
    container_client = blob_service_client.get_container_client(container=storage_container_name)

    def _stage_update_assets(
        file_paths: List[str],
        container_directory: str = "",
    ) -> List[str]:

        file_sas_result = []
        for file_path in file_paths:
            file_name = PurePath(file_path).name
            blob_client = None
            with open(file_path, "rb") as data:
                blob_client = container_client.upload_blob(
                    name=f"{container_directory}{file_name}", data=data, overwrite=overwrite)

            target_datetime_expiry = (datetime.utcnow() + timedelta(hours=3.0))
            sas_token = generate_account_sas(
                account_name=target_account.name,
                account_key=storage_keys.keys[0].value,
                resource_types=ResourceTypes(object=True),
                permission=AccountSasPermissions(read=True),
                expiry=target_datetime_expiry
            )
            file_sas_result.append(f"{blob_client.url}?{sas_token}")

        return file_sas_result

    manifest_sas_uris_map = {}
    for manifest_path in update_manifest_paths:
        manifest: dict = process_json_arg(manifest_path, argument_name="--manifest-path")
        manifest_files = manifest.get("files")
        uploaded_files_map = {}

        manifest_purepath = PurePath(manifest_path)
        manifest_directory_path = manifest_purepath.parent.as_posix()
        manifest_directory_name = manifest_purepath.parent.name

        file_paths = [manifest_path]
        file_names = []
        if manifest_files:
            for file in manifest_files:
                filename = file["filename"]
                if filename in uploaded_files_map:
                    continue
                file_names.append(filename)
                file_paths.append(PurePath(manifest_directory_path, filename).as_posix())
                uploaded_files_map[filename] = 1

        updateId = manifest['updateId']
        qualifier = f"{updateId['provider']}_{updateId['name']}_{updateId['version']}"
        manifest_sas_uris_map[manifest_path] = (
            _stage_update_assets(file_paths, f"{manifest_directory_name}/{qualifier}/"),
            file_names
        )

    user_commands = []
    manifest_count = len(manifest_sas_uris_map)
    for manifest_sas_uris in manifest_sas_uris_map:
        sas_uris, file_names = manifest_sas_uris_map[manifest_sas_uris]
        root_uri = sas_uris.pop(0)
        friendly_name_cmd_seg = ""
        if friendly_name:
            friendly_name_cmd_seg = f" --friendly-name {friendly_name}"
        file_cmd_segs = ""
        for file_uri_index in range(len(sas_uris)):
            file_cmd_segs = file_cmd_segs + f" --file filename={file_names[file_uri_index]} url={sas_uris[file_uri_index]}"
        defer_cmd_seg = ""
        if manifest_count > 1:
            defer_cmd_seg = " --defer"
        user_commands.append(
            f"az iot du update import -n {name} -i {instance_name} -g {resource_group_name} "
            f"--url {root_uri}{friendly_name_cmd_seg}{file_cmd_segs}{defer_cmd_seg}"
        )
        manifest_count = manifest_count - 1

    total_commands = {"commands": user_commands}

    if then_import:
        for command in total_commands["commands"]:
            # New EmbeddedCLI instance created per command due to persisted cache setting.
            import_cli = EmbeddedCLI(cli_ctx=cmd.cli_ctx)
            import_cli.invoke(command.split("az")[1])
        return

    return total_commands
