# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.commands_instance
"""

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azext_iot.deviceupdate import commands_instance as subject

MANAGER_PATH = "azext_iot.deviceupdate.commands_instance.DeviceUpdateInstanceManager"
HANDLE_PATH = "azext_iot.deviceupdate.commands_instance.handle_service_exception"


@pytest.fixture
def manager(mocker):
    m = MagicMock()
    patched = mocker.patch(MANAGER_PATH)
    patched.return_value = m
    m.find_account.return_value.resource_group = "rg"
    m.find_account.return_value.account.name = "acct"
    m.find_account.return_value.account.location = "westus"
    return m


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch(HANDLE_PATH)


def _cmd():
    return MagicMock()


def test_create_instance_basic(manager):
    subject.create_instance(
        cmd=_cmd(), name="acct", instance_name="inst", iothub_resource_ids=["/hub/1"]
    )
    manager.assemble_iothub_resources.assert_called_once_with(["/hub/1"])
    manager.mgmt_client.instances.begin_create.assert_called_once()


def test_create_instance_with_storage(manager):
    subject.create_instance(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        iothub_resource_ids=["/hub/1"],
        storage_resource_id="/storage/1",
        diagnostics=True,
    )
    manager.assemble_diagnostic_storage.assert_called_once_with("/storage/1")


def test_create_instance_error(manager, handle_exc):
    manager.mgmt_client.instances.begin_create.side_effect = AzureError("boom")
    subject.create_instance(cmd=_cmd(), name="acct", instance_name="inst", iothub_resource_ids=["/hub/1"])
    handle_exc.assert_called_once()


def _params(storage=None):
    p = MagicMock()
    p.id = "/subscriptions/s/resourceGroups/myrg/providers/x/accounts/acct"
    p.account_name = "acct"
    p.name = "inst"
    p.diagnostic_storage_properties = storage
    return p


def test_update_instance_no_storage(manager):
    subject.update_instance(cmd=_cmd(), parameters=_params(storage=None))
    manager.mgmt_client.instances.begin_create.assert_called_once()


def test_update_instance_storage_dict_keybased(manager):
    storage = {"authenticationType": "KeyBased", "resourceId": "/storage/1", "connectionString": None}
    p = _params(storage=storage)
    subject.update_instance(cmd=_cmd(), parameters=p)
    manager.assemble_diagnostic_storage.assert_called_once_with("/storage/1")


def test_update_instance_storage_object(manager):
    storage = MagicMock()
    storage.authentication_type = "KeyBased"
    storage.resource_id = "/storage/1"
    storage.connection_string = None
    p = _params(storage=storage)
    subject.update_instance(cmd=_cmd(), parameters=p)
    manager.assemble_diagnostic_storage.assert_called_once_with("/storage/1")


def test_update_instance_storage_with_connection_string_no_reassemble(manager):
    storage = {"authenticationType": "KeyBased", "resourceId": "/storage/1", "connectionString": "cs"}
    subject.update_instance(cmd=_cmd(), parameters=_params(storage=storage))
    manager.assemble_diagnostic_storage.assert_not_called()


def test_update_instance_storage_default_auth_type(manager):
    storage = {"authenticationType": None, "resourceId": "/storage/1", "connectionString": None}
    subject.update_instance(cmd=_cmd(), parameters=_params(storage=storage))
    manager.assemble_diagnostic_storage.assert_called_once()


def test_update_instance_error(manager, handle_exc):
    manager.mgmt_client.instances.begin_create.side_effect = AzureError("boom")
    subject.update_instance(cmd=_cmd(), parameters=_params(storage=None))
    handle_exc.assert_called_once()


def test_list_instances(manager):
    subject.list_instances(cmd=_cmd(), name="acct")
    manager.mgmt_client.instances.list_by_account.assert_called_once()


def test_list_instances_error(manager, handle_exc):
    manager.mgmt_client.instances.list_by_account.side_effect = AzureError("boom")
    subject.list_instances(cmd=_cmd(), name="acct")
    handle_exc.assert_called_once()


def test_show_instance(manager):
    subject.show_instance(cmd=_cmd(), name="acct", instance_name="inst")
    manager.mgmt_client.instances.get.assert_called_once()


def test_show_instance_error(manager, handle_exc):
    manager.mgmt_client.instances.get.side_effect = AzureError("boom")
    subject.show_instance(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_delete_instance(manager):
    subject.delete_instance(cmd=_cmd(), name="acct", instance_name="inst")
    manager.mgmt_client.instances.begin_delete.assert_called_once()


def test_delete_instance_error(manager, handle_exc):
    manager.mgmt_client.instances.begin_delete.side_effect = AzureError("boom")
    subject.delete_instance(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_wait_on_instance(manager):
    subject.wait_on_instance(cmd=_cmd(), name="acct", instance_name="inst")
    manager.mgmt_client.instances.get.assert_called_once()
