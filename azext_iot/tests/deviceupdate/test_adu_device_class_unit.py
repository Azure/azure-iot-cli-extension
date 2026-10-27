# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.commands_device_class
"""

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azure.cli.core.azclierror import ArgumentUsageError
from azext_iot.deviceupdate import commands_device_class as subject

MANAGER_PATH = "azext_iot.deviceupdate.commands_device_class.DeviceUpdateDataManager"
HANDLE_PATH = "azext_iot.deviceupdate.commands_device_class.handle_service_exception"


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


def test_list_device_classes_default(manager):
    subject.list_device_classes(cmd=_cmd(), name="acct", instance_name="inst", filter="f")
    dm(manager).list_device_classes.assert_called_once_with(filter="f")


def test_list_device_classes_by_group(manager):
    subject.list_device_classes(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    dm(manager).list_device_class_subgroups_for_group.assert_called_once_with(group_id="g1", filter=None)


def test_list_device_classes_error(manager, handle_exc):
    dm(manager).list_device_classes.side_effect = AzureError("boom")
    subject.list_device_classes(cmd=_cmd(), name="acct", instance_name="inst")
    handle_exc.assert_called_once()


def test_show_device_class_default(manager):
    subject.show_device_class(cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1")
    dm(manager).get_device_class.assert_called_once_with(device_class_id="dc1")


def test_show_device_class_installable_updates(manager):
    subject.show_device_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", installable_updates=True
    )
    dm(manager).list_installable_updates_for_device_class.assert_called_once_with(device_class_id="dc1")


def test_show_device_class_update_compliance(manager):
    subject.show_device_class(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_class_id="dc1",
        device_group_id="g1",
        update_compliance=True,
    )
    dm(manager).get_device_class_subgroup_update_compliance.assert_called_once_with(group_id="g1", device_class_id="dc1")


def test_show_device_class_best_update(manager):
    subject.show_device_class(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_class_id="dc1",
        device_group_id="g1",
        best_update=True,
    )
    dm(manager).get_best_updates_for_device_class_subgroup.assert_called_once_with(group_id="g1", device_class_id="dc1")


def test_show_device_class_subgroup(manager):
    subject.show_device_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", device_group_id="g1"
    )
    dm(manager).get_device_class_subgroup.assert_called_once_with(group_id="g1", device_class_id="dc1")


def test_show_device_class_multiple_flags_error(manager):
    with pytest.raises(ArgumentUsageError):
        subject.show_device_class(
            cmd=_cmd(),
            name="acct",
            instance_name="inst",
            device_class_id="dc1",
            update_compliance=True,
            best_update=True,
        )


def test_show_device_class_missing_group_error(manager):
    with pytest.raises(ArgumentUsageError):
        subject.show_device_class(
            cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", update_compliance=True
        )


def test_show_device_class_error(manager, handle_exc):
    dm(manager).get_device_class.side_effect = AzureError("boom")
    subject.show_device_class(cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1")
    handle_exc.assert_called_once()


def test_update_device_class_with_friendly_name(manager):
    subject.update_device_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", friendly_name="nice"
    )
    dm(manager).update_device_class.assert_called_once()


def test_update_device_class_no_patch(manager):
    subject.update_device_class(cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1")
    dm(manager).update_device_class.assert_not_called()


def test_update_device_class_error(manager, handle_exc):
    dm(manager).update_device_class.side_effect = AzureError("boom")
    subject.update_device_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", friendly_name="nice"
    )
    handle_exc.assert_called_once()


def test_delete_device_class_default(manager):
    subject.delete_device_class(cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1")
    dm(manager).delete_device_class.assert_called_once_with(device_class_id="dc1")


def test_delete_device_class_subgroup(manager):
    subject.delete_device_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1", device_group_id="g1"
    )
    dm(manager).delete_device_class_subgroup.assert_called_once_with(device_class_id="dc1", group_id="g1")


def test_delete_device_class_error(manager, handle_exc):
    dm(manager).delete_device_class.side_effect = AzureError("boom")
    subject.delete_device_class(cmd=_cmd(), name="acct", instance_name="inst", device_class_id="dc1")
    handle_exc.assert_called_once()
