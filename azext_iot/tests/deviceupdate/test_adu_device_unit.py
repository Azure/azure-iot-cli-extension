# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.commands_device
"""

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azure.cli.core.azclierror import ArgumentUsageError
from azext_iot.deviceupdate import commands_device as subject

MANAGER_PATH = "azext_iot.deviceupdate.commands_device.DeviceUpdateDataManager"
HANDLE_PATH = "azext_iot.deviceupdate.commands_device.handle_service_exception"


@pytest.fixture
def manager(mocker):
    m = MagicMock()
    mocker.patch(MANAGER_PATH).return_value = m
    return m


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch(HANDLE_PATH)


def _cmd():
    return MagicMock()


def dm(manager):
    return manager.data_client.device_management


def test_import_devices(manager):
    subject.import_devices(cmd=_cmd(), name="acct", instance_name="inst", import_type="All")
    dm(manager).begin_import_devices.assert_called_once_with(import_type={"importType": "All"})


def test_import_devices_error(manager, handle_exc):
    dm(manager).begin_import_devices.side_effect = AzureError("boom")
    subject.import_devices(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_list_devices(manager):
    subject.list_devices(cmd=_cmd(), name="acct", instance_name="inst", filter="f")
    dm(manager).list_devices.assert_called_once_with(filter="f")


def test_list_devices_error(manager, handle_exc):
    dm(manager).list_devices.side_effect = AzureError("boom")
    subject.list_devices(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_show_device(manager):
    subject.show_device(cmd=_cmd(), name="acct", instance_name="inst", device_id="d1")
    dm(manager).get_device.assert_called_once_with(device_id="d1")


def test_show_device_error(manager, handle_exc):
    dm(manager).get_device.side_effect = AzureError("boom")
    subject.show_device(cmd=_cmd(), name="acct", instance_name="inst", device_id="d1")
    handle_exc.assert_called_once()


def test_show_device_module(manager):
    subject.show_device_module(cmd=_cmd(), name="acct", instance_name="inst", device_id="d1", module_id="m1")
    dm(manager).get_device_module.assert_called_once_with(device_id="d1", module_id="m1")


def test_show_device_module_error(manager, handle_exc):
    dm(manager).get_device_module.side_effect = AzureError("boom")
    subject.show_device_module(cmd=_cmd(), name="acct", instance_name="inst", device_id="d1", module_id="m1")
    handle_exc.assert_called_once()


def test_list_device_groups(manager):
    subject.list_device_groups(cmd=_cmd(), name="acct", instance_name="inst", order_by="ob")
    dm(manager).list_groups.assert_called_once_with(order_by="ob")


def test_list_device_groups_error(manager, handle_exc):
    dm(manager).list_groups.side_effect = AzureError("boom")
    subject.list_device_groups(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_show_device_group_default(manager):
    subject.show_device_group(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    dm(manager).get_group.assert_called_once_with(group_id="g1")


def test_show_device_group_update_compliance(manager):
    subject.show_device_group(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", update_compliance=True
    )
    dm(manager).get_update_compliance_for_group.assert_called_once_with(group_id="g1")


def test_show_device_group_best_updates(manager):
    subject.show_device_group(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", best_updates=True
    )
    dm(manager).list_best_updates_for_group.assert_called_once_with(group_id="g1")


def test_show_device_group_conflicting_flags(manager):
    with pytest.raises(ArgumentUsageError):
        subject.show_device_group(
            cmd=_cmd(),
            name="acct",
            instance_name="inst",
            device_group_id="g1",
            update_compliance=True,
            best_updates=True,
        )


def test_show_device_group_error(manager, handle_exc):
    dm(manager).get_group.side_effect = AzureError("boom")
    subject.show_device_group(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    handle_exc.assert_called_once()


def test_delete_device_group(manager):
    subject.delete_device_group(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    dm(manager).delete_group.assert_called_once_with(group_id="g1")


def test_delete_device_group_error(manager, handle_exc):
    dm(manager).delete_group.side_effect = AzureError("boom")
    subject.delete_device_group(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    handle_exc.assert_called_once()


def test_show_update_compliance(manager):
    subject.show_update_compliance(cmd=_cmd(), name="acct", instance_name="inst")
    dm(manager).get_update_compliance.assert_called_once()


def test_show_update_compliance_error(manager, handle_exc):
    dm(manager).get_update_compliance.side_effect = AzureError("boom")
    subject.show_update_compliance(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_list_device_health(manager):
    subject.list_device_health(cmd=_cmd(), name="acct", instance_name="inst", filter="state eq 'Healthy'")
    dm(manager).list_health_of_devices.assert_called_once_with(filter="state eq 'Healthy'")


def test_list_device_health_error(manager, handle_exc):
    dm(manager).list_health_of_devices.side_effect = AzureError("boom")
    subject.list_device_health(cmd=_cmd(), name="acct", instance_name="inst", filter="f")
    handle_exc.assert_called_once()
