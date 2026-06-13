# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.commands_account
"""

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azext_iot.deviceupdate import commands_account as subject

ACCOUNT_PATH = "azext_iot.deviceupdate.commands_account.DeviceUpdateAccountManager"
HANDLE_PATH = "azext_iot.deviceupdate.commands_account.handle_service_exception"


@pytest.fixture
def account_manager(mocker):
    manager = MagicMock()
    patched = mocker.patch(ACCOUNT_PATH)
    patched.return_value = manager
    # assemble_account_auth is referenced on the instance.
    manager.assemble_account_auth.return_value = None
    return manager


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch(HANDLE_PATH)


def _cmd():
    cmd = MagicMock()
    return cmd


def test_create_account_with_location(account_manager):
    account_manager.assemble_account_auth.return_value = "identity"
    poller = account_manager.mgmt_client.accounts.begin_create.return_value

    result = subject.create_account(
        cmd=_cmd(),
        name="acct",
        resource_group_name="rg",
        location="westus",
        tags={"a": "b"},
        assign_identity=["[system]"],
        scopes=None,
    )

    account_manager.get_rg_location.assert_not_called()
    account_manager.mgmt_client.accounts.begin_create.assert_called_once()
    poller.add_done_callback.assert_called_once()
    assert result is poller


def test_create_account_without_location_resolves_rg_location(account_manager):
    account_manager.get_rg_location.return_value = "eastus"

    subject.create_account(cmd=_cmd(), name="acct", resource_group_name="rg")

    account_manager.get_rg_location.assert_called_once_with(resource_group_name="rg")


def test_create_account_rbac_handler_assigns_scope(account_manager):
    subject.create_account(
        cmd=_cmd(),
        name="acct",
        resource_group_name="rg",
        location="westus",
        scopes=["/scope/1"],
        role="Owner",
    )
    handler = account_manager.mgmt_client.accounts.begin_create.return_value.add_done_callback.call_args[0][0]

    lro = MagicMock()
    lro.resource.return_value.as_dict.return_value = {
        "identity": {"type": "SystemAssigned", "principal_id": "pid"}
    }
    handler(lro)
    account_manager.assign_msi_scope.assert_called_once_with(scope="/scope/1", principal_id="pid", role="Owner")


def test_create_account_rbac_handler_no_scopes_noop(account_manager):
    subject.create_account(cmd=_cmd(), name="acct", resource_group_name="rg", location="westus", scopes=None)
    handler = account_manager.mgmt_client.accounts.begin_create.return_value.add_done_callback.call_args[0][0]
    handler(MagicMock())
    account_manager.assign_msi_scope.assert_not_called()


def test_create_account_rbac_handler_no_identity(account_manager):
    subject.create_account(cmd=_cmd(), name="acct", resource_group_name="rg", location="westus", scopes=["/s"])
    handler = account_manager.mgmt_client.accounts.begin_create.return_value.add_done_callback.call_args[0][0]
    lro = MagicMock()
    lro.resource.return_value.as_dict.return_value = {"identity": {}}
    handler(lro)
    account_manager.assign_msi_scope.assert_not_called()


def test_create_account_service_error(account_manager, handle_exc):
    account_manager.mgmt_client.accounts.begin_create.side_effect = AzureError("boom")
    subject.create_account(cmd=_cmd(), name="acct", resource_group_name="rg", location="westus")
    handle_exc.assert_called_once()


def test_update_account(account_manager):
    params = MagicMock()
    params.id = "/subscriptions/s/resourceGroups/myrg/providers/x/accounts/acct"
    params.name = "acct"
    subject.update_account(cmd=_cmd(), parameters=params)
    account_manager.mgmt_client.accounts.begin_create.assert_called_once()


def test_update_account_service_error(account_manager, handle_exc):
    account_manager.mgmt_client.accounts.begin_create.side_effect = AzureError("boom")
    params = MagicMock()
    params.id = "/subscriptions/s/resourceGroups/myrg/providers/x/accounts/acct"
    params.name = "acct"
    subject.update_account(cmd=_cmd(), parameters=params)
    handle_exc.assert_called_once()


def test_list_accounts_by_rg(account_manager):
    subject.list_accounts(cmd=_cmd(), resource_group_name="rg")
    account_manager.mgmt_client.accounts.list_by_resource_group.assert_called_once_with(resource_group_name="rg")


def test_list_accounts_by_subscription(account_manager):
    subject.list_accounts(cmd=_cmd())
    account_manager.mgmt_client.accounts.list_by_subscription.assert_called_once()


def test_list_accounts_service_error(account_manager, handle_exc):
    account_manager.mgmt_client.accounts.list_by_subscription.side_effect = AzureError("boom")
    subject.list_accounts(cmd=_cmd())
    handle_exc.assert_called_once()


def test_show_account(account_manager):
    container = account_manager.find_account.return_value
    result = subject.show_account(cmd=_cmd(), name="acct", resource_group_name="rg")
    account_manager.find_account.assert_called_once_with(target_name="acct", target_rg="rg")
    assert result is container.account


def test_delete_account(account_manager):
    account_manager.find_account.return_value.resource_group = "rg"
    subject.delete_account(cmd=_cmd(), name="acct", resource_group_name="rg")
    account_manager.mgmt_client.accounts.begin_delete.assert_called_once_with(resource_group_name="rg", account_name="acct")


def test_delete_account_service_error(account_manager, handle_exc):
    account_manager.find_account.return_value.resource_group = "rg"
    account_manager.mgmt_client.accounts.begin_delete.side_effect = AzureError("boom")
    subject.delete_account(cmd=_cmd(), name="acct", resource_group_name="rg")
    handle_exc.assert_called_once()


def test_wait_on_account(account_manager):
    result = subject.wait_on_account(cmd=_cmd(), name="acct", resource_group_name="rg")
    assert result is account_manager.find_account.return_value.account


def test_show_account_private_connection(account_manager):
    account_manager.find_account.return_value.resource_group = "rg"
    subject.show_account_private_connection(cmd=_cmd(), name="acct", conn_name="conn", resource_group_name="rg")
    account_manager.mgmt_client.private_endpoint_connections.get.assert_called_once()


def test_show_account_private_connection_error(account_manager, handle_exc):
    account_manager.mgmt_client.private_endpoint_connections.get.side_effect = AzureError("boom")
    subject.show_account_private_connection(cmd=_cmd(), name="acct", conn_name="conn")
    handle_exc.assert_called_once()


def test_list_account_private_connections(account_manager):
    subject.list_account_private_connections(cmd=_cmd(), name="acct")
    account_manager.mgmt_client.private_endpoint_connections.list_by_account.assert_called_once()


def test_list_account_private_connections_error(account_manager, handle_exc):
    account_manager.mgmt_client.private_endpoint_connections.list_by_account.side_effect = AzureError("boom")
    subject.list_account_private_connections(cmd=_cmd(), name="acct")
    handle_exc.assert_called_once()


def test_set_account_private_connection(account_manager):
    subject.set_account_private_connection(
        cmd=_cmd(), name="acct", conn_name="conn", status="Approved", description="ok"
    )
    account_manager.mgmt_client.private_endpoint_connections.begin_create_or_update.assert_called_once()


def test_set_account_private_connection_error(account_manager, handle_exc):
    account_manager.mgmt_client.private_endpoint_connections.begin_create_or_update.side_effect = AzureError("boom")
    subject.set_account_private_connection(cmd=_cmd(), name="acct", conn_name="conn", status="Rejected")
    handle_exc.assert_called_once()


def test_delete_account_private_connection(account_manager):
    subject.delete_account_private_connection(cmd=_cmd(), name="acct", conn_name="conn")
    account_manager.mgmt_client.private_endpoint_connections.begin_delete.assert_called_once()


def test_delete_account_private_connection_error(account_manager, handle_exc):
    account_manager.mgmt_client.private_endpoint_connections.begin_delete.side_effect = AzureError("boom")
    subject.delete_account_private_connection(cmd=_cmd(), name="acct", conn_name="conn")
    handle_exc.assert_called_once()


def test_list_account_private_links(account_manager):
    subject.list_account_private_links(cmd=_cmd(), name="acct")
    account_manager.mgmt_client.private_link_resources.list_by_account.assert_called_once()


def test_list_account_private_links_error(account_manager, handle_exc):
    account_manager.mgmt_client.private_link_resources.list_by_account.side_effect = AzureError("boom")
    subject.list_account_private_links(cmd=_cmd(), name="acct")
    handle_exc.assert_called_once()
