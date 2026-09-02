# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Command, argument, and help registration contracts for ADR."""

from unittest.mock import MagicMock

import yaml
from knack.help_files import helps

from azext_iot.adr._help import load_adr_help
from azext_iot.adr.command_map import (
    _DPS_DELETE_CONFIRMATION,
    _HUB_DELETE_CONFIRMATION,
    _SU_DELETE_CONFIRMATION,
    load_adr_commands,
)
from azext_iot.adr.params import load_adr_arguments


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
    assert len(commands) == 107
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
    assert commands["iot adr ns link wait"][:2] == (
        "wait",
        "adr_namespace_show",
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

    assert {
        "messaging_endpoints",
        "provisioning_endpoints",
        "updating_endpoints",
    } <= set(arguments["iot adr ns update"])
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
    # Group is a plain TrackedResource in 2026-11-02-preview: no identity.
    assert "mi_system_assigned" not in arguments["iot adr ns group create"]
    assert "mi_system_assigned" not in arguments["iot adr ns group update"]
    assert "scheduled_time" in arguments["iot adr ns job schedule"]
    assert "run_name" in arguments["iot adr ns job schedule"]
    assert "order_by" in arguments["iot adr ns job run results"]
    assert "order_by" in arguments["iot adr ns job run list"]
    assert "validity_days" in arguments["iot adr ns ca policy update"]
    for name in ("reported_by", "schema", "properties"):
        assert name in arguments["iot adr ns registry-device attribute create"]
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
