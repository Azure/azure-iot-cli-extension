# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Smoke tests that exercise the DPS command/argument registration modules.

These modules are declarative (command-to-implementation maps and argument
definitions) and contain no runtime business logic. Invoking the loader
functions with a mock command loader executes every registration line, which
catches import errors, typos in implementation references, and malformed
argument declarations without requiring a live Azure CLI command table.
"""

from unittest.mock import MagicMock

import yaml
from knack.help_files import helps

from azext_iot.dps._help import load_deviceprovisioningservice_help
from azext_iot.dps.command_map import load_dps_commands
from azext_iot.dps.params import load_dps_arguments


def test_load_dps_help():
    load_deviceprovisioningservice_help()


def test_help_examples_are_workflow_first_and_keep_contract_warnings():
    load_deviceprovisioningservice_help()
    help_data = yaml.safe_load(helps["iot device registration create"])
    examples = help_data["examples"]
    assert "--auth-type login" in examples[0]["text"]
    assert "--group-id" in examples[1]["text"] and "--compute-key" in examples[1]["text"]
    assert "--id-scope" in examples[2]["text"] and "--symmetric-key" in examples[2]["text"]
    assert "--compute-key" in examples[3]["text"]
    assert "--csr" in examples[4]["text"]
    assert "--certificate-file-path" in examples[5]["text"]
    assert "operation-status" in examples[6]["text"]
    summary = help_data["long-summary"]
    for warning in (
        "after preliminary ID scope", "bootstrap credential discovery", "five-minute",
        "certificate-file output", "certificate\norder", "TPM-only authentication is explicitly unsupported",
        "does not replace", "does not cancel", "not the device registration",
    ):
        assert warning in summary


def test_load_dps_commands():
    load_dps_commands(MagicMock(), None)


def test_load_dps_arguments():
    load_dps_arguments(MagicMock(), None)


def test_registration_timeout_argument_is_integer_and_scoped_to_create():
    loader = MagicMock()
    contexts = {}

    def argument_context(name):
        contexts.setdefault(name, MagicMock())
        return contexts[name]

    loader.argument_context.side_effect = argument_context
    load_dps_arguments(loader, None)
    create = contexts["iot device registration create"].__enter__.return_value
    timeout = next(call for call in create.argument.call_args_list if call.args == ("timeout",))
    assert timeout.kwargs["type"] is int
    assert "Positive integer" in timeout.kwargs["help"]
    for name, context in contexts.items():
        if name != "iot device registration create":
            assert all(call.args != ("timeout",) for call in context.__enter__.return_value.argument.call_args_list)
