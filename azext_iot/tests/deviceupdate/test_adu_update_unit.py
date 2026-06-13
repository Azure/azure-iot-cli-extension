# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import json
import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azure.cli.core.azclierror import ArgumentUsageError, ValidationError

import azext_iot.deviceupdate.commands_update as subject

MOD = "azext_iot.deviceupdate.commands_update"


@pytest.fixture
def data_manager(mocker):
    instance = MagicMock()
    instance.container.resource_group = "rg"
    mocker.patch(f"{MOD}.DeviceUpdateDataManager", return_value=instance)
    return instance


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch(f"{MOD}.handle_service_exception")


# ---------------------------------------------------------------------------
# list_updates
# ---------------------------------------------------------------------------


def test_list_updates_by_provider(data_manager):
    subject.list_updates(
        cmd=MagicMock(), name="acct", instance_name="inst", by_provider=True,
        search="s", filter="f", update_name="n", update_provider="p",
    )
    data_manager.data_client.device_update.list_providers.assert_called_once()


def test_list_updates_provider_and_name(data_manager):
    subject.list_updates(
        cmd=MagicMock(), name="acct", instance_name="inst",
        update_provider="p", update_name="n", search="s", filter="f",
    )
    data_manager.data_client.device_update.list_versions.assert_called_once_with(
        provider="p", name="n", filter="f"
    )


def test_list_updates_provider_only(data_manager):
    subject.list_updates(
        cmd=MagicMock(), name="acct", instance_name="inst",
        update_provider="p", search="s", filter="f",
    )
    data_manager.data_client.device_update.list_names.assert_called_once_with(provider="p")


def test_list_updates_name_only(data_manager):
    subject.list_updates(
        cmd=MagicMock(), name="acct", instance_name="inst", update_name="n",
    )
    data_manager.data_client.device_update.list_updates.assert_called_once()


def test_list_updates_default(data_manager):
    subject.list_updates(cmd=MagicMock(), name="acct", instance_name="inst", search="s", filter="f")
    data_manager.data_client.device_update.list_updates.assert_called_once_with(search="s", filter="f")


def test_list_updates_error(data_manager, handle_exc):
    data_manager.data_client.device_update.list_updates.side_effect = AzureError("boom")
    subject.list_updates(cmd=MagicMock(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


# ---------------------------------------------------------------------------
# list_update_files / show_update / show_update_file
# ---------------------------------------------------------------------------


def test_list_update_files(data_manager):
    subject.list_update_files(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v",
    )
    data_manager.data_client.device_update.list_files.assert_called_once_with(
        provider="p", name="n", version="v"
    )


def test_list_update_files_error(data_manager, handle_exc):
    data_manager.data_client.device_update.list_files.side_effect = AzureError("boom")
    subject.list_update_files(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v",
    )
    handle_exc.assert_called_once()


def test_show_update(data_manager):
    subject.show_update(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v",
    )
    data_manager.data_client.device_update.get_update.assert_called_once_with(
        provider="p", name="n", version="v"
    )


def test_show_update_error(data_manager, handle_exc):
    data_manager.data_client.device_update.get_update.side_effect = AzureError("boom")
    subject.show_update(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v",
    )
    handle_exc.assert_called_once()


def test_show_update_file(data_manager):
    subject.show_update_file(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v", update_file_id="1",
    )
    data_manager.data_client.device_update.get_file.assert_called_once_with(
        name="n", provider="p", version="v", file_id="1"
    )


def test_show_update_file_error(data_manager, handle_exc):
    data_manager.data_client.device_update.get_file.side_effect = AzureError("boom")
    subject.show_update_file(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v", update_file_id="1",
    )
    handle_exc.assert_called_once()


def test_delete_update(data_manager):
    result = subject.delete_update(
        cmd=MagicMock(), name="a", instance_name="i",
        update_name="n", update_provider="p", update_version="v",
    )
    data_manager.data_client.device_update.begin_delete_update.assert_called_once_with(
        name="n", provider="p", version="v"
    )
    assert result is data_manager.data_client.device_update.begin_delete_update.return_value


# ---------------------------------------------------------------------------
# import_update
# ---------------------------------------------------------------------------


@pytest.fixture
def import_cache(mocker):
    cache = MagicMock()
    mocker.patch("azext_iot.deviceupdate.providers.base.MicroObjectCache", return_value=cache)
    mocker.patch("azext_iot.deviceupdate.common.get_cache_entry_name", return_value="entry")
    return cache


def test_import_update_with_size_and_hashes(data_manager, import_cache):
    import_cache.get.return_value = None
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": False}
    poller = subject.import_update(
        cmd=cmd, name="a", instance_name="i", url="http://x/m.json",
        size=10, hashes=["sha256=abc"],
    )
    data_manager.calculate_manifest_metadata.assert_not_called()
    data_manager.data_client.device_update.begin_import_update.assert_called_once()
    assert poller is data_manager.data_client.device_update.begin_import_update.return_value


def test_import_update_calculates_metadata(data_manager, import_cache):
    import_cache.get.return_value = None
    meta = MagicMock()
    meta.hash = "h"
    meta.bytes = 5
    data_manager.calculate_manifest_metadata.return_value = meta
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": False}
    subject.import_update(cmd=cmd, name="a", instance_name="i", url="http://x/m.json")
    data_manager.calculate_manifest_metadata.assert_called_once_with("http://x/m.json")


def test_import_update_defer(data_manager, import_cache):
    import_cache.get.return_value = None
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": True}
    result = subject.import_update(
        cmd=cmd, name="a", instance_name="i", url="http://x/m.json", size=10, hashes=["sha256=abc"],
    )
    assert result is None
    import_cache.set.assert_called_once()


def test_import_update_from_cache(data_manager, import_cache):
    import_cache.get.return_value = [MagicMock()]
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": True}
    # url == cache:// forces defer False and uses cached imports.
    subject.import_update(cmd=cmd, name="a", instance_name="i", url="cache://")
    data_manager.data_client.device_update.begin_import_update.assert_called_once()


def test_import_update_handler_succeeded(data_manager, import_cache):
    import_cache.get.return_value = None
    poller = data_manager.data_client.device_update.begin_import_update.return_value
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": False}
    subject.import_update(
        cmd=cmd, name="a", instance_name="i", url="http://x/m.json", size=1, hashes=["sha256=a"],
    )
    handler = poller.add_done_callback.call_args[0][0]
    lro = MagicMock()
    lro.status.return_value = "Succeeded"
    handler(lro)
    import_cache.remove.assert_called_once()


def test_import_update_handler_failed(data_manager, import_cache):
    import_cache.get.return_value = [MagicMock()]
    poller = data_manager.data_client.device_update.begin_import_update.return_value
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": False}
    subject.import_update(
        cmd=cmd, name="a", instance_name="i", url="http://x/m.json", size=1, hashes=["sha256=a"],
    )
    handler = poller.add_done_callback.call_args[0][0]
    lro = MagicMock()
    lro.status.return_value = "Failed"
    lro._pipeline_response.http_response.text.return_value = "error detail"
    handler(lro)
    import_cache.remove.assert_not_called()


def test_import_update_handler_failed_exception(data_manager, import_cache):
    import_cache.get.return_value = None
    poller = data_manager.data_client.device_update.begin_import_update.return_value
    cmd = MagicMock()
    cmd.cli_ctx.data = {"_cache": False}
    subject.import_update(
        cmd=cmd, name="a", instance_name="i", url="http://x/m.json", size=1, hashes=["sha256=a"],
    )
    handler = poller.add_done_callback.call_args[0][0]
    lro = MagicMock()
    lro.status.return_value = "Failed"
    lro._pipeline_response.http_response.text.side_effect = ValueError("nope")
    # Should swallow the exception.
    handler(lro)


# ---------------------------------------------------------------------------
# calculate_hash
# ---------------------------------------------------------------------------


def test_calculate_hash(tmp_path):
    f = tmp_path / "sample.bin"
    f.write_bytes(b"hello world")
    result = subject.calculate_hash(file_paths=[str(f)])
    assert len(result) == 1
    assert result[0]["bytes"] == 11
    assert result[0]["hashAlgorithm"] == "sha256"
    assert result[0]["uri"].startswith("file://")
    assert result[0]["hash"]


# ---------------------------------------------------------------------------
# manifest_init_v5
# ---------------------------------------------------------------------------


def _cmd_with_safe_params(safe_params):
    cmd = MagicMock()
    cmd.cli_ctx.data = {"safe_params": safe_params}
    return cmd


def test_manifest_init_reference_step():
    cmd = _cmd_with_safe_params(["--step"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso", "deviceModel=Vacuum"]],
        steps=[["updateId.provider=ref", "updateId.name=child", "updateId.version=2.0"]],
        no_validation=True,
    )
    step = payload["instructions"]["steps"][0]
    assert step["type"] == "reference"
    assert step["updateId"] == {"provider": "ref", "name": "child", "version": "2.0"}


def test_manifest_init_inline_explicit_files():
    cmd = _cmd_with_safe_params(["--step"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=microsoft/script:1", "files=image", "description=mystep"]],
        no_validation=True,
    )
    step = payload["instructions"]["steps"][0]
    assert step["type"] == "inline"
    assert step["files"] == ["image"]
    assert step["description"] == "mystep"


def test_manifest_init_inline_derived_files(tmp_path):
    payload_file = tmp_path / "m.json"
    payload_file.write_text("{}")
    cmd = _cmd_with_safe_params(["--step", "--file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=custom/handler:1"]],
        files=[[f"path={payload_file}"]],
        no_validation=True,
    )
    step = payload["instructions"]["steps"][0]
    assert step["files"] == ["m.json"]


def test_manifest_init_handler_requires_criteria(tmp_path):
    payload_file = tmp_path / "m.json"
    payload_file.write_text("{}")
    cmd = _cmd_with_safe_params(["--step", "--file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=microsoft/apt:1"]],
        files=[[f"path={payload_file}"]],
    )
    step = payload["instructions"]["steps"][0]
    assert step["handlerProperties"]["installedCriteria"] == "1.0"


def test_manifest_init_skips_empty_entries(tmp_path):
    main_file = tmp_path / "main.bin"
    main_file.write_bytes(b"main")
    cmd = _cmd_with_safe_params(["--step", "--file", "--file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=custom/handler:1"], [""]],
        files=[[f"path={main_file}"], [""]],
        no_validation=True,
    )
    # Empty step and empty file entries are skipped (derivation loop skips the empty file too).
    assert len(payload["instructions"]["steps"]) == 1
    assert len(payload["files"]) == 1


def test_manifest_init_empty_safe_params_reference_step():
    cmd = _cmd_with_safe_params([])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["updateId.provider=ref", "updateId.name=child", "updateId.version=2.0"]],
        no_validation=True,
    )
    assert payload["instructions"]["steps"][0]["type"] == "reference"


def test_manifest_init_multiple_steps():
    cmd = _cmd_with_safe_params(["--step", "--step"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[
            ["updateId.provider=ref", "updateId.name=a", "updateId.version=1.0"],
            ["updateId.provider=ref", "updateId.name=b", "updateId.version=1.0"],
        ],
        no_validation=True,
    )
    assert len(payload["instructions"]["steps"]) == 2


def test_manifest_init_skips_empty_related_file(tmp_path):
    main_file = tmp_path / "main.bin"
    main_file.write_bytes(b"main")
    cmd = _cmd_with_safe_params(["--step", "--file", "--related-file", "--related-file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=microsoft/script:1", "files=main.bin"]],
        files=[[f"path={main_file}"]],
        related_files=[[f"path={main_file}"], [""]],
        no_validation=True,
    )
    assert payload["files"][0]["relatedFiles"]


def test_manifest_init_step_properties(tmp_path):
    payload_file = tmp_path / "m.json"
    payload_file.write_text("{}")
    cmd = _cmd_with_safe_params(["--step", "--file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=microsoft/apt:1", 'properties={"installedCriteria":"2.0"}']],
        files=[[f"path={payload_file}"]],
        no_validation=True,
    )
    step = payload["instructions"]["steps"][0]
    assert step["handlerProperties"]["installedCriteria"] == "2.0"


def test_manifest_init_invalid_step():
    cmd = _cmd_with_safe_params(["--step"])
    with pytest.raises(ArgumentUsageError):
        subject.manifest_init_v5(
            cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
            compatibility=[["deviceManufacturer=Contoso"]],
            steps=[["unknown=foo"]],
            no_validation=True,
        )


def test_manifest_init_file_missing_path():
    cmd = _cmd_with_safe_params(["--step", "--file"])
    with pytest.raises(ArgumentUsageError):
        subject.manifest_init_v5(
            cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
            compatibility=[["deviceManufacturer=Contoso"]],
            steps=[["handler=microsoft/script:1", "files=image"]],
            files=[["downloadHandler=foo"]],
            no_validation=True,
        )


def test_manifest_init_with_files_and_related(tmp_path):
    main_file = tmp_path / "main.bin"
    main_file.write_bytes(b"main")
    related = tmp_path / "related.bin"
    related.write_bytes(b"related")
    cmd = _cmd_with_safe_params(["--step", "--file", "--related-file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"]],
        steps=[["handler=microsoft/script:1", "files=main.bin"]],
        files=[[f"path={main_file}", 'properties={"a":"b"}', "downloadHandler=microsoft/delta:1"]],
        related_files=[[f"path={related}", 'properties={"c":"d"}']],
        no_validation=True,
    )
    pfile = payload["files"][0]
    assert pfile["filename"] == "main.bin"
    assert pfile["properties"] == {"a": "b"}
    assert pfile["downloadHandler"] == {"id": "microsoft/delta:1"}
    assert pfile["relatedFiles"][0]["filename"] == "related.bin"


def test_manifest_init_related_file_missing_path(tmp_path):
    main_file = tmp_path / "main.bin"
    main_file.write_bytes(b"main")
    cmd = _cmd_with_safe_params(["--step", "--file", "--related-file"])
    with pytest.raises(ArgumentUsageError):
        subject.manifest_init_v5(
            cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
            compatibility=[["deviceManufacturer=Contoso"]],
            steps=[["handler=microsoft/script:1", "files=main.bin"]],
            files=[[f"path={main_file}"]],
            related_files=[["properties={}"]],
            no_validation=True,
        )


def test_manifest_init_deployable_and_description():
    cmd = _cmd_with_safe_params(["--step"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
        compatibility=[["deviceManufacturer=Contoso"], [""]],
        steps=[["updateId.provider=ref", "updateId.name=child", "updateId.version=2.0"]],
        description="a description",
        deployable=False,
        no_validation=True,
    )
    assert payload["isDeployable"] is False
    assert payload["description"] == "a description"
    # Empty compatibility entries are skipped.
    assert len(payload["compatibility"]) == 1


def test_manifest_init_validation_success(tmp_path):
    manifest_file = tmp_path / "libcurl.json"
    manifest_file.write_text("{}")
    cmd = _cmd_with_safe_params(["--step", "--file"])
    payload = subject.manifest_init_v5(
        cmd=cmd, update_name="simpleupdate", update_provider="digimaun", update_version="1.0.0",
        compatibility=[["deviceManufacturer=Contoso", "deviceModel=Vacuum"]],
        steps=[["handler=microsoft/apt:1", 'properties={"installedCriteria":"2.0"}']],
        files=[[f"path={manifest_file}"]],
    )
    assert payload["manifestVersion"] == "5.0"
    assert payload["files"][0]["filename"] == "libcurl.json"


def test_manifest_init_validation_failure():
    cmd = _cmd_with_safe_params(["--step"])
    with pytest.raises(ValidationError):
        subject.manifest_init_v5(
            cmd=cmd, update_name="n", update_provider="p", update_version="1.0",
            compatibility=[],
            steps=[],
        )


# ---------------------------------------------------------------------------
# stage_update
# ---------------------------------------------------------------------------


@pytest.fixture
def stage_mocks(mocker, tmp_path):
    cli = MagicMock()
    cli.invoke.return_value.as_json.return_value = {"id": "sub-from-account"}
    mocker.patch("azext_iot.common.embedded_cli.EmbeddedCLI", return_value=cli)

    storage_mgr = MagicMock()
    blob_service_client = MagicMock()
    blob_service_client.credential.account_name = "stg"
    blob_service_client.credential.account_key = "key"
    blob_service_client.get_container_client.return_value.upload_blob.return_value.url = "https://blob/x"
    storage_mgr.get_sas_blob_service_client.return_value = blob_service_client
    mocker.patch(
        "azext_iot.deviceupdate.providers.storage.StorageAccountManager", return_value=storage_mgr
    )
    mocker.patch("azure.storage.blob.generate_account_sas", return_value="sas-token")

    dm = MagicMock()
    dm.container.resource_group = "rg"
    mocker.patch(f"{MOD}.DeviceUpdateDataManager", return_value=dm)

    cache = MagicMock()
    mocker.patch("azext_iot.deviceupdate.providers.base.MicroObjectCache", return_value=cache)
    mocker.patch("azext_iot.deviceupdate.common.get_cache_entry_name", return_value="entry")

    manifest = {
        "updateId": {"provider": "p", "name": "n", "version": "1.0"},
        "files": [
            {"filename": "asset.bin", "relatedFiles": [{"filename": "related.bin"}]},
            {"filename": "other.bin", "relatedFiles": [{"filename": "related.bin"}]},
            {"filename": "asset.bin"},
        ],
    }
    manifest_path = tmp_path / "import.json"
    manifest_path.write_text(json.dumps(manifest))
    (tmp_path / "asset.bin").write_bytes(b"data")
    (tmp_path / "other.bin").write_bytes(b"data")
    (tmp_path / "related.bin").write_bytes(b"data")
    mocker.patch(
        "azext_iot.common.utility.process_json_arg", return_value=manifest
    )
    return {
        "cli": cli,
        "blob_service_client": blob_service_client,
        "manifest_path": str(manifest_path),
    }


def test_stage_update_returns_import_command(stage_mocks):
    result = subject.stage_update(
        cmd=MagicMock(), name="acct", instance_name="inst",
        update_manifest_paths=[stage_mocks["manifest_path"]],
        storage_account_name="stg", storage_container_name="cont",
    )
    assert "importCommand" in result
    assert result["importCommand"].startswith("az iot du update import")


def test_stage_update_then_import(stage_mocks):
    result = subject.stage_update(
        cmd=MagicMock(), name="acct", instance_name="inst",
        update_manifest_paths=[stage_mocks["manifest_path"]],
        storage_account_name="stg", storage_container_name="cont",
        then_import=True,
    )
    assert result is None


def test_stage_update_container_exists(stage_mocks):
    from azure.core.exceptions import ResourceExistsError

    stage_mocks["blob_service_client"].create_container.side_effect = ResourceExistsError("exists")
    result = subject.stage_update(
        cmd=MagicMock(), name="acct", instance_name="inst",
        update_manifest_paths=[stage_mocks["manifest_path"]],
        storage_account_name="stg", storage_container_name="cont",
        friendly_name="friendly",
    )
    assert "importCommand" in result
