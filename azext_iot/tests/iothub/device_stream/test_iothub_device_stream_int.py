# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import pytest
from azext_iot.common.embedded_cli import EmbeddedCLI

cli = EmbeddedCLI()


@pytest.mark.hub_infrastructure(location="northeurope")
def test_device_stream(provisioned_only_iot_hubs_module):
    device_stream = provisioned_only_iot_hubs_module[0]["hub"]["properties"].get(
        "deviceStreams", None
    )
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    rg = provisioned_only_iot_hubs_module[0]["rg"]

    result = cli.invoke(
        f"iot hub devicestream show -n {hub_name} -g {rg}",
        capture_stderr=True
    ).as_json()
    assert result == device_stream
