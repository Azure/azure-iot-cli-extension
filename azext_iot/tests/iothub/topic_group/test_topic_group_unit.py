# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import logging

import pytest
from azure.cli.core.azclierror import (
    InvalidArgumentValueError,
    ManualInterrupt,
    MutuallyExclusiveArgumentError,
    RequiredArgumentMissingError,
    ResourceNotFoundError,
)
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError

import azext_iot.iothub.commands_topic_group as subject

logging.disable(logging.CRITICAL)

hub_name = "test-hub"
hub_rg = "test-rg"
generic_response = {"result": "ok"}

iot_hub_providers_path = "azext_iot.iothub.providers"
path_find_resource = f"{iot_hub_providers_path}.discovery.IotHubDiscovery.find_resource"
handle_service_exception_path = f"{iot_hub_providers_path}.topic_group.handle_service_exception"


def _topic_groups():
    return [
        {
            "topicGroupId": "group-one",
            "topicTemplates": ["template/one"],
        },
        {
            "topicGroupId": "group-two",
            "topicTemplates": ["template/two"],
        },
    ]


@pytest.fixture()
def fixture_topic_group_ops(mocker):
    find_resource = mocker.patch(path_find_resource, autospec=True)

    hub_mock = {
        "name": hub_name,
        "etag": "test-etag",
        "resourcegroup": hub_rg,
        "subscriptionid": "test-sub",
        "properties": {
            "connectionProfile": "mqttv5",
            "mqttV5Settings": {
                "topicGroups": _topic_groups(),
            },
        },
    }
    client = mocker.MagicMock()
    client.begin_create_or_update.return_value = generic_response

    def initialize_mock_client(self, *args):
        self.client = client
        return hub_mock

    find_resource.side_effect = initialize_mock_client
    yield hub_mock, client


def _assert_hub_write(client, hub_mock):
    client.begin_create_or_update.assert_called_once_with(
        resource_group_name=hub_rg,
        resource_name=hub_name,
        iot_hub_description=hub_mock,
        etag="test-etag",
        match_condition=MatchConditions.IfNotModified,
    )


class TestTopicGroupCreate:
    def test_create(self, fixture_topic_group_ops):
        hub_mock, client = fixture_topic_group_ops

        result = subject.topic_group_create(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="group-three",
            topic_templates=["template/three", "template/four"],
            resource_group_name=hub_rg,
        )

        assert result == generic_response
        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"][-1] == {
            "topicGroupId": "group-three",
            "topicTemplates": ["template/three", "template/four"],
        }
        _assert_hub_write(client, hub_mock)

    def test_create_initializes_missing_settings_with_empty_templates(
        self, fixture_topic_group_ops
    ):
        hub_mock, client = fixture_topic_group_ops
        del hub_mock["properties"]["mqttV5Settings"]

        subject.topic_group_create(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="group",
            topic_templates=[],
            resource_group_name=hub_rg,
        )

        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"] == [
            {
                "topicGroupId": "group",
                "topicTemplates": [],
            }
        ]
        _assert_hub_write(client, hub_mock)

    def test_create_rejects_exact_duplicate(self, fixture_topic_group_ops):
        _, client = fixture_topic_group_ops

        with pytest.raises(InvalidArgumentValueError, match="already exists"):
            subject.topic_group_create(
                cmd=None,
                hub_name=hub_name,
                topic_group_id="group-one",
                topic_templates=[],
                resource_group_name=hub_rg,
            )

        client.begin_create_or_update.assert_not_called()

    def test_create_allows_different_id_casing(self, fixture_topic_group_ops):
        hub_mock, client = fixture_topic_group_ops

        subject.topic_group_create(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="GROUP-ONE",
            topic_templates=[],
            resource_group_name=hub_rg,
        )

        assert [
            group["topicGroupId"]
            for group in hub_mock["properties"]["mqttV5Settings"]["topicGroups"]
        ] == ["group-one", "group-two", "GROUP-ONE"]
        _assert_hub_write(client, hub_mock)

    def test_create_error(self, fixture_topic_group_ops, mocker):
        handler = mocker.patch(handle_service_exception_path)
        from azext_iot.iothub.providers.topic_group import TopicGroup

        provider = TopicGroup(cmd=None, hub_name=hub_name, rg=hub_rg)
        error = HttpResponseError("boom")
        provider.discovery.client.begin_create_or_update.side_effect = error
        provider.create(topic_group_id="group-three", topic_templates=[])
        handler.assert_called_once_with(error)


class TestTopicGroupShow:
    def test_show_uses_exact_id(self, fixture_topic_group_ops):
        result = subject.topic_group_show(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="group-one",
            resource_group_name=hub_rg,
        )

        assert result == {
            "topicGroupId": "group-one",
            "topicTemplates": ["template/one"],
        }

    def test_show_does_not_fold_id_casing(self, fixture_topic_group_ops):
        with pytest.raises(ResourceNotFoundError, match="GROUP-ONE"):
            subject.topic_group_show(
                cmd=None,
                hub_name=hub_name,
                topic_group_id="GROUP-ONE",
                resource_group_name=hub_rg,
            )


class TestTopicGroupList:
    def test_list(self, fixture_topic_group_ops):
        result = subject.topic_group_list(
            cmd=None,
            hub_name=hub_name,
            resource_group_name=hub_rg,
        )

        assert result == _topic_groups()

    @pytest.mark.parametrize(
        "mqtt_v5_settings",
        [None, {}, {"topicGroups": None}],
    )
    def test_list_treats_missing_topic_groups_as_empty(
        self, fixture_topic_group_ops, mqtt_v5_settings
    ):
        hub_mock, _ = fixture_topic_group_ops
        hub_mock["properties"]["mqttV5Settings"] = mqtt_v5_settings

        assert subject.topic_group_list(
            cmd=None,
            hub_name=hub_name,
            resource_group_name=hub_rg,
        ) == []

    def test_list_treats_missing_settings_as_empty(self, fixture_topic_group_ops):
        hub_mock, _ = fixture_topic_group_ops
        del hub_mock["properties"]["mqttV5Settings"]

        assert subject.topic_group_list(
            cmd=None,
            hub_name=hub_name,
            resource_group_name=hub_rg,
        ) == []


class TestTopicGroupUpdate:
    @pytest.mark.parametrize("topic_templates", [[], ["replacement/one", "replacement/two"]])
    def test_update_replaces_only_templates(
        self, fixture_topic_group_ops, topic_templates
    ):
        hub_mock, client = fixture_topic_group_ops

        result = subject.topic_group_update(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="group-one",
            topic_templates=topic_templates,
            resource_group_name=hub_rg,
        )

        assert result == generic_response
        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"] == [
            {
                "topicGroupId": "group-one",
                "topicTemplates": topic_templates,
            },
            {
                "topicGroupId": "group-two",
                "topicTemplates": ["template/two"],
            },
        ]
        _assert_hub_write(client, hub_mock)

    def test_update_rejects_missing_id(self, fixture_topic_group_ops):
        _, client = fixture_topic_group_ops

        with pytest.raises(ResourceNotFoundError, match="missing"):
            subject.topic_group_update(
                cmd=None,
                hub_name=hub_name,
                topic_group_id="missing",
                topic_templates=[],
                resource_group_name=hub_rg,
            )

        client.begin_create_or_update.assert_not_called()


class TestTopicGroupDelete:
    def test_delete_single_group(self, fixture_topic_group_ops):
        hub_mock, client = fixture_topic_group_ops

        result = subject.topic_group_delete(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="group-one",
            resource_group_name=hub_rg,
        )

        assert result == generic_response
        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"] == [
            {
                "topicGroupId": "group-two",
                "topicTemplates": ["template/two"],
            }
        ]
        _assert_hub_write(client, hub_mock)

    def test_delete_rejects_missing_id(self, fixture_topic_group_ops):
        _, client = fixture_topic_group_ops

        with pytest.raises(ResourceNotFoundError, match="missing"):
            subject.topic_group_delete(
                cmd=None,
                hub_name=hub_name,
                topic_group_id="missing",
                resource_group_name=hub_rg,
            )

        client.begin_create_or_update.assert_not_called()

    def test_delete_treats_empty_id_as_an_identifier(self, fixture_topic_group_ops):
        hub_mock, client = fixture_topic_group_ops
        topic_groups = hub_mock["properties"]["mqttV5Settings"]["topicGroups"]
        topic_groups[0]["topicGroupId"] = ""

        subject.topic_group_delete(
            cmd=None,
            hub_name=hub_name,
            topic_group_id="",
            resource_group_name=hub_rg,
        )

        assert [group["topicGroupId"] for group in topic_groups] == ["group-two"]
        _assert_hub_write(client, hub_mock)

    def test_delete_all_prompts(self, fixture_topic_group_ops, mocker):
        hub_mock, client = fixture_topic_group_ops
        prompt = mocker.patch(
            "azext_iot.iothub.providers.topic_group.prompt_y_n",
            return_value=True,
        )

        subject.topic_group_delete(
            cmd=None,
            hub_name=hub_name,
            delete_all=True,
            resource_group_name=hub_rg,
        )

        prompt.assert_called_once_with(
            msg=f"Confirm you want to delete all topic groups from IoT Hub '{hub_name}'",
            default="n",
        )
        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"] == []
        _assert_hub_write(client, hub_mock)

    def test_delete_all_yes_bypasses_prompt(self, fixture_topic_group_ops, mocker):
        hub_mock, client = fixture_topic_group_ops
        prompt = mocker.patch("azext_iot.iothub.providers.topic_group.prompt_y_n")

        subject.topic_group_delete(
            cmd=None,
            hub_name=hub_name,
            delete_all=True,
            yes=True,
            resource_group_name=hub_rg,
        )

        prompt.assert_not_called()
        assert hub_mock["properties"]["mqttV5Settings"]["topicGroups"] == []
        _assert_hub_write(client, hub_mock)

    def test_delete_all_preserves_missing_settings(self, fixture_topic_group_ops):
        hub_mock, client = fixture_topic_group_ops
        del hub_mock["properties"]["mqttV5Settings"]

        subject.topic_group_delete(
            cmd=None,
            hub_name=hub_name,
            delete_all=True,
            yes=True,
            resource_group_name=hub_rg,
        )

        assert "mqttV5Settings" not in hub_mock["properties"]
        _assert_hub_write(client, hub_mock)

    def test_delete_all_rejected_confirmation_stops_write(
        self, fixture_topic_group_ops, mocker
    ):
        hub_mock, client = fixture_topic_group_ops
        mocker.patch(
            "azext_iot.iothub.providers.topic_group.prompt_y_n",
            return_value=False,
        )

        with pytest.raises(ManualInterrupt, match="was not confirmed"):
            subject.topic_group_delete(
                cmd=None,
                hub_name=hub_name,
                delete_all=True,
                resource_group_name=hub_rg,
            )

        assert len(hub_mock["properties"]["mqttV5Settings"]["topicGroups"]) == 2
        client.begin_create_or_update.assert_not_called()

    @pytest.mark.parametrize(
        ("topic_group_id", "delete_all", "error_type"),
        [
            (None, False, RequiredArgumentMissingError),
            ("group-one", True, MutuallyExclusiveArgumentError),
        ],
    )
    def test_delete_requires_one_selector(
        self, mocker, topic_group_id, delete_all, error_type
    ):
        find_resource = mocker.patch(path_find_resource, autospec=True)

        with pytest.raises(error_type):
            subject.topic_group_delete(
                cmd=None,
                hub_name=hub_name,
                topic_group_id=topic_group_id,
                delete_all=delete_all,
                resource_group_name=hub_rg,
            )

        find_resource.assert_not_called()


class TestTopicGroupProfile:
    @pytest.mark.parametrize("connection_profile", ["Classic", "classic", None])
    def test_rejects_non_mqtt_v5_hub(
        self, fixture_topic_group_ops, connection_profile
    ):
        hub_mock, client = fixture_topic_group_ops
        hub_mock["properties"]["connectionProfile"] = connection_profile

        with pytest.raises(InvalidArgumentValueError, match="MqttV5"):
            subject.topic_group_list(
                cmd=None,
                hub_name=hub_name,
                resource_group_name=hub_rg,
            )

        client.begin_create_or_update.assert_not_called()

    def test_accepts_lowercase_mqtt_v5_profile(self, fixture_topic_group_ops):
        result = subject.topic_group_list(
            cmd=None,
            hub_name=hub_name,
            resource_group_name=hub_rg,
        )

        assert len(result) == 2
