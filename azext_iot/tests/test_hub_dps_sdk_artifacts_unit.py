# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------
"""Integrated generated-client contracts; no service calls."""
import importlib
import inspect
from pathlib import Path

import pytest
from azure.core.credentials import AzureKeyCredential


@pytest.mark.parametrize(
    "namespace,client_name,version,kwargs",
    [
        ("iothub.mgmt", "IotHubClient", "2026-11-01", {"subscription_id": "subscription"}),
        ("dps.mgmt", "IotDpsClient", "2026-11-01", {"subscription_id": "subscription"}),
        ("dps.service", "ProvisioningServiceClient", "2026-11-01", {"dps_name": "testdps"}),
        ("dps.device", "ProvisioningDeviceClient", "2026-11-01", {}),
    ],
)
def test_generated_client_contract(namespace, client_name, version, kwargs, mocker):
    package = importlib.import_module("azext_iot.sdk." + namespace)
    path = Path(package.__file__).parent
    assert not (path / "models").exists()
    assert not (path / "aio").exists()
    if (path / "types.py").exists():
        types = importlib.import_module(package.__name__ + ".types")
        for _, value in inspect.getmembers(types, inspect.isclass):
            if value.__module__ == types.__name__:
                assert issubclass(value, dict)
    if namespace != "dps.device":
        kwargs["credential"] = AzureKeyCredential("test-token") if namespace == "dps.service" else mocker.Mock()
    with getattr(package, client_name)(**kwargs) as client:
        assert client._config.api_version == version
        if namespace == "dps.service":
            assert client._client._base_url == "https://{dpsName}.azure-devices-provisioning.net"
            assert "deviceTypeRefs" not in (path / "types.py").read_text()
            assert "namespaceName" in (path / "types.py").read_text()
