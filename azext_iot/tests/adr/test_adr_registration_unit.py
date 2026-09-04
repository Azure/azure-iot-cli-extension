# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command, argument, and help registration contracts for ADR."""

import inspect
from unittest.mock import MagicMock

import yaml
from knack.help_files import helps

from azext_iot.adr._help import load_adr_help
from azext_iot.adr.command_map import (
    _DPS_DELETE_CONFIRMATION,
    _HUB_DELETE_CONFIRMATION,
    _SU_DELETE_CONFIRMATION,
    adr_link_ops,
    adr_link_wait_ops,
    load_adr_commands,
)
from azext_iot.adr.params import load_adr_arguments
from azext_iot.adr import commands_link, commands_wait


class _CommandGroup:
    def __init__(self, name, records):
        self.name = name
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def _record(self, kind, name, operation, **kwargs):
        self.records.append((self.name, kind, name, operation, kwargs))

    def command(self, name, operation, **kwargs):
        self._record("command", name, operation, **kwargs)

    def show_command(self, name, operation, **kwargs):
        self._record("show", name, operation, **kwargs)

    def wait_command(self, name, operation, **kwargs):
        self._record("wait", name, operation, **kwargs)


class _CommandLoader:
    def __init__(self):
        self.records = []
        self.groups = []

    def command_group(self, name, **kwargs):
        self.groups.append((name, kwargs))
        return _CommandGroup(name, self.records)

    @staticmethod
    def deprecate(**kwargs):
        return kwargs


class _ArgumentContext:
    def __init__(self, name, records):
        self.name = name
        self.records = records

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def argument(self, name, **kwargs):
        self.records.setdefault(self.name, {})[name] = kwargs

    @staticmethod
    def deprecate(**kwargs):
        return kwargs


class _ArgumentLoader:
    def __init__(self):
        self.cli_ctx = MagicMock()
        self.records = {}

    def argument_context(self, name):
        return _ArgumentContext(name, self.records)


def _registered_commands():
    loader = _CommandLoader()
    load_adr_commands(loader, None)
    return {
        f"{group} {name}": (kind, operation, kwargs)
        for group, kind, name, operation, kwargs in loader.records
    }


def test_2026_command_surface_is_registered():
    commands = _registered_commands()

    assert commands["iot adr ns group list-members"][1] == "adr_group_list_members"
    assert commands["iot adr ns job run cancel"] == (
        "command",
        "adr_job_run_cancel",
        {"confirmation": True, "supports_no_wait": True},
    )
    assert commands["iot adr ns report generate"] == (
        "command",
        "adr_report_generate",
        {"supports_no_wait": True},
    )
    assert commands["iot adr ns report latest"][1] == "adr_report_latest"
    expected_commands = {
        "iot adr ns registry-device create",
        "iot adr ns registry-device show",
        "iot adr ns registry-device list",
        "iot adr ns registry-device update",
        "iot adr ns registry-device delete",
        "iot adr ns registry-device wait",
        "iot adr ns migrate",
        "iot adr ns registry-device auth list",
        "iot adr ns registry-device auth show",
        "iot adr ns registry-device auth show-keys",
        "iot adr ns registry-device auth revoke-certs",
        "iot adr ns registry-device auth wait",
        "iot adr ns registry-device attribute list",
        "iot adr ns registry-device attribute show",
        "iot adr ns registry-device capability list",
        "iot adr ns registry-device capability show",
        "iot adr ns identity show",
        "iot adr ns identity assign",
        "iot adr ns identity remove",
        "iot adr ns identity wait",
        "iot adr ns ca wait",
        "iot adr ns ca policy wait",
        "iot adr ns job run wait",
        "iot adr ns link wait",
        "iot adr ns link su wait",
        "iot adr ns link su delete",
        "iot adr ns link dps wait",
        "iot adr ns link dps delete",
        "iot adr ns link hub wait",
        "iot adr ns link hub delete",
        "iot adr ns su instance check-name",
        "iot adr ns su instance create",
        "iot adr ns su instance show",
        "iot adr ns su instance list",
        "iot adr ns su instance update",
        "iot adr ns su instance delete",
        "iot adr ns su instance wait",
        "iot adr ns su software-update import",
        "iot adr ns su software-update stage",
        "iot adr ns su software-update list",
        "iot adr ns su software-update show",
        "iot adr ns su software-update delete",
        "iot adr ns su software-update calculate-hash",
        "iot adr ns su software-update file list",
        "iot adr ns su software-update file show",
        "iot adr ns su software-update operation-status list",
        "iot adr ns su software-update operation-status show",
        "iot adr ns su software-update catalog provider list",
        "iot adr ns su software-update catalog name list",
        "iot adr ns su software-update catalog version list",
        "iot adr ns su software-update init v5",
        "iot adr ns su software-update wait",
        "iot adr ns su device-class list",
        "iot adr ns su device-class show",
        "iot adr ns su device-class delete",
        "iot adr ns job schedule",
        "iot adr ns job run delete",
        "iot adr ns job run summary",
        "iot adr ns registry-device attribute create",
        "iot adr ns registry-device attribute delete",
    }
    assert expected_commands <= set(commands)
    # There is no Jobs_Schedule API; `job schedule` drives JobRuns_CreateOrReplace.
    assert "iot adr ns job run create" not in commands
    # Groups_CreateOrReplace / Groups_Update are synchronous in 2026-11-02-preview.
    assert commands["iot adr ns group create"] == ("command", "adr_group_create", {})
    assert commands["iot adr ns group update"] == ("command", "adr_group_update", {})
    assert commands["iot adr ns job schedule"] == (
        "command",
        "adr_job_schedule",
        {"supports_no_wait": True},
    )
    assert commands["iot adr ns job run delete"] == (
        "command",
        "adr_job_run_delete",
        {"confirmation": True, "supports_no_wait": True},
    )
    assert len(commands) == 112
    confirmations = {
        "hub": _HUB_DELETE_CONFIRMATION,
        "dps": _DPS_DELETE_CONFIRMATION,
        "su": _SU_DELETE_CONFIRMATION,
    }
    for endpoint in ("hub", "dps", "su"):
        assert commands[f"iot adr ns link {endpoint} delete"] == (
            "command",
            f"adr_link_{endpoint}_delete",
            {
                "confirmation": confirmations[endpoint],
                "supports_no_wait": True,
            },
        )
    assert commands[
        "iot adr ns registry-device auth revoke-certs"
    ][2] == {"confirmation": True, "supports_no_wait": True}
    assert commands["iot adr ns migrate"] == (
        "command",
        "adr_namespace_migrate",
        {"supports_no_wait": True},
    )
    expected_wait_operations = {
        "iot adr ns wait": "adr_namespace_wait",
        "iot adr ns ca wait": "adr_ca_wait",
        "iot adr ns ca policy wait": "adr_ca_policy_wait",
        "iot adr ns registry-device wait": "adr_registry_device_wait",
        "iot adr ns registry-device auth wait": "adr_registry_device_auth_wait",
        "iot adr ns identity wait": "adr_namespace_wait",
        "iot adr ns link wait": "adr_link_wait",
        "iot adr ns link hub wait": "adr_link_hub_wait",
        "iot adr ns link dps wait": "adr_link_dps_wait",
        "iot adr ns link su wait": "adr_link_su_wait",
        "iot adr ns su instance wait": "adr_su_instance_wait",
        "iot adr ns su software-update wait": "adr_su_software_update_wait",
        "iot adr ns group wait": "adr_group_wait",
        "iot adr ns job wait": "adr_job_wait",
        "iot adr ns job run wait": "adr_job_run_wait",
    }
    for command, operation in expected_wait_operations.items():
        assert commands[command][0:2] == ("command", operation)


def test_all_link_commands_receive_factory_client_without_subscription_arg():
    commands = _registered_commands()
    link_commands = {
        name: metadata
        for name, metadata in commands.items()
        if name == "iot adr ns link add"
        or name == "iot adr ns link wait"
        or name.startswith("iot adr ns link hub ")
        or name.startswith("iot adr ns link dps ")
        or name.startswith("iot adr ns link su ")
    }

    assert len(link_commands) == 20
    for _, operation, _ in link_commands.values():
        module = commands_wait if operation.endswith("_wait") else commands_link
        parameters = inspect.signature(getattr(module, operation)).parameters
        assert "client" in parameters
        # --subscription remains Azure CLI's single global _subscription
        # action; registering either spelling here would collide with it.
        assert "subscription" not in parameters
        assert "_subscription" not in parameters


def test_all_link_groups_and_waits_use_namespace_client_factory():
    loader = _CommandLoader()
    load_adr_commands(loader, None)
    groups = dict(loader.groups)
    for group_name in (
        "iot adr ns link",
        "iot adr ns link hub",
        "iot adr ns link dps",
        "iot adr ns link su",
    ):
        assert groups[group_name]["command_type"] is adr_link_ops

    link_waits = [
        kwargs
        for group, _, name, _, kwargs in loader.records
        if group.startswith("iot adr ns link") and name == "wait"
    ]
    assert len(link_waits) == 4
    assert all(
        kwargs["command_type"] is adr_link_wait_ops
        for kwargs in link_waits
    )


def test_unsupported_command_surfaces_are_not_registered():
    commands = _registered_commands()

    assert not any(
        command.startswith(("iot adr ns credential", "iot adr ns policy"))
        for command in commands
    )
    # auth and capability remain service-materialized (read-only).
    # attribute gained create/delete in 2026-11-02-preview.
    for child in ("auth", "capability"):
        assert f"iot adr ns registry-device {child} create" not in commands
        assert f"iot adr ns registry-device {child} update" not in commands
        assert f"iot adr ns registry-device {child} delete" not in commands
    assert "iot adr ns registry-device attribute update" not in commands
    assert not any(
        command.startswith(
            (
                "iot adr ns asset",
                "iot adr ns discovered-",
                "iot adr ns management-endpoint",
                "iot adr ns device",
            )
        )
        for command in commands
    )
    for endpoint in ("hub", "dps", "su"):
        assert f"iot adr ns link {endpoint} remove" not in commands
    # Pre-rename spellings must not resurface.
    for stale in (
        "iot adr ns registry-device auth-profile list",
        "iot adr ns registry-device auth-profile show",
        "iot adr ns registry-device auth-profile get-keys",
        "iot adr ns registry-device auth-profile revoke-certificates",
    ):
        assert stale not in commands
    assert not any(
        command.startswith("iot adr ns su link") for command in commands
    )
    assert not any(
        command.startswith("iot adr ns su update") for command in commands
    )
    for operation in (
        "link-preflight",
        "link-initiate",
        "link-notify",
        "link-update",
    ):
        assert f"iot adr ns su instance {operation}" not in commands
    for command in (
        "iot adr ns su enable",
        "iot adr ns su device-class update",
    ):
        assert command not in commands


def test_all_adr_namespace_command_groups_are_preview():
    loader = _CommandLoader()
    load_adr_commands(loader, None)

    assert loader.groups
    assert all(name.startswith("iot adr ns") for name, _ in loader.groups)
    assert all(options.get("is_preview") is True for _, options in loader.groups)


def test_load_adr_arguments():
    loader = _ArgumentLoader()
    load_adr_arguments(loader, None)
    arguments = loader.records

    assert {"page_size", "skip_token"} <= set(
        arguments["iot adr ns group list-members"]
    )
    assert "status_filter" in arguments["iot adr ns job run list"]
    assert "status_filter" in arguments["iot adr ns job run results"]
    assert {"report_type", "group_name"} <= set(arguments["iot adr ns report"])

    removed_endpoint_arguments = {
        "messaging_endpoints",
        "provisioning_endpoints",
        "updating_endpoints",
    }
    for command in ("iot adr ns create", "iot adr ns update"):
        assert removed_endpoint_arguments.isdisjoint(arguments[command])
        registered_options = {
            option
            for settings in arguments[command].values()
            for option in settings.get("options_list", [])
            if isinstance(option, str)
        }
        assert {
            "--messaging-endpoints",
            "--provisioning-endpoints",
            "--updating-endpoints",
        }.isdisjoint(registered_options)
    assert "observability_enabled" not in arguments["iot adr ns create"]
    assert "observability_enabled" in arguments["iot adr ns update"]
    assert {
        "enablement_state",
        "external_device_id",
        "hardware_revision",
        "software_revision",
    } <= set(arguments["iot adr ns registry-device create"])
    assert "external_device_id" not in arguments[
        "iot adr ns registry-device update"
    ]
    for command in (
        "iot adr ns registry-device show",
        "iot adr ns registry-device wait",
    ):
        assert arguments[command]["external_device_id"]["options_list"] == [
            "--external-device-id",
            "--ext-id",
        ]
    for command in (
        "iot adr ns registry-device create",
        "iot adr ns registry-device update",
    ):
        for argument in (
            "manufacturer",
            "model",
            "hardware_revision",
            "software_revision",
        ):
            assert arguments[command][argument]["help"]
    assert {"system_assigned", "user_assigned_identities"} <= set(
        arguments["iot adr ns identity assign"]
    )
    assert "--ns" in arguments["iot adr ns link"]["namespace_name"]["options_list"]
    bundled = arguments["iot adr ns link add"]
    assert bundled["hub_endpoint_name"]["options_list"][:2] == [
        "--hub-endpoint-name",
        "--hen",
    ]
    assert "--hub-name" in bundled["hub_endpoint_name"]["options_list"]
    assert bundled["dps_endpoint_name"]["options_list"][:2] == [
        "--dps-endpoint-name",
        "--den",
    ]
    assert "--dps-name" in bundled["dps_endpoint_name"]["options_list"]
    for scope, registered in arguments.items():
        if not scope.startswith("iot adr ns link"):
            continue
        assert {"subscription", "_subscription"}.isdisjoint(registered)
        assert not any(
            "--subscription" in settings.get("options_list", [])
            for settings in registered.values()
        )
    # Group is a plain TrackedResource in 2026-11-02-preview: no identity.
    assert "mi_system_assigned" not in arguments["iot adr ns group create"]
    assert "mi_system_assigned" not in arguments["iot adr ns group update"]
    assert "scheduled_time" in arguments["iot adr ns job schedule"]
    assert "run_name" in arguments["iot adr ns job schedule"]
    assert "order_by" in arguments["iot adr ns job run results"]
    assert "order_by" in arguments["iot adr ns job run list"]
    assert "validity_days" in arguments["iot adr ns ca policy update"]
    for command in (
        "iot adr ns ca policy create",
        "iot adr ns ca policy update",
    ):
        validity_help = arguments[command]["validity_days"]["help"]
        assert "7" in validity_help
        assert "90" in validity_help
        assert "inclusive" in validity_help
    for name in ("reported_by", "schema", "properties"):
        assert name in arguments["iot adr ns registry-device attribute create"]
    reported_by = arguments[
        "iot adr ns registry-device attribute create"
    ]["reported_by"]
    assert reported_by["deprecate_info"]["hide"] is True
    assert {
        "mi_system_assigned",
        "mi_user_assigned",
        "location",
        "tags",
    } <= set(arguments["iot adr ns su instance create"])
    assert {
        "mi_system_assigned",
        "mi_user_assigned",
        "tags",
    } <= set(arguments["iot adr ns su instance update"])
    assert "--su-id" in arguments["iot adr ns link su add"][
        "su_resource_id"
    ]["options_list"]
    assert not any(
        command.startswith("iot adr ns su link") for command in arguments
    )
    assert not any(
        command.startswith("iot adr ns su update") for command in arguments
    )
    assert {
        "update_name",
        "update_provider",
        "update_version",
    } <= set(arguments["iot adr ns su software-update"])
    assert {"url", "size", "hashes", "files", "enable_scan"} <= set(
        arguments["iot adr ns su software-update import"]
    )
    assert {
        "manifest_paths",
        "storage_account",
        "storage_container_name",
        "storage_account_subscription",
        "storage_prefix",
        "friendly_name",
        "enable_scan",
        "overwrite",
        "then_import",
        "sas_expiry_hours",
    } <= set(arguments["iot adr ns su software-update stage"])
    assert {"search", "filter"} <= set(
        arguments["iot adr ns su software-update list"]
    )
    assert "update_file_id" in arguments["iot adr ns su software-update file"]
    assert {"file_paths", "hash_algo"} <= set(
        arguments["iot adr ns su software-update calculate-hash"]
    )
    assert {
        "compatibility",
        "steps",
        "files",
        "related_files",
        "no_validation",
    } <= set(arguments["iot adr ns su software-update init"])
    assert "device_class_id" in arguments["iot adr ns su device-class"]
    assert "resource_ids" in arguments["iot adr ns migrate"]
    assert arguments["iot adr ns migrate"]["resource_ids"]["required"] is True

    assert not any(
        command.startswith(("iot adr ns credential", "iot adr ns policy"))
        for command in arguments
    )
    assert {
        "policy_name",
        "certificate_key_type",
        "certificate_validity_days",
    }.isdisjoint(arguments["iot adr ns create"])
    assert {
        "availability",
        "allocation_weight",
    }.isdisjoint(arguments["iot adr ns link hub update"])
    assert not any(
        "delete_linked_resource" in command_arguments
        for command_arguments in arguments.values()
    )

    assert not any(
        command.startswith(
            (
                "iot adr ns asset",
                "iot adr ns discovered-",
                "iot adr ns management-endpoint",
                "iot adr ns device",
            )
        )
        for command in arguments
    )
    assert not any(
        command.startswith("iot adr ns link") and command.endswith(" remove")
        for command in arguments
    )

    for command in (
        "iot adr ns wait",
        "iot adr ns link hub wait",
        "iot adr ns group wait",
        "iot adr ns job run wait",
    ):
        assert {
            "timeout",
            "interval",
            "created",
            "updated",
            "deleted",
            "exists",
            "custom",
        } <= set(arguments[command])

    assert {
        "hub_endpoint_name",
        "dps_endpoint_name",
        "su_endpoint_name",
    } <= set(arguments["iot adr ns link wait"])


def test_every_adr_identity_option_has_canonical_compact_and_hidden_legacy_names():
    loader = _ArgumentLoader()
    load_adr_arguments(loader, None)
    arguments = loader.records

    cases = []
    for command in ("iot adr ns create", "iot adr ns update"):
        cases.extend(
            [
                (
                    command,
                    "outbound_mi_system_assigned",
                    "--outbound-system-assigned-mi",
                    "--omi-sa",
                    "--outbound-mi-system-assigned",
                ),
                (
                    command,
                    "outbound_mi_user_assigned",
                    "--outbound-user-assigned-mi",
                    "--omi-ua",
                    "--outbound-mi-user-assigned",
                ),
            ]
        )
    for resource in ("hub", "dps", "su"):
        for action in ("add", "update"):
            command = f"iot adr ns link {resource} {action}"
            cases.extend(
                [
                    (
                        command,
                        "mi_system_assigned",
                        "--system-assigned-mi",
                        "--mi-sa",
                        "--mi-system-assigned",
                    ),
                    (
                        command,
                        "mi_user_assigned",
                        "--user-assigned-mi",
                        "--mi-ua",
                        "--mi-user-assigned",
                    ),
                ]
            )
    for action in ("create", "update"):
        command = f"iot adr ns su instance {action}"
        cases.extend(
            [
                (
                    command,
                    "mi_system_assigned",
                    "--system-assigned-mi",
                    "--mi-sa",
                    "--mi-system-assigned",
                ),
                (
                    command,
                    "mi_user_assigned",
                    "--user-assigned-mi",
                    "--mi-ua",
                    "--mi-user-assigned",
                ),
            ]
        )
    cases.extend(
        [
            (
                "iot adr ns link add",
                "hub_mi_system_assigned",
                "--hub-system-assigned-mi",
                "--hub-mi-sa",
                "--hub-mi-system-assigned",
            ),
            (
                "iot adr ns link add",
                "hub_mi_user_assigned",
                "--hub-user-assigned-mi",
                "--hub-mi-ua",
                "--hub-mi-user-assigned",
            ),
            (
                "iot adr ns link add",
                "dps_mi_system_assigned",
                "--dps-system-assigned-mi",
                "--dps-mi-sa",
                "--dps-mi-system-assigned",
            ),
            (
                "iot adr ns link add",
                "dps_mi_user_assigned",
                "--dps-user-assigned-mi",
                "--dps-mi-ua",
                "--dps-mi-user-assigned",
            ),
        ]
    )

    for command, argument, canonical, compact, legacy in cases:
        options = arguments[command][argument]["options_list"]
        assert options[:2] == [canonical, compact]
        assert any(
            isinstance(option, dict)
            and option.get("target") == legacy
            and option.get("redirect") == canonical
            and option.get("hide") is True
            for option in options
        ), (command, argument)

    for command in (
        "iot adr ns identity assign",
        "iot adr ns identity remove",
    ):
        assert arguments[command]["system_assigned"]["options_list"] == [
            "--system-assigned",
            "--system",
        ]
        assert arguments[command]["user_assigned_identities"][
            "options_list"
        ] == ["--user-assigned-identity", "--user"]


def test_endpoint_wait_wrappers_require_an_endpoint_name():
    for function_name in (
        "adr_link_hub_wait",
        "adr_link_dps_wait",
        "adr_link_su_wait",
    ):
        parameter = inspect.signature(
            getattr(commands_wait, function_name)
        ).parameters["endpoint_name"]
        assert parameter.default is inspect.Parameter.empty


def test_help_surface_matches_2026_commands_and_su_type():
    load_adr_help()

    for command in (
        "iot adr ns group list-members",
        "iot adr ns job run cancel",
        "iot adr ns report generate",
        "iot adr ns report latest",
        "iot adr ns registry-device create",
        "iot adr ns migrate",
        "iot adr ns registry-device auth show-keys",
        "iot adr ns registry-device auth wait",
        "iot adr ns registry-device attribute list",
        "iot adr ns registry-device capability show",
        "iot adr ns identity assign",
        "iot adr ns su instance create",
        "iot adr ns su instance check-name",
        "iot adr ns su software-update import",
        "iot adr ns su software-update stage",
        "iot adr ns su software-update list",
        "iot adr ns su software-update show",
        "iot adr ns su software-update delete",
        "iot adr ns su software-update calculate-hash",
        "iot adr ns su software-update file list",
        "iot adr ns su software-update file show",
        "iot adr ns su software-update init v5",
        "iot adr ns su software-update wait",
        "iot adr ns su device-class list",
        "iot adr ns su device-class show",
        "iot adr ns su device-class delete",
        "iot adr ns job schedule",
        "iot adr ns job run delete",
        "iot adr ns job run summary",
        "iot adr ns registry-device attribute create",
        "iot adr ns registry-device attribute delete",
        "iot adr ns link hub delete",
        "iot adr ns link dps delete",
        "iot adr ns link su delete",
    ):
        assert command in helps
    assert "iot adr ns job run create" not in helps

    assert "Microsoft.DeviceUpdate/updateInstances" in helps["iot adr ns link su"]
    assert "linkedAccounts" not in helps["iot adr ns link su"]
    for command in ("iot adr ns create", "iot adr ns update"):
        for option in (
            "--messaging-endpoints",
            "--provisioning-endpoints",
            "--updating-endpoints",
        ):
            assert option not in helps[command]
    assert "--observability-enabled" not in helps["iot adr ns create"]
    assert "--observability-enabled" in helps["iot adr ns update"]
    policy_create_help = " ".join(
        helps["iot adr ns ca policy create"].split()
    )
    assert "between 7 and 90 days" in policy_create_help
    assert "--validity-days 7" in helps["iot adr ns ca policy create"]
    assert "--validity-days 90" in helps["iot adr ns ca policy update"]
    assert "starts its initial membership calculation" in helps[
        "iot adr ns group create"
    ]
    assert "once per hour" in helps["iot adr ns group refresh"]

    assert not any(
        command.startswith(
            (
                "iot adr ns credential",
                "iot adr ns policy",
                "iot adr ns asset",
                "iot adr ns discovered-",
                "iot adr ns management-endpoint",
                "iot adr ns device",
            )
        )
        for command in helps
    )
    for endpoint in ("hub", "dps", "su"):
        assert f"iot adr ns link {endpoint} remove" not in helps
        delete_help = helps[f"iot adr ns link {endpoint} delete"]
        assert "Permanently delete" in delete_help
        assert "namespace" in delete_help
        assert "--delete-linked-resource" not in delete_help
    assert not any(command.startswith("iot adr ns su link") for command in helps)
    assert not any(
        command.startswith("iot adr ns su update") for command in helps
    )
    assert "iot adr ns su device-class update" not in helps


def test_every_registered_adr_command_has_help():
    load_adr_help()
    assert set(_registered_commands()) <= set(helps)


def test_all_adr_help_is_valid_yaml():
    load_adr_help()

    for command, help_text in helps.items():
        if command.startswith("iot adr"):
            assert isinstance(yaml.safe_load(help_text), dict), command
