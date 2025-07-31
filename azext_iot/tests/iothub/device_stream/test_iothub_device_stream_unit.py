# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azure.cli.core.azclierror import InvalidArgumentValueError
from azext_iot.iothub.commands_device_stream import show_device_stream
from azext_iot.tests.generators import generate_names

cli = EmbeddedCLI()


@pytest.mark.parametrize("has_device_streams", [True, False])
def test_device_stream(fixture_cmd, fixture_ghcs, mocker, has_device_streams):
    # patch embedded CLI to return a mock IoT Hub body
    hub_body = {"properties": {}}
    if has_device_streams:
        hub_body["properties"]["deviceStreams"] = {
            "streamingEndpoints": ["https://db-001.northeurope-001.streams.azure-devices.net"]
        }
    patched_cli = mocker.patch(
        "azext_iot.iothub.providers.device_stream.EmbeddedCLI",
        autospec=True
    )
    patched_cli.return_value.invoke.return_value.as_json.return_value = hub_body

    if not has_device_streams:
        with pytest.raises(InvalidArgumentValueError) as e:
            show_device_stream(
                cmd=fixture_cmd,
                hub_name=generate_names(),
                resource_group_name=generate_names()
            )
        assert "Device streams are not enabled for this IoT Hub." in str(e.value)
        return

    result = show_device_stream(
        cmd=fixture_cmd,
        hub_name=generate_names(),
        resource_group_name=generate_names()
    )
    assert result == hub_body["properties"]["deviceStreams"]
