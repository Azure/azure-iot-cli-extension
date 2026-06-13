# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import MagicMock
from azure.cli.core.azclierror import ResourceNotFoundError

import azext_iot.deviceupdate.providers.storage as subject
from azext_iot.deviceupdate.providers.storage import StorageAccountManager


def test_init(mocker):
    mocker.patch.object(subject, "AzureCliCredential")
    smc = mocker.patch.object(subject, "StorageManagementClient")
    mgr = StorageAccountManager(subscription_id="sub")
    assert mgr.subscription_id == "sub"
    assert mgr.client is smc.return_value


def _mgr():
    mgr = StorageAccountManager.__new__(StorageAccountManager)
    mgr.subscription_id = "sub"
    mgr.client = MagicMock()
    return mgr


def test_find_storage_account_match():
    mgr = _mgr()
    acc = MagicMock()
    acc.name = "target"
    mgr.client.storage_accounts.list.return_value = [acc]
    assert mgr.find_storage_account("target") is acc


def test_find_storage_account_not_found():
    mgr = _mgr()
    mgr.client.storage_accounts.list.return_value = []
    with pytest.raises(ResourceNotFoundError):
        mgr.find_storage_account("missing")


def test_get_sas_blob_service_client(mocker):
    mgr = _mgr()
    acc = MagicMock()
    acc.name = "target"
    acc.id = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/target"
    acc.primary_endpoints.blob = "https://target.blob.core.windows.net/"
    mgr.client.storage_accounts.list.return_value = [acc]
    mgr.client.storage_accounts.list_keys.return_value.keys = [MagicMock(value="key123")]
    mocker.patch.object(subject, "parse_resource_id", return_value={"resource_group": "rg"})
    bsc = mocker.patch.object(subject, "BlobServiceClient")
    result = mgr.get_sas_blob_service_client("target")
    assert result is bsc.return_value
    bsc.assert_called_once_with(
        account_url="https://target.blob.core.windows.net/", credential="key123"
    )
