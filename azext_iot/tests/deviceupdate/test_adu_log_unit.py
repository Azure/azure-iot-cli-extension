# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from unittest.mock import MagicMock
from azure.core.exceptions import AzureError

import azext_iot.deviceupdate.commands_log as subject

MOD = "azext_iot.deviceupdate.commands_log"


@pytest.fixture
def data_manager(mocker):
    instance = MagicMock()
    mocker.patch(f"{MOD}.DeviceUpdateDataManager", return_value=instance)
    return instance


@pytest.fixture
def handle_exc(mocker):
    return mocker.patch(f"{MOD}.handle_service_exception")


def test_collect_logs_error(data_manager, handle_exc):
    data_manager.data_client.device_management.start_log_collection.side_effect = AzureError("boom")
    subject.collect_logs(
        cmd=MagicMock(), name="a", instance_name="i", log_collection_id="lc", agent_id=[["deviceId=d"]],
    )
    handle_exc.assert_called_once()


def test_list_log_collections_error(data_manager, handle_exc):
    data_manager.data_client.device_management.list_log_collections.side_effect = AzureError("boom")
    subject.list_log_collections(cmd=MagicMock(), name="a", instance_name="i")
    handle_exc.assert_called_once()


def test_show_log_collection_error(data_manager, handle_exc):
    data_manager.data_client.device_management.get_log_collection.side_effect = AzureError("boom")
    subject.show_log_collection(cmd=MagicMock(), name="a", instance_name="i", log_collection_id="lc")
    handle_exc.assert_called_once()
