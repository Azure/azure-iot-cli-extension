# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Native CLI compatibility and local-only contracts for ADR review corrections."""

import base64
import hashlib
from pathlib import Path
from shlex import quote

import pytest
import yaml
from azure.cli.core import AzCommandsLoader
from azure.cli.core.commands.events import EVENT_INVOKER_PRE_LOAD_ARGUMENTS
from azure.cli.core.mock import DummyCli
from azure.cli.core.parser import AzCliCommandParser

from azext_iot import IoTExtCommandsLoader
from azext_iot.common.embedded_cli import EmbeddedCLI
from azext_iot.tests.adr import test_adr_validation_scenarios_unit as cli_tests

offline_cli = cli_tests.offline_cli


@pytest.mark.parametrize("hub_option,dps_option,deprecated", [
    ("--hub-name", "--dps-name", True),
    ("--hn", "--dn", True),
    ("--hub-endpoint-name", "--dps-endpoint-name", False),
    ("--hen", "--den", False),
])
def test_composite_label_aliases_warn_through_native_cli(
    offline_cli, mocker, capfd, hub_option, dps_option, deprecated,
):
    provider = mocker.patch("azext_iot.adr.commands_link.LinkProvider").return_value
    provider.link_add.return_value = {"name": "ns"}
    cli = EmbeddedCLI(cli_ctx=offline_cli)
    output = cli.invoke(
        f"iot adr ns link add --ns ns -g rg {hub_option} hub {dps_option} dps "
        "--hub-id /subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/IotHubs/hub "
        "--dps-id /subscriptions/sub/resourceGroups/rg/providers/Microsoft.Devices/provisioningServices/dps "
        "--dps-system-assigned-mi"
    )
    assert output.success(), output.get_error()
    provider.link_add.assert_called_once()
    assert provider.link_add.call_args.kwargs["hub_endpoint_name"] == "hub"
    assert provider.link_add.call_args.kwargs["dps_endpoint_name"] == "dps"
    warnings = capfd.readouterr().err
    if deprecated:
        assert hub_option in warnings and "--hub-endpoint-name" in warnings
        assert dps_option in warnings and "--dps-endpoint-name" in warnings
        assert "deprecated" in warnings.lower()
    else:
        assert "deprecated" not in warnings.lower()


def test_hash_remains_local_through_native_cli(offline_cli, tmp_path):
    payload = b"local ADR payload"
    path = tmp_path / "payload with spaces.bin"
    path.write_bytes(payload)
    output = EmbeddedCLI(cli_ctx=offline_cli).invoke(
        f"iot adr ns su software-update calculate-hash --file-path {quote(str(path))}"
    )
    assert output.success(), output.get_error()
    assert output.as_json() == [{
        "bytes": len(payload), "hash": base64.b64encode(hashlib.sha256(payload).digest()).decode(),
        "hashAlgorithm": "sha256", "uri": path.as_uri(),
    }]


def test_hub_documented_defaults_preserve_all_unspecified_upsert_values():
    name = "iot hub create"
    cli = DummyCli(commands_loader_cls=IoTExtCommandsLoader)
    loader = cli.commands_loader
    loader.skip_applicability = True
    loader.load_command_table(None)
    loader.command_table = {name: loader.command_table[name]}
    cli.raise_event(EVENT_INVOKER_PRE_LOAD_ARGUMENTS, commands_loader=loader)
    loader.load_arguments(name)
    AzCommandsLoader.load_arguments(loader, name)
    parser = AzCliCommandParser(cli_ctx=cli)
    parser.load_command_table(loader)
    args = parser.parse_args(["iot", "hub", "create", "-n", "hub", "-g", "rg"])
    assert (args.sku, args.unit, args.partition_count, args.retention_day) == (None, None, None, None)
    assert args.disable_local_auth is None
    assert args.system_identity is None and args.user_identities is None


def test_retired_asset_commands_have_no_linter_exclusions():
    root = Path(__file__).resolve().parents[3]
    exclusions = yaml.safe_load((root / "linter_exclusions.yml").read_text(encoding="utf-8"))
    assert all(f"iot adr ns {kind} create" not in exclusions for kind in (
        "asset", "discovered-asset", "discovered-device",
    ))
