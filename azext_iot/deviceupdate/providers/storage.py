# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from azure.identity import AzureCliCredential
from azure.mgmt.storage import StorageManagementClient
from azure.storage.blob import BlobServiceClient
from msrestazure.tools import parse_resource_id
from azure.cli.core.azclierror import ResourceNotFoundError
from typing import TypeVar


StorageAccount = TypeVar("StorageAccount")


class StorageAccountManager(object):
    def __init__(self, subscription_id: str):
        self.subscription_id = subscription_id
        self.client = StorageManagementClient(
            credential=AzureCliCredential(), subscription_id=self.subscription_id)

    def find_storage_account(self, account_name: str) -> StorageAccount:
        list_iterator = self.client.storage_accounts.list()

        for acc in list_iterator:
            if acc.name == account_name:
                return acc

        raise ResourceNotFoundError(
            f"Unable to find storage account: {account_name} in subscription: {self.subscription_id}.")

    def get_sas_blob_service_client(self, account_name: str) -> BlobServiceClient:
        account = self.find_storage_account(account_name)
        storage_rg = parse_resource_id(account.id)["resource_group"]
        storage_keys = self.client.storage_accounts.list_keys(
            resource_group_name=storage_rg, account_name=account.name)
        # azure-mgmt-storage returns a model object (older SDK) or dict (newer SDK/Python 3.13+)
        key_list = storage_keys['keys'] if isinstance(storage_keys, dict) else storage_keys.keys
        first_key = key_list[0]
        credential = first_key['value'] if isinstance(first_key, dict) else first_key.value
        return BlobServiceClient(
            account_url=account.primary_endpoints.blob, credential=credential)
