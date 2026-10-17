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
    adr_link_ops,
    adr_link_wait_ops,
    adr_schema_ops,
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

    def wait_command(self, name, getter_name, **kwargs):
        self._record("wait", name, getter_name, **kwargs)


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


def test_root_loader_lazily_keeps_ignite_adr_and_du_surface(mocker):
    from azure.cli.core.mock import DummyCli

    from azext_iot import IoTExtCommandsLoader

    loader = IoTExtCommandsLoader(DummyCli())
    table = loader.load_command_table([])
    assert "iot adr ns link dps add" in table
    assert "iot adr ns su software-update import" not in table
    assert "iot du account create" in table

    argument_loaders = [
        "azext_iot._params.load_arguments",
        "azext_iot.iothub.params.load_iothub_arguments",
        "azext_iot.central.params.load_central_arguments",
        "azext_iot.digitaltwins.params.load_digitaltwins_arguments",
        "azext_iot.dps.params.load_dps_arguments",
        "azext_iot.deviceupdate.params.load_deviceupdate_arguments",
        "azext_iot.core.params.load_core_arguments",
        "azext_iot.adr.params.load_adr_arguments",
    ]
    patched = [mocker.patch(path) for path in argument_loaders]

    loader.load_arguments("iot adr ns create")

    for argument_loader in patched:
        argument_loader.assert_called_once_with(loader, "iot adr ns create")


def test_2026_command_surface_is_registered():
    commands = _registered_commands()

    expected_commands = {
        "iot adr ns migrate",
        "iot adr ns identity show",
        "iot adr ns identity assign",
        "iot adr ns identity remove",
        "iot adr ns identity wait",
        "iot adr ns ca wait",
        "iot adr ns ca policy wait",

        "iot adr ns link wait",

        "iot adr ns link dps wait",
        "iot adr ns link hub wait",


    }
    assert expected_commands <= set(commands)
    assert "iot adr ns job run create" not in commands
    assert len(commands) == 61
    assert commands["iot adr schema registry create"] == (
        "command", "adr_schema_registry_create", {"supports_no_wait": True},
    )
    assert commands["iot adr schema registry update"] == (
        "command", "adr_schema_registry_update", {"supports_no_wait": True},
    )
    for group, operation in (
        ("iot adr schema", "adr_schema"),
        ("iot adr schema registry", "adr_schema_registry"),
        ("iot adr schema version", "adr_schema_version"),
    ):
        assert commands[f"{group} delete"] == (
            "command", f"{operation}_delete", {"confirmation": True, "supports_no_wait": True},
        )
        assert commands[f"{group} wait"] == ("wait", f"{operation}_show", {})
    for group in ("iot adr schema", "iot adr schema version"):
        assert commands[f"{group} create"][2] == {}
        assert f"{group} update" not in commands
    for endpoint in ("hub", "dps"):
        assert commands[f"iot adr ns link {endpoint} remove"] == (
            "command", f"adr_link_{endpoint}_remove", {"confirmation": True},
        )
        assert hasattr(commands_link, f"adr_link_{endpoint}_remove")
        assert f"iot adr ns link {endpoint} delete" not in commands
    assert commands["iot adr ns migrate"] == (
        "command",
        "adr_namespace_migrate",
        {"supports_no_wait": True},
    )
    expected_wait_operations = {
        "iot adr ns wait": "adr_namespace_wait",
        "iot adr ns ca wait": "adr_ca_wait",
        "iot adr ns ca policy wait": "adr_ca_policy_wait",
        "iot adr ns device wait": "adr_registry_device_wait",

        "iot adr ns identity wait": "adr_namespace_wait",
        "iot adr ns link wait": "adr_link_wait",
        "iot adr ns link hub wait": "adr_link_hub_wait",
        "iot adr ns link dps wait": "adr_link_dps_wait",


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

    assert len(link_commands) == 14
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

    ):
        assert groups[group_name]["command_type"] is adr_link_ops

    link_waits = [
        kwargs
        for group, _, name, _, kwargs in loader.records
        if group.startswith("iot adr ns link") and name == "wait"
    ]
    assert len(link_waits) == 3
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
    assert not any(
        command.startswith(
            (
                "iot adr ns asset",
                "iot adr ns discovered-",
                "iot adr ns management-endpoint",
                "iot adr ns registry-device",
            )
        )
        for command in commands
    )
    for endpoint in ("hub", "dps"):
        assert f"iot adr ns link {endpoint} delete" not in commands
    # Pre-rename spellings must not resurface.
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


def test_all_adr_command_groups_are_ga():
    loader = _CommandLoader()
    load_adr_commands(loader, None)

    assert loader.groups
    assert all(name.startswith("iot adr") for name, _ in loader.groups)
    assert all(options.get("is_preview") is False for _, options in loader.groups)
    for group in ("iot adr schema", "iot adr schema registry", "iot adr schema version"):
        assert dict(loader.groups)[group]["command_type"] is adr_schema_ops


def test_load_adr_arguments():
    loader = _ArgumentLoader()
    load_adr_arguments(loader, None)
    arguments = loader.records

    assert {
        "schema_name", "schema_registry_name", "schema_format", "schema_type",
    } <= set(arguments["iot adr schema"])
    assert "arg_type" not in arguments["iot adr schema"]["schema_format"]
    assert "arg_type" not in arguments["iot adr schema"]["schema_type"]
    assert {
        "schema_registry_name", "registry_namespace", "storage_account_container_url",
    } <= set(arguments["iot adr schema registry"])
    for command in ("iot adr schema registry create", "iot adr schema registry update"):
        assert {
            "mi_system_assigned", "mi_user_assigned",
            "outbound_mi_system_assigned", "outbound_mi_user_assigned",
        } <= set(arguments[command])
    assert {
        "storage_account_resource_id", "storage_container_name", "skip_role_assignment", "custom_role_id",
    }.isdisjoint(arguments["iot adr schema registry"])
    assert {
        "version_name", "schema_name", "schema_registry_name", "schema_content",
    } <= set(arguments["iot adr schema version"])
    assert arguments["iot adr schema version"]["version_name"]["options_list"] == ["--version"]
    assert arguments["iot adr schema version"]["schema_content"]["options_list"] == ["--schema-content"]
    assert arguments["iot adr schema registry"]["storage_account_container_url"]["options_list"] == [
        "--storage-account-container-url", "--container-url",
    ]

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
    assert "observability_enabled" not in arguments["iot adr ns update"]
    assert {"system_assigned", "user_assigned_identities"} <= set(
        arguments["iot adr ns identity assign"]
    )
    assert "--ns" in arguments["iot adr ns link"]["namespace_name"]["options_list"]
    bundled = arguments["iot adr ns link add"]
    assert bundled["hub_endpoint_name"]["options_list"][:2] == [
        "--hub-endpoint-name",
        "--hen",
    ]
    assert bundled["hub_endpoint_name"]["options_list"] == [
        "--hub-endpoint-name",
        "--hen",
    ]
    assert bundled["dps_endpoint_name"]["options_list"][:2] == [
        "--dps-endpoint-name",
        "--den",
    ]
    assert bundled["dps_endpoint_name"]["options_list"] == [
        "--dps-endpoint-name",
        "--den",
    ]
    assert "Wait for DPS linking to succeed" in bundled["no_wait"]["help"]
    for scope, registered in arguments.items():
        if not scope.startswith("iot adr ns link"):
            continue
        assert {"subscription", "_subscription"}.isdisjoint(registered)
        assert not any(
            "--subscription" in settings.get("options_list", [])
            for settings in registered.values()
        )
    assert "validity_days" in arguments["iot adr ns ca policy update"]
    for command in (
        "iot adr ns ca policy create",
        "iot adr ns ca policy update",
    ):
        validity_help = arguments[command]["validity_days"]["help"]
        assert "between 1 and 90 days, inclusive" in validity_help
    assert not any(
        command.startswith("iot adr ns su link") for command in arguments
    )
    assert not any(
        command.startswith("iot adr ns su update") for command in arguments
    )
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
                "iot adr ns registry-device",
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
    } <= set(arguments["iot adr ns link wait"])


def test_every_adr_identity_option_has_canonical_and_compact_names():
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
                ),
                (
                    command,
                    "outbound_mi_user_assigned",
                    "--outbound-user-assigned-mi",
                    "--omi-ua",
                ),
            ]
        )
    for resource in ("hub", "dps"):
        for action in ("add", "update"):
            command = f"iot adr ns link {resource} {action}"
            cases.extend(
                [
                    (
                        command,
                        "mi_system_assigned",
                        "--system-assigned-mi",
                        "--mi-sa",
                    ),
                    (
                        command,
                        "mi_user_assigned",
                        "--user-assigned-mi",
                        "--mi-ua",
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
            ),
            (
                "iot adr ns link add",
                "hub_mi_user_assigned",
                "--hub-user-assigned-mi",
                "--hub-mi-ua",
            ),
            (
                "iot adr ns link add",
                "dps_mi_system_assigned",
                "--dps-system-assigned-mi",
                "--dps-mi-sa",
            ),
            (
                "iot adr ns link add",
                "dps_mi_user_assigned",
                "--dps-user-assigned-mi",
                "--dps-mi-ua",
            ),
        ]
    )

    for command, argument, canonical, compact in cases:
        options = arguments[command][argument]["options_list"]
        assert options == [canonical, compact]

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

    ):
        parameter = inspect.signature(
            getattr(commands_wait, function_name)
        ).parameters["endpoint_name"]
        assert parameter.default is inspect.Parameter.empty


def test_help_surface_matches_ga_commands():
    load_adr_help()

    for command in (


        "iot adr ns migrate",
        "iot adr ns identity assign",


    ):
        assert command in helps
    assert "iot adr ns job run create" not in helps
    for kind in ("hub", "dps"):
        assert f"iot adr ns link {kind} remove" in helps

    for command in ("iot adr ns create", "iot adr ns update"):
        for option in (
            "--messaging-endpoints",
            "--provisioning-endpoints",
            "--updating-endpoints",
        ):
            assert option not in helps[command]
    assert "--observability-enabled" not in helps["iot adr ns create"]
    assert "--observability-enabled" not in helps["iot adr ns update"]
    policy_create_help = " ".join(
        helps["iot adr ns ca policy create"].split()
    )
    assert "below 30" not in policy_create_help
    assert "Central US EUAP" not in policy_create_help
    assert "--validity-days 30" in helps["iot adr ns ca policy create"]
    for action in ("create", "update"):
        policy_help = " ".join(helps[f"iot adr ns ca policy {action}"].split())
        assert "between 1 and 90 days, inclusive" in policy_help
    assert "--validity-days 90" in helps["iot adr ns ca policy update"]
    combined_help = " ".join(helps["iot adr ns link add"].split())
    assert "before submitting a separate Hub update" in combined_help
    assert "--no-wait still waits for this DPS dependency" in combined_help
    assert "Partial completion is not rolled back" in combined_help
    assert "single namespace PATCH" not in combined_help
    assert "one round-trip" not in combined_help

    assert not any(
        command.startswith(
            (
                "iot adr ns credential",
                "iot adr ns policy",
                "iot adr ns asset",
                "iot adr ns discovered-",
                "iot adr ns management-endpoint",
                "iot adr ns registry-device",
            )
        )
        for command in helps
    )
    for endpoint in ("hub", "dps"):
        assert f"iot adr ns link {endpoint} delete" not in helps
        assert f"iot adr ns link {endpoint} remove" in helps
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
