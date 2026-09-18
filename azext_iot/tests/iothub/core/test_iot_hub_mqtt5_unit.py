# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azure.cli.core.azclierror import ManualInterrupt

from azext_iot.core import custom as subject
from azext_iot.core.shared import IotHubConnectionProfile


@pytest.fixture()
def create_context(mocker):
    cmd = mocker.MagicMock()
    client = mocker.MagicMock()
    mocker.patch.object(subject, "_ensure_location", return_value="eastus")
    mocker.patch.object(subject, "_validate_and_set_adr_properties")
    return cmd, client


def _create_hub(create_context, **kwargs):
    cmd, client = create_context
    subject.iot_hub_create(
        cmd=cmd,
        client=client,
        hub_name="hub",
        resource_group_name="rg",
        **kwargs,
    )
    body = client.iot_hub_resource.begin_create_or_update.call_args.kwargs["iot_hub_description"]
    return body


def test_create_without_profile_preserves_classic_payload(create_context, mocker):
    prompt = mocker.patch.object(subject, "prompt_y_n")

    body = _create_hub(create_context)

    assert "connectionProfile" not in body["properties"]
    assert "routing" not in body["properties"]
    prompt.assert_not_called()


def test_create_explicit_classic_does_not_prompt(create_context, mocker):
    prompt = mocker.patch.object(subject, "prompt_y_n")

    body = _create_hub(create_context, connection_profile="Classic")

    assert body["properties"]["connectionProfile"] == "Classic"
    assert "routing" not in body["properties"]
    prompt.assert_not_called()


def test_create_mqtt_v5_adds_required_payload(create_context, mocker):
    prompt = mocker.patch.object(subject, "prompt_y_n")

    body = _create_hub(
        create_context,
        connection_profile="MqttV5",
        sku="S1",
        unit=1,
        yes=True,
    )

    assert body["properties"]["connectionProfile"] == "MqttV5"
    assert body["properties"]["routing"] == {"endpoints": {}}
    assert "mqttV5Settings" not in body["properties"]
    prompt.assert_not_called()


def test_create_mqtt_v5_passes_scale_values_to_service(create_context):
    body = _create_hub(
        create_context,
        connection_profile="MqttV5",
        sku="S2",
        unit=26,
        yes=True,
    )

    assert body["sku"] == {"name": "S2", "capacity": 26}


def test_create_mqtt_v5_prompts_and_continues(create_context, mocker):
    prompt = mocker.patch.object(subject, "prompt_y_n", return_value=True)

    _create_hub(create_context, connection_profile="MqttV5")

    prompt.assert_called_once_with(msg=subject.MQTT_V5_CREATE_CONFIRMATION, default="n")


def test_create_mqtt_v5_rejected_confirmation_stops_request(create_context, mocker):
    _, client = create_context
    mocker.patch.object(subject, "prompt_y_n", return_value=False)

    with pytest.raises(ManualInterrupt, match="was not confirmed"):
        _create_hub(create_context, connection_profile="MqttV5")

    client.iot_hub_resource.begin_create_or_update.assert_not_called()


def test_connection_profile_enum_matches_contract():
    assert [profile.value for profile in IotHubConnectionProfile] == ["Classic", "MqttV5"]


def test_mqtt_v5_profile_detection_is_case_insensitive():
    assert subject._is_mqtt_v5_profile("mQtTv5")
