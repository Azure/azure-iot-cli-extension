# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""Integrated generated-client contracts; no service calls."""
import importlib
from pathlib import Path

import pytest
from azure.core.credentials import AzureKeyCredential


@pytest.mark.parametrize(
    "namespace,client_name,version,kwargs",
    [
        ("iothub.mgmt", "IotHubClient", "2026-10-01-preview", {"subscription_id": "subscription"}),
        ("dps.mgmt", "IotDpsClient", "2026-06-01-preview", {"subscription_id": "subscription"}),
        ("dps.service", "ProvisioningServiceClient", "2026-11-02-preview", {"dps_name": "testdps"}),
        ("dps.device", "ProvisioningDeviceClient", "2026-11-02-preview", {}),
    ],
)
def test_generated_client_contract(namespace, client_name, version, kwargs, mocker):
    package = importlib.import_module("azext_iot.sdk." + namespace)
    path = Path(package.__file__).parent
    assert not (path / "models").exists()
    assert not (path / "aio").exists()
    if namespace in ("iothub.mgmt", "dps.service"):
        assert not (path / "types.py").exists()
    if namespace != "dps.device":
        kwargs["credential"] = AzureKeyCredential("test-token") if namespace == "dps.service" else mocker.Mock()
    with getattr(package, client_name)(**kwargs) as client:
        assert client._config.api_version == version
        if namespace == "dps.service":
            assert client._client._base_url == "https://{dpsName}.azure-devices-provisioning.net"
            assert "deviceTypeRefs" in (path / "operations/_operations.py").read_text()
