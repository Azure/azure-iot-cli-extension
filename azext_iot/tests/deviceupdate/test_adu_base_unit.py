# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.providers.base
"""

import os
import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azure.cli.core.azclierror import (
    CLIInternalError,
    InvalidArgumentValueError,
    ResourceNotFoundError,
)
from azext_iot.deviceupdate.providers import base as subject
from azext_iot.deviceupdate.providers.base import (
    parse_account_rg,
    DeviceUpdateClientHandler,
    DeviceUpdateAccountManager,
    DeviceUpdateInstanceManager,
    DeviceUpdateDataManager,
    MicroObjectCache,
)
from azext_iot.deviceupdate.common import SYSTEM_IDENTITY_ARG


def test_parse_account_rg():
    assert parse_account_rg("/subscriptions/s/resourceGroups/myrg/providers/x/accounts/a") == "myrg"


# ---- DeviceUpdateClientHandler ----


def test_client_handler_get_mgmt_client(mocker):
    get_client = mocker.patch.object(subject, "get_mgmt_service_client")
    handler = DeviceUpdateClientHandler(cmd=MagicMock())
    result = handler.get_mgmt_client()
    get_client.assert_called_once()
    assert result is get_client.return_value


def test_client_handler_get_data_client(mocker):
    patched_client = mocker.patch.object(subject, "DeviceUpdateClient")
    profile_cls = mocker.patch("azure.cli.core._profile.Profile")
    profile_cls.return_value.get_login_credentials.return_value = (MagicMock(), "sub", "tenant")
    mocker.patch("azure.cli.core.commands.client_factory.prepare_client_kwargs_track2", return_value={})
    handler = DeviceUpdateClientHandler(cmd=MagicMock())
    client = handler.get_data_client(endpoint="https://host", instance_id="inst")
    assert client is patched_client.return_value


def test_client_handler_add_useragents_handles_exception():
    handler = DeviceUpdateClientHandler(cmd=MagicMock())
    client = MagicMock()
    client._config.user_agent_policy.add_user_agent.side_effect = Exception("nope")
    # Should swallow the exception and return the client.
    assert handler._add_useragents(client) is client


# ---- DeviceUpdateAccountManager.find_account ----


def _account_manager():
    mgr = DeviceUpdateAccountManager.__new__(DeviceUpdateAccountManager)
    mgr.mgmt_client = MagicMock()
    mgr.cli = MagicMock()
    return mgr


def test_find_account_with_rg():
    mgr = _account_manager()
    account = MagicMock()
    account.id = "/subscriptions/s/resourceGroups/myrg/providers/x/accounts/a"
    mgr.mgmt_client.accounts.get.return_value = account
    container = mgr.find_account(target_name="a", target_rg="myrg")
    assert container.account is account
    assert container.resource_group == "myrg"


def test_find_account_with_rg_service_error(mocker):
    mgr = _account_manager()
    mgr.mgmt_client.accounts.get.side_effect = AzureError("boom")
    handler = mocker.patch.object(subject, "handle_service_exception", side_effect=RuntimeError("handled"))
    with pytest.raises(RuntimeError):
        mgr.find_account(target_name="a", target_rg="myrg")
    handler.assert_called_once()


def test_find_account_by_subscription_match():
    mgr = _account_manager()
    account = MagicMock()
    account.name = "a"
    account.id = "/subscriptions/s/resourceGroups/myrg/providers/x/accounts/a"
    mgr.mgmt_client.accounts.list_by_subscription.return_value = [account]
    container = mgr.find_account(target_name="a")
    assert container.account is account


def test_find_account_by_subscription_no_match_raises():
    mgr = _account_manager()
    mgr.mgmt_client.accounts.list_by_subscription.return_value = []
    with pytest.raises(ResourceNotFoundError):
        mgr.find_account(target_name="a")


def test_find_account_by_subscription_service_error(mocker):
    mgr = _account_manager()
    mgr.mgmt_client.accounts.list_by_subscription.side_effect = AzureError("boom")
    handler = mocker.patch.object(subject, "handle_service_exception", side_effect=RuntimeError("handled"))
    with pytest.raises(RuntimeError):
        mgr.find_account(target_name="a")
    handler.assert_called_once()


# ---- assemble_account_auth (classmethod) ----


def test_assemble_account_auth_none():
    assert DeviceUpdateAccountManager.assemble_account_auth(None) is None


def test_assemble_account_auth_single_system():
    result = DeviceUpdateAccountManager.assemble_account_auth([SYSTEM_IDENTITY_ARG])
    assert "SystemAssigned" in result.type


def test_assemble_account_auth_single_user():
    result = DeviceUpdateAccountManager.assemble_account_auth(["/user/identity"])
    assert "UserAssigned" in result.type
    assert "/user/identity" in result.user_assigned_identities


def test_assemble_account_auth_multiple_with_system():
    result = DeviceUpdateAccountManager.assemble_account_auth([SYSTEM_IDENTITY_ARG, "/user/identity"])
    assert "SystemAssigned" in result.type and "UserAssigned" in result.type
    assert "/user/identity" in result.user_assigned_identities


def test_assemble_account_auth_multiple_users():
    result = DeviceUpdateAccountManager.assemble_account_auth(["/user/a", "/user/b"])
    assert "UserAssigned" in result.type
    assert set(result.user_assigned_identities) == {"/user/a", "/user/b"}


# ---- assign_msi_scope / get_rg_location ----


def test_assign_msi_scope_success():
    mgr = _account_manager()
    op = mgr.cli.invoke.return_value
    op.success.return_value = True
    op.as_json.return_value = {"id": "assignment"}
    assert mgr.assign_msi_scope(principal_id="pid", scope="/scope") == {"id": "assignment"}


def test_assign_msi_scope_failure():
    mgr = _account_manager()
    mgr.cli.invoke.return_value.success.return_value = False
    with pytest.raises(CLIInternalError):
        mgr.assign_msi_scope(principal_id="pid", scope="/scope")


def test_get_rg_location():
    mgr = _account_manager()
    mgr.cli.invoke.return_value.as_json.return_value = {"location": "westus"}
    assert mgr.get_rg_location(resource_group_name="rg") == "westus"


# ---- DeviceUpdateInstanceManager ----


def _instance_manager():
    mgr = DeviceUpdateInstanceManager.__new__(DeviceUpdateInstanceManager)
    mgr.cli = MagicMock()
    return mgr


def test_assemble_iothub_resources():
    mgr = _instance_manager()
    result = mgr.assemble_iothub_resources(["/hub/1", "/hub/2"])
    assert len(result) == 2
    assert result[0].resource_id == "/hub/1"


def test_assemble_diagnostic_storage_reorders_endpoint_suffix():
    mgr = _instance_manager()
    op = mgr.cli.invoke.return_value
    op.success.return_value = True
    op.as_json.return_value = {
        "connectionString": "AccountName=x;EndpointSuffix=core.windows.net;AccountKey=y"
    }
    result = mgr.assemble_diagnostic_storage("/storage/1")
    assert result.connection_string.endswith("EndpointSuffix=core.windows.net")
    assert result.resource_id == "/storage/1"


def test_assemble_diagnostic_storage_default_suffix():
    mgr = _instance_manager()
    op = mgr.cli.invoke.return_value
    op.success.return_value = True
    op.as_json.return_value = {"connectionString": "AccountName=x;AccountKey=y"}
    result = mgr.assemble_diagnostic_storage("/storage/1")
    assert result.connection_string.endswith("EndpointSuffix=core.windows.net")


def test_assemble_diagnostic_storage_failure():
    mgr = _instance_manager()
    mgr.cli.invoke.return_value.success.return_value = False
    with pytest.raises(CLIInternalError):
        mgr.assemble_diagnostic_storage("/storage/1")


# ---- DeviceUpdateDataManager helpers ----


def _data_manager():
    return DeviceUpdateDataManager.__new__(DeviceUpdateDataManager)


def test_calculate_hash_from_bytes():
    result = DeviceUpdateDataManager.calculate_hash_from_bytes(b"hello")
    assert isinstance(result, str) and result


def test_calculate_file_metadata(tmp_path):
    f = tmp_path / "file.bin"
    f.write_bytes(b"hello world")
    meta = DeviceUpdateDataManager.calculate_file_metadata(str(f))
    assert meta.bytes == 11
    assert meta.name == "file.bin"
    assert meta.hash


def test_calculate_manifest_metadata(mocker):
    mgr = _data_manager()
    fake_response = MagicMock()
    fake_response.read.return_value = b"manifest-bytes"
    cm = MagicMock()
    cm.__enter__.return_value = fake_response
    mocker.patch("urllib.request.urlopen", return_value=cm)
    meta = mgr.calculate_manifest_metadata("https://host/manifest")
    assert meta.bytes == len(b"manifest-bytes")
    assert meta.hash


def test_assemble_files_valid():
    mgr = _data_manager()
    result = mgr.assemble_files([["filename=f.bin", "url=https://host/f"]])
    assert result[0].filename == "f.bin"
    assert result[0].url == "https://host/f"


def test_assemble_files_unknown_key_warns():
    mgr = _data_manager()
    result = mgr.assemble_files([["filename=f.bin", "url=https://host/f", "junk=1"]])
    assert result[0].filename == "f.bin"


def test_assemble_files_missing_required_raises():
    mgr = _data_manager()
    with pytest.raises(InvalidArgumentValueError):
        mgr.assemble_files([["filename=f.bin"]])


def test_assemble_files_none():
    mgr = _data_manager()
    assert mgr.assemble_files(None) is None


def test_assemble_agent_ids_device_only():
    mgr = _data_manager()
    result = mgr.assemble_agent_ids([["deviceId=d1"]])
    assert result[0].device_id == "d1"


def test_assemble_agent_ids_device_and_module():
    mgr = _data_manager()
    result = mgr.assemble_agent_ids([["deviceId=d1", "moduleId=m1"]])
    assert result[0].device_id == "d1"
    assert result[0].module_id == "m1"


def test_assemble_agent_ids_unknown_key_warns():
    mgr = _data_manager()
    result = mgr.assemble_agent_ids([["deviceId=d1", "junk=1"]])
    assert result[0].device_id == "d1"


def test_assemble_agent_ids_missing_device_raises():
    mgr = _data_manager()
    with pytest.raises(InvalidArgumentValueError):
        mgr.assemble_agent_ids([["moduleId=m1"]])


def test_assemble_agent_ids_none():
    mgr = _data_manager()
    assert mgr.assemble_agent_ids(None) is None


# ---- MicroObjectCache ----


def _cache():
    cache = MicroObjectCache.__new__(MicroObjectCache)
    cache.cmd = MagicMock()
    cache.subscription_id = "sub"
    cache.cloud_name = "AzureCloud"
    cache._serializer = MagicMock()
    cache._deserializer = MagicMock()
    return cache


def test_cache_get_config_dir_env(monkeypatch):
    monkeypatch.setenv("AZURE_CONFIG_DIR", "/tmp/custom-config")
    assert MicroObjectCache.get_config_dir() == "/tmp/custom-config"


def test_cache_get_config_dir_default(monkeypatch):
    monkeypatch.delenv("AZURE_CONFIG_DIR", raising=False)
    assert MicroObjectCache.get_config_dir().endswith(os.path.join("", ".azure")) or ".azure" in MicroObjectCache.get_config_dir()


def test_cache_get_file_path():
    cache = _cache()
    directory, filename = cache._get_file_path("res", "rg", "DeviceUpdate")
    assert filename == "res.json"
    assert "DeviceUpdate" in directory


def test_cache_save_load_remove(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    cache = _cache()
    cache._serializer.body.return_value = {"k": "v"}
    cache._deserializer.deserialize_data.return_value = {"k": "v"}

    cache.set(resource_name="res", resource_group="rg", resource_type="DeviceUpdate",
              payload=MagicMock(), serialization_model="[Model]")
    loaded = cache.get(resource_name="res", resource_group="rg", resource_type="DeviceUpdate",
                       serialization_model="[Model]")
    assert loaded == {"k": "v"}

    cache.remove(resource_name="res", resource_group="rg", resource_type="DeviceUpdate")
    # Subsequent load returns None when file is gone.
    assert cache.get(resource_name="res", resource_group="rg", resource_type="DeviceUpdate",
                     serialization_model="[Model]") is None


def test_cache_load_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    cache = _cache()
    assert cache.get(resource_name="missing", resource_group="rg", resource_type="DeviceUpdate",
                     serialization_model="[Model]") is None


def test_cache_remove_missing_is_safe(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    cache = _cache()
    # Should not raise even when nothing exists.
    cache.remove(resource_name="missing", resource_group="rg", resource_type="DeviceUpdate")


def test_cache_remove_swallows_oserror(monkeypatch, tmp_path, mocker):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    cache = _cache()
    cache._serializer.body.return_value = {"k": "v"}
    cache.set(resource_name="res", resource_group="rg", resource_type="DeviceUpdate",
              payload=MagicMock(), serialization_model="[Model]")
    mocker.patch("os.remove", side_effect=OSError("locked"))
    # Should swallow the OSError.
    cache.remove(resource_name="res", resource_group="rg", resource_type="DeviceUpdate")


# ---- __init__ coverage for the manager classes ----


def test_account_manager_init(mocker):
    mocker.patch.object(subject, "get_mgmt_service_client")
    mocker.patch.object(subject, "EmbeddedCLI")
    cmd = MagicMock()
    mgr = DeviceUpdateAccountManager(cmd=cmd)
    assert mgr.mgmt_client is not None
    assert mgr.cli is not None


def test_instance_manager_init(mocker):
    mocker.patch.object(subject, "get_mgmt_service_client")
    mocker.patch.object(subject, "EmbeddedCLI")
    mgr = DeviceUpdateInstanceManager(cmd=MagicMock())
    assert mgr.mgmt_client is not None


def test_data_manager_init(mocker):
    mocker.patch.object(subject, "get_mgmt_service_client")
    mocker.patch.object(subject, "EmbeddedCLI")
    find = mocker.patch.object(DeviceUpdateAccountManager, "find_account")
    get_data = mocker.patch.object(subject.DeviceUpdateClientHandler, "get_data_client")
    mgr = DeviceUpdateDataManager(cmd=MagicMock(), account_name="acct", instance_name="inst")
    assert mgr.container is find.return_value
    assert mgr.data_client is get_data.return_value


def test_micro_object_cache_init(mocker):
    from azext_iot.deviceupdate.providers.base import DeviceUpdateDataModels

    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value="sub")
    mocker.patch("azext_iot.sdk.deviceupdate.dataplane._serialization.Serializer")
    mocker.patch("azext_iot.sdk.deviceupdate.dataplane._serialization.Deserializer")
    cmd = MagicMock()
    cmd.cli_ctx.cloud.name = "AzureCloud"
    cache = MicroObjectCache(cmd, DeviceUpdateDataModels)
    assert cache.subscription_id == "sub"
    assert cache.cloud_name == "AzureCloud"


def test_micro_object_cache_init_no_subscription(mocker):
    from azext_iot.deviceupdate.providers.base import DeviceUpdateDataModels

    mocker.patch("azure.cli.core.commands.client_factory.get_subscription_id", return_value=None)
    mocker.patch("azext_iot.sdk.deviceupdate.dataplane._serialization.Serializer")
    mocker.patch("azext_iot.sdk.deviceupdate.dataplane._serialization.Deserializer")
    with pytest.raises(RuntimeError):
        MicroObjectCache(MagicMock(), DeviceUpdateDataModels)
