# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command-layer unit tests for the ADR thin command wrappers.

Each command function instantiates a provider and delegates to a single method.
These tests patch the provider class in the command module and assert the
delegation, exercising the commands_*.py modules.
"""

from unittest.mock import Mock

import pytest

from azext_iot.adr import (
    commands_credential,
    commands_device,
    commands_namespace,
    commands_policy,
)

RG = "test-rg"
NS = "test-namespace"


@pytest.fixture()
def cmd():
    return Mock()


def _patch_provider(mocker, module, attr):
    provider = Mock()
    cls = mocker.patch.object(module, attr, return_value=provider)
    return cls, provider


class TestCredentialCommands:
    def test_create(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_credential, "CredentialProvider")
        commands_credential.adr_credential_create(cmd, namespace_name=NS, resource_group_name=RG, tags={"a": "b"})
        provider.create.assert_called_once_with(namespace_name=NS, resource_group_name=RG, tags={"a": "b"})

    def test_show(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_credential, "CredentialProvider")
        commands_credential.adr_credential_show(cmd, namespace_name=NS, resource_group_name=RG)
        provider.show.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_delete(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_credential, "CredentialProvider")
        commands_credential.adr_credential_delete(cmd, namespace_name=NS, resource_group_name=RG)
        provider.delete.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_synchronize(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_credential, "CredentialProvider")
        commands_credential.adr_credential_synchronize(cmd, namespace_name=NS, resource_group_name=RG)
        provider.synchronize.assert_called_once_with(namespace_name=NS, resource_group_name=RG)


class TestDeviceCommands:
    def test_show(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_device, "DeviceProvider")
        commands_device.adr_device_show(cmd, device_name="dev", namespace_name=NS, resource_group_name=RG)
        provider.show.assert_called_once_with(device_name="dev", namespace_name=NS, resource_group_name=RG)

    def test_list(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_device, "DeviceProvider")
        commands_device.adr_device_list(cmd, namespace_name=NS, resource_group_name=RG)
        provider.list.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_update(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_device, "DeviceProvider")
        commands_device.adr_device_update(
            cmd,
            device_name="dev",
            namespace_name=NS,
            resource_group_name=RG,
            enabled=True,
            tags={"a": "b"},
            operating_system_version="1.0",
            attributes="{}",
            policy_resource_id="pid",
        )
        provider.update.assert_called_once_with(
            device_name="dev",
            namespace_name=NS,
            resource_group_name=RG,
            enabled=True,
            tags={"a": "b"},
            operating_system_version="1.0",
            attributes="{}",
            policy_resource_id="pid",
        )

    def test_revoke(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_device, "DeviceProvider")
        commands_device.adr_device_revoke(
            cmd, device_name="dev", namespace_name=NS, resource_group_name=RG, disable=True
        )
        provider.revoke.assert_called_once_with(
            device_name="dev", namespace_name=NS, resource_group_name=RG, disable=True
        )


class TestNamespaceCommands:
    def test_create(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_create(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            location="westus",
            tags={"a": "b"},
            enable_certificate_management=True,
            policy_name="pol",
            certificate_key_type="ECC",
            certificate_subject="CN=x",
            certificate_validity_days=30,
        )
        provider.create.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            location="westus",
            tags={"a": "b"},
            enable_certificate_management=True,
            policy_name="pol",
            certificate_key_type="ECC",
            certificate_subject="CN=x",
            certificate_validity_days=30,
        )

    def test_show(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_show(cmd, namespace_name=NS, resource_group_name=RG)
        provider.show.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_list(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_list(cmd, resource_group_name=RG)
        provider.list.assert_called_once_with(resource_group_name=RG)

    def test_delete(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_delete(cmd, namespace_name=NS, resource_group_name=RG)
        provider.delete.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_update(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_update(cmd, namespace_name=NS, resource_group_name=RG, tags={"a": "b"})
        provider.update.assert_called_once_with(namespace_name=NS, resource_group_name=RG, tags={"a": "b"})


class TestPolicyCommands:
    def test_create(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_create(
            cmd,
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            certificate_key_type="ECC",
            certificate_subject="CN=x",
            certificate_validity_days=30,
            enable_byor=True,
        )
        provider.create.assert_called_once_with(
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            certificate_key_type="ECC",
            certificate_subject="CN=x",
            certificate_validity_days=30,
            enable_byor=True,
        )

    def test_show(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_show(cmd, policy_name="pol", namespace_name=NS, resource_group_name=RG)
        provider.show.assert_called_once_with(policy_name="pol", namespace_name=NS, resource_group_name=RG)

    def test_list(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_list(cmd, namespace_name=NS, resource_group_name=RG)
        provider.list.assert_called_once_with(namespace_name=NS, resource_group_name=RG)

    def test_delete(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_delete(cmd, policy_name="pol", namespace_name=NS, resource_group_name=RG)
        provider.delete.assert_called_once_with(policy_name="pol", namespace_name=NS, resource_group_name=RG)

    def test_update(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_update(
            cmd,
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            certificate_validity_days=30,
        )
        provider.update.assert_called_once_with(
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            certificate_validity_days=30,
        )

    def test_revoke_issuer(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        commands_policy.adr_policy_revoke_issuer(cmd, policy_name="pol", namespace_name=NS, resource_group_name=RG)
        provider.revoke_issuer.assert_called_once_with(
            policy_name="pol", namespace_name=NS, resource_group_name=RG
        )

    def test_activate_byor(self, mocker, cmd):
        _, provider = _patch_provider(mocker, commands_policy, "PolicyProvider")
        mocker.patch(
            "azext_iot.common.utility.read_file_content", return_value="cert-chain"
        )
        commands_policy.adr_policy_activate_byor(
            cmd,
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            certificate_chain_file="chain.pem",
        )
        provider.activate_byor.assert_called_once_with(
            policy_name="pol",
            namespace_name=NS,
            resource_group_name=RG,
            certificate_chain="cert-chain",
        )
