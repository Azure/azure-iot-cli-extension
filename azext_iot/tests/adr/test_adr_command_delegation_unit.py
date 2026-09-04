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
    commands_group,
    commands_job,
    commands_job_run,
    commands_link,
    commands_namespace,
    commands_report,
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
        assert "observability_enabled" in inspect.signature(
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
            observability_enabled=True,
            no_wait=True,
        )
        provider.update.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            tags={"a": "b"},
            observability_enabled=True,
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


class TestGroupCommands:
    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_forwards_mutable_fields(self, mocker, cmd, operation):
        """Group create/update are synchronous and carry no identity in 2026-11-02-preview."""
        provider = _patch_provider(mocker, commands_group, "GroupProvider")
        kwargs = {
            "group_name": "group",
            "namespace_name": NS,
            "resource_group_name": RG,
            "display_name": "Display",
            "description": "Description",
            "tags": {"a": "b"},
        }
        if operation == "create":
            kwargs["query_string"] = "*"

        getattr(commands_group, f"adr_group_{operation}")(cmd, **kwargs)

        expected = dict(kwargs)
        if operation == "create":
            expected.update({"group_type": "RegistryDevice", "location": None})
        getattr(provider, operation).assert_called_once_with(**expected)

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_rejects_identity_and_no_wait(self, cmd, operation):
        """--system-assigned-mi and --no-wait were dropped for groups."""
        command = getattr(commands_group, f"adr_group_{operation}")
        signature = inspect.signature(command)
        assert "mi_system_assigned" not in signature.parameters
        assert "no_wait" not in signature.parameters

    def test_list_members(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_group, "GroupProvider")
        commands_group.adr_group_list_members(
            cmd,
            group_name="group",
            namespace_name=NS,
            resource_group_name=RG,
            page_size=100,
            skip_token="token",
        )
        provider.list_members.assert_called_once_with(
            group_name="group",
            namespace_name=NS,
            resource_group_name=RG,
            page_size=100,
            skip_token="token",
        )

    def test_count(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_group, "GroupProvider")
        commands_group.adr_group_count(
            cmd, group_name="group", namespace_name=NS, resource_group_name=RG
        )
        provider.count.assert_called_once_with(
            group_name="group", namespace_name=NS, resource_group_name=RG
        )

    def test_delete_no_wait(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_group, "GroupProvider")
        commands_group.adr_group_delete(
            cmd,
            group_name="group",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )
        provider.delete.assert_called_once_with(
            group_name="group",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )


class TestJobCommands:
    def test_create_forwards_2026_fields(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job, "JobProvider")
        commands_job.adr_job_create(
            cmd,
            job_name="job",
            namespace_name=NS,
            resource_group_name=RG,
            update_provider="Contoso",
            update_name="firmware",
            update_version="1.0",
            target_group_name="group",
            job_type="SoftwareUpdate",
            description="description",
            display_name="Display",
            location="westus",
            tags={"a": "b"},
            no_wait=True,
        )
        provider.create.assert_called_once_with(
            job_name="job",
            namespace_name=NS,
            resource_group_name=RG,
            update_provider="Contoso",
            update_name="firmware",
            update_version="1.0",
            target_group_name="group",
            job_type="SoftwareUpdate",
            description="description",
            display_name="Display",
            location="westus",
            tags={"a": "b"},
            no_wait=True,
        )

    def test_schedule_forwards_scheduled_time(self, mocker, cmd):
        """`job schedule` lives on the job group but drives JobRuns_CreateOrReplace."""
        provider = _patch_provider(mocker, commands_job, "JobRunProvider")
        commands_job.adr_job_schedule(
            cmd,
            job_name="job",
            namespace_name=NS,
            resource_group_name=RG,
            run_name="run",
            scheduled_time="2026-11-02T12:00:00+00:00",
            no_wait=True,
        )
        provider.create.assert_called_once_with(
            job_name="job",
            namespace_name=NS,
            resource_group_name=RG,
            run_name="run",
            scheduled_time="2026-11-02T12:00:00+00:00",
            no_wait=True,
        )

    def test_schedule_run_name_is_optional(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job, "JobRunProvider")
        commands_job.adr_job_schedule(
            cmd, job_name="job", namespace_name=NS, resource_group_name=RG
        )
        assert provider.create.call_args.kwargs["run_name"] is None

    def test_job_run_create_command_does_not_exist(self):
        """Scheduling is exposed as `job schedule`, not `job run create`."""
        assert not hasattr(commands_job_run, "adr_job_run_create")


class TestJobRunLifecycleCommands:
    def test_delete(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job_run, "JobRunProvider")
        commands_job_run.adr_job_run_delete(
            cmd,
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )
        provider.delete.assert_called_once_with(
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )

    def test_summary(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job_run, "JobRunProvider")
        commands_job_run.adr_job_run_summary(
            cmd,
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
        )
        provider.summary.assert_called_once_with(
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
        )


class TestJobRunCommands:
    def test_list_by_namespace_with_filter(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job_run, "JobRunProvider")
        commands_job_run.adr_job_run_list(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            status_filter="status eq 'Active'",
        )
        provider.list.assert_called_once_with(
            job_name=None,
            namespace_name=NS,
            resource_group_name=RG,
            status_filter="status eq 'Active'",
            order_by=None,
        )

    def test_results_flattens_provider_iterator(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job_run, "JobRunProvider")
        provider.results.return_value = iter([{"device": "one"}, {"device": "two"}])
        result = commands_job_run.adr_job_run_results(
            cmd,
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            status_filter="status eq 'Failed'",
            order_by="status asc",
        )
        assert result == [{"device": "one"}, {"device": "two"}]
        provider.results.assert_called_once_with(
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            status_filter="status eq 'Failed'",
            order_by="status asc",
        )

    def test_cancel(self, mocker, cmd):
        provider = _patch_provider(mocker, commands_job_run, "JobRunProvider")
        commands_job_run.adr_job_run_cancel(
            cmd,
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )
        provider.cancel.assert_called_once_with(
            job_name="job",
            run_name="run",
            namespace_name=NS,
            resource_group_name=RG,
            no_wait=True,
        )


class TestReportCommands:
    @pytest.mark.parametrize(
        "report_type,group_name",
        [
            ("NamespaceUpdateComplianceReport", None),
            ("GroupBestUpdatesComplianceReport", "group"),
            ("GroupInstallableUpdatesReport", "group"),
        ],
    )
    def test_generate_all_report_types(
        self, mocker, cmd, report_type, group_name
    ):
        provider = _patch_provider(mocker, commands_report, "ReportProvider")
        commands_report.adr_report_generate(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            report_type=report_type,
            group_name=group_name,
            no_wait=True,
        )
        provider.generate.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            report_type=report_type,
            group_name=group_name,
            no_wait=True,
        )

    @pytest.mark.parametrize(
        "report_type,group_name",
        [
            ("NamespaceUpdateComplianceReport", None),
            ("GroupBestUpdatesComplianceReport", "group"),
            ("GroupInstallableUpdatesReport", "group"),
        ],
    )
    def test_latest_all_report_types(
        self, mocker, cmd, report_type, group_name
    ):
        provider = _patch_provider(mocker, commands_report, "ReportProvider")
        commands_report.adr_report_latest(
            cmd,
            namespace_name=NS,
            resource_group_name=RG,
            report_type=report_type,
            group_name=group_name,
        )
        provider.latest.assert_called_once_with(
            namespace_name=NS,
            resource_group_name=RG,
            report_type=report_type,
            group_name=group_name,
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
    )


@pytest.mark.parametrize("kind", ["hub", "dps", "su"])
def test_link_delete_delegates_no_wait(mocker, cmd, kind):
    provider = _patch_provider(mocker, commands_link, "LinkProvider")
    namespace_client = Mock()

    getattr(commands_link, f"adr_link_{kind}_delete")(
        cmd,
        namespace_client,
        endpoint_name="endpoint",
        namespace_name=NS,
        resource_group_name=RG,
        no_wait=True,
    )

    getattr(provider, f"{kind}_delete").assert_called_once_with(
        endpoint_name="endpoint",
        namespace_name=NS,
        resource_group_name=RG,
        no_wait=True,
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
            "adr_link_hub_delete",
            "hub_delete",
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
            "adr_link_dps_delete",
            "dps_delete",
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
        (
            "adr_link_su_add",
            "su_add",
            {
                "endpoint_name": "su",
                "namespace_name": NS,
                "resource_group_name": RG,
                "su_resource_id": "su-id",
            },
        ),
        (
            "adr_link_su_update",
            "su_update",
            {
                "endpoint_name": "su",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_su_delete",
            "su_delete",
            {
                "endpoint_name": "su",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_su_show",
            "su_show",
            {
                "endpoint_name": "su",
                "namespace_name": NS,
                "resource_group_name": RG,
            },
        ),
        (
            "adr_link_su_list",
            "su_list",
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
        tags={"env": "test"},
        validity_days=15,
    )
    provider.update.assert_called_once_with(
        certificate_policy_name="policy",
        certificate_authority_name="ca",
        namespace_name=NS,
        resource_group_name=RG,
        tags={"env": "test"},
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
    pytest.param(
        commands_group,
        "GroupProvider",
        "adr_group_create",
        "create",
        {
            "group_name": "group",
            "namespace_name": NS,
            "resource_group_name": RG,
            "query_string": "SELECT * FROM DEVICE",
        },
        id="group-create",
    ),
    pytest.param(
        commands_group,
        "GroupProvider",
        "adr_group_update",
        "update",
        {
            "group_name": "group",
            "namespace_name": NS,
            "resource_group_name": RG,
        },
        id="group-update",
    ),
    pytest.param(
        commands_group,
        "GroupProvider",
        "adr_group_show",
        "show",
        {
            "group_name": "group",
            "namespace_name": NS,
            "resource_group_name": RG,
        },
        id="group-show",
    ),
    pytest.param(
        commands_group,
        "GroupProvider",
        "adr_group_list",
        "list",
        {"namespace_name": NS, "resource_group_name": RG},
        id="group-list",
    ),
    pytest.param(
        commands_group,
        "GroupProvider",
        "adr_group_refresh",
        "refresh",
        {
            "group_name": "group",
            "namespace_name": NS,
            "resource_group_name": RG,
        },
        id="group-refresh",
    ),
    pytest.param(
        commands_job,
        "JobProvider",
        "adr_job_update",
        "update",
        {"job_name": "job", "namespace_name": NS, "resource_group_name": RG},
        id="job-update",
    ),
    pytest.param(
        commands_job,
        "JobProvider",
        "adr_job_show",
        "show",
        {"job_name": "job", "namespace_name": NS, "resource_group_name": RG},
        id="job-show",
    ),
    pytest.param(
        commands_job,
        "JobProvider",
        "adr_job_list",
        "list",
        {"namespace_name": NS, "resource_group_name": RG},
        id="job-list",
    ),
    pytest.param(
        commands_job,
        "JobProvider",
        "adr_job_delete",
        "delete",
        {"job_name": "job", "namespace_name": NS, "resource_group_name": RG},
        id="job-delete",
    ),
    pytest.param(
        commands_job_run,
        "JobRunProvider",
        "adr_job_run_show",
        "show",
        {
            "job_name": "job",
            "run_name": "run",
            "namespace_name": NS,
            "resource_group_name": RG,
        },
        id="job-run-show",
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
    ("su", "su_resource_id"),
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
    getattr(provider, provider_method).assert_called_once_with(**expected)
