# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Unit tests for azext_iot.deviceupdate.commands_deployment
"""

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError
from azure.cli.core.azclierror import ArgumentUsageError
from azext_iot.deviceupdate import commands_deployment as subject

MANAGER_PATH = "azext_iot.deviceupdate.commands_deployment.DeviceUpdateDataManager"
HANDLE_PATH = "azext_iot.deviceupdate.commands_deployment.handle_service_exception"


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


def test_list_devices_for_deployment(manager):
    subject.list_devices_for_deployment(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_group_id="g1",
        device_class_id="dc1",
        deployment_id="dep1",
        filter="f",
    )
    dm(manager).list_device_states_for_device_class_subgroup_deployment.assert_called_once()


def test_create_deployment_basic(manager):
    subject.create_deployment(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_group_id="g1",
        deployment_id="dep1",
        update_name="u",
        update_provider="p",
        update_version="1.0",
    )
    dm(manager).create_or_update_deployment.assert_called_once()


def test_create_deployment_with_rollback(manager):
    subject.create_deployment(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_group_id="g1",
        deployment_id="dep1",
        update_name="u",
        update_provider="p",
        update_version="1.0",
        start_date_time="2026-01-01T00:00:00Z",
        rollback_update_name="ru",
        rollback_update_provider="rp",
        rollback_update_version="0.9",
        devices_failed_percentage="5",
        devices_failed_count="10",
    )
    dm(manager).create_or_update_deployment.assert_called_once()


def test_create_deployment_incomplete_rollback_error(manager):
    with pytest.raises(ArgumentUsageError):
        subject.create_deployment(
            cmd=_cmd(),
            name="acct",
            instance_name="inst",
            device_group_id="g1",
            deployment_id="dep1",
            update_name="u",
            update_provider="p",
            update_version="1.0",
            devices_failed_percentage="5",
        )


def test_create_deployment_error(manager, handle_exc):
    dm(manager).create_or_update_deployment.side_effect = AzureError("boom")
    subject.create_deployment(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_group_id="g1",
        deployment_id="dep1",
        update_name="u",
        update_provider="p",
        update_version="1.0",
    )
    handle_exc.assert_called_once()


def test_list_deployments_for_group(manager):
    subject.list_deployments(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    dm(manager).list_deployments_for_group.assert_called_once()


def test_list_deployments_for_class(manager):
    subject.list_deployments(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", device_class_id="dc1"
    )
    dm(manager).list_deployments_for_device_class_subgroup.assert_called_once()


def test_list_deployments_error(manager, handle_exc):
    dm(manager).list_deployments_for_group.side_effect = AzureError("boom")
    subject.list_deployments(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1")
    handle_exc.assert_called_once()


def test_show_deployment_default(manager):
    subject.show_deployment(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1")
    dm(manager).get_deployment.assert_called_once()


def test_show_deployment_for_class(manager):
    subject.show_deployment(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1", device_class_id="dc1"
    )
    dm(manager).get_deployment_for_device_class_subgroup.assert_called_once()


def test_show_deployment_status(manager):
    subject.show_deployment(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1", status=True
    )
    dm(manager).get_deployment_status.assert_called_once()


def test_show_deployment_status_for_class(manager):
    subject.show_deployment(
        cmd=_cmd(),
        name="acct",
        instance_name="inst",
        device_group_id="g1",
        deployment_id="dep1",
        device_class_id="dc1",
        status=True,
    )
    dm(manager).get_device_class_subgroup_deployment_status.assert_called_once()


def test_show_deployment_error(manager, handle_exc):
    dm(manager).get_deployment.side_effect = AzureError("boom")
    subject.show_deployment(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1")
    handle_exc.assert_called_once()


def test_delete_deployment_default(manager):
    subject.delete_deployment(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1")
    dm(manager).delete_deployment.assert_called_once()


def test_delete_deployment_for_class(manager):
    subject.delete_deployment(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1", device_class_id="dc1"
    )
    dm(manager).delete_deployment_for_device_class_subgroup.assert_called_once()


def test_delete_deployment_error(manager, handle_exc):
    dm(manager).delete_deployment.side_effect = AzureError("boom")
    subject.delete_deployment(cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", deployment_id="dep1")
    handle_exc.assert_called_once()


def test_cancel_deployment_for_class(manager):
    subject.cancel_deployment_for_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", device_class_id="dc1", deployment_id="dep1"
    )
    dm(manager).stop_deployment.assert_called_once()


def test_cancel_deployment_for_class_error(manager, handle_exc):
    dm(manager).stop_deployment.side_effect = AzureError("boom")
    subject.cancel_deployment_for_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", device_class_id="dc1", deployment_id="dep1"
    )
    handle_exc.assert_called_once()


def test_retry_deployment_for_class(manager):
    subject.retry_deployment_for_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", device_class_id="dc1", deployment_id="dep1"
    )
    dm(manager).retry_deployment.assert_called_once()


def test_retry_deployment_for_class_error(manager, handle_exc):
    dm(manager).retry_deployment.side_effect = AzureError("boom")
    subject.retry_deployment_for_class(
        cmd=_cmd(), name="acct", instance_name="inst", device_group_id="g1", device_class_id="dc1", deployment_id="dep1"
    )
    handle_exc.assert_called_once()
