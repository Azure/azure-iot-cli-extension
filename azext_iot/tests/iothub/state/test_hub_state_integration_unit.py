# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from types import SimpleNamespace

import pytest
from azure.cli.core.azclierror import (
    BadRequestError, CLIInternalError, RequiredArgumentMissingError, ResourceNotFoundError,
)

from azext_iot.tests.iothub.state import test_hub_state_int as subject


@pytest.fixture
def fake_cli(mocker):
    client = SimpleNamespace(
        exception_handler=mocker.Mock(return_value=1),
        result=SimpleNamespace(error=None),
    )
    mocker.patch.object(subject.cli, "az_cli", client)
    return client


@pytest.mark.parametrize("failure_kind", ["cli_error", "nonzero", "system_exit"])
@pytest.mark.parametrize("scenario,failed_operation,expected_events", [
    ("test_migrate_dataplane", None, ["migrate", "compare", "cleanup"]),
    ("test_migrate_dataplane", "migrate", ["migrate"]),
    ("test_export_import_dataplane", None, ["export", "compare", "cleanup", "import", "compare"]),
    ("test_export_import_dataplane", "export", ["export"]),
    ("test_export_import_dataplane", "import", ["export", "compare", "cleanup", "import"]),
])
def test_state_command_error_precedes_comparison(
    mocker, fake_cli, scenario, failed_operation, expected_events, failure_kind
):
    events = []
    error = BadRequestError("Original state command failure")
    exit_code = 2 if failure_kind == "system_exit" else 7

    def invoke(args, out_file):
        assert args[:3] == ["iot", "hub", "state"]
        operation = args[3]
        events.append(operation)
        fake_cli.result.error = error if operation == failed_operation and failure_kind == "cli_error" else None
        if operation == failed_operation:
            if failure_kind == "system_exit":
                raise SystemExit(exit_code)
            return exit_code
        out_file.write("{}")
        return 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    mocker.patch.object(subject.time, "sleep")
    mocker.patch.object(subject, "DATAPLANE_AUTH_TYPES", ["login"])
    mocker.patch.object(subject, "compare_hubs_dataplane", side_effect=lambda *args: events.append("compare"))
    mocker.patch.object(subject, "compare_hub_dataplane_to_file", side_effect=lambda *args: events.append("compare"))
    mocker.patch.object(subject, "clean_up_hub_dataplane", side_effect=lambda *args: events.append("cleanup"))
    hubs = [
        {"name": "origin", "rg": "rg", "filename": "state.json"},
        {"name": "destination", "rg": "rg"},
    ]

    if failed_operation:
        expected_error = BadRequestError if failure_kind == "cli_error" else CLIInternalError
        with pytest.raises(expected_error) as raised:
            getattr(subject, scenario)(hubs)
        if failure_kind == "cli_error":
            assert raised.value is error
        else:
            assert str(raised.value) == f"IoT Hub state command failed with exit code {exit_code}."
    else:
        getattr(subject, scenario)(hubs)
    assert events == expected_events


@pytest.mark.parametrize("scenario", [
    "test_mirgate_hub_dataplane_error",
    "test_export_import_migrate_missing_hubs_error",
])
@pytest.mark.parametrize("outcome", ["expected_error", "success", "unrelated_error"])
def test_expected_state_failures_still_assert_original_error(mocker, fake_cli, scenario, outcome):
    def invoke(args, out_file):
        if outcome == "success":
            error = None
        elif outcome == "unrelated_error":
            error = BadRequestError("Unrelated failure")
        elif args[3] == "import" and "-g" not in args:
            error = RequiredArgumentMissingError("Resource group required")
        else:
            error = ResourceNotFoundError("Hub not found")
        fake_cli.result.error = error
        return 1 if error else 0

    fake_cli.invoke = mocker.Mock(side_effect=invoke)
    args = ([{"name": "hub", "rg": "rg"}],) if scenario == "test_mirgate_hub_dataplane_error" else ()
    if outcome == "expected_error":
        getattr(subject, scenario)(*args)
        assert fake_cli.invoke.call_count == (1 if args else 5)
    else:
        with pytest.raises(AssertionError):
            getattr(subject, scenario)(*args)
