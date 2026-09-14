# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""
Integration tests for IoT Hub discovery and hostname resolution.

Tests cover:
- Hub discovery returns TLS 1.3 hostname properties
- Service hostname used for data plane target on GWv2 hubs
- Connection string uses correct hostname based on GWv2 status
"""

import pytest
from azure.cli.testsdk.reverse_dependency import get_dummy_cli
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.iothub.providers.discovery import IotHubDiscovery
from azext_iot.tests.settings import Setting

cli = EmbeddedCLI()


@pytest.fixture(scope="module")
def discovery():
    cmd_shell = Setting()
    setattr(cmd_shell, "cli_ctx", get_dummy_cli())
    return IotHubDiscovery(cmd_shell)


def test_find_resource_returns_hostname_properties(discovery, provisioned_only_iot_hubs_module):
    """Verify find_resource returns TLS 1.3 hostname properties."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]

    resource = discovery.find_resource(resource_name=hub_name, rg=hub_rg)
    props = resource.get("properties", {})

    assert props.get("hostName"), "hostName (classic) should be present"

    device_hostname = props.get("deviceHostName")
    service_hostname = props.get("serviceHostName")
    if device_hostname:
        assert hub_name in device_hostname
        assert ".device." in device_hostname
    if service_hostname:
        assert hub_name in service_hostname
        assert ".service." in service_hostname


def test_build_target_includes_hostname_fields(discovery, provisioned_only_iot_hubs_module):
    """Verify _build_target populates deviceHostName and serviceHostName."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]

    resource = discovery.find_resource(resource_name=hub_name, rg=hub_rg)
    policy = discovery.find_policy(resource_name=hub_name, rg=hub_rg)
    target = discovery._build_target(resource=resource, policy=policy)

    assert target.get("entity"), "entity (hostname) should be set"
    assert target.get("cs"), "connection string should be set"
    assert "deviceHostName" in target, "target should include deviceHostName key"
    assert "serviceHostName" in target, "target should include serviceHostName key"


def test_gwv2_target_uses_service_hostname(discovery, provisioned_only_iot_hubs_module):
    """For GWv2 hubs, _build_target should use service hostname for entity."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]

    resource = discovery.find_resource(resource_name=hub_name, rg=hub_rg)
    props = resource.get("properties", {})
    gw_version = props.get("iotHubDetails", {}).get("gatewayVersion")
    service_hostname = props.get("serviceHostName")

    if gw_version != "V2" or not service_hostname:
        pytest.skip("Hub is not GWv2 — skipping service hostname test")

    policy = discovery.find_policy(resource_name=hub_name, rg=hub_rg)
    target = discovery._build_target(resource=resource, policy=policy)

    assert target["entity"] == service_hostname, \
        f"GWv2 hub entity should be service hostname. Got: {target['entity']}"
    assert service_hostname in target["cs"], \
        "Connection string should use service hostname for GWv2 hub"


def test_connection_string_uses_gwv2_hostname(provisioned_only_iot_hubs_module):
    """Verify connection-string show uses the device hostname for GWv2 hubs."""
    hub_name = provisioned_only_iot_hubs_module[0]["name"]
    hub_rg = provisioned_only_iot_hubs_module[0]["rg"]

    hub = cli.invoke(f"iot hub show -n {hub_name} -g {hub_rg}").as_json()
    props = hub.get("properties", {})
    device_hostname = props.get("deviceHostName")

    result = cli.invoke(f"iot hub connection-string show -n {hub_name} -g {hub_rg}").as_json()
    cs = result["connectionString"]
    assert "HostName=" in cs

    cs_hostname = None
    for part in cs.split(";"):
        if part.startswith("HostName="):
            cs_hostname = part.split("=", 1)[1]
            break

    assert cs_hostname, "Should extract hostname from connection string"

    if device_hostname:
        assert cs_hostname == device_hostname, \
            f"GWv2 connection string should use device hostname '{device_hostname}'. Got: '{cs_hostname}'"
    else:
        classic_hostname = props.get("hostName")
        assert cs_hostname == classic_hostname, \
            f"V1 connection string should use classic hostname '{classic_hostname}'. Got: '{cs_hostname}'"
