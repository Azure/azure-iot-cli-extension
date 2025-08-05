# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.iothub.conftest import generate_hub_id, RG

cli = EmbeddedCLI()
DEVICE_STREAMS_API_VERSION = "2023-06-30-preview"


@pytest.fixture()
def provisioned_preview_hub():
    name = generate_hub_id()
    hub_resource = cli.invoke(
        f"resource create --name {name} -g {RG} --properties "
        "'{\"sku\": {\"capacity\": 1, \"name\": \"S1\", \"tier\": \"Standard\"}, \"location\": \"northeurope\"}' "
        f"--resource-type Microsoft.Devices/IotHubs --is-full-object --api-version \"{DEVICE_STREAMS_API_VERSION}\"",
        capture_stderr=True
    )
    yield hub_resource.as_json()
    cli.invoke(f"iot hub delete -n {name} -g {RG} --no-wait", capture_stderr=True)


@pytest.mark.hub_infrastructure(location="northeurope")
def test_device_stream(provisioned_preview_hub):
    device_stream = provisioned_preview_hub["properties"]["deviceStreams"]
    hub_name = provisioned_preview_hub["name"]

    result = cli.invoke(
        f"iot hub devicestream show -n {hub_name} -g {RG}",
        capture_stderr=True
    ).as_json()
    assert result == device_stream
