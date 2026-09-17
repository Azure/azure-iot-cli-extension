# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from azext_iot.tests.adr import conftest as subject


def _config():
    reporter = Mock()
    config = Mock()
    config.pluginmanager.get_plugin.return_value = reporter
    return config, reporter


def _request(items):
    return SimpleNamespace(config=Mock(), session=SimpleNamespace(items=items))


@pytest.mark.parametrize("relative_path,expected", [
    ("adr/test_example_int.py", True),
    ("adr/nested/test_example_int.py", True),
    ("adr/test_example_unit.py", False),
    ("adr/test_example_int.py.txt", False),
    ("dps/core/test_example_int.py", False),
    ("iothub/core/test_example_int.py", False),
    ("adr_other/test_example_int.py", False),
], ids=["adr", "nested-adr", "unit", "wrong-suffix", "dps", "hub", "sibling"])
def test_preflight_selects_only_real_adr_integration_paths(mocker, relative_path, expected):
    tests_directory = Path(subject.__file__).resolve().parent.parent
    # No nodeid: classification must use the pytest item's actual file path.
    request = _request([SimpleNamespace(path=tests_directory / relative_path)])
    preflight = mocker.patch.object(subject, "run_adr_integration_preflight")

    subject.adr_integration_preflight.__wrapped__(request)

    if expected:
        preflight.assert_called_once_with(request.config)
    else:
        preflight.assert_not_called()


@pytest.mark.parametrize("foreign_node", [
    "azext_iot/tests/iothub/core/test_iothub_discovery_int.py::TestIoTHubDiscovery::test_iothub_targets",
    "azext_iot/tests/iothub/metadata/test_hub_metadata_int.py::test_linked_metadata_state_and_service_bulk_portability",
    "azext_iot/tests/dps/device_registration/test_iot_device_registration_int.py::"
    "test_register_and_issue_certificate_contract[default]",
], ids=["hub-discovery", "hub-metadata", "dps-registration"])
def test_preflight_ignores_cross_module_focused_runner_parameter_ids(mocker, foreign_node):
    tests_directory = Path(subject.__file__).resolve().parent.parent
    request = _request([
        SimpleNamespace(
            path=tests_directory / "adr/test_adr_base_unit.py",
            nodeid="azext_iot/tests/adr/test_adr_base_unit.py::test_ensure_location[location]",
        ),
        SimpleNamespace(
            path=tests_directory / "test_focused_live_runner_unit.py",
            nodeid="azext_iot/tests/test_focused_live_runner_unit.py::"
            f"test_excluded_or_separately_opted_in_nodes_are_not_debug_authority[suite-phase-{foreign_node}]",
        ),
    ])
    preflight = mocker.patch.object(subject, "run_adr_integration_preflight")

    subject.adr_integration_preflight.__wrapped__(request)

    preflight.assert_not_called()


@pytest.mark.parametrize("live", [None, "", "false", "0"])
def test_selected_adr_integration_fixture_preserves_mandatory_live_guard(mocker, monkeypatch, live):
    if live is None:
        monkeypatch.delenv("AZURE_TEST_RUN_LIVE", raising=False)
    else:
        monkeypatch.setenv("AZURE_TEST_RUN_LIVE", live)
    request = _request([
        SimpleNamespace(path=Path(subject.__file__).resolve().parent / "test_adr_namespace_int.py"),
    ])
    command = mocker.patch.object(subject, "_run_preflight_command")

    with pytest.raises(pytest.UsageError, match="AZURE_TEST_RUN_LIVE"):
        subject.adr_integration_preflight.__wrapped__(request)

    command.assert_not_called()


@pytest.mark.parametrize("filename,integration", [
    ("test_adr_base_unit.py", False),
    ("test_adr_integration_timeouts_unit.py", False),
    ("test_adr_namespace_int.py", True),
], ids=["unit", "unit-with-integration-name", "integration"])
def test_fast_unit_polling_uses_file_path_not_test_names_or_parameters(mocker, monkeypatch, filename, integration):
    from azext_iot.adr.providers import base

    original = mocker.patch.object(base, "wait_for_terminal_state")
    request = SimpleNamespace(node=SimpleNamespace(
        path=Path(subject.__file__).resolve().parent / filename,
        nodeid=f"{filename}::test_internal_error[test_example_int.py]",
    ))
    subject.mock_wait_for_terminal_state.__wrapped__(request, monkeypatch)

    if integration:
        assert base.wait_for_terminal_state is original
    else:
        assert base.wait_for_terminal_state is not original
        poller = Mock()
        assert base.wait_for_terminal_state(poller, poll_interval=30) is poller.result.return_value
        poller.result.assert_called_once_with()
    original.assert_not_called()


def test_preflight_requires_live_mode(monkeypatch):
    monkeypatch.delenv("AZURE_TEST_RUN_LIVE", raising=False)

    with pytest.raises(pytest.UsageError, match="AZURE_TEST_RUN_LIVE"):
        subject.run_adr_integration_preflight(Mock())


def test_preflight_validates_mandatory_resources_and_reports_optional_fixtures(
    monkeypatch,
):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    monkeypatch.setenv("azext_iot_adr_reports_enabled", "1")
    config, reporter = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=[
            "",
            "00000000-0000-0000-0000-000000000000",
            "",
            "",
            "Registered",
            "Registered",
            "",
        ],
    ) as run:
        with patch.object(
            subject,
            "TEST_SUBSCRIPTION",
            "00000000-0000-0000-0000-000000000000",
        ):
            subject.run_adr_integration_preflight(config)

    assert run.call_count == 7
    assert run.call_args_list[0].args[0] == [
        "az",
        "account",
        "set",
        "--subscription",
        "00000000-0000-0000-0000-000000000000",
    ]
    messages = [call.args[0] for call in reporter.write_line.call_args_list]
    assert any("subscription=00000000" in message for message in messages)
    assert any("endpoint=" in message and "api=" in message for message in messages)
    assert any("azext_iot_adr_reports_enabled" in message for message in messages)
    assert any("azext_iot_adr_update_instance_id" in message for message in messages)


def test_preflight_rejects_unregistered_provider(monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    config, _ = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=["", subject.TEST_SUBSCRIPTION, "", "", "NotRegistered"],
    ), pytest.raises(pytest.UsageError, match="must be registered"):
        subject.run_adr_integration_preflight(config)


def test_preflight_rejects_unexpected_subscription(monkeypatch):
    monkeypatch.setenv("AZURE_TEST_RUN_LIVE", "true")
    config, _ = _config()

    with patch.object(
        subject,
        "_run_preflight_command",
        side_effect=["", "different-subscription"],
    ), pytest.raises(pytest.UsageError, match="expected"):
        subject.run_adr_integration_preflight(config)


@pytest.mark.parametrize(
    "side_effect",
    [
        OSError("az not found"),
        subprocess.TimeoutExpired(["az", "account", "show"], 60),
    ],
)
def test_run_preflight_command_translates_execution_failures(side_effect):
    with patch("subprocess.run", side_effect=side_effect), pytest.raises(
        pytest.UsageError, match="could not run"
    ):
        subject._run_preflight_command(["az", "account", "show"])


def test_run_preflight_command_surfaces_cli_error():
    result = Mock(returncode=1, stderr="not logged in", stdout="")
    with patch("subprocess.run", return_value=result), pytest.raises(
        pytest.UsageError, match="not logged in"
    ):
        subject._run_preflight_command(["az", "account", "show"])
