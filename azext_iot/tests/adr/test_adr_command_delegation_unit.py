# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command-layer delegation tests for ADR providers."""

import inspect
from unittest.mock import Mock

import pytest

from azext_iot.adr import (
    commands_certificate_authority,
    commands_certificate_policy,
    commands_link,
    commands_namespace,
)

RG = "test-rg"
NS = "test-namespace"


@pytest.fixture()
def cmd():
    return Mock()


def _patch_provider(mocker, module, attr):
    provider = Mock()
    mocker.patch.object(module, attr, return_value=provider)
    return provider


class TestNamespaceCommands:
    def test_create_and_update_surfaces_exclude_raw_endpoint_parameters(self):
        removed = {
            "messaging_endpoints",
            "provisioning_endpoints",
            "updating_endpoints",
        }

        for command in (
            commands_namespace.adr_namespace_create,
            commands_namespace.adr_namespace_update,
        ):
            assert removed.isdisjoint(inspect.signature(command).parameters)
        assert "observability_enabled" not in inspect.signature(
            commands_namespace.adr_namespace_create
        ).parameters
        assert "observability_enabled" not in inspect.signature(
            commands_namespace.adr_namespace_update
        ).parameters

    def test_create(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_create(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            location="westus",
            tags={"a": "b"},
            outbound_mi_system_assigned=True,
            no_wait=True,
        )
        provider.create.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            location="westus",
            tags={"a": "b"},
            outbound_mi_system_assigned=True,
            outbound_mi_user_assigned=None,
            no_wait=True,
        )

    def test_update(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        commands_namespace.adr_namespace_update(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            no_wait=True,
        )
        provider.update.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            outbound_mi_system_assigned=None,
            outbound_mi_user_assigned=None,
            no_wait=True,
        )

    def test_migrate(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        resource_ids = ["/subscriptions/sub/resourceGroups/rg/providers/"
                        "Microsoft.DeviceRegistry/assets/asset"]

        commands_namespace.adr_namespace_migrate(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            resource_ids=resource_ids,
            no_wait=True,
        )

        provider.migrate.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            resource_ids=resource_ids,
            no_wait=True,
        )

    @pytest.mark.parametrize(
        "function_name, provider_method, kwargs",
        [
            (
                "adr_namespace_identity_show",
                "identity_show",
                {},
            ),
            (
                "adr_namespace_identity_assign",
                "identity_assign",
                {
                    "system_assigned": True,
                    "user_assigned_identities": ["/identity"],
                    "no_wait": True,
                },
            ),
            (
                "adr_namespace_identity_remove",
                "identity_remove",
                {
                    "system_assigned": False,
                    "user_assigned_identities": ["/identity"],
                    "no_wait": True,
                },
            ),
        ],
    )
    def test_identity_commands(
        self, mocker, cmd, function_name, provider_method, kwargs
    ):
        provider = _patch_provider(mocker, commands_namespace, "NamespaceProvider")
        getattr(commands_namespace, function_name)(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            **kwargs,
        )
        getattr(provider, provider_method).assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            **kwargs,
        )


def test_hub_update_surface_is_identity_only(mocker, cmd):
    provider = _patch_provider(mocker, commands_link, "LinkProvider")
    namespace_client = Mock()
    commands_link.adr_link_hub_update(
        cmd,
        namespace_client,
        endpoint_name="hub",
        namespace_name=NS,
        resource_group_name=RG,
        mi_system_assigned=True,
        no_wait=True,
    )
    provider.hub_update.assert_called_once_with(
        endpoint_name="hub",
        namespace_name=NS,
        resource_group_name=RG,
        mi_system_assigned=True,
        mi_user_assigned=None,
        no_wait=True,
        timeout_sec=600,
        wait_sec=30,
    )


@pytest.mark.parametrize(
    "command_name,operation_name,kwargs",
    [
        (
            "adr_link_add",
            "link_add",
            {
                "namespace_name": NS,
                "resource_group_name": RG,
                "hub_endpoint_name": "hub",
                "hub_resource_id": "hub-id",
                "dps_endpoint_name": "dps",
                "dps_resource_id": "dps-id",
            },
        ),
        (
            "adr_link_hub_add",
            "hub_add",
            {
                "endpoint_name": "hub",
                "namespace_name": NS,
                "resource_group_name": RG,
                "hub_resource_id": "hub-id",
            },
        ),
        (
            "adr_link_hub_update",
            "hub_update",
            {
                "endpoint_name": "hub",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_hub_show",
            "hub_show",
            {
                "endpoint_name": "hub",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_hub_list",
            "hub_list",
            {
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_dps_add",
            "dps_add",
            {
                "endpoint_name": "dps",
                "namespace_name": NS,
                "resource_group_name": RG,
                "dps_resource_id": "dps-id",
            },
        ),
        (
            "adr_link_dps_update",
            "dps_update",
            {
                "endpoint_name": "dps",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_dps_show",
            "dps_show",
            {
                "endpoint_name": "dps",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_dps_list",
            "dps_list",
            {
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),


    ],
)
def test_all_link_commands_use_injected_namespace_client(
    mocker,
    cmd,
    command_name,
    operation_name,
    kwargs,
):
    namespace_client = Mock()
    provider = Mock()
    provider_type = mocker.patch.object(
        commands_link,
        "LinkProvider",
        return_value=provider,
    )

    getattr(commands_link, command_name)(cmd, namespace_client, **kwargs)

    provider_type.assert_called_once_with(cmd, client=namespace_client)
    getattr(provider, operation_name).assert_called_once()


def test_certificate_authority_command_still_delegates(mocker, cmd):
    provider = _patch_provider(
        mocker, commands_certificate_authority, "CertificateAuthorityProvider"
    )
    commands_certificate_authority.adr_ca_create(
        cmd,
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        certificate_authority_type="Root",
    )
    provider.create.assert_called_once()


def test_certificate_authority_activate_reads_chain_and_delegates(mocker, cmd):
    provider = _patch_provider(
        mocker, commands_certificate_authority, "CertificateAuthorityProvider"
    )
    mocker.patch(
        "azext_iot.common.utility.read_file_content", return_value="certificate-chain"
    )

    commands_certificate_authority.adr_ca_activate(
        cmd,
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        certificate_chain_file="chain.pem",
        no_wait=True,
    )

    provider.activate.assert_called_once_with(
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        certificate_chain="certificate-chain",
        no_wait=True,
    )


def test_certificate_policy_command_still_delegates(mocker, cmd):
    provider = _patch_provider(
        mocker, commands_certificate_policy, "CertificatePolicyProvider"
    )
    commands_certificate_policy.adr_ca_policy_update(
        cmd,
        certificate_policy_name="policy",
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        validity_days=15,
    )
    provider.update.assert_called_once_with(
        certificate_policy_name="policy",
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        validity_days=15,
    )


_SIMPLE_COMMAND_CASES = [
    pytest.param(
        commands_namespace,
        "NamespaceProvider",
        "adr_namespace_show",
        "show",
        {"namespace_name": NS, "resource_group_name": RG},
        id="namespace-show",
    ),
    pytest.param(
        commands_namespace,
        "NamespaceProvider",
        "adr_namespace_list",
        "list",
        {},
        id="namespace-list",
    ),
    pytest.param(
        commands_namespace,
        "NamespaceProvider",
        "adr_namespace_delete",
        "delete",
        {"namespace_name": NS, "resource_group_name": RG},
        id="namespace-delete",
    ),


]

_SIMPLE_COMMAND_CASES.extend(
    [
        pytest.param(
            commands_certificate_authority,
            "CertificateAuthorityProvider",
            "adr_ca_show",
            "show",
            {
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
            id="ca-show",
        ),
        pytest.param(
            commands_certificate_authority,
            "CertificateAuthorityProvider",
            "adr_ca_list",
            "list",
            {"namespace_name": NS, "resource_group_name": RG},
            id="ca-list",
        ),
        pytest.param(
            commands_certificate_authority,
            "CertificateAuthorityProvider",
            "adr_ca_update",
            "update",
            {
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
                "tags": {"env": "test"},
                "no_wait": True,
            },
            id="ca-update",
        ),
        pytest.param(
            commands_certificate_authority,
            "CertificateAuthorityProvider",
            "adr_ca_delete",
            "delete",
            {
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
                "no_wait": True,
            },
            id="ca-delete",
        ),
        pytest.param(
            commands_certificate_authority,
            "CertificateAuthorityProvider",
            "adr_ca_revoke",
            "revoke",
            {
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
                "no_wait": True,
            },
            id="ca-revoke",
        ),
        pytest.param(
            commands_certificate_policy,
            "CertificatePolicyProvider",
            "adr_ca_policy_create",
            "create",
            {
                "certificate_policy_name": "policy",
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
                "validity_days": 30,
                "no_wait": True,
            },
            id="ca-policy-create",
        ),
        pytest.param(
            commands_certificate_policy,
            "CertificatePolicyProvider",
            "adr_ca_policy_show",
            "show",
            {
                "certificate_policy_name": "policy",
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
            id="ca-policy-show",
        ),
        pytest.param(
            commands_certificate_policy,
            "CertificatePolicyProvider",
            "adr_ca_policy_list",
            "list",
            {
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
            id="ca-policy-list",
        ),
        pytest.param(
            commands_certificate_policy,
            "CertificatePolicyProvider",
            "adr_ca_policy_delete",
            "delete",
            {
                "certificate_policy_name": "policy",
                "certificate_authority_name": "ca",
                "namespace_name": NS,
                "resource_group_name": RG,
                "no_wait": True,
            },
            id="ca-policy-delete",
        ),
    ]
)

for _kind, _resource_argument in (
    ("hub", "hub_resource_id"),
    ("dps", "dps_resource_id"),

):
    _SIMPLE_COMMAND_CASES.extend(
        [
            pytest.param(
                commands_link,
                "LinkProvider",
                f"adr_link_{_kind}_add",
                f"{_kind}_add",
                {
                    "endpoint_name": "endpoint",
                    "namespace_name": NS,
                    "resource_group_name": RG,
                    _resource_argument: "/resource/id",
                },
                id=f"link-{_kind}-add",
            ),
            pytest.param(
                commands_link,
                "LinkProvider",
                f"adr_link_{_kind}_show",
                f"{_kind}_show",
                {
                    "endpoint_name": "endpoint",
                    "namespace_name": NS,
                    "resource_group_name": RG,
                },
                id=f"link-{_kind}-show",
            ),
            pytest.param(
                commands_link,
                "LinkProvider",
                f"adr_link_{_kind}_list",
                f"{_kind}_list",
                {"namespace_name": NS, "resource_group_name": RG},
                id=f"link-{_kind}-list",
            ),
        ]
    )
    if _kind != "hub":
        _SIMPLE_COMMAND_CASES.append(
            pytest.param(
                commands_link,
                "LinkProvider",
                f"adr_link_{_kind}_update",
                f"{_kind}_update",
                {
                    "endpoint_name": "endpoint",
                    "namespace_name": NS,
                    "resource_group_name": RG,
                },
                id=f"link-{_kind}-update",
            )
        )

_SIMPLE_COMMAND_CASES.append(
    pytest.param(
        commands_link,
        "LinkProvider",
        "adr_link_add",
        "link_add",
        {
            "namespace_name": NS,
            "resource_group_name": RG,
            "hub_endpoint_name": "hub",
            "hub_resource_id": "/hubs/hub",
            "dps_endpoint_name": "dps",
            "dps_resource_id": "/dps/dps",
        },
        id="link-bundled-add",
    )
)


@pytest.mark.parametrize(
    "module,provider_name,command_name,provider_method,kwargs",
    _SIMPLE_COMMAND_CASES,
)
def test_simple_command_wrappers_delegate(
    mocker,
    cmd,
    module,
    provider_name,
    command_name,
    provider_method,
    kwargs,
):
    provider = _patch_provider(mocker, module, provider_name)
    command = getattr(module, command_name)
    signature = inspect.signature(command)
    positional = [cmd]
    if "client" in signature.parameters:
        positional.append(Mock())

    command(*positional, **kwargs)

    bound = signature.bind(*positional, **kwargs)
    bound.apply_defaults()
    expected = dict(bound.arguments)
    expected.pop("cmd")
    expected.pop("client", None)
    expected.update(expected.pop("kwargs", {}))
    if module is commands_link and "timeout" in expected:
        timeout = expected.pop("timeout")
        interval = expected.pop("interval")
        expected["timeout_sec"] = 600 if timeout is None else timeout
        expected["wait_sec"] = 30 if interval is None else interval
    getattr(provider, provider_method).assert_called_once_with(**expected)


@pytest.mark.parametrize("kind", ["hub", "dps"])
@pytest.mark.parametrize(
    "options,expected_timeout,expected_interval",
    [
        ({}, 600, 30),
        ({"timeout": None, "interval": None}, 600, 30),
        ({"timeout": 91}, 91, 30),
        ({"interval": 2}, 600, 2),
        ({"timeout": 91, "interval": 2}, 91, 2),
        # Explicit invalid values must reach provider validation, not become defaults.
        ({"timeout": 0, "interval": 0}, 0, 0),
        ({"timeout": -1, "interval": -2}, -1, -2),
    ],
)
@pytest.mark.parametrize("no_wait", [False, True])
def test_link_update_resolves_omitted_recovery_options(
    mocker, cmd, kind, options, expected_timeout, expected_interval, no_wait
):
    provider = _patch_provider(mocker, commands_link, "LinkProvider")
    command = getattr(commands_link, f"adr_link_{kind}_update")

    command(
        cmd,
        Mock(),
        endpoint_name="endpoint",
        namespace_name=NS,
        resource_group_name=RG,
        no_wait=no_wait,
        **options,
    )

    getattr(provider, f"{kind}_update").assert_called_once_with(
        endpoint_name="endpoint",
        namespace_name=NS,
        resource_group_name=RG,
        mi_system_assigned=False,
        mi_user_assigned=None,
        no_wait=no_wait,
        timeout_sec=expected_timeout,
        wait_sec=expected_interval,
    )
