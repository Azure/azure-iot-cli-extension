# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging
import pytest

import azext_iot.iothub.commands_message_endpoint as subject

logging.disable(logging.CRITICAL)

hub_name = "hubname"
hub_rg = "hubrg"
endpoint_name = "ep1"
sentinel = {"result": "ok"}

provider_path = "azext_iot.iothub.commands_message_endpoint.MessageEndpoint"


@pytest.fixture()
def mock_provider(mocker):
    cls = mocker.patch(provider_path)
    instance = cls.return_value
    instance.create.return_value = sentinel
    instance.update.return_value = sentinel
    instance.show.return_value = sentinel
    instance.list.return_value = sentinel
    instance.delete.return_value = sentinel
    yield instance


class TestCreateCommands:
    def test_create_event_hub(self, mock_provider):
        assert subject.message_endpoint_create_event_hub(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name, resource_group_name=hub_rg
        ) == sentinel
        mock_provider.create.assert_called_once()

    def test_create_service_bus_queue(self, mock_provider):
        assert subject.message_endpoint_create_service_bus_queue(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel

    def test_create_service_bus_topic(self, mock_provider):
        assert subject.message_endpoint_create_service_bus_topic(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel

    def test_create_cosmos_db_container(self, mock_provider):
        assert subject.message_endpoint_create_cosmos_db_container(
            cmd=None,
            hub_name=hub_name,
            endpoint_name=endpoint_name,
            container_name="cont",
            database_name="db",
        ) == sentinel

    def test_create_storage_container(self, mock_provider):
        assert subject.message_endpoint_create_storage_container(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name, container_name="cont"
        ) == sentinel


class TestUpdateCommands:
    def test_update_event_hub(self, mock_provider):
        assert subject.message_endpoint_update_event_hub(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel
        mock_provider.update.assert_called_once()

    def test_update_service_bus_queue(self, mock_provider):
        assert subject.message_endpoint_update_service_bus_queue(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel

    def test_update_service_bus_topic(self, mock_provider):
        assert subject.message_endpoint_update_service_bus_topic(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel

    def test_update_cosmos_db_container(self, mock_provider):
        assert subject.message_endpoint_update_cosmos_db_container(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel

    def test_update_storage_container(self, mock_provider):
        assert subject.message_endpoint_update_storage_container(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel


class TestShowListDeleteCommands:
    def test_show(self, mock_provider):
        assert subject.message_endpoint_show(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name
        ) == sentinel
        mock_provider.show.assert_called_once()

    def test_list(self, mock_provider):
        assert subject.message_endpoint_list(cmd=None, hub_name=hub_name) == sentinel
        mock_provider.list.assert_called_once()

    def test_delete(self, mock_provider):
        assert subject.message_endpoint_delete(
            cmd=None, hub_name=hub_name, endpoint_name=endpoint_name, force=True
        ) == sentinel
        mock_provider.delete.assert_called_once()
